"""Color utilities for iTerm2 tab colors and VS Code workspace files."""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

# Constants for hex color validation
_HEX_COLOR_LENGTH = 6
_LUMINANCE_THRESHOLD = 0.5

# Gitignore pattern for workspace files
WORKSPACE_GITIGNORE_PATTERN = "*.local.code-workspace"

# Color presets matching shell functions
COLOR_PRESETS: dict[str, str] = {
    "red": "CC3333",
    "green": "2D8B4E",
    "blue": "2B6CB0",
    "yellow": "D4A017",
    "orange": "CC6633",
    "purple": "7B3FA0",
    "pink": "CC5599",
    "cyan": "2A9D8F",
}


def resolve_color(color: str) -> str | None:
    """Convert preset name or hex to 6-digit hex (no #). Returns None if invalid."""
    # Check if it's a preset
    if color.lower() in COLOR_PRESETS:
        return COLOR_PRESETS[color.lower()]

    # Check if it's a valid hex code
    hex_color = color.lstrip("#")
    if len(hex_color) == _HEX_COLOR_LENGTH:
        try:
            int(hex_color, 16)
            return hex_color.upper()
        except ValueError:
            pass
    return None


def darken_color(hex_color: str, percent: int = 50) -> str:
    """Darken a hex color by percentage."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    factor = (100 - percent) / 100
    r = int(r * factor)
    g = int(g * factor)
    b = int(b * factor)

    return f"{r:02X}{g:02X}{b:02X}"


def foreground_for(hex_color: str) -> str:
    """Return #000000 or #FFFFFF based on luminance."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # Calculate relative luminance
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255

    return "#000000" if luminance > _LUMINANCE_THRESHOLD else "#FFFFFF"


def set_iterm_tab_color(hex_color: str | None) -> None:
    """Set iTerm2 tab color via escape sequences. None = reset."""
    if hex_color is None:
        # Reset tab color
        sys.stdout.write("\033]6;1;bg;*;default\a")
    else:
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        sys.stdout.write(f"\033]6;1;bg;red;brightness;{r}\a")
        sys.stdout.write(f"\033]6;1;bg;green;brightness;{g}\a")
        sys.stdout.write(f"\033]6;1;bg;blue;brightness;{b}\a")
    sys.stdout.flush()


def get_random_preset() -> str:
    """Return a random preset name."""
    return random.choice(list(COLOR_PRESETS.keys()))


def get_workspace_filename(branch: str) -> str:
    """Convert branch name to workspace filename."""
    # Replace slashes with dashes
    safe_name = branch.replace("/", "-")
    return f"{safe_name}.local.code-workspace"


def create_workspace_file(worktree_path: Path, hex_color: str) -> Path:
    """Create .local.code-workspace file with color settings. Returns the file path."""
    # Get branch name for filename
    branch = _get_branch_from_worktree(worktree_path)
    filename = get_workspace_filename(branch)
    workspace_path = worktree_path / filename

    hex_color = hex_color.lstrip("#")
    fg_color = foreground_for(hex_color)
    dark_color = darken_color(hex_color, 50)

    workspace_content = {
        "folders": [{"path": "."}],
        "settings": {
            "workbench.colorCustomizations": {
                "titleBar.activeBackground": f"#{hex_color}",
                "titleBar.activeForeground": fg_color,
                "titleBar.inactiveBackground": f"#{dark_color}",
                "titleBar.inactiveForeground": fg_color,
            }
        },
    }

    with open(workspace_path, "w") as f:
        json.dump(workspace_content, f, indent=2)
        f.write("\n")

    return workspace_path


def read_workspace_color(worktree_path: Path) -> str | None:
    """Read color from existing workspace file. Returns hex (no #) or None."""
    workspace_file = find_workspace_file(worktree_path)
    if workspace_file is None:
        return None

    try:
        with open(workspace_file) as f:
            data = json.load(f)

        color_customizations = data.get("settings", {}).get(
            "workbench.colorCustomizations", {}
        )
        title_bg = color_customizations.get("titleBar.activeBackground")
        if isinstance(title_bg, str):
            return title_bg.lstrip("#")
    except (json.JSONDecodeError, OSError):
        pass

    return None


def find_workspace_file(worktree_path: Path) -> Path | None:
    """Find .local.code-workspace file in directory."""
    for file in worktree_path.iterdir():
        if file.name.endswith(".local.code-workspace"):
            return file
    return None


def delete_workspace_file(worktree_path: Path) -> bool:
    """Delete the workspace file if it exists. Returns True if deleted."""
    workspace_file = find_workspace_file(worktree_path)
    if workspace_file is not None:
        workspace_file.unlink()
        return True
    return False


def _get_branch_from_worktree(worktree_path: Path) -> str:
    """Get branch name from worktree path (for filename generation)."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return "default"


def _get_repo_root(worktree_path: Path) -> Path | None:
    """Get the repository root from a worktree path."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip())
    return None


def is_pattern_in_gitignore(repo_root: Path, pattern: str) -> bool:
    """Check if a pattern exists in .gitignore."""
    gitignore_path = repo_root / ".gitignore"
    if not gitignore_path.exists():
        return False

    try:
        content = gitignore_path.read_text()
        # Check for exact line match (ignoring leading/trailing whitespace)
        for line in content.splitlines():
            if line.strip() == pattern:
                return True
    except OSError:
        pass

    return False


def add_pattern_to_gitignore(repo_root: Path, pattern: str) -> None:
    """Append a pattern to .gitignore, creating file if needed."""
    gitignore_path = repo_root / ".gitignore"

    # Read existing content
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        # Ensure file ends with newline before appending
        if content and not content.endswith("\n"):
            content += "\n"
    else:
        content = ""

    # Append pattern
    content += f"{pattern}\n"
    gitignore_path.write_text(content)
