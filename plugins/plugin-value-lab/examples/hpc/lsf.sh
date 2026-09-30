#!/usr/bin/env bash
#BSUB -J pvl-kernel
#BSUB -n 2
#BSUB -R "span[hosts=1] rusage[mem=2GB]"
#BSUB -W 00:10
set -euo pipefail
: "${PVL_SOURCE:?}" "${PVL_RESULTS_ROOT:?}"
exec bash "$PVL_SOURCE/examples/hpc/run.sh" "$PVL_RESULTS_ROOT/lsf-${LSB_JOBID:?}"
