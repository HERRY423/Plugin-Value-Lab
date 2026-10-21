"""Parent-owned, durable gateway admission using a conservative request envelope.

No token estimator is treated as a bound. Reserve the entire model input window
plus max output at pinned published rates. Only the narrow standard text/client
tool Messages API profile is supported. This is conditional on the provider's
published context/rate contract, not a provider account spending control.
"""
from datetime import datetime, timezone
import hashlib
import json
import copy
import math
from pathlib import Path

from .core import ValidationError, suite_digest, _constant, _unique_object
from .request_budget import RequestBudget


TARIFF = {
    'id': 'anthropic-haiku45-standard-20261012',
    'model': 'claude-haiku-4-5-20251001',
    'context_tokens': 200000, 'max_output_tokens': 64000,
    'input_micros_per_token': 1, 'output_micros_per_token': 5,
    'source': 'https://platform.claude.com/docs/en/models/haiku-4-5/overview',
    'expires_at': '2026-10-15T00:00:00+00:00',
}


def validate_budget_config(config):
    if not isinstance(config, dict) or not {'ledger', 'task_id', 'tariff_sha256'} <= set(config) or set(config) - {'ledger', 'task_id', 'tariff_sha256', 'policy'}:
        raise ValidationError('Gateway budget requires ledger/task_id/tariff_sha256')
    if not isinstance(config['ledger'], str) or not Path(config['ledger']).is_absolute():
        raise ValidationError('Budget ledger must be an absolute parent-only path')
    if not isinstance(config['task_id'], str) or not config['task_id'].strip():
        raise ValidationError('Budget task identity required')
    policy = config.get('policy')
    if policy is not None:
        validate_policy(policy)
    if config['tariff_sha256'] != suite_digest(policy if policy is not None else TARIFF):
        raise ValidationError('Tariff commitment changed; review and freeze again')


DEFAULT_PER_REQUEST_MICROS = 100000
DEFAULT_TOTAL_MICROS = 1000000


