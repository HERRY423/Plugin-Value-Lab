"""Small scientific plugin used ONLY for public, deterministic mutation experiments.

No PVL imports, scorer answers, network, real datasets or accounts. Mutations are
single source replacements in isolated copies; this file remains the clean base.
"""
import csv
import json
import math
from pathlib import Path
from statistics import mean, stdev


def save(value):
    Path('result.json').write_text(json.dumps(value, sort_keys=True), encoding='utf-8')


def table(rows, columns):
    with Path('result.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def bh(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    result, running = [0.] * len(values), 1.
    for rank in range(len(order), 0, -1):
        index = order[rank-1]
        running = min(running, values[index] * len(values) / rank)
        result[index] = running
    return result


def read_reference(task):
    return task['reference_ids'][:]


def read_eval_reference(task):
    return task['reference_ids'][:] + task['evaluation_ids'][:1]


def read_eval_features(task):
    return task['reference_ids'][:] + task['evaluation_ids'][1:]


def exact_backend(values):
    return sum(values) / len(values)


def fallback_backend(values):
    return round(sum(values) / len(values))


def legacy_backend(values):
    return sum(values) / len(values)


def dispatch(task):
    route = 'direct' if task['family'] == 'trigger' and task['variant'] == 2 else 'pvl-seed:analyze'
    return route


def analyze(task):
    family = task['family']
    if family in ('multiple-testing', 'id-alignment'):
        rows = [dict(row) for row in task['rows']]
        q = bh([r['p'] for r in rows])
        for row, value in zip(rows, q):
            row['q'] = value
        # Correct reordering is an explicit negative control.
        if task['variant'] == 1:
            rows.reverse()
        table(rows, ['id', 'p', 'q', 'effect'])
    elif family == 'pseudoreplication':
        units = {r['donor']: r['value'] for r in task['measurements']}
        n_units = len(units)
        values = list(units.values())
        se = stdev(values) / math.sqrt(len(values))
        save({'n_units': n_units, 'analysis_unit': 'donor', 'se': se})
    elif family == 'reference-leakage':
        trained = read_reference(task)
        declared = trained[:]
        if task['variant'] == 1:
            declared.reverse()  # Training-set order has no semantic meaning.
        save({'training_ids': declared, 'score': 1.0})
        Path('model-state.json').write_text(json.dumps({'used_ids': trained}), encoding='utf-8')
    elif family == 'backend-fallback':
        value = exact_backend(task['values'])
        save({'value': value, 'backend': 'exact', 'version': '1'})
    elif family == 'label-semantics':
        labels = task['labels'][:]
        if task['variant'] == 1:
            labels = [task['aliases'].get(label, label) for label in labels]
        rows = [{'id': key, 'label': label} for key, label in zip(task['ids'], labels)]
        if task['variant'] == 2:
            rows.reverse()
        table(rows, ['id', 'label'])
    elif family == 'over-refusal':
        decision = 'allow' if len(task['values']) >= 3 else 'withhold'
        answer = mean(task['values']) if decision == 'allow' else None
        save({'decision': decision, 'answer': answer})
    elif family == 'trigger':
        save({'ok': True})
    else:
        raise ValueError('Unknown seeded task')
