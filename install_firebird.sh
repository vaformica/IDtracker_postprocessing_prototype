#!/usr/bin/env bash
set -euo pipefail

install_dir="${1:-$HOME/idtracker_postprocessing_v1}"
environment_name="${2:-idtracker_reprocess_v1}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$install_dir"
cp "$script_dir/processor.py" "$install_dir/processor.py"
cp "$script_dir/combine_results.py" "$install_dir/combine_results.py"
cp "$script_dir/slurm_worker.py" "$install_dir/slurm_worker.py"
cp "$script_dir/slurm_finalize.py" "$install_dir/slurm_finalize.py"
cp "$script_dir/METHODS.html" "$install_dir/METHODS.html"
cp "$script_dir/README.md" "$install_dir/README.md"
cp "$script_dir/ANALYSIS_REQUIREMENTS_REVIEW.md" \
  "$install_dir/ANALYSIS_REQUIREMENTS_REVIEW.md"

conda_sh="$HOME/miniconda3/etc/profile.d/conda.sh"
if [[ ! -f "$conda_sh" ]]; then
  printf 'ERROR: Conda initialization file not found: %s\n' "$conda_sh" >&2
  exit 1
fi
source "$conda_sh"

if conda env list | awk 'NF && $1 !~ /^#/ {print $1}' | grep -Fxq "$environment_name"; then
  printf 'Reusing existing Conda environment: %s\n' "$environment_name"
else
  printf 'Creating Conda environment: %s\n' "$environment_name"
  conda create --yes --name "$environment_name" \
    python=3.11 numpy h5py matplotlib
fi

environment_python="$HOME/miniconda3/envs/$environment_name/bin/python"
if ! "$environment_python" -c 'import numpy, h5py, matplotlib' 2>/dev/null; then
  printf 'Adding missing numerical/PDF packages to existing environment: %s\n' \
    "$environment_name"
  conda install --yes --name "$environment_name" numpy h5py matplotlib
fi
"$environment_python" -c \
  'import sys, numpy, h5py, matplotlib; print("Firebird environment verified:", sys.executable, numpy.__version__, h5py.__version__, matplotlib.__version__)'

printf '\nInstalled Firebird files in:\n%s\n' "$install_dir"
printf 'Dedicated Conda environment:\n%s\n' "$environment_name"
printf 'Firebird Python:\n%s\n' "$environment_python"
