"""Tmux session manager with git-aware naming and interactive selection UI."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from typing import NamedTuple

import click

from workflow_tools.common import (
    CYAN,
    DIM,
    GREEN,
    YELLOW,
    ValidationError,
    fuzzy_select,
    get_current_branch,
    style_dim,
    style_error,
    style_info,
    style_success,
    style_warn,
    validate_tmux_session_name,
)

# Colors used for list output (not fuzzy picker)

# Separator for tmux list-sessions output (tab is safe - won't appear in session names)
_TMUX_FIELD_SEP = "\t"
_TMUX_SESSION_FIELD_COUNT = 3

# Control character boundaries for sanitization
_CTRL_CHAR_MIN = 32  # First printable ASCII character (space)
_CTRL_CHAR_DEL = 127  # DEL character

# Maximum input length before sanitization (DoS prevention)
_MAX_INPUT_LENGTH = 1024

# Maximum number of extended session names to try (e.g., foo.2, foo.3, ...)
_MAX_EXTENDED_SESSION_COUNTER = 100


class SessionInfo(NamedTuple):
    """Information about a tmux session."""

    name: str
    attached: bool
    windows: int


class AttachAction(NamedTuple):
    """Action to take when attaching to a session."""

    action: str  # "new_window", "detach_other", "join"
    new_session_name: str | None = None  # For "new_window" action


def get_hostname() -> str:
    """Get the hostname for terminal title."""
    return socket.gethostname().split(".")[0]


def sanitize_session_name(name: str) -> str:
    """Sanitize a string to be a valid tmux session name.

    Replaces invalid characters (: . / and whitespace) with hyphens.
    Returns empty string if input is empty or only invalid chars.
    """
    # Replace null bytes and common invalid characters with hyphens
    for char in [":", ".", "/", "\\", "\t", "\n", "\r", "\0"]:
        name = name.replace(char, "-")
    # Collapse multiple hyphens
    while "--" in name:
        name = name.replace("--", "-")
    # Strip leading/trailing hyphens
    return name.strip("-")


def get_suggested_name() -> str:
    """Get suggested session name from current branch or hostname."""
    branch = get_current_branch()
    if branch:
        return sanitize_session_name(branch)
    return sanitize_session_name(get_hostname())


def is_tmux_installed() -> bool:
    """Check if tmux is installed."""
    result = subprocess.run(
        ["which", "tmux"], capture_output=True, check=False, text=True
    )
    return result.returncode == 0


def is_inside_tmux() -> bool:
    """Check if we're running inside a tmux session."""
    return "TMUX" in os.environ


def get_current_session_name() -> str | None:
    """Get the name of the current tmux session (if inside one)."""
    if not is_inside_tmux():
        return None
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#{session_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def print_current_session_info() -> None:
    """Print information about the current tmux session."""
    session_name = get_current_session_name()
    if not session_name:
        click.echo(style_error("Could not determine current session"), err=True)
        return

    # Get detailed session info
    sessions = list_sessions()
    current = next((s for s in sessions if s.name == session_name), None)

    hostname = get_hostname()
    click.echo(style_info(f"Inside tmux session: {session_name}@{hostname}"))
    if current:
        click.echo(style_dim(f"  Windows: {current.windows}"))
        click.echo(
            style_dim(f"  Clients: {'attached' if current.attached else 'detached'}")
        )


def require_outside_tmux(command: str | None = None) -> bool:
    """Check if inside tmux and print error if so. Returns True if inside tmux."""
    if is_inside_tmux():
        session_name = get_current_session_name()
        hostname = get_hostname()
        if command:
            click.echo(
                style_error(
                    f"Cannot run 'tm {command}' from inside tmux session: "
                    f"{session_name}@{hostname}"
                ),
                err=True,
            )
        else:
            click.echo(
                style_error(
                    f"Cannot run 'tm' from inside tmux session: "
                    f"{session_name}@{hostname}"
                ),
                err=True,
            )
        return True
    return False


def list_sessions() -> list[SessionInfo]:
    """List all tmux sessions."""
    # Use tab separator to handle session names with colons
    format_str = _TMUX_FIELD_SEP.join(
        ["#{session_name}", "#{session_attached}", "#{session_windows}"]
    )
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", format_str],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # No server running or other error
        return []

    sessions: list[SessionInfo] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split(_TMUX_FIELD_SEP)
        if len(parts) == _TMUX_SESSION_FIELD_COUNT:
            sessions.append(
                SessionInfo(
                    name=parts[0],
                    attached=parts[1] == "1",
                    windows=int(parts[2]) if parts[2].isdigit() else 0,
                )
            )
    return sessions


