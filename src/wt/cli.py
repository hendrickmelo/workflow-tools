"""Git worktree manager with interactive selection UI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import click
from InquirerPy import inquirer

# Colors using click.style
CYAN = "cyan"
GREEN = "green"
YELLOW = "yellow"
RED = "red"
DIM = "bright_black"
BOLD = "bold"

# Shell integration marker for cd
CD_MARKER = "Switching to "


class WorktreeInfo(NamedTuple):
    """Information about a git worktree."""

    path: Path
    name: str
    branch: str | None
    is_bare: bool


class PRInfo(NamedTuple):
    """Information about a GitHub pull request."""

    number: int
    title: str
    branch: str
    is_draft: bool


def style_error(msg: str) -> str:
    """Style an error message."""
    return click.style(f"✗ {msg}", fg=RED)


def style_success(msg: str) -> str:
    """Style a success message."""
    return click.style(f"✓ {msg}", fg=GREEN)


def style_info(msg: str) -> str:
    """Style an info message."""
    return click.style(f"→ {msg}", fg=CYAN)


def style_warn(msg: str) -> str:
    """Style a warning message."""
    return click.style(f"! {msg}", fg=YELLOW)


def style_dim(msg: str) -> str:
    """Style dim/muted text."""
    return click.style(msg, fg=DIM)


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard. Returns True on success, False if unavailable."""
    # Try platform-specific clipboard commands
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

    return False


def output_cd(path: Path) -> None:
    """Write path to WT_CD_FILE for shell wrapper to handle directory change."""
    cd_file = os.environ.get("WT_CD_FILE")
    if cd_file:
        Path(cd_file).write_text(str(path))
    click.echo(f"{CD_MARKER}{path}")


def run_git(*args: str, capture: bool = True, cwd: Path | None = None) -> str | None:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=capture,
            text=True,
            cwd=cwd,
            check=True,
        )
        return result.stdout.strip() if capture else None
    except subprocess.CalledProcessError:
        return None


def find_repo_root() -> Path | None:
    """Find the root of the main git repository (not worktree)."""
    # Get the common git dir (shared across worktrees)
    git_common = run_git("rev-parse", "--git-common-dir")
    if not git_common:
        return None

    git_common_path = Path(git_common).resolve()

    # If it's a bare repo's .git or ends with .git, parent is repo root
    if git_common_path.name == ".git":
        return git_common_path.parent

    # For worktrees, git-common-dir points to main repo's .git
    return git_common_path.parent


def get_worktrees_dir(repo_root: Path) -> Path:
    """Get the worktrees directory (repo.worktrees/)."""
    return repo_root.parent / f"{repo_root.name}.worktrees"


def get_worktree_path(repo_root: Path, name: str) -> Path:
    """Get the full path for a named worktree."""
    return get_worktrees_dir(repo_root) / name


def get_default_branch(repo_root: Path) -> str:
    """Detect the default branch (main/master/etc)."""
    # Try to get from remote HEAD
    result = run_git("symbolic-ref", "refs/remotes/origin/HEAD", cwd=repo_root)
    if result:
        return result.split("/")[-1]

    # Check common names
    for branch in ["main", "master"]:
        if run_git("rev-parse", "--verify", f"refs/heads/{branch}", cwd=repo_root):
            return branch

    return "main"  # fallback


def get_current_branch() -> str | None:
    """Get the current branch name."""
    return run_git("branch", "--show-current")


def is_worktree_dirty(worktree_path: Path) -> bool:
    """Check if a worktree has uncommitted changes."""
    result = run_git("status", "--porcelain", cwd=worktree_path)
    return bool(result and result.strip())


