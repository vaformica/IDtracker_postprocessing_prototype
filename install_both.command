#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

printf '\nIDtracker post-processing v1 installer\n'
printf 'Local folder: %s\n\n' "$script_dir"

"$script_dir/install_mac.sh"

read -r -p "Firebird SSH host [firebird]: " ssh_host
ssh_host="${ssh_host:-firebird}"
read -r -p "SSH private-key path [$HOME/.ssh/id_ed25519_firebird]: " ssh_key
ssh_key="${ssh_key:-$HOME/.ssh/id_ed25519_firebird}"

if [[ ! -f "$ssh_key" ]]; then
  printf 'ERROR: SSH key does not exist: %s\n' "$ssh_key" >&2
  exit 1
fi

remote_stage="/tmp/idtracker_postprocessing_v1_install_${USER}"
remote_install='$HOME/idtracker_postprocessing_v1'
remote_environment='idtracker_reprocess_v1'

printf '\nTesting SSH connection...\n'
ssh -o BatchMode=yes -o IdentitiesOnly=yes -i "$ssh_key" "$ssh_host" \
  'hostname && python3 --version'

printf '\nCopying the reviewed processor and documentation to Firebird...\n'
ssh -o BatchMode=yes -o IdentitiesOnly=yes -i "$ssh_key" "$ssh_host" \
  "mkdir -p '$remote_stage'"
scp -i "$ssh_key" \
  "$script_dir/processor.py" \
  "$script_dir/postprocessing_qc.py" \
  "$script_dir/combine_results.py" \
  "$script_dir/slurm_worker.py" \
  "$script_dir/slurm_finalize.py" \
  "$script_dir/METHODS.html" \
  "$script_dir/README.md" \
  "$script_dir/DATA_DICTIONARY.md" \
  "$script_dir/ANALYSIS_REQUIREMENTS_REVIEW.md" \
  "$script_dir/install_firebird.sh" \
  "$ssh_host:$remote_stage/"

printf '\nEnsuring the isolated Firebird numerical/PDF environment is ready...\n'
ssh -t -o IdentitiesOnly=yes -i "$ssh_key" "$ssh_host" \
  "bash '$remote_stage/install_firebird.sh' \"$remote_install\" '$remote_environment'"

printf '\nInstallation completed on both machines.\n'
printf 'Double-click this launcher on the Mac:\n%s/launch_gui.command\n\n' "$script_dir"
read -r -p "Press Return to close this window." _
