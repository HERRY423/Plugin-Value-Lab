nextflow.enable.dsl = 2
params.input = 'counts.h5ad'
params.settings = 'settings.json'
params.outdir = 'nextflow-results'

process AGGREGATE_COUNTS {
    cpus 1
    memory '1 GB'
    // PVL deliberately rejects linked input files.
    stageInMode 'copy'
    publishDir params.outdir, mode: 'copy', overwrite: false
    input:
    path 'counts.h5ad'
    path 'settings.json'
    output:
    path 'result'
    script:
    '''
    pvl aggregate counts.h5ad --config settings.json --output result --json
    pvl verify result --json
    '''
}

workflow {
    AGGREGATE_COUNTS(
        Channel.fromPath(params.input, checkIfExists: true),
        file(params.settings, checkIfExists: true)
    )
}
