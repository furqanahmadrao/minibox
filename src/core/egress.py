"""Egress proxy — TCP forwarder with domain allowlist filtering.

Runs as a background task per sandbox.  The sandbox connects to the proxy
via a Unix socket or localhost port, and the proxy checks each destination
against the configured allowlist before forwarding.

The proxy uses a simple framing protocol:
  - Client sends: 2 bytes (family: 2=IPv4, 10=IPv6) + address bytes + 2 bytes (port)
  - Server responds: b"\x00" (OK) or b"\x01" (DENIED)
  - If OK, data flows bidirectionally until one side closes.

This is intentionally lightweight — no SOCKS5 dependency.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import struct

logger = logging.getLogger(__name__)


class EgressProxy:
    """TCP proxy that filters outbound connections by domain allowlist."""

    def __init__(
        self,
        allowlist: list[str],
        listen_host: str = "127.0.0.1",
        listen_port: int = 0,
    ) -> None:
        self.allowlist = allowlist
        self.listen_host = listen_host
        self.listen_port = listen_port
        self._server: asyncio.AbstractServer | None = None
        self._active: list[asyncio.Task] = []

    async def start(self) -> int:
        """Start the proxy. Returns the actual listen port."""
        self._server = await asyncio.start_server(
            self._handle_client,
            self.listen_host,
            self.listen_port,
        )
        # Get assigned port
        sock = self._server.sockets[0]
        self.listen_port = sock.getsockname()[1]
        logger.info("Egress proxy listening on %s:%d", self.listen_host, self.listen_port)
        return self.listen_port

    async def stop(self) -> None:
        """Stop the proxy and close all connections."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for task in self._active:
            task.cancel()
        self._active.clear()

    def _check_domain(self, domain: str) -> bool:
        """Check if a domain is allowed by the egress allowlist."""
        if not self.allowlist:
            return True  # No allowlist = allow all
        for allowed in self.allowlist:
            if domain == allowed or domain.endswith("." + allowed):
                return True
        return False

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection."""
        try:
            # Read framing header: family(2) + addr_len(2) + addr_bytes + port(2)
            header = await reader.readexactly(2)
            family = struct.unpack("!H", header)[0]

            addr_len_data = await reader.readexactly(2)
            addr_len = struct.unpack("!H", addr_len_data)[0]

            addr_bytes = await reader.readexactly(addr_len)
            port_data = await reader.readexactly(2)
            port = struct.unpack("!H", port_data)[0]

            # Resolve and check
            if family == socket.AF_INET:
                ip_str = socket.inet_ntop(socket.AF_INET, addr_bytes)
            elif family == socket.AF_INET6:
                ip_str = socket.inet_ntop(socket.AF_INET6, addr_bytes)
            else:
                await writer.write(b"\x01")
                await writer.drain()
                return

            # Try reverse DNS for domain check
            domain = await asyncio.get_event_loop().run_in_executor(
                None, _reverse_lookup, ip_str
            )

            if not self._check_domain(domain or ip_str):
                logger.info("Egress DENIED: %s (%s:%d)", domain, ip_str, port)
                await writer.write(b"\x01")
                await writer.drain()
                writer.close()
                return

            # Connect to target
            try:
                remote_reader, remote_writer = await asyncio.wait_for(
                    asyncio.open_connection(ip_str, port),
                    timeout=10.0,
                )
            except (OSError, asyncio.TimeoutError) as e:
                logger.warning("Egress connect failed to %s:%d: %s", ip_str, port, e)
                await writer.write(b"\x01")
                await writer.drain()
                writer.close()
                return

            logger.info("Egress ALLOWED: %s (%s:%d)", domain, ip_str, port)
            await writer.write(b"\x00")
            await writer.drain()

            # Bidirectional relay
            done = asyncio.Event()

            async def relay(
                src: asyncio.StreamReader,
                dst: asyncio.StreamWriter,
                label: str,
            ) -> None:
                try:
                    while True:
                        data = await src.read(8192)
                        if not data:
                            break
                        dst.write(data)
                        await dst.drain()
                except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
                    pass
                finally:
                    done.set()

            t1 = asyncio.create_task(relay(reader, remote_writer, "c->s"))
            t2 = asyncio.create_task(relay(remote_reader, writer, "s->c"))

            await done.wait()
            t1.cancel()
            t2.cancel()
            remote_writer.close()

        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        except Exception as e:
            logger.warning("Egress proxy error: %s", e)
        finally:
            try:
                writer.close()
            except Exception:
                pass


def _reverse_lookup(ip: str) -> str | None:
    """Best-effort reverse DNS lookup."""
    try:
        result = socket.gethostbyaddr(ip)
        return result[0]
    except (socket.herror, socket.gaierror, OSError):
        return None


class EgressManager:
    """Manages per-sandbox egress proxies."""

    def __init__(self) -> None:
        self._proxies: dict[str, EgressProxy] = {}

    async def start_for_sandbox(
        self,
        sandbox_id: str,
        allowlist: list[str],
    ) -> int:
        """Start an egress proxy for a sandbox. Returns the listen port."""
        proxy = EgressProxy(allowlist=allowlist)
        port = await proxy.start()
        self._proxies[sandbox_id] = proxy
        return port

    async def stop_for_sandbox(self, sandbox_id: str) -> None:
        """Stop the egress proxy for a sandbox."""
        proxy = self._proxies.pop(sandbox_id, None)
        if proxy:
            await proxy.stop()