def list_worktrees(repo_root: Path) -> list[WorktreeInfo]:
    """List all worktrees for the repository."""
    result = run_git("worktree", "list", "--porcelain", cwd=repo_root)
    if not result:
        return []

    worktrees: list[WorktreeInfo] = []
    current: dict[str, str] = {}

    for line in result.split("\n"):
        if not line:
            if current.get("worktree"):
                path = Path(current["worktree"])
                worktrees.append(
                    WorktreeInfo(
                        path=path,
                        name=path.name,
                        branch=current.get("branch", "").replace("refs/heads/", "")
                        or None,
                        is_bare="bare" in current,
                    )
                )
            current = {}
        elif line.startswith("worktree "):
            current["worktree"] = line[9:]
        elif line.startswith("branch "):
            current["branch"] = line[7:]
        elif line == "bare":
            current["bare"] = "true"

    # Handle last entry
    if current.get("worktree"):
        path = Path(current["worktree"])
        worktrees.append(
            WorktreeInfo(
                path=path,
                name=path.name,
                branch=current.get("branch", "").replace("refs/heads/", "") or None,
                is_bare="bare" in current,
            )
        )

    return worktrees


def list_branches(repo_root: Path, include_remote: bool = True) -> list[str]:
    """List all branches."""
    args = ["branch", "--format=%(refname:short)"]
    if include_remote:
        args.append("-a")

    result = run_git(*args, cwd=repo_root)
    if not result:
        return []

    branches: list[str] = []
    for line in result.split("\n"):
        branch = line.strip()
        if branch and "HEAD" not in branch:
            branches.append(branch)

    return sorted(set(branches))


def list_prs() -> list[PRInfo]:
    """Fetch open PRs from GitHub using gh CLI."""
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--json",
                "number,title,headRefName,isDraft",
                "--limit",
                "100",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        return [
            PRInfo(
                number=pr["number"],
                title=pr["title"],
                branch=pr["headRefName"],
                is_draft=pr["isDraft"],
            )
            for pr in data
        ]
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return []


def fuzzy_select(options: list[str], message: str) -> int | None:
    """Show fuzzy select menu. Returns index or None if cancelled."""
    try:
        prompt = inquirer.fuzzy(  # type: ignore[attr-defined]
            message=message,
            choices=options,
        )
        result = prompt.execute()
        if result is None:
            return None
        return options.index(result)
    except KeyboardInterrupt:
        return None


def select_from_menu(title: str, options: list[str]) -> str | None:
    """Display interactive menu and return selection."""
    if not options:
        click.echo(style_error("No options available."), err=True)
        return None

    index = fuzzy_select(options, title)
    if index is None:
        return None
    return options[index]


def format_branch_option(branch: str) -> str:
    """Format a branch name for display in menu."""
    if branch.startswith("origin/"):
        # Remote branch - show dimmed remote prefix
        remote_part = click.style("origin/", fg=DIM)
        branch_part = click.style(branch[7:], fg=CYAN)
        return f"{remote_part}{branch_part}"
    # Local branch
    return click.style(branch, fg=GREEN)


