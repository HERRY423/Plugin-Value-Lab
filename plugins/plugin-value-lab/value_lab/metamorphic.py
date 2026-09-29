"""Versioned scientific relations over frozen, identity-aligned observations.

No submitted code is executed. A relation is a necessary consistency condition,
not a correctness oracle or evidence that an asserted computation actually ran.
"""
from copy import deepcopy
import math
from pathlib import Path

from .core import ValidationError, load_json, suite_digest, write_json
from .science import keys, number, reference, reference_json

FORMAT = 'pvl-metamorphic-design-1'
OBSERVATIONS = 'pvl-metamorphic-observations-1'
RELATIONS = {
    'row_permutation': {'output_kind': 'numeric', 'meaning': 'Row identity permutation preserves numeric results'},
    'feature_permutation': {'output_kind': 'numeric', 'meaning': 'Feature identity permutation preserves numeric results'},
    'positive_scale': {'output_kind': 'numeric', 'meaning': 'Declared positive input scaling induces declared output factors'},
    'partition_invariance': {'output_kind': 'partition', 'meaning': 'Row permutation preserves co-membership, not arbitrary label names'},
    'contrast_reversal': {'output_kind': 'numeric', 'meaning': 'Reversing a fixed two-sided unshrunk Wald contrast negates effect and reverses CI endpoints'},
}


def catalog():
    return {'format': 'pvl-metamorphic-catalog-1', 'relations': deepcopy(RELATIONS),
            'grading_dependencies': 'python_standard_library', 'executes_submitted_code': False,
            'extension_policy': 'Reviewed source registration with validation, transform, comparison and mutation tests; no dynamic imports'}


def _ids(values, label, maximum=10000):
    if (not isinstance(values, list) or not 1 <= len(values) <= maximum
            or any(not isinstance(v, str) or not v.strip() or len(v) > 128 for v in values)
            or len(set(values)) != len(values)):
        raise ValidationError('Expected bounded unique ' + label)
    return values


def _matrix(value):
    keys(value, 'row_ids columns values')
    rows, columns = _ids(value['row_ids'], 'row IDs'), _ids(value['columns'], 'column IDs', 1000)
    data = value['values']
    if (len(rows) * len(columns) > 200000 or not isinstance(data, list) or len(data) != len(rows)
            or any(not isinstance(row, list) or len(row) != len(columns) for row in data)):
        raise ValidationError('Matrix shape differs from entity identities or exceeds budget')
    for row in data:
        for item in row:
            number(item)
    return {rid: dict(zip(columns, row)) for rid, row in zip(rows, data)}


def _output(value, schema):
    if schema['kind'] == 'numeric':
        rows = _matrix(value)
        if set(value['columns']) != set(schema['columns']):
            raise ValidationError('Output column coverage differs from frozen schema')
    else:
        keys(value, 'row_ids labels')
        ids = _ids(value['row_ids'], 'partition row IDs')
        labels = value['labels']
        if (not isinstance(labels, list) or len(labels) != len(ids)
                or any(not isinstance(v, str) or not v.strip() or len(v) > 128 for v in labels)):
            raise ValidationError('Partition needs a nonempty label for every entity')
        rows = dict(zip(ids, labels))
    if set(rows) != set(schema['row_ids']):
        raise ValidationError('Output entity coverage differs from frozen schema')
    return rows


def validate_spec(spec):
    keys(spec, 'design')
    reference(spec['design'])