def validate_policy(policy):
    """Lab-owned snapshot; no embedded current-price claims or secret values."""
    required = {'endpoint', 'protocol', 'network_scope', 'allowed_addresses',
                'per_request_micros', 'total_micros', 'tariffs'}
    if not isinstance(policy, dict) or set(policy) != required:
        raise ValidationError('Frozen policy requires endpoint/protocol/network_scope/allowed_addresses/per_request_micros/total_micros/tariffs')
    from .model_endpoint import validate_endpoint
    validate_endpoint(policy)
    if policy['protocol'] not in ('anthropic_messages', 'openai_chat'):
        raise ValidationError('Unsupported priced text protocol')
    per, total = policy['per_request_micros'], policy['total_micros']
    if type(per) is not int or type(total) is not int or not 0 < per <= total <= 10**12:
        raise ValidationError('Require integer 0 < per-request <= total USD micros')
    tariffs = policy['tariffs']
    if not isinstance(tariffs, list) or not 1 <= len(tariffs) <= 8:
        raise ValidationError('Freeze 1–8 model tariffs')
    models = set()
    fields = set(TARIFF)
    for tariff in tariffs:
        if not isinstance(tariff, dict) or set(tariff) != fields:
            raise ValidationError('Each model needs its own complete tariff snapshot')
        for key in ('id', 'model', 'source', 'expires_at'):
            if not isinstance(tariff[key], str) or not tariff[key].strip():
                raise ValidationError('Missing tariff ' + key)
        if tariff['model'] in models:
            raise ValidationError('Duplicate model tariff')
        models.add(tariff['model'])
        for key in ('context_tokens', 'max_output_tokens'):
            if type(tariff[key]) is not int or not 1 <= tariff[key] <= 10**8:
                raise ValidationError('Invalid tariff token bound')
        for key in ('input_micros_per_token', 'output_micros_per_token'):
            value = tariff[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10**6:
                raise ValidationError('Invalid tariff rate')
        try:
            expiry = datetime.fromisoformat(tariff['expires_at'])
            if expiry.tzinfo is None:
                raise ValueError('timezone required')
        except (ValueError, TypeError) as exc:
            raise ValidationError('Tariff expiry must include timezone') from exc


def envelope(tariff, output):
    from decimal import Decimal, ROUND_CEILING
    if type(output) is not int or not 1 <= output <= tariff['max_output_tokens']:
        raise ValidationError('Output exceeds priced model limit')
    amount = (Decimal(tariff['context_tokens']) * Decimal(str(tariff['input_micros_per_token']))
              + Decimal(output) * Decimal(str(tariff['output_micros_per_token'])))
    return int(amount.to_integral_value(rounding=ROUND_CEILING))


def _text_blocks(content, *, system=False):
    if isinstance(content, str):
        return
    if not isinstance(content, list):
        raise ValidationError('Only text and client tool messages are budgeted')
    for block in content:
        if not isinstance(block, dict):
            raise ValidationError('Invalid content block')
        kind = block.get('type')
        if kind == 'text' and set(block) == {'type', 'text'} and isinstance(block['text'], str):
            continue
        if not system and kind == 'tool_use' and set(block) == {'type', 'id', 'name', 'input'} and isinstance(block['input'], dict):
            continue
        if not system and kind == 'tool_result' and set(block) <= {'type', 'tool_use_id', 'content', 'is_error'} and {'type', 'tool_use_id', 'content'} <= set(block):
            _text_blocks(block['content'], system=True)
            continue
        raise ValidationError('Unpriced content/cache/server tool feature refused')


def request_upper(path, body, beta, tariff=None, protocol='anthropic_messages'):
    tariff = TARIFF if tariff is None else tariff
    expected_path = '/v1/messages' if protocol == 'anthropic_messages' else '/v1/chat/completions'
    if path != expected_path or beta:
        raise ValidationError('Budget profile allows only standard /v1/messages without beta')
    try:
        payload = json.loads(body, parse_constant=_constant, object_pairs_hook=_unique_object)
    except (ValueError, TypeError) as exc:
        raise ValidationError('Invalid budgeted request JSON') from exc
    if protocol == 'openai_chat':
        allowed = {'model', 'max_tokens', 'messages', 'temperature', 'top_p', 'stop', 'stream'}
        if (not isinstance(payload, dict) or set(payload) - allowed
                or not {'model', 'max_tokens', 'messages'} <= set(payload)
                or payload['model'] != tariff['model']):
            raise ValidationError('Unpriced chat feature or model refused')
        if not isinstance(payload['messages'], list) or not payload['messages']:
            raise ValidationError('Messages required')
        for message in payload['messages']:
            if (not isinstance(message, dict) or set(message) != {'role', 'content'}
                    or message['role'] not in ('system', 'user', 'assistant')
                    or not isinstance(message['content'], str)):
                raise ValidationError('Only standard text chat is priced')
        return envelope(tariff, payload['max_tokens'])
    allowed = {'model', 'max_tokens', 'messages', 'system', 'tools', 'tool_choice',
               'stream', 'temperature', 'top_p', 'top_k', 'stop_sequences', 'metadata'}
    if not isinstance(payload, dict) or set(payload) - allowed or not {'model', 'max_tokens', 'messages'} <= set(payload):
        raise ValidationError('Unpriced request feature refused')
    if payload['model'] != tariff['model']:
        raise ValidationError('Model does not have a pinned request envelope')
    output = payload['max_tokens']
    if type(output) is not int or not 1 <= output <= tariff['max_output_tokens']:
        raise ValidationError('Output exceeds priced model limit')
    if not isinstance(payload['messages'], list) or not payload['messages']:
        raise ValidationError('Messages required')
    for message in payload['messages']:
        if not isinstance(message, dict) or set(message) != {'role', 'content'} or message['role'] not in ('user', 'assistant'):
            raise ValidationError('Unpriced message feature refused')
        _text_blocks(message['content'])
    if 'system' in payload:
        _text_blocks(payload['system'], system=True)
    if 'tools' in payload:
        if not isinstance(payload['tools'], list):
            raise ValidationError('Invalid tools')
        for tool in payload['tools']:
            if (not isinstance(tool, dict) or not {'name', 'input_schema'} <= set(tool)
                    or set(tool) - {'name', 'description', 'input_schema'}):
                raise ValidationError('Only client-defined tools are priced; server tools refused')
    # Full window covers hidden system/tool overhead; no estimate or cache discount.
    return envelope(tariff, output)


class GatewayBudget:
    def __init__(self, gateway):
        config = gateway.get('budget')
        if config is None:
            from .native import require_budget_boundary
            require_budget_boundary()
        validate_budget_config(config)
        self.policy = copy.deepcopy(config.get('policy'))
        self.snapshot = self.policy if self.policy is not None else copy.deepcopy(TARIFF)
        self.tariffs = {t['model']: t for t in self.policy['tariffs']} if self.policy else {TARIFF['model']: self.snapshot}
        self.endpoint = self.policy['endpoint'] if self.policy else 'https://api.anthropic.com'
        self.protocol = self.policy['protocol'] if self.policy else 'anthropic_messages'
        if gateway['endpoint'] != self.endpoint or set(gateway['models']) != set(self.tariffs):
            raise ValidationError('Priced gateway requires the frozen origin and model whitelist')
        if gateway.get('protocol', 'anthropic_messages') != self.protocol:
            raise ValidationError('Frozen gateway protocol mismatch')
        for key, default in (('network_scope', 'public'), ('allowed_addresses', [])):
            if gateway.get(key, default) != (self.policy[key] if self.policy else default):
                raise ValidationError('Frozen endpoint scope mismatch')
        self.ledger = RequestBudget(config['ledger'], config['task_id'])
        self.tariff_sha256 = config['tariff_sha256']
        self.check()

    def check(self):
        if (self.tariff_sha256 != suite_digest(self.snapshot)
                or any(datetime.now(timezone.utc) >= datetime.fromisoformat(t['expires_at']) for t in self.tariffs.values())):
            raise ValidationError('TARIFF_EXPIRED_OR_CHANGED: reverify prices and context before launch')
        state = self.ledger.status()
        if self.policy and any(state[key] != self.policy[key] for key in ('per_request_micros', 'total_micros')):
            raise ValidationError('Ledger limits differ from frozen lab policy')
        if state['status'] != 'ACCOUNTING_READY':
            raise ValidationError(state['status'] + ': gateway admission denied')
        return state

    def preflight(self, max_output_tokens):
        state = self.check()
        upper = max(envelope(t, max_output_tokens) for t in self.tariffs.values())
        if upper > state['per_request_micros']:
            raise ValidationError('PER_REQUEST_CAP_EXCEEDED: conservative model envelope cannot fit the approved cap')
        if upper > state['remaining_micros']:
            raise ValidationError('TASK_BUDGET_EXHAUSTED')

    def reserve(self, key, path, body, beta):
        self.check()
        try:
            model = json.loads(body, parse_constant=_constant, object_pairs_hook=_unique_object)['model']
            tariff = self.tariffs[model]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValidationError('Model does not have a frozen tariff') from exc
        upper = request_upper(path, body, beta, tariff, self.protocol)
        digest = suite_digest({'origin': self.endpoint, 'method': 'POST', 'path': path,
                               'body_sha256': hashlib.sha256(body).hexdigest(), 'beta': beta,
                               'tariff_sha256': self.tariff_sha256})
        result = self.ledger.reserve(key, digest, model + ' POST ' + path, upper, allow_zero=upper == 0)
        if not result['dispatch']:
            raise ValidationError('RECOVER_ORIGINAL_INVOCATION: reservation replay cannot dispatch')
        return {'key': key, 'upper_micros': upper, 'request_sha256': digest,
                'tariff_sha256': self.tariff_sha256, 'model_tariff_sha256': suite_digest(tariff),
                'model': model, 'enforcement': 'GATEWAY_CONDITIONAL_ON_FROZEN_TARIFF',
                'provider_cap_verified': False}
