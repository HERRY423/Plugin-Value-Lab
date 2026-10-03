"""Read-only session handoff assessment against explicitly submitted current facts.

Stored guidance remains historical truth. Compatibility with a new environment
is a separate, checkpoint-bound report, never an automatic lifecycle mutation.
"""
import argparse
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import platform
import re
import sys

from .core import ValidationError, suite_digest
from .decision_store import DecisionStore, UNRESOLVED
from .delivery import publish_bundle, read_bundle
from .host_capabilities import resolve_requirements, SEMANTICS
from . import adapter_qualification

FORMAT = 'pvl-continuity-environment-1'


def _require(condition, message):
    if not condition:
        raise ValidationError(message)


def _identity():
    return {'python': sys.version, 'platform': platform.platform(),
            'sources': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(files('value_lab').iterdir(), key=lambda p: p.name) if p.name.endswith('.py')}}


def compare_judgment(retained, current):
    """Classify re-interpretation, without running a scorer or changing observations."""
    if current is None:
        return {'action': 'VERIFY_JUDGMENT_IDENTITY', 'changed': ['current_identity_missing']}
    _require(isinstance(current, dict) and set(current) == {'contract', 'implementation'}, 'Invalid current judgment identity')
    contract = current['contract']
    _require(isinstance(contract, dict) and set(contract) == {'grader', 'reference', 'domain'}
             and all(isinstance(v, dict) and v for v in contract.values()), 'Explicit grading/reference/domain contracts required')
    _require(current['implementation'] is None or isinstance(current['implementation'], str)
             and current['implementation'].strip(), 'Invalid implementation identity')
    changed = [k for k in ('grader', 'reference', 'domain')
               if suite_digest(contract[k]) != suite_digest(retained['contract'][k])]
    if current['implementation'] != retained['implementation']:
        changed.append('implementation')
    unknown = current['implementation'] is None or retained['implementation'] is None
    return {'action': 'VERIFY_JUDGMENT_IDENTITY' if unknown else 'RESCORE_RETAINED_OBSERVATIONS' if changed else 'REUSE_RETAINED_JUDGMENT',
            'changed': changed, 'observation_sha256': retained['observation_sha256'],
            'retained_result_sha256': retained['result_sha256']}


