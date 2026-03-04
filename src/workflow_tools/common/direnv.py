"""Direnv detection and .envrc setup for pixi and uv projects."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

ENVRC_PIXI = """\
watch_file pixi.lock
pixi install --frozen 2>/dev/null || pixi install
eval "$(pixi shell-hook -s bash)"
"""

ENVRC_UV = """\
watch_file uv.lock
uv sync 2>/dev/null
VIRTUAL_ENV="$(pwd)/.venv"
export VIRTUAL_ENV
PATH="$VIRTUAL_ENV/bin:$PATH"
export PATH
"""


class SetupResult(NamedTuple):
    """Result of setup_direnv()."""

    created: bool
    manager: str | None = None
    already_exists: bool = False
    direnv_installed: bool = False


def detect_env_manager(path: Path) -> str | None:
    """Detect the environment manager used in a project.

    Returns "pixi", "uv", or None.
    """
    # 1. pixi.toml → pixi
    if (path / "pixi.toml").exists():
        return "pixi"

    pyproject = path / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        # 2. pyproject.toml with [tool.pixi → pixi
        if "[tool.pixi" in content:
            return "pixi"
        # 4. pyproject.toml with [project] (no pixi) → uv
        if "[project]" in content:
            return "uv"

    # 3. uv.lock → uv
    if (path / "uv.lock").exists():
        return "uv"

    return None


def get_envrc_content(manager: str) -> str:
    """Return .envrc content for the given environment manager."""
    if manager == "pixi":
        return ENVRC_PIXI
    if manager == "uv":
        return ENVRC_UV
    msg = f"Unknown environment manager: {manager}"
    raise ValueError(msg)


def is_direnv_installed() -> bool:
    """Check if direnv is available on PATH."""
    return shutil.which("direnv") is not None


def get_direnv_install_hint() -> str:
    """Return platform-specific direnv installation instructions."""
    return (
        "Install direnv:\n"
        "  macOS:   brew install direnv\n"
        "  Ubuntu:  sudo apt install direnv\n"
        "  Other:   https://direnv.net/docs/installation.html\n"
        "\n"
        "Then add to your shell config:\n"
        '  eval "$(direnv hook zsh)"   # or bash/fish'
    )


def setup_direnv(path: Path, *, force: bool = False) -> SetupResult:
    """Set up .envrc for a project directory.

    Detects the environment manager (pixi/uv), writes .envrc,
    and runs `direnv allow` if direnv is installed.

    Returns SetupResult indicating what happened.
    """
    manager = detect_env_manager(path)
    if manager is None:
        return SetupResult(created=False)

    envrc = path / ".envrc"
    if envrc.exists() and not force:
        return SetupResult(created=False, manager=manager, already_exists=True)

    envrc.write_text(get_envrc_content(manager))

    direnv_available = is_direnv_installed()
    if direnv_available:
        subprocess.run(
            ["direnv", "allow"],
            cwd=path,
            check=False,
            capture_output=True,
        )

    return SetupResult(created=True, manager=manager, direnv_installed=direnv_available)
