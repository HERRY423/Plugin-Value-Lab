nextflow.enable.dsl = 2
include { PVL_AGGREGATE } from './modules/pvl/aggregate/main'
params.input = 'counts.h5ad'
params.settings = 'settings.json'
params.outdir = 'nextflow-results'
workflow {
    PVL_AGGREGATE(Channel.of(tuple([id: 'donor-paired'],
        file(params.input, checkIfExists: true), file(params.settings, checkIfExists: true))))
}