def inspect(store, environment, *, checkpoint=None):
    """Verify retained evidence, then separately assess current applicability.

    All environment identities and claim dependencies are explicit submitted
    facts, not automatic discovery or proof of completeness/authenticity.
    """
    identity = _identity()
    view = store.snapshot(checkpoint=checkpoint)
    _require(isinstance(environment, dict) and set(environment) == {
        'format', 'checkpoint', 'dependencies', 'judgments', 'decisions', 'host'}, 'Invalid continuity environment')
    _require(environment['format'] == FORMAT and suite_digest(environment['checkpoint']) == suite_digest(view['checkpoint']),
             'STALE_ENVIRONMENT: bind the current verified decision checkpoint')
    suite_digest(environment)
    for key in ('dependencies', 'judgments', 'decisions'):
        _require(isinstance(environment[key], dict), 'Environment mappings must be explicit')
    _require(all(isinstance(k, str) and k and (v is None or isinstance(v, str) and v.strip())
                 for k, v in environment['dependencies'].items()), 'Dependencies require identities or explicit unknowns')
    layer = view.get('explanations', {})
    judgments, decisions = layer.get('judgments', {}), layer.get('decisions', {})
    _require(set(environment['judgments']) <= set(judgments) and set(environment['decisions']) <= set(decisions),
             'Environment references unknown historical objects')
    dependency_changes = {k: {'retained': view['effective_dependencies'].get(k),
                              'current': environment['dependencies'].get(k)}
                          for k in sorted(set(view['effective_dependencies']) | set(environment['dependencies']))
                          if view['effective_dependencies'].get(k) is None or environment['dependencies'].get(k) is None
                          or view['effective_dependencies'].get(k) != environment['dependencies'].get(k)}
    comparisons = {jid: compare_judgment(j, environment['judgments'].get(jid)) for jid, j in judgments.items()}
    host = environment['host']
    qualification = None
    host_binding_issues = []
    if host is not None:
        _require(isinstance(host, dict) and set(host) == {'snapshot', 'receipt', 'receipt_sha256',
                  'expected_session_id', 'expected_prefix_sha256'}, 'Invalid host evidence binding')
        qualification = adapter_qualification.assess(host['receipt'], host['snapshot'], host['receipt_sha256'])
        observed = host['snapshot']['capabilities']['session_identity']
        if (not isinstance(host['expected_session_id'], str) or not host['expected_session_id']
                or observed['status'] != 'OBSERVED' or not isinstance(observed['value'], dict)
                or observed['value'].get('session_id') != host['expected_session_id']):
            host_binding_issues.append('HOST_SESSION_BINDING_MISMATCH')
        prefix = host['snapshot']['source'].get('complete_prefix_sha256')
        if not isinstance(prefix, str) or re.fullmatch('[a-f0-9]{64}', prefix) is None or prefix != host['expected_prefix_sha256']:
            host_binding_issues.append('HOST_SOURCE_BINDING_MISMATCH')
    rows = {}
    actions = deepcopy(view['next_steps'])
    for did, decision in decisions.items():
        status = layer['decision_states'][did]['status']
        if status in ('superseded', 'not_applicable'):
            rows[did] = {'status': 'HISTORICAL_ONLY', 'recorded_status': status, 'reasons': [], 'actions': []}
            continue
        reasons, needed, resolution = [], [], None
        if checkpoint is None:
            reasons.append('HISTORY_ANCHOR_UNVERIFIED')
            needed.append('VERIFY_RETAINED_CHECKPOINT')
        if status != 'current':
            reasons.append('RECORDED_GUIDANCE_REQUIRES_REVIEW')
            needed.append('REVIEW_GUIDANCE')
        if dependency_changes:
            reasons.append('DEPENDENCY_CHANGED_OR_UNKNOWN')
            needed.append('REVIEW_DEPENDENCY_APPLICABILITY')
        judgment = comparisons[decision['judgment_id']]
        if judgment['action'] != 'REUSE_RETAINED_JUDGMENT':
            reasons.append('JUDGMENT_CHANGED_OR_UNKNOWN')
            needed.append(judgment['action'])
        current = environment['decisions'].get(did)
        if current is None:
            reasons.append('CURRENT_POLICY_SCOPE_AND_HOST_REQUIREMENTS_UNKNOWN')
            needed.append('VERIFY_DECISION_CONTEXT')
        else:
            _require(isinstance(current, dict) and set(current) == {'policy', 'scope', 'host_requirements'}, 'Invalid current decision context')
            _require(isinstance(current['scope'], dict) and current['scope'] and isinstance(current['policy'], dict)
                     and set(current['policy']) == {'purpose', 'quality_thresholds', 'budget_micros'}, 'Explicit current scope and policy required')
            policy = current['policy']
            _require(isinstance(policy['purpose'], str) and policy['purpose'].strip()
                     and isinstance(policy['quality_thresholds'], dict) and policy['quality_thresholds']
                     and (policy['budget_micros'] is None or type(policy['budget_micros']) is int and policy['budget_micros'] >= 0),
                     'Invalid current policy values')
            if suite_digest(current['scope']) != suite_digest(decision['scope']):
                reasons.append('SCOPE_CHANGED')
                needed.append('REVIEW_NEW_SCOPE_APPLICABILITY')
            if suite_digest(current['policy']) != suite_digest(decision['policy']):
                reasons.append('POLICY_CHANGED')
                needed.append('REDECIDE_WITH_RETAINED_JUDGMENT' if judgment['action'] == 'REUSE_RETAINED_JUDGMENT'
                              else 'REDECIDE_AFTER_JUDGMENT_REVIEW')
            claims = current['host_requirements']
            _require(isinstance(claims, dict), 'Declare host claims explicitly; empty means no host-dependent claim')
            for claim, requirements in claims.items():
                _require(isinstance(claim, str) and claim and isinstance(requirements, dict) and requirements
                         and all(k in SEMANTICS and isinstance(v, str) and v for k, v in requirements.items()), 'Invalid host claim requirements')
            if claims:
                if host is None:
                    reasons.append('HOST_EVIDENCE_MISSING')
                    needed.append('COLLECT_QUALIFIED_HOST_EVIDENCE')
                else:
                    resolution = resolve_requirements(host['snapshot'], claims)
                    if qualification['status'] != 'LOCAL_CONFORMANCE_BOUND':
                        reasons.extend(qualification['reasons'])
                        needed.append('REQUALIFY_ADAPTER')
                    if host_binding_issues:
                        reasons.extend(host_binding_issues)
                        needed.append('VERIFY_HOST_SOURCE_BINDING')
                    if any(r['status'] != 'LOCAL_EVIDENCE_AVAILABLE' for r in resolution['claims'].values()):
                        reasons.append('HOST_CLAIM_EVIDENCE_INSUFFICIENT')
                        needed.append('COLLECT_MISSING_HOST_FACTS')
        row = {'status': 'REVIEW_REQUIRED' if reasons else 'RECORDED_CURRENT_COMPATIBLE',
               'recorded_status': status, 'reasons': reasons, 'actions': list(dict.fromkeys(needed)),
               'judgment_comparison': judgment, 'host_claim_resolution': resolution}
        rows[did] = row
        actions.extend({'action': a, 'decision_id': did} for a in row['actions'])
    compatible = [did for did, row in rows.items() if row['status'] == 'RECORDED_CURRENT_COMPATIBLE']
    # Leaf judgments without guidance still need explicit version assessment.
    parents = {j['parent'] for j in judgments.values()}
    for jid, comparison in comparisons.items():
        if jid not in parents and comparison['action'] != 'REUSE_RETAINED_JUDGMENT':
            actions.append({'action': comparison['action'], 'judgment_id': jid})
    # Legacy-only material stays readable; it never gains a current pointer.
    actions = list({suite_digest(a): a for a in actions}.values())
    _require(identity == _identity(), 'Runtime changed during assessment')
    return {'format': 'pvl-continuity-assessment-1', 'checkpoint': view['checkpoint'],
            'checkpoint_verified': view['checkpoint_verified'], 'environment_sha256': suite_digest(environment),
            'implementation': identity, 'status': 'FOLLOW_UP_REQUIRED' if actions else 'RETAINED_MATERIAL_REVIEWED',
            'decisions': rows, 'compatible_recorded_decisions': compatible,
            'judgment_comparisons': comparisons, 'dependency_changes': dependency_changes,
            'host_qualification': qualification, 'host_binding_issues': host_binding_issues,
            'next_steps': actions, 'costs': view['costs'], 'missing_evidence': view['missing_evidence'],
            'unresolved_invocations': {i: {k: deepcopy(a[k]) for k in (
                'requirement', 'mode', 'operation', 'external_key', 'invocation_id', 'status', 'max_cost_micros')}
                for i, a in view['attempts'].items() if a['status'] in UNRESOLVED},
            'observation_groups': view['observation_groups'],
            'legacy_interpretations_without_lifecycle': view['legacy_interpretations_without_lifecycle'],
            'scientific_sample_size': None, 'new_executions': 0, 'new_judgments': 0,
            'execution_authorized': False, 'environment_authenticated': False,
            'historical_state_modified': False, 'scientific_validity_inferred': False}


