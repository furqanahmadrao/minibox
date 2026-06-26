"""Seccomp BPF profile compiler — with comprehensive syscall blocking.

Compiles a JSON seccomp profile to raw BPF bytecode for bubblewrap.
"""

from __future__ import annotations

import logging
import re
import struct

logger = logging.getLogger(__name__)

# ── BPF constants ──────────────────────────────────────────────────────────
BPF_LD = 0x00
BPF_W = 0x00
BPF_ABS = 0x20
BPF_JMP = 0x05
BPF_JEQ = 0x10
BPF_RET = 0x06

AUDIT_ARCH_X86_64 = 0xC000003E
SECCOMP_DATA_ARCH = 0
SECCOMP_DATA_NR = 4

SCMP_ACT_ALLOW = 0x7FFF0000


def _scmp_act_errno(e: int) -> int:
    return 0x00050000 | (e & 0xFFFF)


# Comprehensive x86_64 syscall blocklist
_BLOCKED_SYSCALLS: dict[str, int] = {
    # Namespace escape vectors
    "unshare": 272,
    "setns": 308,
    # Privilege escalation
    "ptrace": 101,
    "personality": 136,
    # Kernel module manipulation
    "init_module": 175,
    "finit_module": 313,
    "delete_module": 176,
    # Mount/filesystem escape
    "mount": 165,
    "umount2": 166,
    "pivot_root": 155,
    "chroot": 161,
    # System manipulation
    "reboot": 169,
    "sethostname": 170,
    "setdomainname": 171,
    "kexec_load": 246,
    "kexec_file_load": 320,
    "swapon": 175,
    "swapoff": 176,
    "acct": 163,
    "settimeofday": 164,
    "iopl": 174,
    "ioperm": 173,
    # io_uring (attack surface)
    "io_uring_setup": 425,
    "io_uring_enter": 426,
    "io_uring_register": 427,
    # Key management (container escape vector)
    "keyctl": 250,
    "add_key": 248,
    "request_key": 249,
    # BPF (code injection)
    "bpf": 321,
    # Memory mapping tricks
    "remap_file_pages": 216,
    "mbind": 237,
    "set_mempolicy": 238,
    "get_mempolicy": 239,
    "migrate_pages": 256,
    "move_pages": 279,
    # Misc kernel attack surface
    "lookup_dcookie": 212,
    "vserver": 236,
    "userfaultfd": 323,
    "pkey_mprotect": 329,
    "pkey_alloc": 330,
    "pkey_free": 331,
    # Process manipulation
    "process_vm_readv": 310,
    "process_vm_writev": 311,
    "kcmp": 312,
    "sched_setattr": 314,
    "sched_getattr": 315,
    # Perf/perf_event_open — side channel
    "perf_event_open": 298,
}


# Docker/OCI action mapping
_ACTION_MAP_DOCKER: dict[str, int] = {
    "allow": SCMP_ACT_ALLOW,
    "errno": _scmp_act_errno(1),
    "trap": 0x00060000,
    "trace": 0x7FF00000,
    "kill_process": 0x00080000,
    "kill_thread": 0x00000000,
    "log": 0x7FFC0000,
    "allow_return": 0x7FFC0001,
}

# Libseccomp action mapping
_ACTION_MAP_LIBSECCOMP: dict[str, int] = {
    "SCMP_ACT_ALLOW": SCMP_ACT_ALLOW,
    "_scmp_act_errno": _scmp_act_errno(1),
    "_scmp_act_errno(EPERM)": _scmp_act_errno(1),
    "_scmp_act_errno(ENOSYS)": _scmp_act_errno(38),
    "_scmp_act_errno(EACCES)": _scmp_act_errno(13),
    "SCMP_ACT_KILL_PROCESS": 0x00080000,
    "SCMP_ACT_KILL": 0x00000000,
    "SCMP_ACT_TRAP": 0x00060000,
    "SCMP_ACT_TRACE": 0x7FF00000,
    "SCMP_ACT_LOG": 0x7FFC0000,
}


def _parse_action(action_str: str) -> int:
    """Parse an action string to a BPF return value."""
    if action_str in _ACTION_MAP_LIBSECCOMP:
        return _ACTION_MAP_LIBSECCOMP[action_str]
    if action_str in _ACTION_MAP_DOCKER:
        return _ACTION_MAP_DOCKER[action_str]
    if action_str.startswith("_scmp_act_errno"):
        m = re.search(r"\((\d+)\)", action_str)
        if m:
            return _scmp_act_errno(int(m.group(1)))
    logger.warning("Unknown seccomp action '%s', defaulting to ERRNO(1)", action_str)
    return _scmp_act_errno(1)


def _bpf_insn(opcode: int, jt: int, jf: int, k: int) -> bytes:
    """Pack a single BPF instruction: opcode(2) + jt(1) + jf(1) + k(4)."""
    return struct.pack("<HBBI", opcode, jt, jf, k)


