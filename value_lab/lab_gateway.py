"""Freeze operator-supplied model rates and explicit budget history; no network."""
from pathlib import Path

from .core import load_json, suite_digest, ValidationError
from .gateway_budget import validate_policy, DEFAULT_PER_REQUEST_MICROS, DEFAULT_TOTAL_MICROS
from .request_budget import RequestBudget
from .screening import _save


def freeze_models(policy_path, ledger_path, task_id, output, *, history_path=None,
                  history_ref=None, api_key_env='PVL_MODEL_KEY', no_auth=False,
                  max_output_tokens=1000, max_requests=100):
    policy = load_json(policy_path)
    if not isinstance(policy, dict):
        raise ValidationError('Model policy must be an object')
    policy = {'per_request_micros': DEFAULT_PER_REQUEST_MICROS,
              'total_micros': DEFAULT_TOTAL_MICROS, **policy}
    validate_policy(policy)
    output = Path(output).resolve()
    ledger_path = Path(ledger_path).resolve()
    if output.exists():
        raise ValidationError('Use a new freeze directory')
    gateway = {k: policy[k] for k in ('endpoint', 'protocol', 'network_scope', 'allowed_addresses')}
    gateway.update(models=[t['model'] for t in policy['tariffs']], api_key_env=api_key_env,
                   auth='none' if no_auth else 'api_key', max_requests=max_requests,
                   max_output_tokens=max_output_tokens, request_timeout_seconds=120,
                   budget={'ledger': str(ledger_path), 'task_id': task_id,
                           'policy': policy, 'tariff_sha256': suite_digest(policy)})
    from .online_sandbox import validate_config
    validate_config({'format': 'pvl-online-sandbox-1', 'backend': 'bubblewrap',
                     'runtime': '/unused-for-freeze', 'executable': 'claude', 'gateway': gateway})
    if ledger_path.exists():
        if history_path or history_ref:
            raise ValidationError('Existing ledger is reopened; history cannot be replaced')
        ledger = RequestBudget(ledger_path, task_id)
    else:
        if history_path is None or not history_ref:
            raise ValidationError('New ledger requires explicit history inventory and coverage reference')
        ledger = RequestBudget.create(ledger_path, task_id, policy['per_request_micros'], policy['total_micros'],
                                      history=load_json(history_path), coverage_ref=history_ref)
    if any(ledger.status()[k] != policy[k] for k in ('per_request_micros', 'total_micros')):
        raise ValidationError('Existing ledger limits cannot be changed by freezing another policy')
    output.mkdir(parents=True)
    _save(output / 'gateway.json', gateway)
    _save(output / 'policy.json', policy)
    from .gateway_budget import GatewayBudget
    try:
        GatewayBudget(gateway).preflight(max_output_tokens)
        status, reason = 'READY_FOR_REVIEW', None
    except ValidationError as exc:
        status, reason = 'BLOCKED', str(exc)
    result = {'status': status, 'reason': reason, 'gateway': str(output / 'gateway.json'),
              'policy_sha256': suite_digest(policy), 'model_calls': 0, 'paid_launch_authorized': False}
    _save(output / 'freeze-result.json', result)
    return result
