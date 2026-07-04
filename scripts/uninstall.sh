#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${HOME}/.local/share/sede"
BIN_PATH="${HOME}/.local/bin/sede"
CONFIG_DIR="${HOME}/.config/sede"
CACHE_DIR="${HOME}/.cache/sede"
STATE_DIR="${HOME}/.local/state/sede"

rm -f "$BIN_PATH"
rm -rf "$INSTALL_ROOT"
rm -rf "$CONFIG_DIR" "$CACHE_DIR" "$STATE_DIR"

echo "sede has been removed from this user profile."
echo "Note: assistant session data in ~/.claude and ~/.copilot was not modified."
