"""GitHub PR management CLI with interactive selection UI."""

from __future__ import annotations

import json
import sys
import webbrowser

import click

from workflow_tools.common import (
    CYAN,
    DIM,
    GREEN,
    YELLOW,
    ValidationError,
    copy_to_clipboard,
    fuzzy_select,
    require_repo,
    run_git,
    style_dim,
    style_error,
    style_info,
    style_success,
    style_warn,
    validate_pr_number,
    validate_worktree_name,
)
from workflow_tools.common.shell import output_cd
from workflow_tools.common.ui import fuzzy_select_multi
from workflow_tools.pr.api import (
    ActionResult,
    PRInfo,
    ReviewThread,
    approve_pr,
    close_pr,
    format_date,
    get_current_branch,
    get_pending_review,
    get_pr_comments,
    get_pr_diff,
    get_pr_files,
    get_pr_for_branch,
    get_review_threads,
    get_viewer_login,
    list_open_prs,
    mark_draft,
    mark_ready,
    post_comment,
    reply_to_thread,
    request_changes,
    require_repo_info,
    resolve_thread,
    submit_pending_review,
    unresolve_thread,
)
from workflow_tools.wt.cli import create_worktree, get_worktree_path

# Preview truncation lengths
PREVIEW_SHORT = 40
PREVIEW_LONG = 50
DIFF_CONTEXT_LINES = 5


def get_pr_or_exit(pr_num: int | None, ctx_pr_num: int | None = None) -> PRInfo:
    """Get PR info or exit with error."""
    num = pr_num or ctx_pr_num
    pr = get_pr_for_branch(num)
    if not pr:
        if num:
            click.echo(style_error(f"PR #{num} not found"), err=True)
        else:
            branch = get_current_branch()
            click.echo(
                style_error(f"No PR found for branch '{branch}'"),
                err=True,
            )
        sys.exit(1)
    return pr


def format_pr_option(pr: PRInfo) -> str:
    """Format a PR for display in picker."""
    draft = " [draft]" if pr.is_draft else ""
    return f"#{pr.number}{draft} {pr.head_branch} - {pr.title}"


def print_action_results(results: list[ActionResult]) -> bool:
    """Print action results. Returns True if all succeeded."""
    any_failed = False
    for result in results:
        if result.success:
            click.echo(style_success(result.message))
        else:
            click.echo(style_error(result.message), err=True)
            any_failed = True
    return not any_failed


def format_thread_option(thread: ReviewThread) -> str:
    """Format a thread for display in picker."""
    status = "[resolved]" if thread.is_resolved else "[unresolved]"
    line = thread.line or thread.start_line or "?"
    preview = ""
    if thread.comments:
        preview = thread.comments[0].body[:PREVIEW_LONG].replace("\n", " ")
        if len(thread.comments[0].body) > PREVIEW_LONG:
            preview += "..."
    return f"{thread.path}:{line} {status} - {preview}"


@click.group(invoke_without_command=True)
@click.option(
    "-p", "--pr-num", type=int, help="PR number (default: current branch's PR)"
)
@click.version_option(package_name="workflow-tools")
@click.pass_context
def cli(ctx: click.Context, pr_num: int | None) -> None:
    """GitHub PR management with interactive selection.

    When run without a subcommand, shows interactive PR picker
    then displays PR info and actions menu.

    EXAMPLES:
        pr                    # Interactive: pick PR, then action
        pr info               # Show current branch's PR info
        pr info 123           # Show PR #123 info
        pr threads            # List unresolved threads
        pr resolve THREAD_ID  # Resolve a thread
        pr approve            # Approve current branch's PR

    THREAD IDS:
        Thread IDs look like: PRRT_kwDOABC123_abc456
        Get them from 'pr threads' or 'pr info' output.

    ALIASES:
        pr i  = pr info
        pr f  = pr files
        pr d  = pr diff
        pr t  = pr threads
        pr ls = pr list
        pr r  = pr resolve
        pr ur = pr unresolve
        pr re = pr reply
        pr c  = pr comment
        pr a  = pr approve
        pr rc = pr request-changes
        pr o  = pr open
        pr co = pr checkout
        pr sw = pr checkout
    """
    ctx.ensure_object(dict)
    ctx.obj["pr_num"] = pr_num

    if ctx.invoked_subcommand is None:
        ctx.invoke(interactive_mode)


