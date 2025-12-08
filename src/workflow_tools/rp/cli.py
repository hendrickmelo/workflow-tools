"""Repository management CLI with fast discovery and interactive selection."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click

from workflow_tools.common import (
    CYAN,
    DIM,
    GREEN,
    YELLOW,
    fuzzy_select,
    style_dim,
    style_error,
    style_info,
    style_success,
    style_warn,
)
from workflow_tools.common.github import run_gh, run_gh_json
from workflow_tools.common.shell import output_cd as _output_cd
from workflow_tools.rp.discovery import RepoCache, RepoInfo


def output_cd(path: Path) -> None:
    """Write path to RP_CD_FILE for shell wrapper."""
    _output_cd(path, env_var="RP_CD_FILE")


def get_cache() -> RepoCache:
    """Get the repo cache instance."""
    return RepoCache()


def format_repo_options(repos: list[RepoInfo]) -> list[str]:
    """Format repos for display in picker (no ANSI codes - InquirerPy doesn't support them).

    Returns column-aligned options with name and path.
    """
    if not repos:
        return []

    max_name = max(len(r.name) for r in repos)
    options = []
    for repo in repos:
        name_padded = repo.name.ljust(max_name)
        path_short = repo.path.replace(str(Path.home()), "~")
        options.append(f"{name_padded}  {path_short}")
    return options


def select_directory(message: str, base_paths: list[Path] | None = None) -> Path | None:
    """Interactive directory selection for clone destination."""
    if base_paths is None:
        base_paths = [Path.home() / "Documents"]

    # Build list of directories (1-2 levels deep under base paths)
    dirs: list[Path] = []
    for base in base_paths:
        if not base.exists():
            continue
        dirs.append(base)
        try:
            dirs.extend(
                child
                for child in sorted(base.iterdir())
                if child.is_dir() and not child.name.startswith(".")
            )
        except PermissionError:
            continue

    options = [str(d).replace(str(Path.home()), "~") for d in dirs]
    options.append("[+] Enter custom path...")

    index = fuzzy_select(options, message)
    if index is None:
        return None

    if index == len(options) - 1:
        # Custom path
        custom = click.prompt("Path", type=click.Path())
        return Path(custom).expanduser()

    return dirs[index]


@click.group(invoke_without_command=True)
@click.version_option(package_name="workflow-tools")
@click.option(
    "--refresh", "-r", is_flag=True, help="Force cache refresh before selection"
)
@click.pass_context
def cli(ctx: click.Context, *, refresh: bool) -> None:
    """Repository management with fast discovery.

    Switch between repos, create new ones, fork, clone, and rename.

    EXAMPLES:
        rp                    # Interactive: pick repo to switch to
        rp -r                 # Refresh cache first
        rp list               # List all discovered repos
        rp create my-project  # Create new GitHub repo
        rp fork owner/repo    # Fork a GitHub repo
        rp clone              # Clone one of your GitHub repos
        rp rename old new     # Rename local folder and GitHub repo
        rp refresh            # Force refresh repo cache

    ALIASES:
        rp sw = rp switch
        rp ls = rp list
        rp cr = rp create
        rp fk = rp fork
        rp cl = rp clone
        rp rn = rp rename
        rp rf = rp refresh
    """
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        ctx.invoke(switch_cmd, refresh=refresh)


@cli.command("switch")
@click.argument("name", required=False)
@click.option(
    "--refresh", "-r", is_flag=True, help="Force cache refresh before selection"
)
def switch_cmd(name: str | None, *, refresh: bool) -> None:
    """Switch to a repository.

    Without NAME, shows interactive picker with fuzzy search.
    Press Ctrl+R in the picker to refresh the repo list.

    EXAMPLES:
        rp                      # Interactive: pick repo
        rp switch workflow      # Switch to repo named 'workflow'
        rp -r                   # Refresh cache first
    """
    cache = get_cache()
    force_refresh = refresh

    if name:
        # Direct switch - no interactive mode
        repos, _ = cache.get_repos(force_refresh=force_refresh, show_progress=True)
        if not repos:
            click.echo(style_error("No repositories found. Try 'rp refresh'"), err=True)
            sys.exit(1)
        repo = cache.find_repo(name)
        if not repo:
            click.echo(style_error(f"Repository '{name}' not found"), err=True)
            sys.exit(1)
        output_cd(Path(repo.path))
        return

    # Interactive mode with refresh option
    while True:
        repos, from_cache = cache.get_repos(
            force_refresh=force_refresh, show_progress=True
        )

        if not repos:
            click.echo(style_error("No repositories found. Try 'rp refresh'"), err=True)
            sys.exit(1)

        options = format_repo_options(repos)
        # Add refresh option at the top if using cache
        if from_cache:
            options = ["[refresh list]", *options]

        index = fuzzy_select(options, "Select repository")

        if index is None:
            click.echo(style_dim("Cancelled."))
            return

        # Handle refresh option
        if from_cache and index == 0:
            force_refresh = True
            continue

        # Adjust index if refresh option was present
        repo_index = index - 1 if from_cache else index
        selected = repos[repo_index]
        output_cd(Path(selected.path))
        return


@cli.command("list")
@click.option("--json", "-j", "as_json", is_flag=True, help="Output as JSON")
@click.option("--path-only", is_flag=True, help="Output just paths (one per line)")
@click.option("--refresh", "-r", is_flag=True, help="Force cache refresh")
def list_cmd(*, as_json: bool, path_only: bool, refresh: bool) -> None:
    """List all discovered repositories.

    EXAMPLES:
        rp list               # List all repos
        rp ls --json          # JSON output
        rp ls --path-only     # Just paths for scripting
        rp ls -r              # Refresh cache first
    """
    cache = get_cache()
    repos, _ = cache.get_repos(force_refresh=refresh, show_progress=True)

    if as_json:
        click.echo(json.dumps([r._asdict() for r in repos], indent=2))
        return

    if path_only:
        for repo in repos:
            click.echo(repo.path)
        return

    if not repos:
        click.echo(style_dim("No repositories found"))
        return

    # Calculate max widths for alignment
    max_name = max(len(r.name) for r in repos)
    max_path = max(len(r.path.replace(str(Path.home()), "~")) for r in repos)

    for repo in repos:
        # Pad raw strings BEFORE styling
        name_padded = repo.name.ljust(max_name)
        path_short = repo.path.replace(str(Path.home()), "~")
        path_padded = path_short.ljust(max_path)

        # Now apply styling
        name_styled = click.style(name_padded, fg=CYAN, bold=True)
        path_styled = click.style(path_padded, fg=DIM)

        remote_badge = ""
        if repo.remote_type == "github":
            remote_badge = click.style("[github]", fg=GREEN)
        elif repo.remote_type == "local":
            remote_badge = click.style("[local]", fg=YELLOW)
        elif repo.remote_type != "other":
            remote_badge = click.style(f"[{repo.remote_type}]", fg=DIM)

        click.echo(f"  {name_styled} {path_styled} {remote_badge}")


@cli.command()
def refresh() -> None:
    """Force refresh the repository cache.

    Scans ~/Documents for git repositories and updates the cache.

    EXAMPLES:
        rp refresh
        rp rf
    """
    cache = get_cache()
    click.echo(style_info("Scanning for repositories..."))
    repos, _ = cache.get_repos(force_refresh=True)
    click.echo(style_success(f"Found {len(repos)} repositories"))


@cli.command()
@click.argument("name")
@click.option(
    "--public", "visibility", flag_value="public", help="Create public repository"
)
@click.option(
    "--private",
    "visibility",
    flag_value="private",
    default=True,
    help="Create private repository (default)",
)
@click.option("--description", "-d", help="Repository description")
@click.option(
    "--path", "-p", type=click.Path(), help="Destination directory (skip prompt)"
)
@click.option("--no-clone", is_flag=True, help="Create on GitHub only, don't clone")
def create(
    name: str,
    visibility: str,
    description: str | None,
    path: str | None,
    *,
    no_clone: bool,
) -> None:
    """Create a new GitHub repository.

    Creates a repo on GitHub and optionally clones it locally.

    EXAMPLES:
        rp create my-project              # Create private repo, prompt for location
        rp create my-project --public     # Create public repo
        rp create my-project -p ~/Code    # Create in specific directory
        rp create my-project --no-clone   # GitHub only
    """
    # Create repo on GitHub
    args = ["repo", "create", name, f"--{visibility}"]
    if description:
        args.extend(["--description", description])

    click.echo(style_info(f"Creating {visibility} repository '{name}' on GitHub..."))
    result = run_gh(*args)
    if result is None:
        click.echo(style_error("Failed to create repository"), err=True)
        sys.exit(1)

    click.echo(style_success(f"Created repository: {result.strip()}"))

    if no_clone:
        return

    # Determine destination
    dest_dir: Path
    if path:
        dest_dir = Path(path).expanduser()
    else:
        selected = select_directory("Clone to")
        if selected is None:
            click.echo(style_dim("Cancelled clone."))
            return
        dest_dir = selected

    clone_path = dest_dir / name

    # Clone via SSH
    click.echo(style_info(f"Cloning to {clone_path}..."))
    clone_result = subprocess.run(
        [
            "git",
            "clone",
            f"git@github.com:{result.strip().split('/')[-2]}/{name}.git",
            str(clone_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    if clone_result.returncode != 0:
        # Try HTTPS as fallback
        click.echo(style_warn("SSH clone failed, trying HTTPS..."))
        subprocess.run(
            ["gh", "repo", "clone", name, str(clone_path)],
            check=False,
        )

    if clone_path.exists():
        cache = get_cache()
        cache.add_repo(clone_path)
        click.echo(style_success(f"Cloned to {clone_path}"))
        output_cd(clone_path)
    else:
        click.echo(style_error("Clone failed"), err=True)
        sys.exit(1)


@cli.command()
@click.argument("repo", required=False)
@click.option(
    "--path", "-p", type=click.Path(), help="Destination directory (skip prompt)"
)
@click.option("--name", "-n", "custom_name", help="Custom local folder name")
@click.option("--no-clone", is_flag=True, help="Fork on GitHub only")
def fork(
    repo: str | None,
    path: str | None,
    custom_name: str | None,
    *,
    no_clone: bool,
) -> None:
    """Fork a GitHub repository.

    Creates a fork on your GitHub account and optionally clones it.

    EXAMPLES:
        rp fork owner/repo              # Fork and clone (prompts for location)
        rp fork owner/repo -p ~/Code    # Fork and clone to specific directory
        rp fork                         # Interactive: search GitHub repos
        rp fork owner/repo --no-clone   # Fork only, don't clone
    """
    if not repo:
        # Interactive search
        query = click.prompt("Search GitHub repos")
        result = run_gh_json(
            "search", "repos", "--json", "fullName,description", "--limit", "20", query
        )
        if not result:
            click.echo(style_error("Search failed or no results"), err=True)
            sys.exit(1)

        options = [
            f"{r['fullName']}  {click.style(r.get('description', '')[:40] or '', fg=DIM)}"
            for r in result
        ]
        index = fuzzy_select(options, "Select repo to fork")
        if index is None:
            click.echo(style_dim("Cancelled."))
            return

        repo = result[index]["fullName"]

    # Fork on GitHub
    click.echo(style_info(f"Forking {repo}..."))
    fork_result = run_gh("repo", "fork", repo, "--clone=false")
    if fork_result is None:
        click.echo(style_error("Failed to fork repository"), err=True)
        sys.exit(1)

    click.echo(style_success(f"Forked {repo}"))

    if no_clone:
        return

    # Determine destination
    dest_dir: Path
    if path:
        dest_dir = Path(path).expanduser()
    else:
        selected = select_directory("Clone to")
        if selected is None:
            click.echo(style_dim("Cancelled clone."))
            return
        dest_dir = selected

    # Get forked repo name (last part of owner/repo)
    repo_name = custom_name or repo.split("/")[-1]
    clone_path = dest_dir / repo_name

    # Get viewer's username for the fork URL
    viewer = run_gh("api", "user", "--jq", ".login")
    if not viewer:
        click.echo(style_error("Could not determine your GitHub username"), err=True)
        sys.exit(1)

    # Clone via SSH
    click.echo(style_info(f"Cloning to {clone_path}..."))
    clone_result = subprocess.run(
        [
            "git",
            "clone",
            f"git@github.com:{viewer.strip()}/{repo_name}.git",
            str(clone_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    if clone_result.returncode != 0:
        # Try with gh clone as fallback
        click.echo(style_warn("SSH clone failed, trying gh clone..."))
        subprocess.run(
            ["gh", "repo", "clone", f"{viewer.strip()}/{repo_name}", str(clone_path)],
            check=False,
        )

    if clone_path.exists():
        cache = get_cache()
        cache.add_repo(clone_path)
        click.echo(style_success(f"Cloned to {clone_path}"))
        output_cd(clone_path)
    else:
        click.echo(style_error("Clone failed"), err=True)
        sys.exit(1)


@cli.command()
@click.argument("repo_name", required=False)
@click.option(
    "--path", "-p", type=click.Path(), help="Destination directory (skip prompt)"
)
@click.option("--all", "-a", "clone_all", is_flag=True, help="Clone all uncloned repos")
def clone(repo_name: str | None, path: str | None, *, clone_all: bool) -> None:
    """Clone one of your own GitHub repositories.

    Shows a list of your GitHub repos, highlighting which are already cloned locally.

    EXAMPLES:
        rp clone              # Interactive: pick from your repos
        rp clone my-repo      # Clone specific repo
        rp clone -p ~/Code    # Clone to specific directory
    """
    # Get user's repos from GitHub
    click.echo(style_info("Fetching your repositories..."))
    gh_repos = run_gh_json(
        "repo", "list", "--json", "name,url,description", "--limit", "100"
    )
    if not gh_repos:
        click.echo(style_error("Failed to fetch repositories"), err=True)
        sys.exit(1)

    # Get local repos to check what's already cloned
    cache = get_cache()
    local_repos, _ = cache.get_repos()
    local_names = {r.name for r in local_repos}

    if repo_name:
        # Direct clone
        matching = [r for r in gh_repos if r["name"] == repo_name]
        if not matching:
            click.echo(style_error(f"Repository '{repo_name}' not found"), err=True)
            sys.exit(1)

        if repo_name in local_names:
            # Find path and switch to it
            for r in local_repos:
                if r.name == repo_name:
                    click.echo(style_info(f"'{repo_name}' already cloned at {r.path}"))
                    output_cd(Path(r.path))
                    return
    else:
        # Interactive selection
        options = []
        uncloned_repos = []
        for r in gh_repos:
            name = r["name"]
            desc = r.get("description", "")[:40] or ""
            if name in local_names:
                local_path = next(
                    (lr.path for lr in local_repos if lr.name == name), ""
                )
                short_path = local_path.replace(str(Path.home()), "~")
                options.append(
                    f"{name}  {click.style(f'[cloned: {short_path}]', fg=GREEN)}"
                )
            else:
                options.append(f"{name}  {click.style(desc, fg=DIM)}")
                uncloned_repos.append(r)

        if clone_all:
            if not uncloned_repos:
                click.echo(style_info("All repos are already cloned"))
                return
            repos_to_clone = uncloned_repos
        else:
            index = fuzzy_select(options, "Select repository")
            if index is None:
                click.echo(style_dim("Cancelled."))
                return

            selected = gh_repos[index]
            if selected["name"] in local_names:
                # Switch to existing repo
                for r in local_repos:
                    if r.name == selected["name"]:
                        click.echo(style_info(f"Already cloned, switching to {r.path}"))
                        output_cd(Path(r.path))
                        return
            repos_to_clone = [selected]

    # Determine destination
    dest_dir: Path
    if path:
        dest_dir = Path(path).expanduser()
    else:
        selected = select_directory("Clone to")
        if selected is None:
            click.echo(style_dim("Cancelled."))
            return
        dest_dir = selected

    # Clone the repos
    for repo in repos_to_clone:
        repo_name = repo["name"]
        clone_path = dest_dir / repo_name

        if clone_path.exists():
            click.echo(style_warn(f"Skipping {repo_name}: directory already exists"))
            continue

        click.echo(style_info(f"Cloning {repo_name}..."))

        # Clone via gh (handles SSH/HTTPS automatically)
        result = subprocess.run(
            ["gh", "repo", "clone", repo_name, str(clone_path)],
            check=False,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0 and clone_path.exists():
            cache.add_repo(clone_path)
            click.echo(style_success(f"Cloned {repo_name} to {clone_path}"))
        else:
            click.echo(style_error(f"Failed to clone {repo_name}"), err=True)

    # If single repo cloned, cd to it
    if len(repos_to_clone) == 1:
        clone_path = dest_dir / repos_to_clone[0]["name"]
        if clone_path.exists():
            output_cd(clone_path)


@cli.command()
@click.argument("old_name")
@click.argument("new_name")
@click.option("--local-only", is_flag=True, help="Only rename local folder")
@click.option("--github-only", is_flag=True, help="Only rename on GitHub")
def rename(
    old_name: str, new_name: str, *, local_only: bool, github_only: bool
) -> None:
    """Rename a repository (local folder and/or GitHub).

    EXAMPLES:
        rp rename old-name new-name     # Rename both local and GitHub
        rp rename old-name new-name --local-only   # Local only
        rp rename old-name new-name --github-only  # GitHub only
    """
    cache = get_cache()
    repo = cache.find_repo(old_name)

    if not github_only:
        if not repo:
            click.echo(
                style_error(f"Repository '{old_name}' not found locally"), err=True
            )
            sys.exit(1)

        old_path = Path(repo.path)
        new_path = old_path.parent / new_name

        if new_path.exists():
            click.echo(style_error(f"Directory '{new_path}' already exists"), err=True)
            sys.exit(1)

        # Rename local directory
        click.echo(style_info(f"Renaming {old_path} → {new_path}"))
        old_path.rename(new_path)
        cache.remove_repo(old_path)
        cache.add_repo(new_path)
        click.echo(style_success("Renamed local directory"))

    if not local_only:
        # Rename on GitHub
        click.echo(
            style_info(f"Renaming repository on GitHub: {old_name} → {new_name}")
        )
        result = run_gh("repo", "rename", new_name, "-y")
        if result is None:
            click.echo(style_error("Failed to rename on GitHub"), err=True)
            if not github_only:
                # Revert local rename
                new_path.rename(old_path)
                cache.remove_repo(new_path)
                cache.add_repo(old_path)
                click.echo(style_warn("Reverted local rename"))
            sys.exit(1)

        click.echo(style_success("Renamed on GitHub"))

        # Update git remote URL if we renamed locally
        if not github_only:
            new_path = old_path.parent / new_name
            viewer = run_gh("api", "user", "--jq", ".login")
            if viewer:
                new_url = f"git@github.com:{viewer.strip()}/{new_name}.git"
                subprocess.run(
                    ["git", "remote", "set-url", "origin", new_url],
                    cwd=new_path,
                    check=False,
                    capture_output=True,
                )
                click.echo(style_info(f"Updated remote URL to {new_url}"))

    if not github_only:
        output_cd(new_path)


# Command aliases
cli.add_command(switch_cmd, name="sw")
cli.add_command(list_cmd, name="ls")
cli.add_command(create, name="cr")
cli.add_command(fork, name="fk")
cli.add_command(clone, name="cl")
cli.add_command(rename, name="rn")
cli.add_command(refresh, name="rf")


if __name__ == "__main__":
    cli()
