"""Executed file interventions using the locked scientific sandbox runner.

Full 2/3-factor replacements retain all cases and outputs. No old observation is
rescored as a counterfactual. This isolates a local configuration effect, not a
plugin's native activation, source line, or general scientific causal effect.
"""
from itertools import product
from pathlib import Path
import random

from .artifacts import confined, sha
from .core import ValidationError, load_json, suite_digest, write_json
from .native_evidence import _separate
from .science_execution import execute, read_pinned, validate_manifest


def validate_design(design):
    if (not isinstance(design, dict) or set(design) != {'format', 'cases', 'components', 'seed'}
            or design['format'] != 'pvl-component-localization-1' or type(design['seed']) is not int):
        raise ValidationError('Expected pvl-component-localization-1 design')
    components = design['components']
    if not isinstance(components, list) or len(components) not in (2, 3):
        raise ValidationError('Declare 2 or 3 file components')
    names, targets = set(), set()
    for c in components:
        if (not isinstance(c, dict) or set(c) != {'id', 'target', 'candidate', 'replacement'}
                or not isinstance(c['id'], str) or not c['id'] or c['id'] in names or c['target'] in targets):
            raise ValidationError('Unique component IDs and nonoverlapping targets required')
        from .science import reference
        confined(Path.cwd(), c['target'])
        reference(c['candidate'])
        reference(c['replacement'])
        if c['candidate']['sha256'] == c['replacement']['sha256']:
            raise ValidationError('Replacement must change component bytes')
        names.add(c['id'])
        targets.add(c['target'])
    cases = design['cases']
    if not isinstance(cases, list) or not 2 <= len(cases) <= 32:
        raise ValidationError('Include 2..32 cases, including a passing control')
    ids = set()
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {'id', 'role', 'manifest'}
                or not isinstance(case['id'], str) or not case['id'] or case['id'] in ids
                or case['role'] not in ('target', 'control')):
            raise ValidationError('Case IDs must be unique and roles target/control')
        ids.add(case['id'])
        validate_manifest(case['manifest'])
        if targets & set(case['manifest']['files']):
            raise ValidationError('Component targets cannot replace frozen common files')
    if {c['role'] for c in cases} != {'target', 'control'}:
        raise ValidationError('Retain target and passing control cases')
    if len({suite_digest(c['manifest']['environment']) for c in cases}) != 1:
        raise ValidationError('All cases must share a frozen environment lock')


def summarize(design, runs):
    """Preserve missing/error outcomes; only completed, checked controls qualify."""
    n = len(design['components'])
    arms = [''.join(v) for v in product('01', repeat=n)]
    expected = {(a, c['id']) for a in arms for c in design['cases']}
    keys = [(r['arm'], r['case_id']) for r in runs]
    if len(set(keys)) != len(keys) or not set(keys) <= expected:
        raise ValidationError('Duplicate or foreign intervention run')
    indexed = {(r['arm'], r['case_id']): r for r in runs}
    controls = [c['id'] for c in design['cases'] if c['role'] == 'control']
    def ok(row):
        return (row is not None and row.get('pipeline_completed') is True and
                row.get('environment_check') == 'MATCH_BEFORE_AND_AFTER' and row.get('passed') is True)
    edges = []
    for arm in arms:
        for i, component in enumerate(design['components']):
            if arm[i] != '0':
                continue
            replacement = arm[:i] + '1' + arm[i+1:]
            controls_pass = all(ok(indexed.get((a, c))) for a in (arm, replacement) for c in controls)
            for case in design['cases']:
                if case['role'] != 'target':
                    continue
                before, after = indexed.get((arm, case['id'])), indexed.get((replacement, case['id']))
                established = bool(controls_pass and before and before.get('pipeline_completed') is True and
                    before.get('environment_check') == 'MATCH_BEFORE_AND_AFTER' and before.get('passed') is False and ok(after))
                changed = []
                if before and after:
                    right = {o['path']: o for o in after.get('outputs', [])}
                    changed = [o['path'] for o in before.get('outputs', []) if o['passed'] is False
                               and right.get(o['path'], {}).get('passed') is True]
                edges.append({'component': component['id'], 'from_arm': arm, 'to_arm': replacement,
                    'case_id': case['id'], 'resolved_output_checks': changed,
                    'controls_pass': controls_pass, 'failure_disappeared': established,
                    'status': 'LOCAL_REPLACEMENT_EFFECT' if established else 'NOT_ESTABLISHED'})
    return {'format': 'pvl-component-localization-report-1', 'design_sha256': suite_digest(design),
        'status': 'COMPLETE' if set(keys) == expected else 'INCOMPLETE',
        'planned_runs': len(expected), 'recorded_runs': len(runs), 'runs': runs, 'contrasts': edges,
        'bit_meaning': {'0': 'candidate', '1': 'replacement'}, 'automatic_retry': False,
        'native_plugin_activation': 'NOT_ESTABLISHED', 'source_line_localization': 'NOT_ESTABLISHED',
        'scope': 'Conditional file-replacement effects in actual local sandbox runs; all fixed inputs and controls retained. No population causal estimate.'}