def validate_design(design):
    keys(design, 'format source output tolerance relations')
    if design['format'] != FORMAT:
        raise ValidationError('Unsupported metamorphic design version')
    source = design['source']
    keys(source, 'matrix context')
    _matrix(source['matrix'])
    if not isinstance(source['context'], dict):
        raise ValidationError('Scientific method context must be an object')
    suite_digest(source)
    schema = design['output']
    if not isinstance(schema, dict) or schema.get('kind') not in ('numeric', 'partition'):
        raise ValidationError('Output schema must be numeric or partition')
    keys(schema, 'kind row_ids columns' if schema['kind'] == 'numeric' else 'kind row_ids')
    _ids(schema['row_ids'], 'output row IDs')
    if schema['kind'] == 'numeric':
        _ids(schema['columns'], 'output column IDs', 1000)
    keys(design['tolerance'], 'absolute relative')
    for value in design['tolerance'].values():
        if not 0 <= number(value) <= .0001:
            raise ValidationError('Metamorphic tolerances must be frozen within 0..1e-4')
    relations = design['relations']
    if not isinstance(relations, list) or not 1 <= len(relations) <= 32:
        raise ValidationError('Expected 1..32 prospective metamorphic relations')
    ids = {'baseline'}
    for relation in relations:
        keys(relation, 'id relation parameters rationale')
        from .core import _text
        from .declarative import _name
        _name(relation['id'], 'relation id')
        _text(relation['rationale'], 'scientific applicability rationale')
        name, params = relation['relation'], relation['parameters']
        if not isinstance(name, str) or name not in RELATIONS or relation['id'].casefold() in ids:
            raise ValidationError('Unknown or duplicate relation')
        ids.add(relation['id'].casefold())
        if schema['kind'] != RELATIONS[name]['output_kind']:
            raise ValidationError('Relation output kind differs from schema')
        if name in ('row_permutation', 'feature_permutation', 'partition_invariance'):
            keys(params, 'order')
            original = source['matrix']['columns' if name == 'feature_permutation' else 'row_ids']
            _ids(params['order'], 'permutation')
            if set(params['order']) != set(original) or params['order'] == original:
                raise ValidationError('Permutation must cover exact identities and change their order')
        elif name == 'positive_scale':
            keys(params, 'columns factor output_factors')
            _ids(params['columns'], 'scaled input columns')
            if not set(params['columns']) <= set(source['matrix']['columns']):
                raise ValidationError('Unknown scaled input column')
            if not .001 <= number(params['factor']) <= 1000 or params['factor'] == 1:
                raise ValidationError('Positive scale needs a nontrivial factor in .001..1000')
            if not isinstance(params['output_factors'], dict) or set(params['output_factors']) != set(schema['columns']):
                raise ValidationError('Every output column requires an explicit expected scale factor')
            for value in params['output_factors'].values():
                if not .000001 <= number(value) <= 1000000:
                    raise ValidationError('Output scale factors must be positive and bounded')
        else:
            keys(params, 'effect standard_error ci_lower ci_upper p_value q_value')
            if (any(not isinstance(v, str) or v not in schema['columns'] for v in params.values())
                    or len(set(params.values())) != len(params)):
                raise ValidationError('Contrast roles must name distinct frozen output columns')
            context = source['context']
            contrast = context.get('contrast')
            if (not isinstance(contrast, list) or len(contrast) != 2
                    or any(not isinstance(v, str) or not v.strip() for v in contrast) or contrast[0] == contrast[1]
                    or context.get('test') != 'two_sided_wald' or context.get('lfc_shrinkage') is not False
                    or context.get('testing_family') != 'fixed' or context.get('fit_policy') != 'same_fit'):
                raise ValidationError('Contrast reversal requires a fixed-family, same-fit, two-sided unshrunk Wald contract')
        changed = transform(source, relation)
        _matrix(changed['matrix'])
        if suite_digest(changed) == suite_digest(source):
            raise ValidationError('Metamorphic transformation has no effect on this input')
    return design


def transform(source, relation):
    """Only reviewed transforms; no eval, expression language or module loading."""
    result = deepcopy(source)
    matrix, name, p = result['matrix'], relation['relation'], relation['parameters']
    if name in ('row_permutation', 'partition_invariance'):
        lookup = dict(zip(matrix['row_ids'], matrix['values']))
        matrix['row_ids'] = list(p['order'])
        matrix['values'] = [lookup[i] for i in p['order']]
    elif name == 'feature_permutation':
        order = [matrix['columns'].index(c) for c in p['order']]
        matrix['columns'] = list(p['order'])
        matrix['values'] = [[row[i] for i in order] for row in matrix['values']]
    elif name == 'positive_scale':
        matrix['values'] = [[v * p['factor'] if c in p['columns'] else v
                             for c, v in zip(matrix['columns'], row)] for row in matrix['values']]
    elif name == 'contrast_reversal':
        result['context']['contrast'].reverse()
    else:
        raise ValidationError('Unregistered scientific transformation')
    return result


def build_inputs(design):
    validate_design(design)
    inputs = {'baseline': deepcopy(design['source'])}
    inputs.update({r['id']: transform(design['source'], r) for r in design['relations']})
    return inputs


def _compare(baseline, observed, relation, tolerance):
    name, params = relation['relation'], relation['parameters']
    mismatches, count, max_error = [], 0, 0.0
    if name == 'partition_invariance':
        forward, backward = {}, {}
        for rid in sorted(baseline):
            a, b = baseline[rid], observed[rid]
            if (a in forward and forward[a] != b) or (b in backward and backward[b] != a):
                count += 1
                if len(mismatches) < 20:
                    mismatches.append({'row_id': rid, 'reason': 'cluster_co_membership_changed'})
            forward[a], backward[b] = b, a
        return count, mismatches, None
    for rid in sorted(baseline):
        expected = dict(baseline[rid])
        if name == 'positive_scale':
            expected = {c: v * params['output_factors'][c] for c, v in expected.items()}
        elif name == 'contrast_reversal':
            expected[params['effect']] *= -1
            expected[params['ci_lower']] = -baseline[rid][params['ci_upper']]
            expected[params['ci_upper']] = -baseline[rid][params['ci_lower']]
        for column, wanted in expected.items():
            number(wanted)
            actual = observed[rid][column]
            error = abs(actual - wanted)
            # Avoid non-JSON infinity in diagnostics for extreme finite values.
            if math.isfinite(error) and max_error is not None:
                max_error = max(max_error, error)
            elif not math.isfinite(error):
                max_error = None
            if not math.isclose(actual, wanted, abs_tol=tolerance['absolute'], rel_tol=tolerance['relative']):
                count += 1
                if len(mismatches) < 20:
                    mismatches.append({'row_id': rid, 'column': column, 'expected': wanted, 'observed': actual})
    return count, mismatches, max_error


