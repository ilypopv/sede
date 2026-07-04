#!/usr/bin/env bash
set -euo pipefail

SOURCE="latest"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--source)
      SOURCE="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Python is required but was not found. Install Python 3.9+ first." >&2
  exit 1
fi

INSTALL_ROOT="${HOME}/.local/share/sede"
VENV_DIR="${INSTALL_ROOT}/venv"
BIN_DIR="${HOME}/.local/bin"
LAUNCHER_PATH="${BIN_DIR}/sede"
REPO_URL="https://github.com/ilypopv/sede.git"

if [[ "$SOURCE" == "latest" ]]; then
  PACKAGE_SPEC="git+${REPO_URL}@main"
else
  PACKAGE_SPEC="git+${REPO_URL}@${SOURCE}"
fi

echo "Installing sede (${SOURCE})..."
mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV_DIR/bin/pip" install "$PACKAGE_SPEC"

cat > "$LAUNCHER_PATH" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec "$HOME/.local/share/sede/venv/bin/python" -m sede "$@"
EOF
chmod +x "$LAUNCHER_PATH"

echo
echo "sede was installed successfully."
echo "Binary: $LAUNCHER_PATH"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "Add this to your shell profile if needed:"
  echo "  export PATH=\"$BIN_DIR:\$PATH\""
fi
