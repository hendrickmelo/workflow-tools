"""GitHub PR API operations via gh CLI and GraphQL."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from typing import Any, NamedTuple

import click

from workflow_tools.common import style_error
from workflow_tools.common.github import get_repo_info, gh_api_graphql, run_gh


class PRInfo(NamedTuple):
    """Pull request information."""

    number: int
    id: str  # GraphQL node ID for mutations
    title: str
    body: str | None
    url: str
    state: str
    author: str
    base_branch: str
    head_branch: str
    is_draft: bool
    mergeable: str | None
    review_decision: str | None
    additions: int
    deletions: int
    changed_files: int


class ThreadComment(NamedTuple):
    """A comment within a review thread."""

    id: str
    author: str
    body: str
    created_at: str
    diff_hunk: str | None


class ReviewThread(NamedTuple):
    """A review thread with comments."""

    id: str  # PRRT_xxx format
    path: str
    line: int | None
    start_line: int | None
    is_resolved: bool
    is_outdated: bool
    comments: list[ThreadComment]


class DiscussionComment(NamedTuple):
    """A PR-level discussion comment."""

    id: str
    author: str
    body: str
    created_at: str


class ActionResult(NamedTuple):
    """Result of a GitHub action."""

    success: bool
    message: str


class PRListInfo(NamedTuple):
    """Minimal PR info for listing operations (used by wt pr command)."""

    number: int
    title: str
    branch: str
    is_draft: bool


def list_prs_simple() -> list[PRListInfo]:
    """Fetch open PRs with minimal fields (for wt pr command).

    Returns a list of PRListInfo with just number, title, branch, and draft status.
    """
    result = run_gh(
        "pr", "list", "--json", "number,title,headRefName,isDraft", "--limit", "100"
    )
    if not result:
        return []
    try:
        data = json.loads(result)
        return [
            PRListInfo(
                number=pr["number"],
                title=pr["title"],
                branch=pr["headRefName"],
                is_draft=pr["isDraft"],
            )
            for pr in data
        ]
    except (json.JSONDecodeError, KeyError):
        return []


def get_current_branch() -> str | None:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def require_repo_info() -> tuple[str, str]:
    """Get repo info or exit with error."""
    info = get_repo_info()
    if not info:
        click.echo(
            style_error("Not in a GitHub repository or gh CLI not available"),
            err=True,
        )
        sys.exit(1)
    return info


def get_pr_for_branch(pr_num: int | None = None) -> PRInfo | None:
    """Get PR data for current branch or specific PR number."""
    fields = "number,title,body,url,state,author,baseRefName,headRefName,reviewDecision,additions,deletions,changedFiles,isDraft,mergeable,id"
    if pr_num:
        result = run_gh("pr", "view", str(pr_num), "--json", fields)
    else:
        result = run_gh("pr", "view", "--json", fields)

    if not result:
        return None

    try:
        data = json.loads(result)
        return PRInfo(
            number=data["number"],
            id=data["id"],
            title=data["title"],
            body=data.get("body"),
            url=data["url"],
            state=data["state"],
            author=data["author"]["login"],
            base_branch=data["baseRefName"],
            head_branch=data["headRefName"],
            is_draft=data["isDraft"],
            mergeable=data.get("mergeable"),
            review_decision=data.get("reviewDecision"),
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            changed_files=data.get("changedFiles", 0),
        )
    except (json.JSONDecodeError, KeyError):
        return None


def list_open_prs(
    *, author: str | None = None, include_drafts: bool = True
) -> list[PRInfo]:
    """List open PRs in the repository."""
    args = ["pr", "list", "--json", "number,title,headRefName,isDraft,id,author,url"]

    if author:
        args.extend(["--author", author])
    if not include_drafts:
        args.append("--draft=false")

    result = run_gh(*args)
    if not result:
        return []

    try:
        data = json.loads(result)
        return [
            PRInfo(
                number=pr["number"],
                id=pr["id"],
                title=pr["title"],
                body=None,
                url=pr["url"],
                state="OPEN",
                author=pr["author"]["login"],
                base_branch="",
                head_branch=pr["headRefName"],
                is_draft=pr["isDraft"],
                mergeable=None,
                review_decision=None,
                additions=0,
                deletions=0,
                changed_files=0,
            )
            for pr in data
        ]
    except (json.JSONDecodeError, KeyError):
        return []


def get_pr_diff(pr_num: int) -> str | None:
    """Get the diff for a PR."""
    return run_gh("pr", "diff", str(pr_num))


def get_pr_files(pr_num: int) -> list[str]:
    """Get list of changed files in a PR."""
    result = run_gh(
        "pr", "view", str(pr_num), "--json", "files", "--jq", ".files[].path"
    )
    if not result:
        return []
    return [f for f in result.strip().split("\n") if f]


def get_review_threads(owner: str, repo: str, pr_number: int) -> list[ReviewThread]:
    """Get review threads with resolution status using GraphQL."""
    query = """
    query($owner: String!, $repo: String!, $pr: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          reviewThreads(first: 100) {
            nodes {
              id
              isResolved
              isOutdated
              path
              line
              startLine
              comments(first: 50) {
                nodes {
                  id
                  author { login }
                  body
                  createdAt
                  path
                  line
                  diffHunk
                }
              }
            }
          }
        }
      }
    }
    """
    result = gh_api_graphql(query, {"owner": owner, "repo": repo, "pr": pr_number})
    if not result:
        return []

    try:
        threads_data = (
            result.get("data", {})
            .get("repository", {})
            .get("pullRequest", {})
            .get("reviewThreads", {})
            .get("nodes", [])
        )
        threads = []
        for t in threads_data:
            comments = [
                ThreadComment(
                    id=c["id"],
                    author=c.get("author", {}).get("login", "unknown"),
                    body=c.get("body", ""),
                    created_at=c.get("createdAt", ""),
                    diff_hunk=c.get("diffHunk"),
                )
                for c in t.get("comments", {}).get("nodes", [])
            ]
            threads.append(
                ReviewThread(
                    id=t["id"],
                    path=t.get("path", "unknown"),
                    line=t.get("line"),
                    start_line=t.get("startLine"),
                    is_resolved=t.get("isResolved", False),
                    is_outdated=t.get("isOutdated", False),
                    comments=comments,
                )
            )
        return threads
    except (KeyError, TypeError):
        return []


def get_pr_comments(owner: str, repo: str, pr_number: int) -> list[DiscussionComment]:
    """Get PR-level issue comments."""
    result = run_gh("api", f"repos/{owner}/{repo}/issues/{pr_number}/comments")
    if not result:
        return []

    try:
        data = json.loads(result)
        return [
            DiscussionComment(
                id=c["id"],
                author=c.get("user", {}).get("login", "unknown"),
                body=c.get("body", ""),
                created_at=c.get("created_at", ""),
            )
            for c in data
        ]
    except (json.JSONDecodeError, KeyError):
        return []


def format_date(iso_date: str) -> str:
    """Format ISO date to readable format."""
    try:
        dt = datetime.fromisoformat(iso_date)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return iso_date


# Action functions


def post_comment(pr_num: int, message: str) -> ActionResult:
    """Post a comment on the PR."""
    result = run_gh("pr", "comment", str(pr_num), "--body", message)
    if result is None:
        return ActionResult(False, "Failed to post comment")
    return ActionResult(True, "Comment posted")


def resolve_thread(thread_id: str) -> ActionResult:
    """Resolve a review thread using GraphQL."""
    query = """
    mutation($threadId: ID!) {
      resolveReviewThread(input: {threadId: $threadId}) {
        thread { isResolved }
      }
    }
    """
    result = gh_api_graphql(query, {"threadId": thread_id})
    if not result or result.get("errors"):
        return ActionResult(False, f"Failed to resolve thread {thread_id}")
    return ActionResult(True, f"Resolved thread {thread_id}")


def unresolve_thread(thread_id: str) -> ActionResult:
    """Unresolve a review thread using GraphQL."""
    query = """
    mutation($threadId: ID!) {
      unresolveReviewThread(input: {threadId: $threadId}) {
        thread { isResolved }
      }
    }
    """
    result = gh_api_graphql(query, {"threadId": thread_id})
    if not result or result.get("errors"):
        return ActionResult(False, f"Failed to unresolve thread {thread_id}")
    return ActionResult(True, f"Unresolved thread {thread_id}")


def get_pending_review(
    pr_id: str, viewer_login: str | None = None
) -> dict[str, Any] | None:
    """Check if there's a pending review for the current user."""
    query = """
    query($prId: ID!) {
      node(id: $prId) {
        ... on PullRequest {
          reviews(first: 10, states: PENDING) {
            nodes {
              id
              author { login }
              state
            }
          }
        }
      }
    }
    """
    result = gh_api_graphql(query, {"prId": pr_id})
    if not result:
        return None

    reviews: list[dict[str, Any]] = (
        result.get("data", {}).get("node", {}).get("reviews", {}).get("nodes", [])
    )
    for review in reviews:
        if (
            viewer_login is None
            or review.get("author", {}).get("login") == viewer_login
        ):
            return review
    return None


