"""Minibox CLI — command-line client for controlling Minibox."""

from __future__ import annotations

import json
import sys

try:
    import click
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from cli.client import MiniboxClient, CREDENTIALS_FILE


console = Console() if HAS_RICH else None


def _get_client(ctx) -> MiniboxClient:
    return ctx.obj["client"]


def _print_json(data):
    if HAS_RICH:
        console.print_json(json.dumps(data, indent=2))
    else:
        print(json.dumps(data, indent=2))


def _print_table(rows: list[dict], columns: list[str]):
    if not HAS_RICH:
        for row in rows:
            print("  ".join(str(row.get(c, "")) for c in columns))
        return

    table = Table()
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*[str(row.get(c, "")) for c in columns])
    console.print(table)


@click.group()
@click.option("--host", envvar="MINIBOX_HOST", default="https://localhost:8080", help="Minibox server URL")
@click.option("--api-key", envvar="MINIBOX_API_KEY", default="", help="API key")
@click.option("--token", envvar="MINIBOX_TOKEN", default="", help="JWT token")
@click.option("--no-verify-ssl", is_flag=True, default=False, help="Disable SSL verification")
@click.option("--cert", envvar="MINIBOX_CERT", default="", help="CA certificate for self-signed certs")
@click.pass_context
def cli(ctx, host: str, api_key: str, token: str, no_verify_ssl: bool, cert: str):
    """Minibox — self-hosted agent sandbox CLI."""
    ctx.ensure_object(dict)
    ctx.obj["client"] = MiniboxClient(
        host=host,
        api_key=api_key,
        token=token,
        verify_ssl=not no_verify_ssl,
        cert_path=cert or None,
    )


@cli.command()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def login(ctx, output_json):
    """Login to Minibox server. Credentials are persisted in ~/.minibox/."""
    import getpass

    username = input("Username: ")
    password = getpass.getpass("Password: ")

    client = _get_client(ctx)
    result = client.login(username, password)

    if output_json:
        _print_json(result)
    else:
        if HAS_RICH:
            console.print(Panel(
                f"[green]Login successful![/green]\n\n"
                f"Token expires in: {result['expires_in']}s\n"
                f"Refresh token expires in: {result.get('refresh_expires_in', 0)}s\n\n"
                f"Credentials saved to: {CREDENTIALS_FILE}",
                title="Minibox Auth",
            ))
        else:
            print(f"Login successful. Token expires in: {result['expires_in']}s")
            print(f"Credentials saved to: {CREDENTIALS_FILE}")


@cli.command()
@click.pass_context
def logout(ctx):
    """Clear persisted credentials."""
    client = _get_client(ctx)
    client.clear_credentials()
    if HAS_RICH:
        console.print("[green]Credentials cleared.[/green]")
    else:
        print("Credentials cleared.")


@cli.command()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def whoami(ctx, output_json):
    """Show current user info and scopes."""
    client = _get_client(ctx)
    result = client.me()

    if output_json:
        _print_json(result)
    else:
        if HAS_RICH:
            console.print(Panel(
                f"[bold]User:[/bold] {result.get('sub', 'unknown')}\n"
                f"[bold]Role:[/bold] {result.get('role', 'unknown')}\n"
                f"[bold]Auth:[/bold] {result.get('auth_method', 'unknown')}\n"
                f"[bold]Scopes:[/bold] {', '.join(result.get('scopes', []))}",
                title="Current Identity",
            ))
        else:
            print(json.dumps(result, indent=2))


@cli.command()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def scopes(ctx, output_json):
    """List available scopes and groups."""
    client = _get_client(ctx)
    result = client.scopes()

    if output_json:
        _print_json(result)
    else:
        if HAS_RICH:
            console.print("[bold]Scope Groups:[/bold]")
            for group, scope_list in result.get("groups", {}).items():
                console.print(f"  [cyan]{group}[/cyan]: {', '.join(scope_list)}")
            console.print()
            console.print("[bold]Individual Scopes:[/bold]")
            for scope, desc in result.get("scopes", {}).items():
                console.print(f"  [green]{scope}[/green]: {desc}")
        else:
            print(json.dumps(result, indent=2))


@cli.command()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def audit(ctx, output_json):
    """Show recent audit log."""
    client = _get_client(ctx)
    result = client.audit_log()

    if output_json:
        _print_json(result)
    else:
        if not result:
            print("No audit entries.")
            return
        _print_table(result, ["timestamp", "event", "user", "ip", "success"])


@cli.command()
@click.option("--template", "-t", default="python-dev", help="Template ID")
@click.option("--ttl", default=1800, help="Time-to-live in seconds")
@click.option("--network", "-n", default="egress-only", help="Network mode")
@click.option("--memory", "-m", default=512, help="Memory in MB")
@click.option("--label", "-l", default="", help="Label for the sandbox")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def create(ctx, template, ttl, network, memory, label, output_json):
    """Create a new sandbox."""
    client = _get_client(ctx)
    result = client.create(template=template, ttl=ttl, network=network, memory_mb=memory, label=label)

    if output_json:
        _print_json(result)
    else:
        if HAS_RICH:
            console.print(Panel(
                f"[green]Sandbox created![/green]\n\n"
                f"ID: [bold]{result['sandbox_id']}[/bold]\n"
                f"Template: {result['template']}\n"
                f"Status: {result['status']}\n"
                f"TTL: {result['ttl']}s",
                title="Minibox",
            ))
        else:
            print(f"Sandbox created: {result['sandbox_id']}")