@cli.command("interactive", hidden=True)
@click.pass_context
def interactive_mode(ctx: click.Context) -> None:
    """Interactive mode: pick PR, show actions menu."""
    pr_num = ctx.obj.get("pr_num")

    if not pr_num:
        # Pick from open PRs
        prs = list_open_prs()
        if not prs:
            click.echo(style_error("No open PRs found"), err=True)
            sys.exit(1)

        options = [format_pr_option(p) for p in prs]
        index = fuzzy_select(options, "Select PR")
        if index is None:
            click.echo(style_dim("Cancelled."))
            return

        pr_num = prs[index].number

    # Get full PR info
    pr = get_pr_or_exit(pr_num)
    owner, repo = require_repo_info()

    # Show PR summary
    draft = click.style(" [DRAFT]", fg=YELLOW) if pr.is_draft else ""
    click.echo()
    click.echo(
        click.style(f"PR #{pr.number}: ", fg=CYAN, bold=True)
        + click.style(pr.title, bold=True)
        + draft
    )
    click.echo(click.style(pr.url, fg=DIM))
    click.echo(f"  Author: {pr.author} | Base: {pr.base_branch} ← {pr.head_branch}")
    click.echo(
        f"  +{pr.additions} -{pr.deletions} in {pr.changed_files} files"
        + (f" | Review: {pr.review_decision}" if pr.review_decision else "")
    )
    click.echo()

    # Get thread count
    threads = get_review_threads(owner, repo, pr.number)
    unresolved = [t for t in threads if not t.is_resolved]

    # Actions menu
    actions = [
        "[i] View full info",
        f"[t] View threads ({len(unresolved)} unresolved)",
        "[f] View files",
        "[d] View diff",
        "[o] Open in browser",
        "[w] Create worktree",
        "[r] Resolve threads",
        "[y] Reply to thread",
        "[c] Post comment",
        "[a] Approve",
        "[x] Request changes",
        "[s] Toggle draft/ready",
        "[q] Quit",
    ]

    while True:
        click.echo()
        index = fuzzy_select(actions, "Action")
        if index is None or index == len(actions) - 1:  # Quit
            click.echo(style_dim("Done."))
            return

        action = actions[index]
        if "[i]" in action:
            ctx.obj["pr_num"] = pr.number
            ctx.invoke(info)
        elif "[t]" in action:
            ctx.obj["pr_num"] = pr.number
            ctx.invoke(threads_cmd)
        elif "[f]" in action:
            ctx.invoke(files, pr_num=pr.number)
        elif "[d]" in action:
            ctx.invoke(diff, pr_num=pr.number)
        elif "[o]" in action:
            ctx.invoke(open_cmd, pr_num=pr.number)
        elif "[w]" in action:
            ctx.invoke(checkout_cmd, pr_num=pr.number)
            return  # Exit after creating worktree (we've cd'd away)
        elif "[r]" in action:
            ctx.obj["pr_num"] = pr.number
            ctx.invoke(resolve)
        elif "[y]" in action:
            ctx.obj["pr_num"] = pr.number
            ctx.invoke(reply)
        elif "[c]" in action:
            message = click.prompt("Comment")
            result = post_comment(pr.number, message)
            print_action_results([result])
        elif "[a]" in action:
            ctx.invoke(approve, pr_num=pr.number)
        elif "[x]" in action:
            message = click.prompt("Message")
            ctx.invoke(request_changes_cmd, message=message, pr_num=pr.number)
        elif "[s]" in action:
            if pr.is_draft:
                ctx.invoke(ready_cmd, pr_num=pr.number)
            else:
                ctx.invoke(draft_cmd, pr_num=pr.number)
            # Refresh PR info
            pr = get_pr_or_exit(pr.number)


