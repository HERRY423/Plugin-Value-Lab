"""Three-delivery integration acceptance using preserved synthetic history only."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from check_interpretation_history import exercise
from value_lab import adapter_qualification, continuity
from value_lab.codex_context import capture
from value_lab.context_stream import capabilities
from value_lab.core import ValidationError, suite_digest
from value_lab.decision_store import DecisionStore


def run(output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    prior = exercise(root / 'history')  # Actually grades retained JSON under both rules.
    store = DecisionStore(root / 'history/decision.sqlite')
    state = store.snapshot()
    decision = deepcopy(state['explanations']['decisions']['d3'])
    payload = {k: decision[k] for k in ('judgment_id', 'policy', 'scope')}
    payload.update(decision_id='d4', replaces='d3', status='current',
                   recommendation='Do not use the nonconforming synthetic artifact; retain failure.',
                   reason='Explicit bounded non-use decision after corrected format check')
    store.append('decide', payload, key='explicit-non-use', expected_sequence=state['sequence'])
    before = store.snapshot()
    anchor = before['checkpoint']
    (root / 'retained-checkpoint.json').write_text(json.dumps(anchor), encoding='utf-8')
    fixture = ROOT / 'tests/fixtures/codex-context-v1.json'
    receipt = adapter_qualification.qualify(fixture, root / 'qualification-work')
    assert receipt['status'] == 'PASS'
    (root / 'qualification.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    events = next(c['events'] for c in json.loads(fixture.read_bytes())['cases'] if c['name'] == 'measured')
    source = root / 'synthetic.jsonl'
    source.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
    snapshot = capabilities(capture(source, 'session'))
    env = {'format': continuity.FORMAT, 'checkpoint': anchor, 'dependencies': before['effective_dependencies'],
           'judgments': {i: {k: j[k] for k in ('contract', 'implementation')}
                         for i, j in before['explanations']['judgments'].items()},
           'decisions': {'d4': {k: payload[k] for k in ('policy', 'scope')} | {
               'host_requirements': {'usage': {'request_usage': 'response-bound-input-includes-cache/v1'}}}},
           'host': {'snapshot': snapshot, 'receipt': receipt, 'receipt_sha256': suite_digest(receipt),
                    'expected_session_id': 'session', 'expected_prefix_sha256': snapshot['source']['complete_prefix_sha256']}}
    environment = root / 'environment.json'
    environment.write_text(json.dumps(env), encoding='utf-8')
    store.export(root / 'recovery')
    restored_path = root / 'new-session.sqlite'
    command = [sys.executable, '-m', 'value_lab.decision_store', '--store', str(restored_path), 'restore',
               '--bundle', str(root / 'recovery'), '--checkpoint', str(root / 'retained-checkpoint.json')]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
    command = [sys.executable, '-m', 'value_lab.continuity', '--store', str(restored_path),
               '--checkpoint', str(root / 'retained-checkpoint.json'), '--environment', str(environment),
               '--output', str(root / 'handoff')]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
    subprocess.run(command + ['--verify'], cwd=ROOT, check=True, capture_output=True)
    restored = DecisionStore(restored_path)
    report = continuity.verify(restored, env, root / 'handoff', checkpoint=anchor)
    assert report['compatible_recorded_decisions'] == []
    assert report['decisions']['d4']['recorded_status'] == 'review_required'
    assert report['decisions']['d4']['judgment_comparison']['action'] == 'REUSE_RETAINED_JUDGMENT'
    assert report['host_qualification']['status'] == 'LOCAL_CONFORMANCE_BOUND'
    variants = {}
    for label in ('rule_upgrade', 'policy_change', 'unqualified_host', 'wrong_session', 'unknown_cost_capability'):
        changed = deepcopy(env)
        if label == 'rule_upgrade':
            changed['judgments']['j2']['implementation'] = 'new-grader-build'
        elif label == 'policy_change':
            changed['decisions']['d4']['policy']['purpose'] = 'new purpose'
        elif label == 'unqualified_host':
            changed['host']['snapshot']['qualification']['observed_engine_version'] = 'future'
        elif label == 'wrong_session':
            changed['host']['expected_session_id'] = 'different'
        else:
            changed['decisions']['d4']['host_requirements'] = {'cash': {'settled_cost': 'actual-settled-currency-charge/v1'}}
        assessment = continuity.inspect(restored, changed, checkpoint=anchor)
        assert assessment['compatible_recorded_decisions'] == []
        variants[label] = assessment['decisions']['d4']
    assert restored.snapshot() == before and store.snapshot() == before
    result = {'format': 'pvl-continuity-acceptance-1', 'status': 'PASS', 'evidence': 'SIMULATION_ONLY',
              'separate_process_restore_and_assessment': True, 'checkpoint_verified': True,
              'old_rule': prior['old_rule'], 'corrected_rule': prior['corrected_rule'],
              'observations_costs_and_history_unchanged': True, 'qualified_controls': receipt['checks'],
              'pending_review_not_reactivated_by_matching_environment': True,
              'variants': variants, 'new_executions': 0, 'new_scientific_samples': 0,
              'paid_calls': 0, 'live_host_verified': False, 'real_researcher_benefit_established': False,
              'execution_authorized': False,
              'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
                  'value_lab/continuity.py', 'value_lab/adapter_qualification.py', 'scripts/check_continuity.py')}}
    (root / 'acceptance.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    print(json.dumps(run(parser.parse_args().output), indent=2))
