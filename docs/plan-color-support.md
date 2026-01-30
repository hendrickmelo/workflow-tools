# Plan: Add Color Support to wt CLI

## Goal
Add iTerm2 tab color and VS Code workspace color support to `wt`, using `.local.code-workspace` files as storage.

## Behavior Summary
- **On worktree switch**: Read color from `.local.code-workspace` file (if exists) → apply to iTerm2 tab
- **On first switch (no color set)**: Auto-assign random preset color → create workspace file + set iTerm2
- **Manual command**: `wt color <preset|hex|reset>` to set/change colors
- **No auto-open**: VS Code workspace file is created but not auto-opened

## Design

### Color Presets (same as shell functions)
```python
COLOR_PRESETS = {
    "red": "CC3333",
    "green": "2D8B4E",
    "blue": "2B6CB0",
    "yellow": "D4A017",
    "orange": "CC6633",
    "purple": "7B3FA0",
    "pink": "CC5599",
    "cyan": "2A9D8F",
}
```

### Storage: `.local.code-workspace` file
- Located in worktree root directory
- Named: `{branch-name}.local.code-workspace` (slashes → dashes)
- Contains VS Code workspace settings with color customizations
- Color is extracted by parsing the JSON and reading `titleBar.activeBackground`

### New Module: `src/workflow_tools/common/color.py`

```python
# Color preset mapping
COLOR_PRESETS: dict[str, str]

# Helper functions
def resolve_color(color: str) -> str | None
    """Convert preset name or hex to 6-digit hex (no #). Returns None if invalid."""

def darken_color(hex_color: str, percent: int = 50) -> str
    """Darken a hex color by percentage."""

def foreground_for(hex_color: str) -> str
    """Return #000000 or #FFFFFF based on luminance."""

def set_iterm_tab_color(hex_color: str | None) -> None
    """Set iTerm2 tab color via escape sequences. None = reset."""

def get_random_preset() -> str
    """Return a random preset name."""

def get_workspace_filename(branch: str) -> str
    """Convert branch name to workspace filename."""

def create_workspace_file(path: Path, hex_color: str) -> None
    """Create .local.code-workspace file with color settings."""

def read_workspace_color(worktree_path: Path) -> str | None
    """Read color from existing workspace file. Returns hex or None."""

def find_workspace_file(worktree_path: Path) -> Path | None
    """Find .local.code-workspace file in directory."""
```

### Changes to `src/workflow_tools/wt/cli.py`

#### 1. New command: `wt color`
```python
@cli.command("color")
@click.argument("color", required=False)
def color_cmd(color: str | None) -> None:
    """Set worktree color for iTerm2 tab and VS Code workspace.

    COLOR can be a preset (red, green, blue, yellow, orange, purple, pink, cyan),
    a 6-digit hex code, or 'reset' to clear.
    """
```

**Behavior:**
- No argument: show current color + usage
- `reset`: remove workspace file + reset iTerm2 tab
- preset/hex: create/update workspace file + set iTerm2 tab

#### 2. New command: `wt code`
```python
@cli.command("code")
@click.argument("name", required=False)
def code_cmd(name: str | None) -> None:
    """Open VS Code with the worktree's workspace settings.

    If NAME is provided, opens that worktree. Otherwise uses current directory
    or shows interactive selection.
    """
```

**Behavior:**
- Finds (or creates) the `.local.code-workspace` file for the worktree
- Runs `code <workspace-file>` to open VS Code with the color settings
- If no workspace file exists, creates one with a random color first

#### 3. Modify `switch_cmd` (lines 533-580)
After `output_cd(worktree_path)`:
```python
# Apply worktree color
color_hex = read_workspace_color(worktree_path)
if color_hex is None:
    # First switch - assign random color
    preset = get_random_preset()
    color_hex = COLOR_PRESETS[preset]
    branch = get_current_branch(worktree_path) or "default"
    create_workspace_file(worktree_path, color_hex)
    click.echo(style_info(f"Assigned color: {preset}"))
set_iterm_tab_color(color_hex)
```

#### 4. Modify `create_worktree` function (optional enhancement)
Could assign color at creation time, but switch handles it.

## Files to Create/Modify

| File | Action |
|------|--------|
| `src/workflow_tools/common/color.py` | **Create** - Color utilities |
| `src/workflow_tools/common/__init__.py` | **Modify** - Export color functions |
| `src/workflow_tools/wt/cli.py` | **Modify** - Add `color` command, modify `switch_cmd` |

## Implementation Steps

1. Create `color.py` with helper functions
2. Add exports to `common/__init__.py`
3. Add `wt color` command to `cli.py`
4. Modify `switch_cmd` to apply colors on switch
5. Run `pixi run cleanup` to format/lint
6. Test manually

## Verification

1. **Test color command:**
   ```bash
   cd /path/to/worktree
   wt color blue      # Should set iTerm2 tab + create workspace file
   wt color           # Should show current color
   wt color reset     # Should reset iTerm2 + remove file
   ```

2. **Test switch with auto-color:**
   ```bash
   wt sw              # Switch to worktree without workspace file
   # Should auto-assign random color and create workspace file
   ```

3. **Test switch with existing color:**
   ```bash
   wt color green     # Set color
   wt sw other        # Switch away
   wt sw back         # Switch back - should restore green iTerm2 tab
   ```

4. **Test code command:**
   ```bash
   wt code            # Should open VS Code with workspace file for current worktree
   wt code feature-x  # Should open VS Code for named worktree
   ```