@cli.command()
@click.argument("pr_num", type=int, required=False)
@click.option("--json", "-j", "as_json", is_flag=True, help="Output as JSON")
@click.option("--full", "-f", is_flag=True, help="Show full diff context")
@click.option("--resolved", "-r", is_flag=True, help="Include resolved threads")
@click.pass_context
def info(
    ctx: click.Context,
    pr_num: int | None,
    *,
    as_json: bool,
    full: bool,
    resolved: bool,
) -> None:
    """View PR information and review threads.

    Shows PR metadata, description, and review comments.
    By default shows only unresolved review threads.

    EXAMPLES:
        pr info           # Current branch's PR
        pr info 123       # Specific PR
        pr info --json    # JSON output for scripting
        pr info -r        # Include resolved threads
        pr info -f        # Show full diff context
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))
    owner, repo = require_repo_info()

    threads = get_review_threads(owner, repo, pr.number)
    pr_comments = get_pr_comments(owner, repo, pr.number)

    if as_json:
        output = {
            "pr": pr._asdict(),
            "review_threads": [t._asdict() for t in threads],
            "discussion_comments": [c._asdict() for c in pr_comments],
        }
        click.echo(json.dumps(output, indent=2, default=str))
        return

    # Markdown-style output
    draft_marker = " [DRAFT]" if pr.is_draft else ""
    click.echo(f"# PR #{pr.number}: {pr.title}{draft_marker}")
    click.echo()
    click.echo(f"**URL:** {pr.url}")
    click.echo(f"**Author:** {pr.author}")
    click.echo(f"**State:** {pr.state}")
    if pr.review_decision:
        click.echo(f"**Review Decision:** {pr.review_decision}")
    if pr.mergeable:
        click.echo(f"**Mergeable:** {pr.mergeable}")
    click.echo(f"**Base:** {pr.base_branch} ← {pr.head_branch}")
    click.echo(
        f"**Changes:** +{pr.additions} -{pr.deletions} in {pr.changed_files} files"
    )
    click.echo()
    click.echo("## Description")
    click.echo()
    click.echo(pr.body or "*No description provided*")
    click.echo()

    # Review threads
    if resolved:
        display_threads = threads
        resolved_count = sum(1 for t in threads if t.is_resolved)
        unresolved_count = len(threads) - resolved_count
        click.echo(
            f"## Review Comments ({unresolved_count} unresolved, {resolved_count} resolved)"
        )
    else:
        display_threads = [t for t in threads if not t.is_resolved]
        click.echo(f"## Unresolved Review Comments ({len(display_threads)})")
    click.echo()

    if not display_threads:
        click.echo("*No review comments to display*")
        click.echo()
    else:
        for thread in display_threads:
            line = thread.line or thread.start_line or "?"
            resolved_marker = "[RESOLVED] " if thread.is_resolved else ""
            outdated = "[outdated] " if thread.is_outdated else ""

            click.echo(f"### {resolved_marker}{outdated}{thread.path}:{line}")
            click.echo(f"**Thread ID:** `{thread.id}`")
            click.echo()

            for i, comment in enumerate(thread.comments):
                author = comment.author
                created = format_date(comment.created_at)

                if i == 0 and comment.diff_hunk:
                    # Show diff context
                    hunk = comment.diff_hunk.strip()
                    if not full:
                        lines = hunk.split("\n")
                        hunk = "\n".join(
                            lines[-DIFF_CONTEXT_LINES:]
                            if len(lines) > DIFF_CONTEXT_LINES
                            else lines
                        )
                    click.echo("```diff")
                    click.echo(hunk)
                    click.echo("```")
                    click.echo()

                click.echo(f"**{author}** ({created}):")
                click.echo()
                click.echo(comment.body)
                click.echo()

    # Discussion comments
    if pr_comments:
        click.echo(f"## Discussion Comments ({len(pr_comments)})")
        click.echo()
        for disc_comment in pr_comments:
            author = disc_comment.author
            created = format_date(disc_comment.created_at)
            click.echo(f"### {author} ({created})")
            click.echo()
            click.echo(disc_comment.body)
            click.echo()
    else:
        click.echo("## Discussion Comments (0)")
        click.echo()
        click.echo("*No discussion comments*")


@cli.command()
@click.argument("pr_num", type=int, required=False)
@click.pass_context
def files(ctx: click.Context, pr_num: int | None) -> None:
    """List files changed in the PR.

    Outputs one file path per line, suitable for piping.

    EXAMPLES:
        pr files              # Current branch's PR
        pr files 123          # Specific PR
        pr files | xargs cat  # View all changed files
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))
    file_list = get_pr_files(pr.number)
    for f in file_list:
        click.echo(f)


