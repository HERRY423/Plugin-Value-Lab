process PVL_AGGREGATE {
    tag "$meta.id"
    label 'process_low'
    stageInMode 'copy'
    conda "${moduleDir}/environment.yml"
    input:
    tuple val(meta), path('counts.h5ad'), path('settings.json')
    output:
    tuple val(meta), path('result'), emit: result
    path 'versions.yml', emit: versions
    script:
    '''
    pvl aggregate counts.h5ad --config settings.json --output result --json
    pvl verify result --json
    printf 'PVL_AGGREGATE:\n  plugin-value-lab: "%s"\n' "$(pvl --version)" > versions.yml
    '''
}