def session_exists(name: str) -> bool:
    """Check if a session with the given name exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def get_session_info(name: str) -> SessionInfo | None:
    """Get info for a specific session, or None if it doesn't exist."""
    sessions = list_sessions()
    return next((s for s in sessions if s.name == name), None)


def find_next_extended_name(base_name: str) -> str:
    """Find the next available extended session name (e.g., foo.2, foo.3).

    If the base session is 'foo', checks for 'foo.2', 'foo.3', etc.
    and returns the first one that doesn't exist.
    """
    # Start at .2 (the original is implicitly .1)
    counter = 2
    while True:
        extended_name = f"{base_name}.{counter}"
        if not session_exists(extended_name):
            return extended_name
        counter += 1
        # Safety limit to prevent infinite loops
        if counter > _MAX_EXTENDED_SESSION_COUNTER:
            # Fall back to timestamp-based name
            return f"{base_name}.{int(time.time())}"


def prompt_attach_options(session_name: str) -> AttachAction | None:
    """Prompt user for action when attaching to an already-attached session.

    Returns AttachAction describing what to do, or None if cancelled.
    """
    extended_name = find_next_extended_name(session_name)

    options = [
        f"[+] Create new window ({extended_name})",
        "[D] Detach other client and attach",
        "[J] Join session (share with other client)",
    ]

    click.echo(style_warn(f"Session '{session_name}' is already attached."))
    index = fuzzy_select(options, "How do you want to attach?")

    if index is None:
        return None
    if index == 0:
        return AttachAction(action="new_window", new_session_name=extended_name)
    if index == 1:
        return AttachAction(action="detach_other")
    return AttachAction(action="join")


def attach_to_session(session_name: str) -> None:
    """Attach to a session, prompting for options if already attached.

    This is the main entry point for attaching to sessions. It checks if
    the session is already attached and prompts the user for how to proceed.
    """
    session_info = get_session_info(session_name)

    if session_info is None:
        click.echo(style_error(f"Session '{session_name}' not found."), err=True)
        sys.exit(1)

    if not session_info.attached:
        # Session is not attached, just attach directly
        click.echo(style_info(f"Attaching to session '{session_name}'..."))
        run_tmux_attach(session_name)
        return

    # Session is attached, prompt for action
    action = prompt_attach_options(session_name)

    if action is None:
        click.echo(style_dim("Cancelled."))
        return

    if action.action == "new_window":
        click.echo(
            style_success(f"Creating grouped session '{action.new_session_name}'...")
        )
        run_tmux_new_grouped(action.new_session_name, session_name)  # type: ignore[arg-type]
    elif action.action == "detach_other":
        click.echo(style_info("Detaching other client and attaching..."))
        run_tmux_attach(session_name, detach_other=True)
    else:  # join
        click.echo(style_info(f"Joining session '{session_name}'..."))
        run_tmux_attach(session_name)


def _strip_control_chars(s: str) -> str:
    """Strip control characters to prevent terminal escape injection."""
    # Remove all control characters (0x00-0x1F and 0x7F)
    return "".join(
        c for c in s if ord(c) >= _CTRL_CHAR_MIN and ord(c) != _CTRL_CHAR_DEL
    )


def set_terminal_title(session_name: str) -> None:
    """Print escape sequence to set terminal title."""
    hostname = get_hostname()
    # Sanitize to prevent escape sequence injection
    safe_session = _strip_control_chars(session_name)
    safe_hostname = _strip_control_chars(hostname)
    title = f"{safe_session}@{safe_hostname}"
    # Print escape sequence to set terminal title
    sys.stdout.write(f"\033]0;{title}\a")
    sys.stdout.flush()


def run_tmux_attach(session_name: str, *, detach_other: bool = False) -> None:
    """Attach to a tmux session, replacing current process.

    Note: For attach, we don't sanitize because the session already exists
    with whatever name it has (possibly created outside tm).

    Args:
        session_name: Name of the session to attach to
        detach_other: If True, detach other clients before attaching (-d flag)
    """
    set_terminal_title(session_name)
    # Use exec to replace current process with tmux
    if detach_other:
        os.execlp("tmux", "tmux", "attach-session", "-d", "-t", session_name)
    else:
        os.execlp("tmux", "tmux", "attach-session", "-t", session_name)


def run_tmux_new_grouped(new_session_name: str, target_session: str) -> None:
    """Create a new session grouped with an existing session, replacing current process.

    This creates a new session that shares windows with the target session,
    allowing independent window selection while sharing the same windows.
    """
    set_terminal_title(new_session_name)
    # Create a new session grouped with the target session
    os.execlp(
        "tmux",
        "tmux",
        "new-session",
        "-t",
        target_session,
        "-s",
        new_session_name,
    )