@cli.command()
@click.argument("pr_num", type=int, required=False)
@click.pass_context
def diff(ctx: click.Context, pr_num: int | None) -> None:
    """Show the PR diff.

    EXAMPLES:
        pr diff          # Current branch's PR diff
        pr diff 123      # Specific PR diff
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))
    diff_content = get_pr_diff(pr.number)
    if diff_content:
        click.echo(diff_content)


@cli.command("threads")
@click.argument("pr_num", type=int, required=False)
@click.option("--resolved", "-r", is_flag=True, help="Include resolved threads")
@click.option("--json", "-j", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def threads_cmd(
    ctx: click.Context, pr_num: int | None, *, resolved: bool, as_json: bool
) -> None:
    """List review threads with their IDs.

    Shows thread ID, file:line, resolution status, and comment preview.
    Thread IDs can be used with resolve/unresolve/reply commands.

    EXAMPLES:
        pr threads           # Unresolved threads only
        pr threads -r        # All threads including resolved
        pr threads --json    # JSON output for scripting

    OUTPUT FORMAT:
        PRRT_abc123  src/main.py:42  [unresolved]  "Consider using..."
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))
    owner, repo = require_repo_info()

    thread_list = get_review_threads(owner, repo, pr.number)

    if not resolved:
        thread_list = [t for t in thread_list if not t.is_resolved]

    if as_json:
        click.echo(
            json.dumps([t._asdict() for t in thread_list], indent=2, default=str)
        )
        return

    if not thread_list:
        click.echo(style_dim("No threads to display"))
        return

    for t in thread_list:
        status = (
            click.style("[resolved]", fg=GREEN)
            if t.is_resolved
            else click.style("[unresolved]", fg=YELLOW)
        )
        line = t.line or t.start_line or "?"
        preview = ""
        if t.comments:
            preview = t.comments[0].body[:PREVIEW_SHORT].replace("\n", " ")
            if len(t.comments[0].body) > PREVIEW_SHORT:
                preview += "..."
        thread_id = click.style(t.id, fg=DIM)
        click.echo(f'  {thread_id}  {t.path}:{line}  {status}  "{preview}"')


@cli.command("list")
@click.option("--author", "-a", help="Filter by author")
@click.option("--mine", "-m", is_flag=True, help="Show only my PRs")
@click.option("--draft/--no-draft", "-d/-D", default=True, help="Include draft PRs")
@click.option("--json", "-j", "as_json", is_flag=True, help="JSON output")
def list_cmd(author: str | None, *, mine: bool, draft: bool, as_json: bool) -> None:
    """List open PRs in the repository.

    EXAMPLES:
        pr list              # All open PRs
        pr list --mine       # My PRs only
        pr list -a username  # PRs by specific author
        pr ls --json         # JSON output
        pr ls --no-draft     # Exclude draft PRs
    """
    if mine:
        author = get_viewer_login()

    prs = list_open_prs(author=author, include_drafts=draft)

    if as_json:
        click.echo(json.dumps([p._asdict() for p in prs], indent=2, default=str))
        return

    if not prs:
        click.echo(style_dim("No open PRs found"))
        return

    for pr in prs:
        num = click.style(f"#{pr.number}", fg=CYAN, bold=True)
        draft_marker = click.style(" [draft]", fg=YELLOW) if pr.is_draft else ""
        author_styled = click.style(f"@{pr.author}", fg=DIM)
        click.echo(
            f"  {num}{draft_marker} {pr.head_branch} - {pr.title} {author_styled}"
        )