def fetch_origin(repo_root: Path) -> bool:
    """Fetch from origin. Returns True on success."""
    click.echo(style_info("Fetching from origin..."))
    result = subprocess.run(
        ["git", "fetch", "origin"],
        check=False,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def prompt_base_branch(repo_root: Path) -> str | None:
    """Prompt for base branch: main (default), HEAD, or pick a branch."""
    # Fetch to ensure we have latest remote state
    fetch_origin(repo_root)

    default_branch = get_default_branch(repo_root)
    branches = list_branches(repo_root, include_remote=False)

    # Build options: default branch first, then HEAD, then "Pick..."
    base_options = [f"{default_branch} (default)", "HEAD (current)"]
    if branches:
        base_options.append("Pick a branch...")

    index = fuzzy_select(base_options, "Branch from")
    if index is None:
        return None

    if index == 0:
        # Use remote version of default branch for latest commits
        return f"origin/{default_branch}"
    if index == 1:
        return "HEAD"
    # Pick from all branches (includes remotes)
    all_branches = list_branches(repo_root)
    return select_from_menu("Select base branch", all_branches)


def prompt_fork_base(repo_root: Path) -> str | None:
    """Prompt for fork base: HEAD (default), main, or pick a branch."""
    default_branch = get_default_branch(repo_root)
    branches = list_branches(repo_root, include_remote=False)

    # Build options: HEAD first (default for fork), then main, then "Pick..."
    base_options = ["HEAD (current)", f"{default_branch}"]
    if branches:
        base_options.append("Pick a branch...")

    index = fuzzy_select(base_options, "Branch from")
    if index is None:
        return None

    if index == 0:
        return "HEAD"
    if index == 1:
        # Fetch and use remote version for latest commits
        fetch_origin(repo_root)
        return f"origin/{default_branch}"
    # Pick from all branches (includes remotes)
    fetch_origin(repo_root)
    all_branches = list_branches(repo_root)
    return select_from_menu("Select base branch", all_branches)


def select_branch_interactive(repo_root: Path) -> tuple[str, bool] | None:
    """Interactive branch selection. Returns (branch_name, is_new_branch) or None."""
    branches = list_branches(repo_root)

    # Special option at the top
    special_opts = ["[+] Create new branch"]
    options = special_opts + branches

    index = fuzzy_select(options, "Select branch")
    if index is None:
        return None

    if index == 0:  # Create new branch
        branch_name = click.prompt(
            click.style("  New branch name", fg=CYAN), prompt_suffix=" → "
        )
        base = prompt_base_branch(repo_root)
        if not base:
            return None
        # Create branch from selected base
        if base != "HEAD":
            run_git("branch", branch_name, base, cwd=repo_root)
            return (branch_name, False)  # Branch exists now, no need for -b
        return (branch_name, True)
    # Return actual branch name
    return (branches[index - len(special_opts)], False)


def create_worktree(
    repo_root: Path, name: str, branch: str, *, new_branch: bool = False
) -> Path | None:
    """Create a worktree. Returns path on success, None on failure."""
    worktree_path = get_worktree_path(repo_root, name)

    if worktree_path.exists():
        click.echo(
            style_error(f"Worktree '{name}' already exists at {worktree_path}"),
            err=True,
        )
        return None

    # Ensure worktrees directory exists
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    # Build command
    args = ["worktree", "add"]
    if new_branch:
        args.extend(["-b", branch, str(worktree_path)])
    else:
        args.extend([str(worktree_path), branch])

    result = subprocess.run(
        ["git", *args],
        check=False,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        click.echo(style_success(f"Created worktree '{name}'"))
        click.echo(style_dim(f"  {worktree_path}"))
        return worktree_path
    click.echo(style_error(f"Failed to create worktree: {result.stderr}"), err=True)
    return None


def require_repo() -> Path:
    """Get repo root or exit with error."""
    repo_root = find_repo_root()
    if not repo_root:
        click.echo(style_error("Not in a git repository"), err=True)
        sys.exit(1)
    return repo_root


# CLI Commands


@click.group(invoke_without_command=True)
@click.version_option(package_name="wt")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Git worktree manager with interactive selection."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(switch_cmd)


@cli.command()
@click.argument("name", required=False)
@click.option("-b", "--branch", help="Branch to checkout/create (non-interactive)")
def create(name: str | None, branch: str | None) -> None:
    """Create a new worktree.

    Without -b flag, shows interactive branch picker.
    """
    repo_root = require_repo()

    if branch:
        # Non-interactive mode
        if not name:
            click.echo(style_error("Name required when using -b flag"), err=True)
            sys.exit(1)

        # Check if branch exists
        existing = run_git(
            "rev-parse", "--verify", f"refs/heads/{branch}", cwd=repo_root
        )
        new_branch = existing is None

        if new_branch:
            # Create from default branch
            default = get_default_branch(repo_root)
            run_git("branch", branch, default, cwd=repo_root)

        worktree_path = create_worktree(repo_root, name, branch, new_branch=False)
        if worktree_path:
            output_cd(worktree_path)
    else:
        # Interactive mode
        result = select_branch_interactive(repo_root)
        if not result:
            click.echo(style_dim("Cancelled."))
            return

        selected_branch, is_new = result

        if not name:
            # Suggest name from branch
            suggested = selected_branch.replace("origin/", "").replace("/", "-")
            name = click.prompt(
                click.style("  Worktree name", fg=CYAN),
                default=suggested,
                prompt_suffix=" → ",
            )

        worktree_path = create_worktree(
            repo_root, name, selected_branch, new_branch=is_new
        )
        if worktree_path:
            output_cd(worktree_path)


@cli.command()
@click.argument("name", required=False)
def pr(name: str | None) -> None:
    """Create worktree from a GitHub PR.

    Shows interactive PR picker.
    """
    repo_root = require_repo()

    click.echo(style_info("Fetching PRs from GitHub..."))
    prs = list_prs()
    if not prs:
        click.echo(
            style_error("No open PRs found (or gh CLI not available)."), err=True
        )
        sys.exit(1)

    # Format PR options
    options: list[str] = []
    for p in prs:
        draft = " [draft]" if p.is_draft else ""
        options.append(f"#{p.number}{draft} {p.branch} - {p.title}")

    index = fuzzy_select(options, "Select PR")
    if index is None:
        click.echo(style_dim("Cancelled."))
        return

    selected_pr = prs[index]

    # Fetch the PR branch
    click.echo(style_info(f"Fetching PR #{selected_pr.number}..."))
    subprocess.run(
        ["gh", "pr", "checkout", str(selected_pr.number), "--detach"],
        check=False,
        capture_output=True,
    )

    # Use branch name as default worktree name
    if not name:
        suggested = selected_pr.branch.replace("/", "-")
        name = click.prompt(
            click.style("  Worktree name", fg=CYAN),
            default=suggested,
            prompt_suffix=" → ",
        )

    # Fetch and create worktree with the PR's branch
    run_git(
        "fetch",
        "origin",
        f"pull/{selected_pr.number}/head:{selected_pr.branch}",
        cwd=repo_root,
    )
    worktree_path = create_worktree(
        repo_root, name, selected_pr.branch, new_branch=False
    )
    if worktree_path:
        output_cd(worktree_path)


@cli.command()
@click.argument("name", required=False)
def fork(name: str | None) -> None:
    """Create worktree with a new branch.

    Prompts for branch name, then base branch (defaults to current HEAD).
    """
    repo_root = require_repo()

    # Prompt for new branch name
    new_branch = click.prompt(
        click.style("  New branch name", fg=CYAN),
        prompt_suffix=" → ",
    )

    # Prompt for base branch (default to HEAD)
    base = prompt_fork_base(repo_root)
    if not base:
        click.echo(style_dim("Cancelled."))
        return

    # Prompt for worktree name
    if not name:
        suggested = new_branch.replace("/", "-")
        name = click.prompt(
            click.style("  Worktree name", fg=CYAN),
            default=suggested,
            prompt_suffix=" → ",
        )

    # Create branch from base if not HEAD
    if base != "HEAD":
        run_git("branch", new_branch, base, cwd=repo_root)
        worktree_path = create_worktree(repo_root, name, new_branch, new_branch=False)
    else:
        worktree_path = create_worktree(repo_root, name, new_branch, new_branch=True)

    if worktree_path:
        output_cd(worktree_path)


@cli.command("list")
def list_cmd() -> None:
    """List all worktrees."""
    repo_root = require_repo()

    worktrees = list_worktrees(repo_root)

    if not worktrees:
        click.echo(style_dim("No worktrees found."))
        return

    for wt in worktrees:
        name_styled = click.style(wt.name, fg=CYAN, bold=True)

        if wt.is_bare:
            branch_styled = click.style("[bare]", fg=DIM)
        elif wt.branch:
            branch_styled = click.style(f"[{wt.branch}]", fg=GREEN)
        else:
            branch_styled = click.style("[detached]", fg=YELLOW)

        path_styled = click.style(str(wt.path), fg=DIM)

        click.echo(f"  {name_styled:30} {branch_styled:40} {path_styled}")


@cli.command("switch")
@click.argument("name", required=False)
def switch_cmd(name: str | None) -> None:
    """Switch to a worktree.

    Without NAME, shows interactive picker.
    """
    repo_root = require_repo()

    if name:
        # Direct switch
        worktree_path = get_worktree_path(repo_root, name)
        if not worktree_path.exists():
            click.echo(
                style_error(f"Worktree '{name}' not found at {worktree_path}"), err=True
            )
            sys.exit(1)
        output_cd(worktree_path)
        return

    # Interactive mode
    worktrees = list_worktrees(repo_root)
    # Filter out bare repo
    worktrees = [wt for wt in worktrees if not wt.is_bare]

    if not worktrees:
        click.echo(style_error("No worktrees found."), err=True)
        sys.exit(1)

    # Format options
    options: list[str] = []
    for wt in worktrees:
        branch_info = f"[{wt.branch}]" if wt.branch else "[detached]"
        options.append(f"{wt.name} {branch_info}")

    index = fuzzy_select(options, "Select worktree")
    if index is None:
        click.echo(style_dim("Cancelled."))
        return

    selected = worktrees[index]
    output_cd(selected.path)


def do_remove_worktree(
    repo_root: Path, name: str, worktree_path: Path, *, force: bool = False
) -> bool:
    """Remove a worktree with dirty check and cd-back logic. Returns True on success."""
    # Check if we're in the worktree being removed
    cwd = Path.cwd().resolve()
    in_removed_worktree = cwd == worktree_path.resolve() or str(cwd).startswith(
        str(worktree_path.resolve()) + os.sep
    )

    # Check if dirty and prompt if needed
    if not force and is_worktree_dirty(worktree_path):
        if not click.confirm(
            style_warn(f"Worktree '{name}' has uncommitted changes. Remove anyway?"),
            default=False,
        ):
            click.echo(style_dim("Cancelled."))
            return False
        force = True

    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree_path))

    result = subprocess.run(
        ["git", *args], check=False, cwd=repo_root, capture_output=True, text=True
    )

    if result.returncode == 0:
        click.echo(style_success(f"Removed worktree '{name}'"))
        # Switch back to main repo if we were in the removed worktree
        if in_removed_worktree:
            output_cd(repo_root)
        return True
    click.echo(style_error(f"Failed to remove: {result.stderr}"), err=True)
    return False