def _contrast_domains(rows, roles):
    for row in rows.values():
        if (row[roles['standard_error']] < 0 or row[roles['ci_lower']] > row[roles['ci_upper']]
                or not row[roles['ci_lower']] <= row[roles['effect']] <= row[roles['ci_upper']]
                or any(not 0 <= row[roles[k]] <= 1 for k in ('p_value', 'q_value'))):
            raise ValidationError('Invalid Wald interval, standard error or probability domain')


def assess(design, observations):
    inputs = build_inputs(design)
    keys(observations, 'format design_sha256 runs')
    receipt = {'format': 'pvl-metamorphic-receipt-1', 'scope': 'METAMORPHIC_CONSISTENCY_ONLY',
               'design_sha256': suite_digest(design), 'scientific_validity': 'NOT_ESTABLISHED',
               'execution_evidence': 'SUBMITTED_ARTIFACTS_NOT_ATTESTED', 'oracle_required': True,
               'relations': [], 'tolerance': design['tolerance']}
    if observations['format'] != OBSERVATIONS or observations['design_sha256'] != suite_digest(design):
        return None, dict(receipt, status='UNKNOWN', reason='Observation design commitment missing or changed')
    runs = observations['runs']
    if not isinstance(runs, list) or len(runs) > 33:
        raise ValidationError('Observation runs must be a bounded list')
    indexed = {}
    for run in runs:
        keys(run, 'id input_sha256 status output')
        if not isinstance(run['id'], str) or run['id'] not in inputs or run['id'] in indexed:
            raise ValidationError('Unknown or duplicate metamorphic run identity')
        if run['status'] not in ('completed', 'error', 'timeout'):
            raise ValidationError('Invalid metamorphic run status')
        indexed[run['id']] = run
    def resolved(identity):
        run = indexed.get(identity)
        if run is None or run['status'] != 'completed':
            return None, 'missing_or_failed_run'
        if run['input_sha256'] != suite_digest(inputs[identity]):
            return None, 'input_commitment_mismatch'
        return _output(run['output'], design['output']), None
    base, base_issue = resolved('baseline')
    if base_issue is None:
        try:
            observations_digest = suite_digest(observations)
        except (ValueError, TypeError) as exc:
            raise ValidationError('Observations must contain finite JSON values') from exc
        # Derived from validated identities, never a grader's self-declared role.
        receipt['correctness_target'] = {
            'path': f"runs.{next(i for i, run in enumerate(runs) if run['id'] == 'baseline')}.output",
            'schema': deepcopy(design['output']),
            'observations_sha256': observations_digest}
    for relation in design['relations']:
        row = {'id': relation['id'], 'relation': relation['relation'], 'passed': None,
               'source_input_sha256': suite_digest(inputs['baseline']),
               'followup_input_sha256': suite_digest(inputs[relation['id']]),
               'applicability': relation['rationale']}
        other, issue = resolved(relation['id'])
        if base_issue or issue:
            row.update(status='UNKNOWN', reason=base_issue or issue)
        else:
            if relation['relation'] == 'contrast_reversal':
                _contrast_domains(base, relation['parameters'])
                _contrast_domains(other, relation['parameters'])
            count, mismatches, max_error = _compare(base, other, relation, design['tolerance'])
            row.update(passed=count == 0, status='FAIL' if count else 'PASS',
                       mismatch_count=count, counterexamples=mismatches, max_absolute_error=max_error)
        receipt['relations'].append(row)
    states = [row['passed'] for row in receipt['relations']]
    passed = False if False in states else None if None in states else True
    receipt['status'] = 'FAIL' if passed is False else 'UNKNOWN' if passed is None else 'PASS'
    receipt['planned_relations'] = len(states)
    receipt['resolved_relations'] = sum(v is not None for v in states)
    return passed, receipt