@cli.command()
@click.argument("thread_ids", nargs=-1, required=False)
@click.option(
    "--all", "-a", "resolve_all", is_flag=True, help="Resolve all unresolved threads"
)
@click.pass_context
def resolve(
    ctx: click.Context, thread_ids: tuple[str, ...], *, resolve_all: bool
) -> None:
    """Resolve review threads.

    Without arguments, shows interactive picker of unresolved threads.

    THREAD IDS:
        Thread IDs look like: PRRT_kwDOABC123_abc456
        Get them from 'pr threads' or 'pr info' output.

    EXAMPLES:
        pr resolve                          # Interactive picker
        pr resolve PRRT_abc123              # Resolve one thread
        pr resolve PRRT_abc PRRT_def        # Resolve multiple
        pr resolve --all                    # Resolve all threads
    """
    pr = get_pr_or_exit(None, ctx.obj.get("pr_num"))
    owner, repo = require_repo_info()

    if not thread_ids and not resolve_all:
        # Interactive mode
        all_threads = get_review_threads(owner, repo, pr.number)
        unresolved = [t for t in all_threads if not t.is_resolved]

        if not unresolved:
            click.echo(style_info("No unresolved threads"))
            return

        options = [format_thread_option(t) for t in unresolved]
        indices = fuzzy_select_multi(options, "Select threads to resolve")
        if not indices:
            click.echo(style_dim("Cancelled."))
            return

        thread_ids = tuple(unresolved[i].id for i in indices)

    if resolve_all:
        all_threads = get_review_threads(owner, repo, pr.number)
        unresolved = [t for t in all_threads if not t.is_resolved]
        thread_ids = tuple(t.id for t in unresolved)

    if not thread_ids:
        click.echo(style_dim("No threads to resolve"))
        return

    results = [resolve_thread(tid) for tid in thread_ids]
    print_action_results(results)


@cli.command()
@click.argument("thread_ids", nargs=-1, required=False)
@click.pass_context
def unresolve(ctx: click.Context, thread_ids: tuple[str, ...]) -> None:
    """Unresolve review threads.

    Without arguments, shows interactive picker of resolved threads.

    EXAMPLES:
        pr unresolve                    # Interactive picker
        pr unresolve PRRT_abc123        # Unresolve one thread
        pr unresolve PRRT_abc PRRT_def  # Unresolve multiple
    """
    pr = get_pr_or_exit(None, ctx.obj.get("pr_num"))
    owner, repo = require_repo_info()

    if not thread_ids:
        # Interactive mode
        all_threads = get_review_threads(owner, repo, pr.number)
        resolved_threads = [t for t in all_threads if t.is_resolved]

        if not resolved_threads:
            click.echo(style_info("No resolved threads"))
            return

        options = [format_thread_option(t) for t in resolved_threads]
        indices = fuzzy_select_multi(options, "Select threads to unresolve")
        if not indices:
            click.echo(style_dim("Cancelled."))
            return

        thread_ids = tuple(resolved_threads[i].id for i in indices)

    results = [unresolve_thread(tid) for tid in thread_ids]
    print_action_results(results)


