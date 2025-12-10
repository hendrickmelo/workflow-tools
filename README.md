# workflow-tools

CLI tools for git workflow: worktrees, PRs, repository management, and tmux sessions.

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/emmapowers/workflow-tools/main/install.sh | bash
```

For development (changes take effect immediately):
```bash
git clone git@github.com:emmapowers/workflow-tools.git
cd workflow-tools
./install-dev.sh
```

## Commands

### `wt` - Git Worktree Manager

```bash
wt                  # Interactive picker to switch worktrees
wt create           # Interactive branch picker
wt create <name> -b <branch>
wt pr               # Create worktree from open PR
wt fork <name>      # Fork from current branch
wt list             # List worktrees
wt remove           # Interactive picker
wt remove <name>    # Remove specific worktree
wt claude           # Open Claude Code in worktree
wt path <name>      # Print worktree path
wt cleanup          # Remove current worktree and switch to main
```

Aliases: `cr`, `sw`, `ls`, `rm`, `fk`, `c`

### `rp` - Repository Manager

```bash
rp                  # Interactive picker to switch repos
rp -r               # Refresh cache and pick
rp list             # List all discovered repos
rp create <name>    # Create new GitHub repo
rp fork <owner/repo>  # Fork a GitHub repo
rp clone            # Clone one of your GitHub repos
rp rename <old> <new>  # Rename local folder and GitHub repo
rp refresh          # Force refresh repo cache
```

Aliases: `sw`, `ls`, `cr`, `fk`, `cl`, `rn`, `rf`

### `pr` - Pull Request Manager

```bash
pr                  # Show PR for current branch
pr <number>         # Show specific PR
pr list             # List open PRs
pr diff             # Show PR diff
pr files            # List changed files
pr threads          # List review threads
pr resolve <id>     # Resolve thread(s)
pr unresolve <id>   # Unresolve thread(s)
pr reply <id>       # Reply to thread
```

### `tm` - Tmux Session Manager

```bash
tm                  # Smart default: attach to branch-matching session or show picker
tm create           # Create session (defaults to current branch name)
tm create <name>    # Create session with specific name
tm attach           # Interactive picker to attach
tm attach <name>    # Attach to specific session
tm list             # List all sessions
tm kill             # Interactive picker to kill
tm kill <name>      # Kill specific session
```

Aliases: `c`, `a`, `ls`, `k`

Features:
- Git-aware: suggests session names based on current branch
- Sets terminal title to `sessionname@hostname`
- Detects when inside tmux and shows current session info
- Blocks create/attach/kill from inside tmux

## Shell Integration

Run `workflow-tools install` to enable:
- Auto-cd after switching repos/worktrees
- Shell aliases (`wt`, `rp`, `pr`, `tm`)
