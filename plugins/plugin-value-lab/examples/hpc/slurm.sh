#!/usr/bin/env bash
#SBATCH --job-name=pvl-kernel
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=2G
#SBATCH --time=00:10:00
set -euo pipefail
: "${PVL_SOURCE:?}" "${PVL_RESULTS_ROOT:?}"
exec bash "$PVL_SOURCE/examples/hpc/run.sh" "$PVL_RESULTS_ROOT/slurm-${SLURM_JOB_ID:?}"