@cli.command()
@click.argument("thread_id", required=False)
@click.argument("message", required=False)
@click.option(
    "--resolve",
    "-r",
    "do_resolve",
    is_flag=True,
    help="Also resolve the thread after replying",
)
@click.pass_context
def reply(
    ctx: click.Context,
    thread_id: str | None,
    message: str | None,
    *,
    do_resolve: bool,
) -> None:
    """Reply to a review thread.

    Without arguments, shows interactive thread picker then prompts for message.

    EXAMPLES:
        pr reply                              # Interactive mode
        pr reply PRRT_abc "Done"              # Reply with message
        pr reply PRRT_abc "Fixed" --resolve   # Reply and resolve
    """
    pr = get_pr_or_exit(None, ctx.obj.get("pr_num"))
    owner, repo = require_repo_info()

    if not thread_id:
        # Interactive mode
        all_threads = get_review_threads(owner, repo, pr.number)
        # Show unresolved first
        all_threads.sort(key=lambda t: t.is_resolved)

        if not all_threads:
            click.echo(style_info("No threads to reply to"))
            return

        options = [format_thread_option(t) for t in all_threads]
        index = fuzzy_select(options, "Select thread to reply to")
        if index is None:
            click.echo(style_dim("Cancelled."))
            return

        thread_id = all_threads[index].id

        # Show thread context
        thread = all_threads[index]
        click.echo()
        click.echo(f"--- Thread: {thread.path}:{thread.line or '?'} ---")
        for comment in thread.comments:
            click.echo(f"@{comment.author} ({format_date(comment.created_at)}):")
            click.echo(comment.body)
            click.echo()

    if not message:
        message = click.prompt("Reply")

    # Check for pending review
    viewer = get_viewer_login()
    pending_review = get_pending_review(pr.id, viewer)

    result = reply_to_thread(thread_id, message, pr.id)
    results = [result]

    if result.success:
        # Submit the reply
        submit_result = submit_pending_review(pr.id)
        if not submit_result.success and pending_review is None:
            results.append(submit_result)

    if do_resolve and result.success:
        resolve_result = resolve_thread(thread_id)
        results.append(resolve_result)

    print_action_results(results)


@cli.command()
@click.argument("message", required=False)
@click.argument("pr_num", type=int, required=False)
@click.pass_context
def comment(ctx: click.Context, message: str | None, pr_num: int | None) -> None:
    """Post a comment on the PR (discussion comment, not review).

    Without message, prompts interactively for the comment text.

    EXAMPLES:
        pr comment "All review comments addressed"
        pr comment "Fixed" 123    # Comment on PR #123
        pr c "LGTM"               # Short alias
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))

    if not message:
        message = click.prompt("Comment")

    result = post_comment(pr.number, message)
    print_action_results([result])


@cli.command()
@click.argument("pr_num", type=int, required=False)
@click.option("--message", "-m", help="Optional approval message")
@click.pass_context
def approve(ctx: click.Context, pr_num: int | None, message: str | None) -> None:
    """Submit an approving review.

    EXAMPLES:
        pr approve              # Approve current branch's PR
        pr approve 123          # Approve PR #123
        pr approve -m "LGTM!"   # With message
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))
    result = approve_pr(pr.number, message)
    print_action_results([result])


@cli.command("request-changes")
@click.argument("message")
@click.argument("pr_num", type=int, required=False)
@click.pass_context
def request_changes_cmd(ctx: click.Context, message: str, pr_num: int | None) -> None:
    """Submit a review requesting changes.

    EXAMPLES:
        pr request-changes "Please add tests"
        pr rc "Add error handling" 123
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))
    result = request_changes(pr.number, message)
    print_action_results([result])


@cli.command("ready")
@click.argument("pr_num", type=int, required=False)
@click.pass_context
def ready_cmd(ctx: click.Context, pr_num: int | None) -> None:
    """Mark PR as ready for review (from draft).

    EXAMPLES:
        pr ready        # Current branch's PR
        pr ready 123    # Specific PR
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))
    result = mark_ready(pr.number)
    print_action_results([result])


@cli.command("draft")
@click.argument("pr_num", type=int, required=False)
@click.pass_context
def draft_cmd(ctx: click.Context, pr_num: int | None) -> None:
    """Convert PR to draft.

    EXAMPLES:
        pr draft        # Current branch's PR
        pr draft 123    # Specific PR
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))
    result = mark_draft(pr.number)
    print_action_results([result])


@cli.command("open")
@click.argument("pr_num", type=int, required=False)
@click.pass_context
def open_cmd(ctx: click.Context, pr_num: int | None) -> None:
    """Open the PR in the default web browser.

    Uses Python's webbrowser module which respects the $BROWSER environment
    variable. Works automatically in VS Code Remote SSH sessions.
    Falls back to copying the URL to clipboard if browser can't be opened.

    EXAMPLES:
        pr open          # Open current branch's PR
        pr open 123      # Open PR #123
        pr o             # Short alias
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))
    click.echo(style_info(f"Opening PR #{pr.number} in browser..."))
    click.echo(f"  {pr.url}")

    try:
        webbrowser.open(pr.url)
    except Exception:
        # Browser opening failed, copy to clipboard as fallback
        if copy_to_clipboard(pr.url):
            click.echo(style_dim("  (copied to clipboard)"))