def run_tmux_new(session_name: str) -> None:
    """Create and attach to a new tmux session, replacing current process.

    Sanitizes the session name first, then validates as a safety check.
    This function does not return - it replaces the current process with tmux.
    """
    original_name = session_name

    # Early length check before sanitization to prevent DoS
    if len(session_name) > _MAX_INPUT_LENGTH:
        click.echo(style_error("Session name too long"), err=True)
        sys.exit(1)

    # Sanitize first (convert invalid chars to hyphens)
    session_name = sanitize_session_name(session_name)

    # Handle empty result after sanitization
    if not session_name:
        click.echo(
            style_error(
                f"Invalid session name: {original_name!r} (no valid characters)"
            ),
            err=True,
        )
        sys.exit(1)

    # Validate as safety check
    try:
        validate_tmux_session_name(session_name)
    except ValidationError as e:
        click.echo(style_error(str(e)), err=True)
        sys.exit(1)

    # Notify user if name was changed
    if session_name != original_name:
        click.echo(style_dim(f"  (sanitized to '{session_name}')"))

    set_terminal_title(session_name)
    # Use exec to replace current process with tmux
    os.execlp("tmux", "tmux", "new-session", "-s", session_name)


def format_session_option(session: SessionInfo) -> str:
    """Format a session for display in picker (plain text for fuzzy select)."""
    status = "attached" if session.attached else "detached"
    return f"{session.name} [{status}] ({session.windows} windows)"


def require_tmux() -> None:
    """Exit with error if tmux is not installed."""
    if not is_tmux_installed():
        click.echo(style_error("tmux is not installed"), err=True)
        sys.exit(1)


# CLI Commands


@click.group(invoke_without_command=True)
@click.version_option(package_name="workflow-tools")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Tmux session manager with git-aware naming.

    EXAMPLES:
        tm                  # Smart default: attach or show picker/menu
        tm create           # Create session (defaults to branch name)
        tm attach           # Interactive: pick session to attach
        tm list             # List all sessions
        tm kill             # Interactive: pick session to kill

    ALIASES:
        tm c  = tm create
        tm a  = tm attach
        tm ls = tm list
        tm k  = tm kill
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(default_cmd)


@cli.command("default", hidden=True)
def default_cmd() -> None:
    """Smart default behavior."""
    require_tmux()

    # If inside tmux, show current session info
    if is_inside_tmux():
        print_current_session_info()
        return

    # Get current branch name
    suggested = get_suggested_name()
    sessions = list_sessions()

    # If matching session exists, auto-attach
    matching = [s for s in sessions if s.name == suggested]
    if matching:
        attach_to_session(suggested)
        return

    # If sessions exist, show picker
    if sessions:
        options = [format_session_option(s) for s in sessions]
        # Add create option at the top
        options.insert(0, "[+] Create new session")

        index = fuzzy_select(options, "Select session")
        if index is None:
            click.echo(style_dim("Cancelled."))
            return

        if index == 0:
            # Create new session
            name = click.prompt(
                click.style("  Session name", fg=CYAN),
                default=suggested,
                prompt_suffix=" → ",
            )
            click.echo(style_success(f"Creating session '{name}'..."))
            run_tmux_new(name)
        else:
            # Attach to selected session
            selected = sessions[index - 1]
            attach_to_session(selected.name)
        return

    # No sessions - show action menu
    options = [
        "[+] Create new session",
        "[?] List sessions",
    ]

    index = fuzzy_select(options, "No sessions found")
    if index is None:
        click.echo(style_dim("Cancelled."))
        return

    if index == 0:
        # Create new session
        name = click.prompt(
            click.style("  Session name", fg=CYAN),
            default=suggested,
            prompt_suffix=" → ",
        )
        click.echo(style_success(f"Creating session '{name}'..."))
        run_tmux_new(name)
    else:
        click.echo(style_dim("No sessions to list."))


@cli.command()
@click.argument("name", required=False)
def create(name: str | None) -> None:
    """Create a new tmux session.

    If NAME is not provided, prompts with current branch name as default.

    EXAMPLES:
        tm create              # Prompt for name (default: branch name)
        tm create my-session   # Create session named 'my-session'
        tm c feature           # Create session named 'feature'
    """
    require_tmux()

    if require_outside_tmux("create"):
        return

    if not name:
        suggested = get_suggested_name()
        name = click.prompt(
            click.style("  Session name", fg=CYAN),
            default=suggested,
            prompt_suffix=" → ",
        )

    # Check if session already exists
    if session_exists(name):
        if click.confirm(
            style_warn(f"Session '{name}' already exists. Attach to it?"),
            default=True,
        ):
            attach_to_session(name)
        else:
            click.echo(style_dim("Cancelled."))
        return

    click.echo(style_success(f"Creating session '{name}'..."))
    run_tmux_new(name)