def submit_pending_review(pr_id: str, review_id: str | None = None) -> ActionResult:
    """Submit a pending review."""
    if review_id is None:
        pending = get_pending_review(pr_id)
        if pending is None:
            return ActionResult(False, "No pending review to submit")
        review_id = pending["id"]

    query = """
    mutation($prId: ID!, $reviewId: ID!) {
      submitPullRequestReview(input: {pullRequestId: $prId, pullRequestReviewId: $reviewId, event: COMMENT}) {
        pullRequestReview { state }
      }
    }
    """
    result = gh_api_graphql(query, {"prId": pr_id, "reviewId": review_id})
    if not result or result.get("errors"):
        return ActionResult(False, "Failed to submit review")
    return ActionResult(True, "Review submitted")


def reply_to_thread(thread_id: str, message: str, pr_id: str) -> ActionResult:
    """Reply to a review thread using GraphQL."""
    # Get the first comment ID from the thread to reply to
    get_thread_query = """
    query($threadId: ID!) {
      node(id: $threadId) {
        ... on PullRequestReviewThread {
          comments(first: 1) {
            nodes { id }
          }
        }
      }
    }
    """
    result = gh_api_graphql(get_thread_query, {"threadId": thread_id})
    if not result:
        return ActionResult(False, f"Failed to get thread info: {thread_id}")

    comments = (
        result.get("data", {}).get("node", {}).get("comments", {}).get("nodes", [])
    )
    if not comments:
        return ActionResult(False, f"No comments found in thread {thread_id}")

    comment_id = comments[0]["id"]

    # Now reply to that comment
    reply_query = """
    mutation($prId: ID!, $commentId: ID!, $body: String!) {
      addPullRequestReviewComment(input: {pullRequestId: $prId, inReplyTo: $commentId, body: $body}) {
        comment { id }
      }
    }
    """
    result = gh_api_graphql(
        reply_query, {"prId": pr_id, "commentId": comment_id, "body": message}
    )
    if not result or result.get("errors"):
        return ActionResult(False, f"Failed to reply to thread {thread_id}")
    return ActionResult(True, f"Replied to thread {thread_id}")


