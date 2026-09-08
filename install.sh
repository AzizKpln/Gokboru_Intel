#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$EUID" -eq 0 ]]; then echo "Do not run the installer as root." >&2; exit 1; fi
missing=()
python3 -c 'import tkinter' >/dev/null 2>&1 || missing+=(python3-tk)
dpkg-query -W -f='${Status}' python3-venv 2>/dev/null | grep -q 'install ok installed' || missing+=(python3-venv)
if (( ${#missing[@]} )); then
  echo "Installing required system components: ${missing[*]}"
  if command -v pkexec >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    pkexec apt-get update
    pkexec env DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
  else
    sudo apt-get update
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
  fi
fi
python3 -c 'import tkinter' >/dev/null 2>&1 || { echo "Unable to install the GUI component (python3-tk)." >&2; exit 1; }
exec python3 "$PROJECT_DIR/setup_gui.py"
