"""Unified CLI for workflow tools: wt, pr, rp."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

from workflow_tools.common import (
    copy_to_clipboard,
    style_dim,
    style_error,
    style_info,
    style_success,
)
from workflow_tools.pr.cli import cli as pr_cli
from workflow_tools.rp.cli import cli as rp_cli
from workflow_tools.tm.cli import cli as tm_cli
from workflow_tools.wt.cli import cli as wt_cli


@click.group()
@click.version_option(package_name="workflow-tools")
def cli() -> None:
    """Workflow tools: git worktrees, PRs, repositories, and tmux sessions.

    COMMANDS:
        wt    Git worktree management
        pr    Pull request management
        rp    Repository discovery and management
        tm    Tmux session management

    EXAMPLES:
        workflow-tools wt           # Interactive worktree picker
        workflow-tools pr           # Show PR for current branch
        workflow-tools rp           # Interactive repo picker
        workflow-tools tm           # Smart tmux session attach/create
        workflow-tools install      # Install shell integration

    After installing shell integration, use short aliases:
        wt, pr, rp, tm
    """


# Add subcommand groups
cli.add_command(wt_cli, name="wt")
cli.add_command(pr_cli, name="pr")
cli.add_command(rp_cli, name="rp")
cli.add_command(tm_cli, name="tm")


@cli.command()
@click.option(
    "--shell",
    type=click.Choice(["zsh", "bash", "auto"]),
    default="auto",
    help="Shell type (default: auto-detect)",
)
@click.option(
    "--print",
    "print_only",
    is_flag=True,
    help="Print shell script instead of installing",
)
def install(shell: str, *, print_only: bool) -> None:
    """Install shell integration (cd support + aliases).

    Adds aliases for wt, pr, rp with cd support for wt and rp.

    EXAMPLES:
        workflow-tools install              # Auto-detect shell
        workflow-tools install --shell zsh  # Install for zsh
        workflow-tools install --print      # Print script only
    """
    if shell == "auto":
        shell_path = os.environ.get("SHELL", "")
        if "zsh" in shell_path:
            shell = "zsh"
        elif "bash" in shell_path:
            shell = "bash"
        else:
            click.echo(
                style_error(f"Unknown shell: {shell_path}. Use --shell to specify."),
                err=True,
            )
            sys.exit(1)

    wrapper = _get_shell_wrapper(shell)

    if print_only:
        click.echo(wrapper)
        return

    # Determine config file
    home = Path.home()
    config_file = home / ".zshrc" if shell == "zsh" else home / ".bashrc"
    # Ensure ~/.local/bin is in PATH before running workflow-tools
    install_block = """# workflow-tools shell integration
export PATH="$HOME/.local/bin:$PATH"
eval "$(workflow-tools install --print)\""""

    # Check if already installed
    source_cmd = f"source {config_file}"
    if config_file.exists():
        content = config_file.read_text()
        if "workflow-tools install --print" in content:
            click.echo(style_info(f"Already installed in {config_file}"))
            click.echo(style_dim(f"  Restart your shell or run: {source_cmd}"))
            if copy_to_clipboard(source_cmd):
                click.echo(style_dim("  (copied to clipboard)"))
            return

    # Append to config
    with config_file.open("a") as f:
        f.write(f"\n{install_block}\n")

    click.echo(style_success(f"Installed to {config_file}"))
    click.echo(style_dim(f"  Restart your shell or run: {source_cmd}"))
    if copy_to_clipboard(source_cmd):
        click.echo(style_dim("  (copied to clipboard)"))


def _get_shell_wrapper(shell: str) -> str:
    """Get shell wrapper script with aliases."""
    # Find the binary location
    binary = _find_binary()

    if shell == "zsh":
        return f"""
# workflow-tools shell integration
export WT_CD_FILE="${{TMPDIR:-/tmp}}/.wt_cd_$$"
export RP_CD_FILE="${{TMPDIR:-/tmp}}/.rp_cd_$$"

# wt: worktree management with cd support
wt() {{
    rm -f "$WT_CD_FILE"
    "{binary}" wt "$@"
    local exit_code=$?
    if [[ -f "$WT_CD_FILE" ]]; then
        cd "$(cat "$WT_CD_FILE")"
        rm -f "$WT_CD_FILE"
    fi
    return $exit_code
}}

# pr: pull request management with cd support (for pr checkout)
pr() {{
    rm -f "$WT_CD_FILE"
    "{binary}" pr "$@"
    local exit_code=$?
    if [[ -f "$WT_CD_FILE" ]]; then
        cd "$(cat "$WT_CD_FILE")"
        rm -f "$WT_CD_FILE"
    fi
    return $exit_code
}}

# rp: repository management with cd support
rp() {{
    rm -f "$RP_CD_FILE"
    "{binary}" rp "$@"
    local exit_code=$?
    if [[ -f "$RP_CD_FILE" ]]; then
        cd "$(cat "$RP_CD_FILE")"
        rm -f "$RP_CD_FILE"
    fi
    return $exit_code
}}

# tm: tmux session management
tm() {{
    "{binary}" tm "$@"
}}
"""
    # bash
    return f"""
# workflow-tools shell integration
export WT_CD_FILE="${{TMPDIR:-/tmp}}/.wt_cd_$$"
export RP_CD_FILE="${{TMPDIR:-/tmp}}/.rp_cd_$$"

# wt: worktree management with cd support
wt() {{
    rm -f "$WT_CD_FILE"
    "{binary}" wt "$@"
    local exit_code=$?
    if [[ -f "$WT_CD_FILE" ]]; then
        cd "$(cat "$WT_CD_FILE")"
        rm -f "$WT_CD_FILE"
    fi
    return $exit_code
}}

# pr: pull request management with cd support (for pr checkout)
pr() {{
    rm -f "$WT_CD_FILE"
    "{binary}" pr "$@"
    local exit_code=$?
    if [[ -f "$WT_CD_FILE" ]]; then
        cd "$(cat "$WT_CD_FILE")"
        rm -f "$WT_CD_FILE"
    fi
    return $exit_code
}}

# rp: repository management with cd support
rp() {{
    rm -f "$RP_CD_FILE"
    "{binary}" rp "$@"
    local exit_code=$?
    if [[ -f "$RP_CD_FILE" ]]; then
        cd "$(cat "$RP_CD_FILE")"
        rm -f "$RP_CD_FILE"
    fi
    return $exit_code
}}

# tm: tmux session management
tm() {{
    "{binary}" tm "$@"
}}
"""


def _find_binary() -> str:
    """Find the workflow-tools binary location."""
    result = subprocess.run(
        ["which", "workflow-tools"], capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return "workflow-tools"


GITHUB_REPO = "emmapowers/workflow-tools"


@cli.command()
def update() -> None:
    """Update workflow-tools to the latest version.

    Pulls the latest code from the main branch and reinstalls.

    EXAMPLES:
        workflow-tools update
    """
    click.echo(style_info("Updating workflow-tools..."))
    result = subprocess.run(
        [
            "uv",
            "tool",
            "install",
            f"git+https://github.com/{GITHUB_REPO}@main",
            "--force",
            "--reinstall",
        ],
        check=False,
    )
    if result.returncode == 0:
        click.echo(style_success("Updated to latest!"))
    else:
        click.echo(style_error("Update failed"), err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
