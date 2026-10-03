"""Host-independent, per-claim capability vocabulary. No execution authority.

Adapters supply observations; consumers name required semantics, not host names.
Qualification means a parser/format contract, not provider authentication.
"""
from copy import deepcopy

from .core import ValidationError, suite_digest

FORMAT = 'pvl-host-capabilities-1'
SEMANTICS = {
    'session_identity': 'local-session-id/v1',
    'request_identity': 'local-response-turn-id/v1',
    'model_identity': 'local-turn-model-label/v1',
    'plugin_identity': 'observed-plugin-bytes/v1',
    'artifact_access': 'authorized-local-artifact-access/v1',
    'tool_declared': 'declared-tool-inventory/v1',
    'tool_loaded': 'observed-tool-load/v1',
    'tool_invoked': 'observed-tool-invocation/v1',
    'request_usage': 'response-bound-input-includes-cache/v1',
    'thread_usage': 'host-thread-cumulative-ledger/v1',
    'turn_usage': 'host-turn-cumulative-ledger/v1',
    'stream_usage': 'host-context-stream-cumulative-ledger/v1',
    'context_sample': 'post-response-input-plus-output-sample/v1',
    'settled_cost': 'actual-settled-currency-charge/v1',
    'comparable_execution': 'independent-matched-arms/v1',
    'incremental_resume': 'verified-prefix-parser-checkpoint/v1',
    'remote_task_status': 'reconciled-remote-execution-status/v1',
}
STATES = ('OBSERVED', 'UNKNOWN', 'UNSUPPORTED', 'NOT_PROVIDED')


def fact(name, status, value=None, *, evidence=(), reason):
    return dict(semantic_id=SEMANTICS[name], status=status, value=deepcopy(value),
                evidence=deepcopy(list(evidence)), reason=reason)


def validate(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {'format', 'adapter', 'qualification', 'source', 'capabilities', 'execution_authorized'}:
        raise ValidationError('Invalid capability snapshot envelope')
    if snapshot['format'] != FORMAT or snapshot['execution_authorized'] is not False:
        raise ValidationError('Capabilities never authorize execution')
    if not isinstance(snapshot['adapter'], str) or not snapshot['adapter']:
        raise ValidationError('Adapter identity is required')
    if not isinstance(snapshot['qualification'], dict) or not isinstance(snapshot['source'], dict):
        raise ValidationError('Qualification and source bindings are required')
    rows = snapshot['capabilities']
    if not isinstance(rows, dict) or set(rows) != set(SEMANTICS):
        raise ValidationError('Capability coverage must be explicit, including unavailable facts')
    for name, row in rows.items():
        if not isinstance(row, dict) or set(row) != {'semantic_id', 'status', 'value', 'evidence', 'reason'}:
            raise ValidationError('Invalid capability fact')
        if row['semantic_id'] != SEMANTICS[name] or row['status'] not in STATES:
            raise ValidationError('Unknown capability semantics or status; requalification required')
        if not isinstance(row['reason'], str) or not row['reason'].strip() or not isinstance(row['evidence'], list):
            raise ValidationError('Capability facts need reasons and evidence references')
        if row['status'] == 'OBSERVED':
            if row['value'] is None or not row['evidence'] or any(not isinstance(e, dict) or not e for e in row['evidence']):
                raise ValidationError('Observed capability needs a value and source reference')
        elif row['value'] is not None:
            raise ValidationError('Unavailable capability cannot supply a fallback measurement')
    suite_digest(snapshot)  # Reject non-JSON/nonfinite values.
    return snapshot


def resolve_requirements(snapshot, claims):
    """Resolve each claim independently; readiness is local evidence sufficiency.

    Each claim maps capability names to exact semantic identifiers. Empty claims
    are invalid: no observation is ever manufactured from an unrelated success.
    """
    validate(snapshot)
    if not isinstance(claims, dict) or not claims:
        raise ValidationError('Explicit claim requirements are required')
    result = {}
    for claim, requirements in claims.items():
        if not isinstance(claim, str) or not claim or not isinstance(requirements, dict) or not requirements:
            raise ValidationError('Claims require nonempty semantic dependencies')
        reasons = []
        for name, semantic in requirements.items():
            row = snapshot['capabilities'].get(name)
            if row is None or row['semantic_id'] != semantic:
                reasons.append({'capability': name, 'reason': 'SEMANTICS_NOT_QUALIFIED'})
            elif row['status'] != 'OBSERVED':
                reasons.append({'capability': name, 'reason': row['status'], 'detail': row['reason']})
        result[claim] = {'status': 'LOCAL_EVIDENCE_AVAILABLE' if not reasons else 'INSUFFICIENT_EVIDENCE',
                         'blockers': reasons, 'execution_authorized': False}
    return {'format': 'pvl-capability-resolution-1', 'snapshot_sha256': suite_digest(snapshot),
            'claims': result, 'provider_authenticated': False, 'scientific_validity_inferred': False}


def compare_capabilities(before, after):
    """Changes are scoped to individual facts; no whole-tool health boolean."""
    validate(before)
    validate(after)
    changed = [name for name in SEMANTICS if before['capabilities'][name] != after['capabilities'][name]]
    return {'changed_capabilities': changed,
            'qualification_changed': before['qualification'] != after['qualification'],
            'before_sha256': suite_digest(before), 'after_sha256': suite_digest(after),
            'unrelated_artifact_checks_invalidated': False}
