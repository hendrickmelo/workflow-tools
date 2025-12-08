#!/bin/bash
# Install workflow-tools in development mode
# Creates a wrapper script that runs the module from this repo

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.local/bin"
WRAPPER="${INSTALL_DIR}/workflow-tools"

mkdir -p "${INSTALL_DIR}"

cat > "${WRAPPER}" << EOF
#!/bin/bash
# Development wrapper for workflow-tools
# Runs the module from: ${SCRIPT_DIR}
cd "${SCRIPT_DIR}" && exec pixi run python -m workflow_tools.cli "\$@"
EOF

chmod +x "${WRAPPER}"

echo "Installed development wrapper to ${WRAPPER}"
echo "Make sure ${INSTALL_DIR} is in your PATH"