@cli.command()
@click.argument("name", required=False)
@click.option("-f", "--force", is_flag=True, help="Force remove even if dirty")
def remove(name: str | None, *, force: bool) -> None:
    """Remove a worktree.

    Without NAME, shows interactive picker.
    """
    repo_root = require_repo()

    if name is None:
        # Interactive mode
        worktrees = list_worktrees(repo_root)
        worktrees = [wt for wt in worktrees if not wt.is_bare]

        if not worktrees:
            click.echo(style_error("No worktrees found."), err=True)
            sys.exit(1)

        # Format options
        options: list[str] = []
        for wt in worktrees:
            branch_info = f"[{wt.branch}]" if wt.branch else "[detached]"
            options.append(f"{wt.name} {branch_info}")

        index = fuzzy_select(options, "Select worktree to remove")
        if index is None:
            click.echo(style_dim("Cancelled."))
            return

        selected = worktrees[index]
        name = selected.name
        worktree_path = selected.path

        # Confirm removal
        if not click.confirm(style_warn(f"Remove worktree '{name}'?"), default=False):
            click.echo(style_dim("Cancelled."))
            return
    else:
        worktree_path = get_worktree_path(repo_root, name)

        if not worktree_path.exists():
            click.echo(
                style_error(f"Worktree '{name}' not found at {worktree_path}"), err=True
            )
            sys.exit(1)

    if not do_remove_worktree(repo_root, name, worktree_path, force=force):
        sys.exit(1)


