"""Parent-owned, durable gateway admission using a conservative request envelope.

No token estimator is treated as a bound. Reserve the entire model input window
plus max output at pinned published rates. Only the narrow standard text/client
tool Messages API profile is supported. This is conditional on the provider's
published context/rate contract, not a provider account spending control.
"""
from datetime import datetime, timezone
import hashlib
import json
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
    if not isinstance(config, dict) or set(config) != {'ledger', 'task_id', 'tariff_sha256'}:
        raise ValidationError('Gateway budget requires ledger/task_id/tariff_sha256')
    if not isinstance(config['ledger'], str) or not Path(config['ledger']).is_absolute():
        raise ValidationError('Budget ledger must be an absolute parent-only path')
    if not isinstance(config['task_id'], str) or not config['task_id'].strip():
        raise ValidationError('Budget task identity required')
    if config['tariff_sha256'] != suite_digest(TARIFF):
        raise ValidationError('Tariff commitment changed; review and freeze again')


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


def request_upper(path, body, beta):
    if path != '/v1/messages' or beta:
        raise ValidationError('Budget profile allows only standard /v1/messages without beta')
    try:
        payload = json.loads(body, parse_constant=_constant, object_pairs_hook=_unique_object)
    except (ValueError, TypeError) as exc:
        raise ValidationError('Invalid budgeted request JSON') from exc
    allowed = {'model', 'max_tokens', 'messages', 'system', 'tools', 'tool_choice',
               'stream', 'temperature', 'top_p', 'top_k', 'stop_sequences', 'metadata'}
    if not isinstance(payload, dict) or set(payload) - allowed or not {'model', 'max_tokens', 'messages'} <= set(payload):
        raise ValidationError('Unpriced request feature refused')
    if payload['model'] != TARIFF['model']:
        raise ValidationError('Model does not have a pinned request envelope')
    output = payload['max_tokens']
    if type(output) is not int or not 1 <= output <= TARIFF['max_output_tokens']:
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
    return TARIFF['context_tokens'] * TARIFF['input_micros_per_token'] + output * TARIFF['output_micros_per_token']


class GatewayBudget:
    def __init__(self, gateway):
        config = gateway.get('budget')
        if config is None:
            from .native import require_budget_boundary
            require_budget_boundary()
        validate_budget_config(config)
        if gateway['endpoint'] != 'https://api.anthropic.com' or gateway['models'] != [TARIFF['model']]:
            raise ValidationError('Priced gateway requires the pinned Anthropic origin and model')
        self.ledger = RequestBudget(config['ledger'], config['task_id'])
        self.tariff_sha256 = config['tariff_sha256']
        self.check()

    def check(self):
        if (self.tariff_sha256 != suite_digest(TARIFF)
                or datetime.now(timezone.utc) >= datetime.fromisoformat(TARIFF['expires_at'])):
            raise ValidationError('TARIFF_EXPIRED_OR_CHANGED: reverify prices and context before launch')
        state = self.ledger.status()
        if state['status'] != 'ACCOUNTING_READY':
            raise ValidationError(state['status'] + ': gateway admission denied')
        return state

    def preflight(self, max_output_tokens):
        state = self.check()
        upper = TARIFF['context_tokens'] * TARIFF['input_micros_per_token'] + max_output_tokens * TARIFF['output_micros_per_token']
        if upper > state['per_request_micros']:
            raise ValidationError('PER_REQUEST_CAP_EXCEEDED: conservative model envelope cannot fit the approved cap')
        if upper > state['remaining_micros']:
            raise ValidationError('TASK_BUDGET_EXHAUSTED')

    def reserve(self, key, path, body, beta):
        self.check()
        upper = request_upper(path, body, beta)
        digest = suite_digest({'origin': 'https://api.anthropic.com', 'method': 'POST', 'path': path,
                               'body_sha256': hashlib.sha256(body).hexdigest(), 'beta': beta,
                               'tariff_sha256': self.tariff_sha256})
        result = self.ledger.reserve(key, digest, 'Anthropic POST ' + path, upper)
        if not result['dispatch']:
            raise ValidationError('RECOVER_ORIGINAL_INVOCATION: reservation replay cannot dispatch')
        return {'key': key, 'upper_micros': upper, 'request_sha256': digest,
                'tariff_sha256': self.tariff_sha256, 'enforcement': 'GATEWAY_CONDITIONAL_ON_PUBLISHED_TARIFF',
                'provider_cap_verified': False}