def run_interventions(design_path, expected_id, inputs, submitted, output, *, runtime=None):
    design_path = Path(design_path).resolve()
    design = load_json(design_path)
    validate_design(design)
    if suite_digest(design) != expected_id:
        raise ValidationError('Design commitment mismatch')
    root, source, answers = (Path(p).resolve() for p in (output, inputs, submitted))
    for path in (source, answers, design_path.parent):
        _separate(root, path)
    # Preflight every declared byte before creating a durable execution claim.
    variants = [{k: read_pinned(source, c[k]) for k in ('candidate', 'replacement')} for c in design['components']]
    common = [{p: read_pinned(source, {'path': p, 'sha256': h}) for p, h in c['manifest']['files'].items()}
              for c in design['cases']]
    locks = [read_pinned(design_path.parent, c['manifest']['environment']) for c in design['cases']]
    for case in design['cases']:
        for row in case['manifest']['outputs']:
            read_pinned(answers, row['submitted'])
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / 'design.json', design)
    schedule = [(a, i) for a in map(''.join, product('01', repeat=len(variants))) for i in range(len(common))]
    random.Random(design['seed']).shuffle(schedule)
    write_json(root / 'schedule.json', [{'arm': a, 'case_id': design['cases'][i]['id']} for a, i in schedule])
    write_json(root / 'started.json', {'design_sha256': expected_id, 'automatic_retry': False})
    runs = []
    for index, (arm, ci) in enumerate(schedule):
        case = design['cases'][ci]
        stage = root / 'stages' / str(index)
        stage.mkdir(parents=True)
        blobs = dict(common[ci])
        for i, c in enumerate(design['components']):
            blobs[c['target']] = variants[i]['replacement' if arm[i] == '1' else 'candidate']
        for name, content in blobs.items():
            p = confined(stage, name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        config = root / 'configs' / str(index)
        config.mkdir(parents=True)
        manifest = dict(case['manifest'], files={p: sha(stage / p) for p in blobs},
                        environment={'path': 'environment.lock.json', 'sha256': case['manifest']['environment']['sha256']})
        (config / 'environment.lock.json').write_bytes(locks[ci])
        write_json(config / 'manifest.json', manifest)
        destination = root / 'executions' / str(index)
        try:
            receipt = execute(config / 'manifest.json', suite_digest(manifest), stage, answers, destination, runtime=runtime)
            row = {k: receipt.get(k) for k in ('status', 'pipeline_completed', 'environment_check', 'passed', 'outputs', 'error')}
            row['receipt'] = {'path': str(destination.relative_to(root) / 'receipt.json'), 'sha256': sha(destination / 'receipt.json')}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row = {'status': 'UNRESOLVED', 'pipeline_completed': False, 'passed': None, 'outputs': [], 'error': str(exc)[:500]}
        row.update(arm=arm, case_id=case['id'], execution_index=index,
                   component_sha256={c['id']: manifest['files'][c['target']] for c in design['components']})
        runs.append(row)
        write_json(root / 'report.json', summarize(design, runs))
    return summarize(design, runs)