@cli.command()
@click.argument("name", required=False)
def claude(name: str | None) -> None:
    """Open Claude Code in a worktree.

    Without NAME, shows interactive picker.
    """
    repo_root = require_repo()

    if name is None:
        # Interactive mode
        worktrees = list_worktrees(repo_root)
        worktrees = [wt for wt in worktrees if not wt.is_bare]

        if not worktrees:
            click.echo(style_error("No worktrees found."), err=True)
            sys.exit(1)

        options: list[str] = []
        for wt in worktrees:
            branch_info = f"[{wt.branch}]" if wt.branch else "[detached]"
            options.append(f"{wt.name} {branch_info}")

        index = fuzzy_select(options, "Select worktree for Claude")
        if index is None:
            click.echo(style_dim("Cancelled."))
            return

        worktree_path = worktrees[index].path
    else:
        worktree_path = get_worktree_path(repo_root, name)

        if not worktree_path.exists():
            click.echo(
                style_error(f"Worktree '{name}' not found at {worktree_path}"), err=True
            )
            sys.exit(1)

    click.echo(style_info(f"Opening Claude in {worktree_path}..."))
    subprocess.run(["claude"], check=False, cwd=worktree_path)


@cli.command()
@click.argument("name")
def path(name: str) -> None:
    """Print the path to a worktree."""
    repo_root = require_repo()

    worktree_path = get_worktree_path(repo_root, name)

    if not worktree_path.exists():
        click.echo(style_error(f"Worktree '{name}' not found"), err=True)
        sys.exit(1)

    # Output just the path (no styling for piping)
    click.echo(worktree_path)