def publish(store, environment, output, *, checkpoint=None, resume=False):
    report = inspect(store, environment, checkpoint=checkpoint)
    encode = lambda v: (json.dumps(v, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    lines = ['# 跨会话恢复检查', '', '原始证据、费用和历史解释保持不变；此报告不授权执行。', '',
             '历史检查点已核验：' + str(report['checkpoint_verified']),
             '总费用（USD micros；null 表示未知）：' + str(report['costs']['total_cost_micros']), '',
             '## 当前适用性', '']
    for did, row in report['decisions'].items():
        from .usage import _markdown
        lines.append('- ' + _markdown(did + ': ' + row['status'] + '; ' + ', '.join(row['reasons'])))
    lines += ['', '完整下一步、版本差异及宿主资格见 assessment.json。',
              '依赖、策略和宿主要求是提交的范围声明，不是系统自动发现的完整清单。',
              '报告只适用于所绑定的检查点和环境；恢复后追加事件或升级实现需重新检查。']
    return publish_bundle(output, {'assessment.json': encode(report), 'environment.json': encode(environment),
                                  'HANDOFF.md': ('\n'.join(lines) + '\n').encode()}, resume=resume)


def verify(store, environment, output, *, checkpoint=None):
    manifest = read_bundle(output)
    _require(set(manifest['files']) == {'assessment.json', 'environment.json', 'HANDOFF.md'}, 'Invalid assessment bundle')
    _require(json.loads((Path(output) / 'environment.json').read_bytes()) == environment, 'Assessment environment changed')
    retained = json.loads((Path(output) / 'assessment.json').read_bytes())
    _require(suite_digest(retained) == suite_digest(inspect(store, environment, checkpoint=checkpoint)),
             'STALE_ASSESSMENT: inspect current state and environment again')
    return retained


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True)
    parser.add_argument('--environment', required=True)
    parser.add_argument('--checkpoint')
    parser.add_argument('--output', required=True)
    parser.add_argument('--resume-publication', action='store_true')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(argv)
    environment = json.loads(Path(args.environment).read_bytes())
    checkpoint = json.loads(Path(args.checkpoint).read_bytes()) if args.checkpoint else None
    if args.verify:
        report = verify(DecisionStore(args.store), environment, args.output, checkpoint=checkpoint)
        print(json.dumps({'status': 'VERIFIED', 'assessment_status': report['status']}))
        return 0
    result = publish(DecisionStore(args.store), environment, args.output, checkpoint=checkpoint, resume=args.resume_publication)
    print(json.dumps(result))
    return 0 if result['status'] == 'COMMITTED' else 3


if __name__ == '__main__':
    raise SystemExit(main())