@cli.command()
@click.argument("name", required=False)
def attach(name: str | None) -> None:
    """Attach to an existing tmux session.

    If NAME is not provided, shows interactive picker.

    EXAMPLES:
        tm attach              # Interactive: pick session
        tm attach my-session   # Attach to 'my-session'
        tm a feature           # Attach to 'feature'
    """
    require_tmux()

    if require_outside_tmux("attach"):
        return

    sessions = list_sessions()

    if not sessions:
        click.echo(style_error("No tmux sessions found."), err=True)
        if click.confirm(style_info("Create a new session?"), default=True):
            suggested = get_suggested_name()
            session_name = click.prompt(
                click.style("  Session name", fg=CYAN),
                default=suggested,
                prompt_suffix=" → ",
            )
            click.echo(style_success(f"Creating session '{session_name}'..."))
            run_tmux_new(session_name)
        return

    if name:
        # Direct attach
        attach_to_session(name)
        return

    # Interactive mode
    if len(sessions) == 1:
        # Only one session, attach directly
        session = sessions[0]
        attach_to_session(session.name)
        return

    # Multiple sessions, show picker
    options = [format_session_option(s) for s in sessions]
    index = fuzzy_select(options, "Select session")
    if index is None:
        click.echo(style_dim("Cancelled."))
        return

    selected = sessions[index]
    attach_to_session(selected.name)


@cli.command("list")
def list_cmd() -> None:
    """List all tmux sessions.

    EXAMPLES:
        tm list
        tm ls
    """
    require_tmux()

    sessions = list_sessions()

    if not sessions:
        click.echo(style_dim("No tmux sessions found."))
        return

    for session in sessions:
        name_styled = click.style(session.name, fg=CYAN, bold=True)
        if session.attached:
            status_styled = click.style("[attached]", fg=GREEN)
        else:
            status_styled = click.style("[detached]", fg=YELLOW)
        windows_styled = click.style(f"{session.windows} windows", fg=DIM)
        click.echo(f"  {name_styled:30} {status_styled:20} {windows_styled}")


@cli.command()
@click.argument("name", required=False)
@click.option("-f", "--force", is_flag=True, help="Kill without confirmation")
def kill(name: str | None, *, force: bool) -> None:
    """Kill a tmux session.

    If NAME is not provided, shows interactive picker.

    EXAMPLES:
        tm kill                # Interactive: pick session to kill
        tm kill my-session     # Kill 'my-session'
        tm k feature -f        # Force kill 'feature' without confirmation
    """
    require_tmux()

    if require_outside_tmux("kill"):
        return

    sessions = list_sessions()

    if not sessions:
        click.echo(style_error("No tmux sessions found."), err=True)
        sys.exit(1)

    if name:
        # Direct kill
        if not session_exists(name):
            click.echo(style_error(f"Session '{name}' not found."), err=True)
            sys.exit(1)

        if not force and not click.confirm(
            style_warn(f"Kill session '{name}'?"), default=False
        ):
            click.echo(style_dim("Cancelled."))
            return

        result = subprocess.run(
            ["tmux", "kill-session", "-t", name],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            click.echo(style_success(f"Killed session '{name}'"))
        else:
            click.echo(
                style_error(f"Failed to kill session: {result.stderr}"), err=True
            )
            sys.exit(1)
        return

    # Interactive mode
    options = [format_session_option(s) for s in sessions]
    index = fuzzy_select(options, "Select session to kill")
    if index is None:
        click.echo(style_dim("Cancelled."))
        return

    selected = sessions[index]

    if not force and not click.confirm(
        style_warn(f"Kill session '{selected.name}'?"), default=False
    ):
        click.echo(style_dim("Cancelled."))
        return

    result = subprocess.run(
        ["tmux", "kill-session", "-t", selected.name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        click.echo(style_success(f"Killed session '{selected.name}'"))
    else:
        click.echo(style_error(f"Failed to kill session: {result.stderr}"), err=True)
        sys.exit(1)


# Short aliases for frequently used commands
cli.add_command(create, name="c")
cli.add_command(attach, name="a")
cli.add_command(list_cmd, name="ls")
cli.add_command(kill, name="k")


if __name__ == "__main__":
    cli()