def approve_pr(pr_num: int, message: str | None = None) -> ActionResult:
    """Submit an approving review."""
    args = ["pr", "review", str(pr_num), "--approve"]
    if message:
        args.extend(["--body", message])
    result = run_gh(*args)
    if result is None:
        return ActionResult(False, "Failed to approve PR")
    return ActionResult(True, "PR approved")


def request_changes(pr_num: int, message: str) -> ActionResult:
    """Submit a review requesting changes."""
    result = run_gh("pr", "review", str(pr_num), "--request-changes", "--body", message)
    if result is None:
        return ActionResult(False, "Failed to request changes")
    return ActionResult(True, "Changes requested")


def mark_ready(pr_num: int) -> ActionResult:
    """Mark PR as ready for review."""
    result = run_gh("pr", "ready", str(pr_num))
    if result is None:
        return ActionResult(False, "Failed to mark PR ready")
    return ActionResult(True, "PR marked as ready for review")


def mark_draft(pr_num: int) -> ActionResult:
    """Convert PR to draft."""
    result = run_gh("pr", "ready", str(pr_num), "--undo")
    if result is None:
        return ActionResult(False, "Failed to convert to draft")
    return ActionResult(True, "PR converted to draft")


def close_pr(pr_num: int) -> ActionResult:
    """Close the PR."""
    result = run_gh("pr", "close", str(pr_num))
    if result is None:
        return ActionResult(False, "Failed to close PR")
    return ActionResult(True, "PR closed")


def get_viewer_login() -> str | None:
    """Get the current authenticated user's login."""
    result = run_gh("api", "user", "--jq", ".login")
    return result.strip() if result else None