# Shell integration scripts
SHELL_WRAPPER_ZSH = """
# wt shell integration
export WT_CD_FILE="${TMPDIR:-/tmp}/.wt_cd_$$"

wt() {
    rm -f "$WT_CD_FILE"
    "${WT_BIN:-$HOME/.local/bin/wt}" "$@"
    local exit_code=$?

    if [[ -f "$WT_CD_FILE" ]]; then
        cd "$(cat "$WT_CD_FILE")"
        rm -f "$WT_CD_FILE"
    fi

    return $exit_code
}

# wt completions for zsh
_wt_worktrees() {
    local worktrees_dir
    worktrees_dir="$(git rev-parse --show-toplevel 2>/dev/null).worktrees"
    [[ -d "$worktrees_dir" ]] && ls "$worktrees_dir" 2>/dev/null
}

_wt_branches() {
    git branch -a --format='%(refname:short)' 2>/dev/null | grep -v HEAD
}

_wt() {
    local state
    _arguments -C \\
        '1: :->command' \\
        '*: :->args'

    case $state in
        command)
            local commands=(
                'create:Create a new worktree'
                'cr:Create a new worktree (alias)'
                'switch:Switch to a worktree'
                'sw:Switch to a worktree (alias)'
                'pr:Create worktree from a GitHub PR'
                'fork:Create worktree from current branch'
                'fk:Create worktree from current branch (alias)'
                'list:List all worktrees'
                'ls:List all worktrees (alias)'
                'remove:Remove a worktree'
                'rm:Remove a worktree (alias)'
                'cleanup:Remove the current worktree'
                'claude:Open Claude Code in a worktree'
                'c:Open Claude Code in a worktree (alias)'
                'path:Print the path to a worktree'
                'install:Install shell integration'
            )
            _describe 'command' commands
            ;;
        args)
            case $words[2] in
                switch|sw|remove|rm|claude|c|path)
                    local worktrees=($(_wt_worktrees))
                    _describe 'worktree' worktrees
                    ;;
                create|cr)
                    if [[ "$words[-2]" == "-b" || "$words[-2]" == "--branch" ]]; then
                        local branches=($(_wt_branches))
                        _describe 'branch' branches
                    fi
                    ;;
            esac
            ;;
    esac
}

compdef _wt wt
"""

SHELL_WRAPPER_BASH = """
# wt shell integration
export WT_CD_FILE="${TMPDIR:-/tmp}/.wt_cd_$$"

wt() {
    rm -f "$WT_CD_FILE"
    "${WT_BIN:-$HOME/.local/bin/wt}" "$@"
    local exit_code=$?

    if [[ -f "$WT_CD_FILE" ]]; then
        cd "$(cat "$WT_CD_FILE")"
        rm -f "$WT_CD_FILE"
    fi

    return $exit_code
}

# wt completions for bash
_wt_worktrees() {
    local worktrees_dir
    worktrees_dir="$(git rev-parse --show-toplevel 2>/dev/null).worktrees"
    [[ -d "$worktrees_dir" ]] && ls "$worktrees_dir" 2>/dev/null
}

_wt_branches() {
    git branch -a --format='%(refname:short)' 2>/dev/null | grep -v HEAD
}

_wt_completions() {
    local cur prev commands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    commands="create cr switch sw pr fork fk list ls remove rm cleanup claude c path install"

    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=($(compgen -W "$commands" -- "$cur"))
        return 0
    fi

    case "${COMP_WORDS[1]}" in
        switch|sw|remove|rm|claude|c|path)
            COMPREPLY=($(compgen -W "$(_wt_worktrees)" -- "$cur"))
            ;;
        create|cr)
            if [[ "$prev" == "-b" || "$prev" == "--branch" ]]; then
                COMPREPLY=($(compgen -W "$(_wt_branches)" -- "$cur"))
            fi
            ;;
    esac
    return 0
}

complete -F _wt_completions wt
"""