5. **Verify workspace file format:**
   ```bash
   cat *.local.code-workspace
   # Should have proper JSON with colorCustomizations
   ```

## Status

**Implemented**: 2025-01-29

All features implemented and tested:
- `wt color` command works with presets, hex codes, and reset
- `wt code` command opens VS Code with workspace file
- `wt switch` auto-assigns colors on first switch
- All 96 tests pass
- Linting (black, ruff, mypy) passes

---

## Enhancement: Auto-add to .gitignore

### Goal
When creating a `.local.code-workspace` file, check if the pattern is in `.gitignore`. If not, offer to add it automatically.

### Behavior
- After creating a workspace file, check if `*.local.code-workspace` is already in `.gitignore`
- If not found, prompt user: "Add *.local.code-workspace to .gitignore? [Y/n]"
- If yes, append the pattern to `.gitignore` (create file if needed)
- Only prompt once per repository (track via presence in .gitignore)

### New Functions in `color.py`

```python
WORKSPACE_GITIGNORE_PATTERN = "*.local.code-workspace"

def is_pattern_in_gitignore(repo_root: Path, pattern: str) -> bool:
    """Check if a pattern exists in .gitignore."""

def add_pattern_to_gitignore(repo_root: Path, pattern: str) -> None:
    """Append a pattern to .gitignore, creating file if needed."""

def ensure_workspace_in_gitignore(repo_root: Path) -> bool:
    """Check gitignore and prompt to add pattern if missing. Returns True if added."""
```

### Changes to CLI

Modify places where workspace files are created to call `ensure_workspace_in_gitignore()`:

1. **`color_cmd`** - after `create_workspace_file()`
2. **`code_cmd`** - after `create_workspace_file()`
3. **`apply_worktree_color`** - after `create_workspace_file()`

### Implementation Steps

1. Add `WORKSPACE_GITIGNORE_PATTERN` constant to `color.py`
2. Add `is_pattern_in_gitignore()` function
3. Add `add_pattern_to_gitignore()` function
4. Add `ensure_workspace_in_gitignore()` function with prompt
5. Export new functions from `common/__init__.py`
6. Update CLI to call `ensure_workspace_in_gitignore()` after creating workspace files
7. Run `pixi run cleanup`
8. Reinstall via `uv tool install --reinstall`

### Verification

```bash
# In a repo without *.local.code-workspace in .gitignore
wt color blue
# Should prompt: "Add *.local.code-workspace to .gitignore? [Y/n]"
# After accepting, check .gitignore contains the pattern

# Run again - should not prompt
wt color green
# No prompt (pattern already in .gitignore)
```

---

## Enhancement: Remember "No" Answer for Session

### Goal
When user declines to add the pattern to `.gitignore`, remember that choice for the rest of the shell session so they're not prompted again.

### Approach
Extend the shell wrapper pattern used for `cd` support. The wrapper already:
1. Sets up temp files (e.g., `WT_CD_FILE`)
2. Runs the Python command
3. Reads the temp file and acts on it (cd)

We'll add a similar mechanism for environment variables:
1. Add `WT_ENV_FILE` temp file
2. Python writes `export VAR=value` to this file when needed
3. Shell wrapper sources the file after command completes

### Environment Variable
```bash
WT_GITIGNORE_SKIP=1  # Set when user declines gitignore prompt
```

### Changes to Shell Wrapper (`cli.py`)

Update `_get_shell_wrapper()` to add env file support:

```bash
export WT_ENV_FILE="${TMPDIR:-/tmp}/.wt_env_$$"

wt() {
    rm -f "$WT_CD_FILE" "$WT_ENV_FILE"
    "workflow-tools" wt "$@"
    local exit_code=$?
    [[ -f "$WT_ENV_FILE" ]] && source "$WT_ENV_FILE" && rm -f "$WT_ENV_FILE"
    [[ -f "$WT_CD_FILE" ]] && cd "$(cat "$WT_CD_FILE")" && rm -f "$WT_CD_FILE"
    return $exit_code
}
```

### Changes to `shell.py`

Add function to write environment variables:

```python
def output_env(var: str, value: str, env_var: str = "WT_ENV_FILE") -> None:
    """Write an export statement to env file for shell wrapper."""
```

### Changes to `wt/cli.py`

Modify `ensure_workspace_in_gitignore()`:

```python
def ensure_workspace_in_gitignore(worktree_path: Path) -> None:
    # Check if user already declined this session
    if os.environ.get("WT_GITIGNORE_SKIP"):
        return

    if is_pattern_in_gitignore(repo_root, WORKSPACE_GITIGNORE_PATTERN):
        return

    if click.confirm(...):
        add_pattern_to_gitignore(...)
    else:
        # Remember choice for session
        output_env("WT_GITIGNORE_SKIP", "1")
```

### Implementation Steps

1. Update plan (this section)
2. Add `output_env()` to `shell.py`
3. Export `output_env` from `common/__init__.py`
4. Update shell wrapper in `cli.py` to handle `WT_ENV_FILE`
5. Modify `ensure_workspace_in_gitignore()` to check/set env var
6. Run `pixi run cleanup`
7. Reinstall and re-source shell

### Verification

```bash
# Source new shell wrapper
source ~/.zshrc

# First time - should prompt
wt color blue
# Answer 'n' to gitignore prompt

# Second time in same session - should NOT prompt
wt color green
# No prompt (WT_GITIGNORE_SKIP is set)

# New shell session - should prompt again
# (open new terminal)
wt color red
# Prompt appears again
```
