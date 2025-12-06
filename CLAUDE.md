# Claude Code Instructions

## Project Overview
`wt` is a CLI tool for managing git worktrees with interactive selection UI. It creates worktrees in a sibling directory (`repo.worktrees/<name>`) and integrates with GitHub PRs.

## Commands
```bash
pixi run cleanup   # Auto-fix: black, ruff --fix, mypy (daemon)
pixi run lint      # Check only: black --check, ruff, mypy
pixi run ci        # CI checks (same as lint)
pixi run build     # Build wheel
pixi run install   # Build binary and install to ~/.local/bin
pixi run clean     # Remove build artifacts
```

## Code Style
- Python 3.11+, strict mypy typing
- Use `click.style()` for colored output (see `style_*` helpers)
- Use `InquirerPy.inquirer.fuzzy` for interactive selection with fuzzy search
- Prefer `NamedTuple` for data classes
- Run `pixi run cleanup` before committing

## Architecture
- `src/wt/cli.py` - Single module with all commands
- Entry point: `wt.cli:cli`
- Binary built with PyApp (Rust-based Python bundler)
