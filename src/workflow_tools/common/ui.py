"""Shared UI utilities: colors, styling, and interactive selection."""

from __future__ import annotations

import click
from InquirerPy import inquirer

# Colors using click.style
CYAN = "cyan"
GREEN = "green"
YELLOW = "yellow"
RED = "red"
DIM = "bright_black"
BOLD = "bold"


def style_error(msg: str) -> str:
    """Style an error message."""
    return click.style(f"✗ {msg}", fg=RED)


def style_success(msg: str) -> str:
    """Style a success message."""
    return click.style(f"✓ {msg}", fg=GREEN)


def style_info(msg: str) -> str:
    """Style an info message."""
    return click.style(f"→ {msg}", fg=CYAN)


def style_warn(msg: str) -> str:
    """Style a warning message."""
    return click.style(f"! {msg}", fg=YELLOW)


def style_dim(msg: str) -> str:
    """Style dim/muted text."""
    return click.style(msg, fg=DIM)


def fuzzy_select(options: list[str], message: str) -> int | None:
    """Show fuzzy select menu. Returns index or None if cancelled.

    Uses exact substring matching which gives predictable results -
    typing a character shows only options containing that character,
    with matches at the start appearing first.
    """
    try:
        prompt = inquirer.fuzzy(  # type: ignore[attr-defined]
            message=message,
            choices=options,
            match_exact=True,  # Substring match gives more predictable results
        )
        result = prompt.execute()
        if result is None:
            return None
        return options.index(result)
    except KeyboardInterrupt:
        return None


def fuzzy_select_multi(options: list[str], message: str) -> list[int] | None:
    """Show fuzzy multi-select menu. Returns list of indices or None if cancelled."""
    try:
        prompt = inquirer.fuzzy(  # type: ignore[attr-defined]
            message=message,
            choices=options,
            multiselect=True,
        )
        result = prompt.execute()
        if result is None:
            return None
        return [options.index(r) for r in result]
    except KeyboardInterrupt:
        return None


def select_from_menu(title: str, options: list[str]) -> str | None:
    """Display interactive menu and return selection."""
    if not options:
        click.echo(style_error("No options available."), err=True)
        return None

    index = fuzzy_select(options, title)
    if index is None:
        return None
    return options[index]
