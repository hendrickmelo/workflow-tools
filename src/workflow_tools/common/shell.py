"""Shell integration utilities for workflow tools."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import click

# Shell integration marker for cd
CD_MARKER = "Switching to "


def output_cd(path: Path, env_var: str = "WT_CD_FILE") -> None:
    """Write path to CD file for shell wrapper to handle directory change.

    Args:
        path: The path to change to
        env_var: Environment variable containing the CD file path
    """
    cd_file = os.environ.get(env_var)
    if cd_file:
        # Validate cd_file is in temp directory to prevent path traversal
        try:
            cd_path = Path(cd_file).resolve()
            temp_dir = Path(tempfile.gettempdir()).resolve()
            cd_path.relative_to(temp_dir)
            cd_path.write_text(str(path))
        except (ValueError, OSError):
            # Not in temp dir or write failed - skip silently
            pass
    click.echo(f"{CD_MARKER}{path}")


def _osc52_copy(text: str) -> bool:
    """Copy text to clipboard using OSC 52 escape sequence.

    OSC 52 allows copying to the local clipboard even over SSH,
    supported by many modern terminals (iTerm2, Windows Terminal,
    Ghostty, Kitty, WezTerm, tmux with allow-passthrough, etc.).

    Returns True (always succeeds in sending the sequence).
    """
    # Base64 encode the text
    encoded = base64.b64encode(text.encode()).decode()

    # OSC 52 format: ESC ] 52 ; c ; <base64> BEL
    # c = clipboard (as opposed to p = primary selection on Linux)
    osc52_seq = f"\033]52;c;{encoded}\a"

    # Write directly to terminal (bypass any output buffering)
    sys.stdout.write(osc52_seq)
    sys.stdout.flush()

    return True


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard. Returns True on success, False if unavailable.

    First tries OSC 52 escape sequence (works over SSH in modern terminals),
    then falls back to platform-specific commands.
    """
    # First try OSC 52 - works over SSH in modern terminals
    # We always try this as it's the most likely to work in SSH sessions
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return _osc52_copy(text)

    # Try platform-specific clipboard commands for local sessions
    clipboard_commands = [
        ["pbcopy"],  # macOS
        ["xclip", "-selection", "clipboard"],  # Linux with xclip
        ["xsel", "--clipboard", "--input"],  # Linux with xsel
        ["clip"],  # Windows
    ]

    for cmd in clipboard_commands:
        try:
            subprocess.run(
                cmd,
                input=text.encode(),
                check=True,
                capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    # Fall back to OSC 52 even for local sessions (terminal might support it)
    return _osc52_copy(text)


# Shell wrapper scripts
SHELL_WRAPPER_TEMPLATE_ZSH = """
# {tool_name} shell integration
export {env_var}="${{TMPDIR:-/tmp}}/.{tool_name}_cd_$$"

{tool_name}() {{
    rm -f "${env_var}"
    "${{{bin_var}:-$HOME/.local/bin/{tool_name}}}" "$@"
    local exit_code=$?

    if [[ -f "${env_var}" ]]; then
        cd "$(cat "${env_var}")"
        rm -f "${env_var}"
    fi

    return $exit_code
}}
"""

SHELL_WRAPPER_TEMPLATE_BASH = """
# {tool_name} shell integration
export {env_var}="${{TMPDIR:-/tmp}}/.{tool_name}_cd_$$"

{tool_name}() {{
    rm -f "${env_var}"
    "${{{bin_var}:-$HOME/.local/bin/{tool_name}}}" "$@"
    local exit_code=$?

    if [[ -f "${env_var}" ]]; then
        cd "$(cat "${env_var}")"
        rm -f "${env_var}"
    fi

    return $exit_code
}}
"""


def get_shell_wrapper(tool_name: str, env_var: str, shell: str = "zsh") -> str:
    """Generate shell wrapper script for a tool.

    Args:
        tool_name: Name of the tool (e.g., 'wt', 'rp')
        env_var: Environment variable for CD file (e.g., 'WT_CD_FILE')
        shell: Shell type ('zsh' or 'bash')
    """
    template = (
        SHELL_WRAPPER_TEMPLATE_ZSH if shell == "zsh" else SHELL_WRAPPER_TEMPLATE_BASH
    )
    bin_var = f"{tool_name.upper()}_BIN"
    return template.format(tool_name=tool_name, env_var=env_var, bin_var=bin_var)