def compile_profile_to_bpf(profile: dict) -> bytes:
    """Compile a seccomp profile (Docker or libseccomp format) to BPF bytecode."""
    default_action_str = profile.get("defaultAction") or profile.get(
        "default_action", "SCMP_ACT_ALLOW"
    )
    default_action = _parse_action(default_action_str)

    # Determine block action from first non-ALLOW syscall entry
    block_action = _scmp_act_errno(1)  # default: EPERM
    blocked: dict[str, int] = {}
    for entry in profile.get("syscalls", []):
        action_str = entry.get("action", "")
        action_val = _parse_action(action_str)
        if action_val != SCMP_ACT_ALLOW:
            block_action = action_val
            for name in entry.get("names", []):
                if name in _BLOCKED_SYSCALLS:
                    blocked[name] = _BLOCKED_SYSCALLS[name]
                else:
                    logger.debug("Unknown syscall '%s' in blocked list, skipping", name)

    if not blocked:
        logger.debug("No blocked syscalls, returning ALLOW-all BPF")
        # Single ALLOW instruction
        return _bpf_ret(default_action)

    sorted_blocked = sorted(blocked.items(), key=lambda x: x[1])
    n = len(sorted_blocked)

    instructions: list[bytes] = []

    # 0: load architecture
    instructions.append(_bpf_insn(BPF_LD | BPF_W | BPF_ABS, 0, 0, SECCOMP_DATA_ARCH))
    # 1: check arch — if wrong, skip n+1 instructions to reach ALLOW at index 3+n
    instructions.append(_bpf_insn(BPF_JMP | BPF_JEQ, 0, n + 1, AUDIT_ARCH_X86_64))
    # 2: load syscall number
    instructions.append(_bpf_insn(BPF_LD | BPF_W | BPF_ABS, 0, 0, SECCOMP_DATA_NR))

    # 3..3+n-1: compare each blocked syscall NR
    # jt = n-i jumps to BLOCK at index 3+n+1; jf = 0 falls through to next comparison
    for i, (name, nr) in enumerate(sorted_blocked):
        jt = n - i  # skip to BLOCK ret
        instructions.append(_bpf_insn(BPF_JMP | BPF_JEQ, jt, 0, nr))

    # 3+n: ALLOW (default action)
    instructions.append(_bpf_ret(default_action))
    # 3+n+1: BLOCK (block action for matched syscalls)
    instructions.append(_bpf_ret(block_action))

    bpf_bytes = b"".join(instructions)
    logger.info(
        "Compiled seccomp profile: %d blocked syscalls, %d BPF bytes",
        n,
        len(bpf_bytes),
    )
    return bpf_bytes


def _bpf_ret(val: int) -> bytes:
    """BPF RET instruction with value."""
    return _bpf_insn(BPF_RET, 0, 0, val)


# ── Default profile (comprehensive) ───────────────────────────────────────
SECCOMP_DEFAULT = {
    "defaultAction": "SCMP_ACT_ALLOW",
    "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_X86", "SCMP_ARCH_AARCH64"],
    "syscalls": [
        {
            "names": [
                # Namespace escape
                "unshare",
                "setns",
                # Privilege escalation
                "ptrace",
                "personality",
                # Kernel modules
                "init_module",
                "finit_module",
                "delete_module",
                # Mount escape
                "mount",
                "umount2",
                "pivot_root",
                "chroot",
                # System manipulation
                "reboot",
                "sethostname",
                "setdomainname",
                "kexec_load",
                "kexec_file_load",
                "swapon",
                "swapoff",
                "acct",
                "settimeofday",
                "iopl",
                "ioperm",
                # io_uring
                "io_uring_setup",
                "io_uring_enter",
                "io_uring_register",
                # Key management
                "keyctl",
                "add_key",
                "request_key",
                # BPF
                "bpf",
                # Memory tricks
                "remap_file_pages",
                "mbind",
                "set_mempolicy",
                "get_mempolicy",
                "migrate_pages",
                "move_pages",
                # Misc
                "lookup_dcookie",
                "vserver",
                "userfaultfd",
                "pkey_mprotect",
                "pkey_alloc",
                "pkey_free",
                # Process manipulation
                "process_vm_readv",
                "process_vm_writev",
                "kcmp",
                "sched_setattr",
                "sched_getattr",
                # Perf
                "perf_event_open",
            ],
            "action": "_scmp_act_errno(1)",
        }
    ],
}


def compile_custom_profile(
    blocked_syscalls: list[str] | None = None,
    allowed_syscalls: list[str] | None = None,
) -> dict:
    """Compile a custom seccomp profile."""
    profile = SECCOMP_DEFAULT.copy()

    if blocked_syscalls:
        allowed = set(profile["syscalls"][0]["names"])
        allowed -= set(blocked_syscalls)
        profile["syscalls"][0]["names"] = sorted(allowed)

    if allowed_syscalls:
        profile["syscalls"][0]["names"] = sorted(set(allowed_syscalls))

    return profile
