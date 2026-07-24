#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_dir="$script_dir/venv-mac"

python3 -c 'import tkinter' || {
  printf '%s\n' \
    "ERROR: This Python installation does not include Tkinter." \
    "Install a standard Python from python.org, then run this installer again." >&2
  exit 1
}

if [[ ! -x "$venv_dir/bin/python3" ]]; then
  printf 'Creating Mac environment once: %s\n' "$venv_dir"
  python3 -m venv "$venv_dir"
else
  printf 'Reusing existing Mac environment: %s\n' "$venv_dir"
fi
if ! "$venv_dir/bin/python3" -c \
  'import tomlkit, numpy, h5py, matplotlib' 2>/dev/null; then
  printf 'Installing only missing prototype dependencies...\n'
  "$venv_dir/bin/python3" -m pip install tomlkit numpy h5py matplotlib
fi
"$venv_dir/bin/python3" -c \
  'import tkinter, tomlkit, numpy, h5py, matplotlib; print("Mac GUI and PDF environment verified")'

chmod +x "$script_dir/launch_gui.command"
printf '\nMac installation finished.\nDouble-click:\n%s/launch_gui.command\n' "$script_dir"
