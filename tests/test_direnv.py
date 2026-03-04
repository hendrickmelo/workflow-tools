"""Tests for direnv detection and setup."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from workflow_tools.common.direnv import (
    SetupResult,
    detect_env_manager,
    get_direnv_install_hint,
    get_envrc_content,
    is_direnv_installed,
    setup_direnv,
)


class TestDetectEnvManager:
    """Tests for detect_env_manager()."""

    def test_detect_pixi_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pixi.toml").write_text("[project]\nname = 'test'\n")
        assert detect_env_manager(tmp_path) == "pixi"

    def test_detect_pixi_in_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'test'\n\n[tool.pixi.workspace]\nchannels = []\n"
        )
        assert detect_env_manager(tmp_path) == "pixi"

    def test_detect_uv_lock(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text("")
        assert detect_env_manager(tmp_path) == "uv"

    def test_detect_uv_pyproject_fallback(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        assert detect_env_manager(tmp_path) == "uv"

    def test_detect_none(self, tmp_path: Path) -> None:
        assert detect_env_manager(tmp_path) is None

    def test_pixi_toml_takes_priority_over_uv_lock(self, tmp_path: Path) -> None:
        (tmp_path / "pixi.toml").write_text("[project]\n")
        (tmp_path / "uv.lock").write_text("")
        assert detect_env_manager(tmp_path) == "pixi"

    def test_pixi_in_pyproject_takes_priority_over_uv_lock(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'test'\n\n[tool.pixi.workspace]\n"
        )
        (tmp_path / "uv.lock").write_text("")
        assert detect_env_manager(tmp_path) == "pixi"


class TestGetEnvrcContent:
    """Tests for get_envrc_content()."""

    def test_envrc_content_pixi(self) -> None:
        content = get_envrc_content("pixi")
        assert "pixi install" in content
        assert "pixi shell-hook" in content
        assert "watch_file pixi.lock" in content

    def test_envrc_content_uv(self) -> None:
        content = get_envrc_content("uv")
        assert "uv sync" in content
        assert "VIRTUAL_ENV" in content
        assert "watch_file uv.lock" in content

    def test_envrc_content_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown"):
            get_envrc_content("unknown")


class TestIsDirenvInstalled:
    """Tests for is_direnv_installed()."""

    def test_direnv_installed(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/direnv"):
            assert is_direnv_installed() is True

    def test_direnv_not_installed(self) -> None:
        with patch("shutil.which", return_value=None):
            assert is_direnv_installed() is False


class TestGetDirenvInstallHint:
    """Tests for get_direnv_install_hint()."""

    def test_hint_contains_install_instructions(self) -> None:
        hint = get_direnv_install_hint()
        assert "brew install direnv" in hint
        assert "apt install direnv" in hint
        assert "direnv.net" in hint
        assert "direnv hook" in hint


class TestSetupDirenv:
    """Tests for setup_direnv()."""

    def test_setup_creates_envrc_for_pixi(self, tmp_path: Path) -> None:
        (tmp_path / "pixi.toml").write_text("[project]\n")
        with patch("shutil.which", return_value="/usr/bin/direnv"), patch(
            "subprocess.run"
        ):
            result = setup_direnv(tmp_path)
        assert result.created is True
        assert result.manager == "pixi"
        assert result.direnv_installed is True
        assert (tmp_path / ".envrc").exists()
        assert "pixi" in (tmp_path / ".envrc").read_text()

    def test_setup_creates_envrc_for_uv(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text("")
        with patch("shutil.which", return_value="/usr/bin/direnv"), patch(
            "subprocess.run"
        ):
            result = setup_direnv(tmp_path)
        assert result.created is True
        assert result.manager == "uv"
        assert (tmp_path / ".envrc").exists()
        assert "uv sync" in (tmp_path / ".envrc").read_text()

    def test_setup_skips_when_no_manager(self, tmp_path: Path) -> None:
        result = setup_direnv(tmp_path)
        assert result.created is False
        assert result.manager is None
        assert not (tmp_path / ".envrc").exists()

    def test_setup_skips_existing_envrc(self, tmp_path: Path) -> None:
        (tmp_path / "pixi.toml").write_text("[project]\n")
        (tmp_path / ".envrc").write_text("# existing\n")
        result = setup_direnv(tmp_path)
        assert result.created is False
        assert result.already_exists is True
        assert (tmp_path / ".envrc").read_text() == "# existing\n"

    def test_setup_force_overwrites(self, tmp_path: Path) -> None:
        (tmp_path / "pixi.toml").write_text("[project]\n")
        (tmp_path / ".envrc").write_text("# existing\n")
        with patch("shutil.which", return_value="/usr/bin/direnv"), patch(
            "subprocess.run"
        ):
            result = setup_direnv(tmp_path, force=True)
        assert result.created is True
        assert "pixi" in (tmp_path / ".envrc").read_text()

    def test_setup_warns_no_direnv(self, tmp_path: Path) -> None:
        (tmp_path / "pixi.toml").write_text("[project]\n")
        with patch("shutil.which", return_value=None):
            result = setup_direnv(tmp_path)
        assert result.created is True
        assert result.direnv_installed is False
        assert (tmp_path / ".envrc").exists()

    def test_setup_runs_direnv_allow(self, tmp_path: Path) -> None:
        (tmp_path / "pixi.toml").write_text("[project]\n")
        with patch("shutil.which", return_value="/usr/bin/direnv"), patch(
            "subprocess.run"
        ) as mock_run:
            setup_direnv(tmp_path)
        mock_run.assert_called_once_with(
            ["direnv", "allow"],
            cwd=tmp_path,
            check=False,
            capture_output=True,
        )