INSTALL_LINE = 'eval "$(wt install --print)"'


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
    """Install shell integration (cd support + completions).

    Appends to ~/.zshrc or ~/.bashrc.
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

    # Just print the script (used by eval)
    if print_only:
        if shell == "zsh":
            click.echo(SHELL_WRAPPER_ZSH)
        else:
            click.echo(SHELL_WRAPPER_BASH)
        return

    # Determine config file
    home = Path.home()
    config_file = home / ".zshrc" if shell == "zsh" else home / ".bashrc"

    # Check if already installed
    source_cmd = f"source {config_file}"
    if config_file.exists():
        content = config_file.read_text()
        if INSTALL_LINE in content:
            click.echo(style_info(f"Already installed in {config_file}"))
            click.echo(style_dim(f"  Restart your shell or run: {source_cmd}"))
            if copy_to_clipboard(source_cmd):
                click.echo(style_dim("  (copied to clipboard)"))
            return

    # Append to config
    with config_file.open("a") as f:
        f.write(f"\n# wt shell integration\n{INSTALL_LINE}\n")

    click.echo(style_success(f"Installed to {config_file}"))
    click.echo(style_dim(f"  Restart your shell or run: {source_cmd}"))
    if copy_to_clipboard(source_cmd):
        click.echo(style_dim("  (copied to clipboard)"))


@cli.command()
def cleanup() -> None:
    """Remove the current worktree.

    Prompts for confirmation, checks for uncommitted changes,
    and switches back to the main repo after removal.
    """
    repo_root = require_repo()
    cwd = Path.cwd().resolve()

    # Find which worktree we're in
    worktrees = list_worktrees(repo_root)
    current_wt: WorktreeInfo | None = None

    for wt in worktrees:
        if wt.is_bare:
            continue
        wt_path = wt.path.resolve()
        if cwd == wt_path or str(cwd).startswith(str(wt_path) + os.sep):
            current_wt = wt
            break

    if current_wt is None:
        click.echo(style_error("Not in a worktree."), err=True)
        sys.exit(1)

    # Check if in main repo
    if current_wt.path.resolve() == repo_root.resolve():
        click.echo(style_error("Cannot cleanup the main repository."), err=True)
        sys.exit(1)

    # Confirm removal
    if not click.confirm(
        style_warn(f"Remove current worktree '{current_wt.name}'?"), default=False
    ):
        click.echo(style_dim("Cancelled."))
        return

    branch_to_delete = current_wt.branch

    if not do_remove_worktree(repo_root, current_wt.name, current_wt.path):
        sys.exit(1)

    # Offer to delete the branch
    if branch_to_delete:
        if click.confirm(
            style_warn(f"Delete branch '{branch_to_delete}'?"), default=False
        ):
            result = run_git("branch", "-d", branch_to_delete, cwd=repo_root)
            if result is not None:
                click.echo(style_success(f"Deleted branch '{branch_to_delete}'"))
            # Try force delete if normal delete fails
            elif click.confirm(
                style_warn(
                    f"Branch '{branch_to_delete}' is not fully merged. Force delete?"
                ),
                default=False,
            ):
                result = run_git("branch", "-D", branch_to_delete, cwd=repo_root)
                if result is not None:
                    click.echo(
                        style_success(f"Force deleted branch '{branch_to_delete}'")
                    )
                else:
                    click.echo(
                        style_error(f"Failed to delete branch '{branch_to_delete}'"),
                        err=True,
                    )


# Short aliases for frequently used commands
cli.add_command(create, name="cr")
cli.add_command(switch_cmd, name="sw")
cli.add_command(list_cmd, name="ls")
cli.add_command(remove, name="rm")
cli.add_command(fork, name="fk")
cli.add_command(pr, name="pr")  # already 2 letters
cli.add_command(claude, name="c")


if __name__ == "__main__":
    cli()
