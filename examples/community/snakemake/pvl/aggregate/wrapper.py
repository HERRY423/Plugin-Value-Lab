"""Only aggregate + verify; biological settings come from the explicit JSON input."""
from pathlib import Path
import subprocess

log = Path(snakemake.log[0])
log.parent.mkdir(parents=True, exist_ok=True)
with log.open('w', encoding='utf-8') as stream:
    subprocess.run(['pvl', 'aggregate', str(snakemake.input.counts), '--config',
                    str(snakemake.input.settings), '--output', str(snakemake.output[0]), '--json'],
                   stdout=stream, stderr=subprocess.STDOUT, check=True)
    subprocess.run(['pvl', 'verify', str(snakemake.output[0]), '--json'],
                   stdout=stream, stderr=subprocess.STDOUT, check=True)
