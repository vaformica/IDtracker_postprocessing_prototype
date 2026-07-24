#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
python_path="$script_dir/venv-mac/bin/python3"

if [[ ! -x "$python_path" ]]; then
  printf 'The Mac environment is not installed.\nRun install_both.command first.\n' >&2
  read -r -p "Press Return to close." _
  exit 1
fi

exec "$python_path" "$script_dir/firebird_gui.py"
