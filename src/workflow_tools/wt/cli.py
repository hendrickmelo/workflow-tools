"""Git worktree manager with interactive selection UI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import click

from workflow_tools.common import (
    CYAN,
    DIM,
    GREEN,
    YELLOW,
    ValidationError,
    fuzzy_select,
    get_default_branch,
    list_branches,
    require_repo,
    run_git,
    select_from_menu,
    style_dim,
    style_error,
    style_info,
    style_success,
    style_warn,
    validate_pr_number,
    validate_worktree_name,
)
from workflow_tools.common.git import fetch_origin, is_repo_dirty
from workflow_tools.common.shell import output_cd as _output_cd
from workflow_tools.pr.api import list_prs_simple


def output_cd(path: Path) -> None:
    """Write path to WT_CD_FILE for shell wrapper."""
    _output_cd(path, env_var="WT_CD_FILE")


class WorktreeInfo(NamedTuple):
    """Information about a git worktree."""

    path: Path
    name: str
    branch: str | None
    is_bare: bool


def get_worktrees_dir(repo_root: Path) -> Path:
    """Get the worktrees directory (repo.worktrees/)."""
    return repo_root.parent / f"{repo_root.name}.worktrees"


def get_worktree_path(repo_root: Path, name: str) -> Path:
    """Get the full path for a named worktree."""
    return get_worktrees_dir(repo_root) / name


def is_worktree_dirty(worktree_path: Path) -> bool:
    """Check if a worktree has uncommitted changes."""
    return is_repo_dirty(worktree_path)


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


def format_branch_option(branch: str) -> str:
    """Format a branch name for display in menu."""
    if branch.startswith("origin/"):
        # Remote branch - show dimmed remote prefix
        remote_part = click.style("origin/", fg=DIM)
        branch_part = click.style(branch[7:], fg=CYAN)
        return f"{remote_part}{branch_part}"
    # Local branch
    return click.style(branch, fg=GREEN)


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
            result = run_git("branch", branch_name, base, cwd=repo_root)
            if result is None:
                click.echo(
                    style_error(
                        f"Failed to create branch '{branch_name}' from '{base}'"
                    ),
                    err=True,
                )
                return None
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


# CLI Commands


@click.group(invoke_without_command=True)
@click.version_option(package_name="workflow-tools")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Git worktree manager with interactive selection.

    EXAMPLES:
        wt                  # Interactive: pick worktree to switch to
        wt create           # Interactive: create new worktree
        wt create foo       # Create worktree named 'foo'
        wt pr               # Create worktree from GitHub PR
        wt fork             # Create worktree with new branch
        wt list             # List all worktrees
        wt remove foo       # Remove worktree 'foo'
        wt cleanup          # Remove current worktree

    ALIASES:
        wt sw = wt switch
        wt cr = wt create
        wt ls = wt list
        wt rm = wt remove
        wt fk = wt fork
        wt c  = wt claude
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(switch_cmd)


@cli.command()
@click.argument("name", required=False)
@click.option("-b", "--branch", help="Branch to checkout/create (non-interactive)")
def create(name: str | None, branch: str | None) -> None:
    """Create a new worktree.

    Without -b flag, shows interactive branch picker.

    EXAMPLES:
        wt create                    # Interactive mode
        wt create foo -b feature     # Create 'foo' with branch 'feature'
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
            git_result = run_git("branch", branch, default, cwd=repo_root)
            if git_result is None:
                click.echo(
                    style_error(f"Failed to create branch '{branch}' from '{default}'"),
                    err=True,
                )
                sys.exit(1)

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

        # Validate worktree name
        try:
            name = validate_worktree_name(name)
        except ValidationError as e:
            click.echo(style_error(str(e)), err=True)
            return

        worktree_path = create_worktree(
            repo_root, name, selected_branch, new_branch=is_new
        )
        if worktree_path:
            output_cd(worktree_path)


@cli.command("pr")
@click.argument("name", required=False)
def pr_cmd(name: str | None) -> None:
    """Create worktree from a GitHub PR.

    Shows interactive PR picker.

    EXAMPLES:
        wt pr           # Interactive: pick from open PRs
        wt pr review    # Create worktree named 'review' from selected PR
    """
    repo_root = require_repo()

    click.echo(style_info("Fetching PRs from GitHub..."))
    prs = list_prs_simple()
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

    # Validate worktree name
    try:
        name = validate_worktree_name(name)
    except ValidationError as e:
        click.echo(style_error(str(e)), err=True)
        return

    # Validate PR number
    try:
        pr_num = validate_pr_number(selected_pr.number)
    except ValidationError as e:
        click.echo(style_error(str(e)), err=True)
        return

    # Fetch and create worktree with the PR's branch
    fetch_result = run_git(
        "fetch",
        "origin",
        f"pull/{pr_num}/head:{selected_pr.branch}",
        cwd=repo_root,
    )
    if fetch_result is None:
        click.echo(
            style_error(f"Failed to fetch PR #{pr_num}"),
            err=True,
        )
        return

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

    EXAMPLES:
        wt fork              # Interactive: create new branch
        wt fork feature      # Create worktree named 'feature'
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

    # Validate worktree name
    try:
        name = validate_worktree_name(name)
    except ValidationError as e:
        click.echo(style_error(str(e)), err=True)
        return

    # Create branch from base if not HEAD
    if base != "HEAD":
        result = run_git("branch", new_branch, base, cwd=repo_root)
        if result is None:
            click.echo(
                style_error(f"Failed to create branch '{new_branch}' from '{base}'"),
                err=True,
            )
            return
        worktree_path = create_worktree(repo_root, name, new_branch, new_branch=False)
    else:
        worktree_path = create_worktree(repo_root, name, new_branch, new_branch=True)

    if worktree_path:
        output_cd(worktree_path)


@cli.command("list")
def list_cmd() -> None:
    """List all worktrees.

    EXAMPLES:
        wt list
        wt ls
    """
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

    EXAMPLES:
        wt switch           # Interactive: pick worktree
        wt switch foo       # Switch to worktree 'foo'
        wt foo              # Same (switch is default command)
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

    EXAMPLES:
        wt remove           # Interactive: pick worktree to remove
        wt remove foo       # Remove worktree 'foo'
        wt rm foo -f        # Force remove even with uncommitted changes
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

    EXAMPLES:
        wt claude           # Interactive: pick worktree
        wt claude foo       # Open Claude in worktree 'foo'
        wt c foo            # Same (alias)
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
    """Print the path to a worktree.

    EXAMPLES:
        wt path foo         # Print path to worktree 'foo'
        cd $(wt path foo)   # Change to worktree directory
    """
    repo_root = require_repo()

    worktree_path = get_worktree_path(repo_root, name)

    if not worktree_path.exists():
        click.echo(style_error(f"Worktree '{name}' not found"), err=True)
        sys.exit(1)

    # Output just the path (no styling for piping)
    click.echo(worktree_path)


@cli.command()
def cleanup() -> None:
    """Remove the current worktree.

    Prompts for confirmation, checks for uncommitted changes,
    and switches back to the main repo after removal.

    EXAMPLES:
        wt cleanup          # Remove current worktree (with confirmation)
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
cli.add_command(claude, name="c")


if __name__ == "__main__":
    cli()
