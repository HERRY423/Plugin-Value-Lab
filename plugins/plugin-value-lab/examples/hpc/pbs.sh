#!/usr/bin/env bash
#PBS -N pvl-kernel
#PBS -l select=1:ncpus=2:mem=2gb
#PBS -l walltime=00:10:00
set -euo pipefail
: "${PVL_SOURCE:?}" "${PVL_RESULTS_ROOT:?}"
exec bash "$PVL_SOURCE/examples/hpc/run.sh" "$PVL_RESULTS_ROOT/pbs-${PBS_JOBID:?}"