def _reference_qualification(definitions, grades):
    """Bind a complete baseline proposition to each checked relation artifact.

    This qualifies coverage, not the truth/independence of an author-supplied
    reference. Unsupported oracle contracts stay unresolved, never inferred
    from a successful status, grader name, type exclusion or another artifact.
    """
    indexed = {grade['id']: grade for grade in grades}
    targets = []
    for relation in definitions:
        if relation['type'] != 'metamorphic':
            continue
        verification = indexed.get(relation['id'], {}).get('verification', {})
        target = verification.get('correctness_target')
        candidates = []
        for rule in definitions:
            if rule['id'] == relation['id']:
                continue
            grade = indexed.get(rule['id'], {})
            checked = grade.get('verification', {})
            row = {'grader_id': rule['id'], 'qualified': False}
            candidates.append(row)
            if not target:
                row['reason'] = 'BASELINE_TARGET_UNAVAILABLE'
                continue
            expected = None
            if rule['type'] == 'artifact' and rule['verifier']['kind'] == 'json_fields':
                bound = (rule['artifact'] == relation['artifact']
                         and verification.get('artifact_sha256') is not None
                         and checked.get('artifact_sha256') == verification['artifact_sha256']
                         and checked.get('artifact_path') == verification.get('artifact_path'))
                expected = rule['verifier']['expected']
                if any(path == target['path'] or path.startswith(target['path'] + '.')
                       or target['path'].startswith(path + '.')
                       for path in rule['verifier'].get('unordered_paths', [])):
                    row['reason'] = 'UNORDERED_COMPARISON_DOES_NOT_BIND_RESULT_IDENTITIES'
                    continue
            elif rule['type'] == 'json_equals':
                bound = checked.get('output_json_sha256') == target['observations_sha256']
                expected = {rule['path']: rule['value']}
            else:
                row['reason'] = 'NO_SUPPORTED_COMPLETE_RESULT_PROPOSITION'
                continue
            if not bound:
                row['reason'] = 'REFERENCE_NOT_BOUND_TO_RELATION_ARTIFACT'
                continue
            output = {}
            for path, value in expected.items():
                # Whole output, an ancestor object, or its complete immediate
                # fields all express the same frozen result proposition.
                if path == target['path'] or target['path'].startswith(path + '.'):
                    try:
                        for part in target['path'].split('.')[len(path.split('.')):]:
                            value = value[int(part)] if isinstance(value, list) else value[part]
                        output = value
                        break
                    except (KeyError, IndexError, TypeError, ValueError):
                        continue
                prefix = target['path'] + '.'
                if path.startswith(prefix) and '.' not in path[len(prefix):]:
                    output[path[len(prefix):]] = value
            try:
                _output(output, target['schema'])
            except (ValueError, TypeError, KeyError, IndexError):
                row['reason'] = 'REFERENCE_DOES_NOT_COVER_COMPLETE_BASELINE_RESULT'
                continue
            row.update(qualified=grade.get('passed') is True,
                       reason='COMPLETE_BOUND_RESULT_REFERENCE' if grade.get('passed') is True
                       else 'REFERENCE_CHECK_FAILED_OR_UNKNOWN',
                       reference_sha256=suite_digest(output))
        targets.append({'grader_id': relation['id'], 'target': target,
                        'qualified': any(row['qualified'] for row in candidates), 'candidates': candidates})
    return {'status': 'QUALIFIED' if targets and all(t['qualified'] for t in targets) else 'UNKNOWN',
            'targets': targets, 'scope': 'Complete frozen baseline result coverage only',
            'reference_truth': 'NOT_INDEPENDENTLY_VALIDATED'}


def check(path, spec, root):
    try:
        design = reference_json(root, spec['design'])
        validate_design(design)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise OSError('Invalid frozen metamorphic design') from exc
    return assess(design, load_json(path))


def prepare(design, output):
    inputs = build_inputs(design)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    for identity, value in inputs.items():
        write_json(root / (identity + '.input.json'), value)
    manifest = {'format': 'pvl-metamorphic-inputs-1', 'design_sha256': suite_digest(design),
                'inputs': {identity: {'path': identity + '.input.json', 'sha256': suite_digest(value)} for identity, value in inputs.items()},
                'output_schema': design['output'], 'executed': False}
    write_json(root / 'inputs.json', manifest)
    return manifest


def collect(design, results_root, output):
    """Collect explicit result files; this action never executes an adapter."""
    from .artifacts import confined, MAX_BYTES
    inputs, runs = build_inputs(design), []
    for identity, value in inputs.items():
        path = confined(results_root, identity + '.result.json')
        if not path.exists():
            continue  # assessment retains UNKNOWN, never silently drops denominator
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValidationError('Invalid metamorphic result file')
        row = load_json(path)
        keys(row, 'input_sha256 status output')
        runs.append({'id': identity, **row})
    observations = {'format': OBSERVATIONS, 'design_sha256': suite_digest(design), 'runs': runs}
    passed, receipt = assess(design, observations)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / 'observations.json', observations)
    write_json(root / 'assessment.json', receipt)
    return {'passed': passed, 'status': receipt['status'], 'output': str(root), 'execution': False}