@cli.command("checkout")
@click.argument("pr_num", type=int, required=False)
@click.argument("name", required=False)
@click.pass_context
def checkout_cmd(ctx: click.Context, pr_num: int | None, name: str | None) -> None:
    """Create a worktree for the PR's branch.

    Fetches the PR's head branch and creates a new worktree for it.
    If a worktree already exists for the branch, switches to it and pulls
    the latest changes.

    EXAMPLES:
        pr checkout          # Create worktree for current branch's PR
        pr checkout 123      # Create worktree for PR #123
        pr co 123 review     # Create worktree named 'review' for PR #123
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))
    repo_root = require_repo()

    # Validate PR number
    try:
        validated_pr_num = validate_pr_number(pr.number)
    except ValidationError as e:
        click.echo(style_error(str(e)), err=True)
        sys.exit(1)

    # Use branch name as default worktree name
    if not name:
        suggested = pr.head_branch.replace("/", "-")
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
        sys.exit(1)

    # Check if worktree already exists
    worktree_path = get_worktree_path(repo_root, name)
    if worktree_path.exists():
        click.echo(style_info(f"Worktree '{name}' already exists, switching to it..."))
        # Pull latest changes
        click.echo(style_info("Pulling latest changes..."))
        pull_result = run_git("pull", "--ff-only", cwd=worktree_path)
        if pull_result is None:
            click.echo(style_warn("Could not pull (may have local changes)"))
        else:
            click.echo(style_success("Updated to latest"))
        output_cd(worktree_path)
        return

    # Fetch the PR branch
    click.echo(style_info(f"Fetching PR #{validated_pr_num}..."))
    fetch_result = run_git(
        "fetch",
        "origin",
        f"pull/{validated_pr_num}/head:{pr.head_branch}",
        cwd=repo_root,
    )
    if fetch_result is None:
        click.echo(style_error(f"Failed to fetch PR #{validated_pr_num}"), err=True)
        sys.exit(1)

    # Create the worktree
    created_path = create_worktree(repo_root, name, pr.head_branch, new_branch=False)
    if created_path:
        output_cd(created_path)


@cli.command()
@click.argument("pr_num", type=int, required=False)
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def close(ctx: click.Context, pr_num: int | None, *, force: bool) -> None:
    """Close the PR.

    Prompts for confirmation unless --force is used.

    EXAMPLES:
        pr close           # Close with confirmation
        pr close -f 123    # Force close PR #123
    """
    pr = get_pr_or_exit(pr_num, ctx.obj.get("pr_num"))

    if not force:
        if not click.confirm(style_warn(f"Close PR #{pr.number}?"), default=False):
            click.echo(style_dim("Cancelled."))
            return

    result = close_pr(pr.number)
    print_action_results([result])


# Command aliases
cli.add_command(info, name="i")
cli.add_command(files, name="f")
cli.add_command(diff, name="d")
cli.add_command(threads_cmd, name="t")
cli.add_command(list_cmd, name="ls")
cli.add_command(resolve, name="r")
cli.add_command(unresolve, name="ur")
cli.add_command(reply, name="re")
cli.add_command(comment, name="c")
cli.add_command(approve, name="a")
cli.add_command(request_changes_cmd, name="rc")
cli.add_command(open_cmd, name="o")
cli.add_command(checkout_cmd, name="co")
cli.add_command(checkout_cmd, name="sw")


if __name__ == "__main__":
    cli()
