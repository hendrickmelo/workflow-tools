#!/usr/bin/env bash
set -euo pipefail

REPO="emmapowers/workflow-tools"

info() { printf "\033[34m=>\033[0m %s\n" "$1"; }
error() { printf "\033[31mError:\033[0m %s\n" "$1" >&2; exit 1; }

# Platform check
case "$(uname -s)" in
    Darwin|Linux) ;;
    *) error "Unsupported platform: $(uname -s)" ;;
esac

# Ensure ~/.local/bin is in PATH
export PATH="$HOME/.local/bin:$PATH"

# Install uv if not present
if ! command -v uv &>/dev/null; then
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# Install workflow-tools
info "Installing workflow-tools..."
uv tool install "git+https://github.com/${REPO}" --force

# Shell integration
info "Setting up shell integration..."
workflow-tools install

# Determine shell rc file for message
case "${SHELL:-}" in
    */zsh)  RC_FILE=~/.zshrc ;;
    */bash) RC_FILE=~/.bashrc ;;
    *)      RC_FILE="your shell rc file" ;;
esac

info "Done! Restart your shell or run: source $RC_FILE"