@cli.command("list")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def list_sandboxes(ctx, output_json):
    """List all sandboxes."""
    client = _get_client(ctx)
    result = client.list()

    if output_json:
        _print_json(result)
    else:
        if not result:
            print("No sandboxes.")
            return
        _print_table(result, ["sandbox_id", "status", "template", "label", "exec_count", "ttl_remaining"])


@cli.command()
@click.argument("sandbox_id")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def status(ctx, sandbox_id, output_json):
    """Get sandbox status."""
    client = _get_client(ctx)
    result = client.get(sandbox_id)

    if output_json:
        _print_json(result)
    else:
        _print_json(result)


@cli.command()
@click.argument("sandbox_id")
@click.argument("cmd")
@click.option("--workdir", "-w", default="/", help="Working directory")
@click.option("--timeout", "-T", default=30, help="Timeout in seconds")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def exec(ctx, sandbox_id, cmd, workdir, timeout, output_json):
    """Execute a command in a sandbox."""
    client = _get_client(ctx)
    result = client.exec(sandbox_id, cmd, workdir=workdir, timeout=timeout)

    if output_json:
        _print_json(result)
    else:
        if result.get("stdout"):
            print(result["stdout"], end="")
        if result.get("stderr"):
            print(result["stderr"], end="", file=sys.stderr)
        sys.exit(result.get("exit_code", 1))


@cli.command()
@click.argument("sandbox_id")
@click.argument("path")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def read(ctx, sandbox_id, path, output_json):
    """Read a file from a sandbox."""
    client = _get_client(ctx)
    result = client.read(sandbox_id, path)

    if output_json:
        _print_json(result)
    else:
        print(result.get("content", ""))


@cli.command()
@click.argument("sandbox_id")
@click.argument("path")
@click.argument("content", required=False)
@click.option("--file", "-f", "from_file", help="Read content from file")
@click.pass_context
def write(ctx, sandbox_id, path, content, from_file):
    """Write a file to a sandbox."""
    client = _get_client(ctx)

    if from_file:
        with open(from_file) as f:
            content = f.read()
    elif content is None:
        content = sys.stdin.read()

    result = client.write(sandbox_id, path, content)
    print(f"Written: {result.get('path')}")


@cli.command()
@click.argument("sandbox_id")
@click.option("--path", "-p", default="/", help="Path to list")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def tree(ctx, sandbox_id, path, output_json):
    """List files in a sandbox."""
    client = _get_client(ctx)
    result = client.tree(sandbox_id, path)

    if output_json:
        _print_json(result)
    else:
        def print_tree(entry, indent=0):
            prefix = "  " * indent
            icon = "d" if entry.get("type") == "directory" else "f"
            print(f"{prefix}[{icon}] {entry['name']}")
            for child in entry.get("children", []):
                print_tree(child, indent + 1)

        print_tree(result)


@cli.command()
@click.argument("sandbox_id")
@click.argument("path")
@click.confirmation_option(prompt="Are you sure?")
@click.pass_context
def rm(ctx, sandbox_id, path):
    """Delete a file from a sandbox."""
    client = _get_client(ctx)
    client.delete_file(sandbox_id, path)
    print(f"Deleted: {path}")


@cli.command()
@click.argument("sandbox_id")
@click.option("--label", "-l", default="", help="Snapshot label")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def snapshot(ctx, sandbox_id, label, output_json):
    """Checkpoint a sandbox."""
    client = _get_client(ctx)
    result = client.snapshot(sandbox_id, label)

    if output_json:
        _print_json(result)
    else:
        print(f"Snapshot created: {result['snapshot_id']}")


@cli.command()
@click.argument("sandbox_id")
@click.argument("snapshot_id")
@click.option("--label", "-l", default="", help="Label for the fork")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def fork(ctx, sandbox_id, snapshot_id, label, output_json):
    """Fork a sandbox from a snapshot."""
    client = _get_client(ctx)
    result = client.fork(sandbox_id, snapshot_id, label)

    if output_json:
        _print_json(result)
    else:
        print(f"Forked sandbox: {result['sandbox_id']}")


@cli.command()
@click.argument("sandbox_id")
@click.confirmation_option(prompt="Are you sure you want to destroy this sandbox?")
@click.pass_context
def destroy(ctx, sandbox_id):
    """Destroy a sandbox."""
    client = _get_client(ctx)
    client.destroy(sandbox_id)
    print(f"Destroyed: {sandbox_id}")


@cli.command()
@click.argument("sandbox_id")
@click.pass_context
def pause(ctx, sandbox_id):
    """Pause a sandbox."""
    client = _get_client(ctx)
    client.pause(sandbox_id)
    print(f"Paused: {sandbox_id}")


@cli.command()
@click.argument("sandbox_id")
@click.pass_context
def resume(ctx, sandbox_id):
    """Resume a sandbox."""
    client = _get_client(ctx)
    client.resume(sandbox_id)
    print(f"Resumed: {sandbox_id}")


@cli.command()
@click.argument("sandbox_id")
@click.argument("port", type=int)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def expose(ctx, sandbox_id, port, output_json):
    """Forward a port from sandbox to host."""
    client = _get_client(ctx)
    result = client.expose_port(sandbox_id, port)

    if output_json:
        _print_json(result)
    else:
        print(f"Port {port} -> {result['url']}")


@cli.command()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def templates(ctx, output_json):
    """List available templates."""
    client = _get_client(ctx)
    result = client.templates()

    if output_json:
        _print_json(result)
    else:
        _print_table(result, ["id", "name", "description", "is_custom"])


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
