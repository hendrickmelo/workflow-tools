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

# Install uv if not present
if ! command -v uv &>/dev/null; then
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install workflow-tools
info "Installing workflow-tools..."
uv tool install "git+https://github.com/${REPO}" --force

# Shell integration
info "Setting up shell integration..."
workflow-tools install

info "Done! Restart your shell or run: source ~/.zshrc"
