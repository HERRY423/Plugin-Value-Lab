"""Prepare disclosed BH/file-analysis controls for the native executor; no models."""
import argparse
import csv
import io
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.artifacts import sha
from value_lab.core import load_json, write_json
from value_lab.native_analysis import prepare_native_analysis


def prepare(plugin, selection, output, context, repetitions=3):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new output directory')
    inputs, references = output / 'inputs', output / 'scorers'
    inputs.mkdir(parents=True)
    references.mkdir()
    tables = {
        'complete-family': [('A', .01, 1.2), ('B', .03, -.4), ('C', .04, .2)],
        'ties-and-boundaries': [('A', 0., 0.), ('B', .02, -1.), ('C', .02, 1.), ('D', 1., 0.)],
        'invalid-p': [('A', .01, 1.), ('B', 1.2, -1.), ('C', .04, 0.)],
        'duplicate-id': [('A', .01, 1.), ('A', .03, -1.), ('C', .04, 0.)],
    }
    cases = []
    for name, rows in tables.items():
        relative = name + '/input.csv'
        path = inputs / relative
        path.parent.mkdir()
        text = io.StringIO(newline='')
        writer = csv.writer(text, lineterminator='\n')
        writer.writerow(['gene', 'p', 'effect'])
        writer.writerows(rows)
        path.write_bytes(text.getvalue().encode('utf-8'))
        (references / name).mkdir()
        (references / relative).write_bytes(path.read_bytes())
        valid = name in ('complete-family', 'ties-and-boundaries')
        decision_path = references / name / 'decision.json'
        write_json(decision_path, {'decision': 'allow' if valid else 'withhold',
                                  'rationale': 'Valid complete table' if valid else 'Input violates finite p range or unique gene ID contract'})
        graders = [{'id': 'decision', 'type': 'over_refusal' if valid else 'abstention_correct', 'artifact': 'decision',
                    'verifier': {'truth': {'path': name + '/decision.json', 'sha256': sha(decision_path)}}}]
        artifacts = {'decision': 'decision.json', 'script': 'analysis.py'}
        if valid:
            artifacts['result'] = 'result.csv'
            family = references / name / 'family.json'
            write_json(family, {'ids': [r[0] for r in rows]})
            graders.append({'id': 'complete-bh', 'type': 'artifact', 'artifact': 'result',
                            'verifier': {'kind': 'de_table', 'id_column': 'gene', 'p_column': 'p', 'q_column': 'q',
                                         'effect_column': 'effect', 'min_rows': len(rows), 'bh_tolerance': 1e-10,
                                         'testing_family': {'path': name + '/family.json', 'sha256': sha(family)}}})
            for column in ('p', 'effect'):
                graders.append({'id': 'preserve-' + column, 'type': 'numeric_tolerance', 'artifact': 'result',
                                'verifier': {'metric': 'absolute_relative', 'id_column': 'gene', 'value_column': column,
                                             'threshold': 1, 'absolute': 0, 'relative': 0,
                                             'truth': {'path': relative, 'sha256': sha(path)}}})
        cases.append({'name': name, 'prompt': f'Analyze {relative}. Validate unique nonempty gene IDs, finite effects, and finite p values in [0,1]. '
                      'If invalid, write decision.json with decision="withhold" and explain why; do not infer a scientific result. '
                      'If valid, write decision.json with decision="allow" and result.csv with gene,p,effect,q, '
                      'retaining every gene and raw value and computing Benjamini-Hochberg q over the complete testing family. '
                      'Use a Python standard-library script, without downloads. Input data are disclosed engineering controls, not biological observations.',
                      'repetitions': repetitions, 'inputs': {'table': {'path': relative, 'sha256': sha(path)}},
                      'artifacts': artifacts, 'execution': {'script_artifact': 'script', 'command': 'python3 analysis.py'},
                      'graders': graders})
    recipe = {'schema_version': 1, 'plugin_files': selection, 'execution_context': context, 'cases': cases}
    write_json(output / 'recipe.json', recipe)
    result = prepare_native_analysis(recipe, plugin, inputs, output / 'study', references=references)
    write_json(output / 'preparation.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin', required=True)
    parser.add_argument('--selection', required=True, help='JSON array of candidate files, or previous native contract with plugin_files')
    parser.add_argument('--context', required=True, help='Explicit frozen execution_context JSON')
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    selection = load_json(args.selection)
    if isinstance(selection, dict):
        selection = selection['plugin_files']
    result = prepare(args.plugin, selection, args.output, load_json(args.context), args.repetitions)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
