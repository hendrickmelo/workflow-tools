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
