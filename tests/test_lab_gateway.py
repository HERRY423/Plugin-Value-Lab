"""Synthetic rates and mocked transports; no provider calls or current-price claims."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError, suite_digest, load_json
from value_lab.gateway_budget import GatewayBudget, TARIFF, envelope, validate_policy
from value_lab.lab_gateway import freeze_models
from value_lab.model_endpoint import validate_endpoint
from value_lab.online_sandbox import ModelGateway
from value_lab.request_budget import RequestBudget


def policy(scope='public', protocol='anthropic_messages'):
    return {'endpoint': 'https://api.example.com', 'protocol': protocol,
            'network_scope': scope, 'allowed_addresses': [], 'per_request_micros': 500000, 'total_micros': 1000000,
            'tariffs': [{**TARIFF, 'id': 'synthetic-a', 'model': 'model-a', 'expires_at': '2099-01-01T00:00:00+00:00',
                         'source': 'synthetic tariff for test only'},
                        {**TARIFF, 'id': 'synthetic-b', 'model': 'model-b', 'input_micros_per_token': .25,
                         'output_micros_per_token': .75, 'expires_at': '2099-01-01T00:00:00+00:00',
                         'source': 'synthetic tariff for test only'}]}


class LabGatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.policy = policy()
        self.path = self.root / 'ledger.db'
        self.ledger = RequestBudget.create(self.path, 'lab', 500000, 1000000,
                                           history=[], coverage_ref='synthetic task')

    def gateway_config(self):
        return {**{k: self.policy[k] for k in ('endpoint', 'protocol', 'network_scope', 'allowed_addresses')},
                'models': [t['model'] for t in self.policy['tariffs']], 'api_key_env': 'PVL_MODEL_KEY',
                'max_requests': 100, 'max_output_tokens': 100, 'request_timeout_seconds': 5,
                'budget': {'ledger': str(self.path), 'task_id': 'lab', 'tariff_sha256': suite_digest(self.policy),
                           'policy': deepcopy(self.policy)}}

    def frame(self, model='model-a', rid=1, **changes):
        body = {'model': model, 'max_tokens': 20, 'messages': [{'role': 'user', 'content': 'test'}], **changes}
        return {'kind': 'request', 'id': rid, 'path': '/v1/chat/completions' if self.policy['protocol'] == 'openai_chat' else '/v1/messages',
                'body': base64.b64encode(json.dumps(body).encode()).decode(), 'beta': ''}

    def gateway(self, transport=None):
        return ModelGateway(self.gateway_config(), 'fixture-key', transport or (lambda *a: (200, 'application/json', b'{}')),
                            invocation_id='a' * 64)

    def test_multimodel_individual_rates_share_task_ledger_above_old_cap(self):
        gateway = self.gateway()
        gateway.request(self.frame(), 5)
        gateway.request(self.frame('model-b', 2), 5)
        self.assertEqual([r['upper'] for r in self.ledger.status()['requests']], [200100, 50015])
        self.assertNotEqual(*[e['budget_reservation']['model_tariff_sha256'] for e in gateway.events])
        self.assertEqual(self.ledger.status()['remaining_micros'], 749885)

    def test_non_allowlisted_or_unpriced_features_never_dispatch(self):
        calls = []
        gateway = self.gateway(lambda *a: calls.append(a))
        for frame in (self.frame('other'), self.frame(thinking={'type': 'enabled'})):
            with self.assertRaises(ValidationError): gateway.request(frame, 5)
        self.assertEqual(calls, [])
        self.assertEqual(self.ledger.status()['requests'], [])
        gateway.config['endpoint'] = 'https://changed.example.com'
        with self.assertRaisesRegex(ValidationError, 'configuration changed'):
            gateway.request(self.frame(), 5)
        self.assertEqual(calls, [])

    def test_policy_tampering_expiry_budget_and_origin_mismatch(self):
        for field, value in [('endpoint', 'https://other.example.com'), ('models', ['model-a']), ('protocol', 'openai_chat')]:
            config = self.gateway_config()
            config[field] = value
            with self.assertRaises(ValidationError): GatewayBudget(config)
        config = self.gateway_config()
        config['budget']['policy']['tariffs'][0]['input_micros_per_token'] = 0
        with self.assertRaisesRegex(ValidationError, 'commitment'): GatewayBudget(config)
        self.policy['per_request_micros'] = 400000
        with self.assertRaisesRegex(ValidationError, 'limits'): GatewayBudget(self.gateway_config())
        self.policy['per_request_micros'] = 500000
        self.policy['tariffs'][1]['expires_at'] = '2020-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValidationError, 'EXPIRED'): GatewayBudget(self.gateway_config())

    def test_fractional_rates_round_up_and_invalid_numbers_rejected(self):
        self.assertEqual(envelope({**TARIFF, 'context_tokens': 1, 'input_micros_per_token': .1,
                                   'output_micros_per_token': .2}, 1), 1)
        for bad in (float('nan'), float('inf'), -1, True, None):
            spec = policy()
            spec['tariffs'][0]['input_micros_per_token'] = bad
            with self.assertRaises(ValidationError): validate_policy(spec)
        spec = policy()
        spec['tariffs'][1]['model'] = 'model-a'
        with self.assertRaisesRegex(ValidationError, 'Duplicate'): validate_policy(spec)

    def local_policy(self):
        self.policy.update(endpoint='http://127.0.0.1:8080', network_scope='local',
                           allowed_addresses=['127.0.0.1'], protocol='openai_chat')
        for t in self.policy['tariffs']:
            t.update(input_micros_per_token=0, output_micros_per_token=0)

    def test_zero_price_local_chat_keeps_idempotency_and_counting(self):
        self.local_policy()
        config = self.gateway_config()
        config['auth'] = 'none'
        gateway = ModelGateway(config, None, lambda *a: (200, 'application/json', b'{}'), invocation_id='a' * 64)
        gateway.request(self.frame(), 5)
        self.assertEqual(self.ledger.status()['requests'][0]['upper'], 0)
        self.assertEqual(gateway.requests, 1)
        with self.assertRaises(ValidationError): self.gateway().request(self.frame(), 5)

    def test_local_actual_http_transport_path_and_dns_pin_denial(self):
        self.local_policy()
        class Response:
            status = 200
            def read1(self, size): return b''
            def getheader(self, *args): return 'application/json'
        class Connection:
            sock = None
            def request(self, method, path, body, headers):
                self.headers = headers
                self.path = path
            def getresponse(self): return Response()
            def close(self): pass
        connection = Connection()
        config = self.gateway_config()
        config['auth'] = 'none'
        gateway = ModelGateway(config, None, invocation_id='b' * 64)
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 8080))]), \
             patch('http.client.HTTPConnection', return_value=connection):
            gateway.request(self.frame(), 5)
        self.assertEqual(connection.path, '/v1/chat/completions')
        self.assertNotIn('authorization', connection.headers)
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.2', 8080))]), \
             patch('http.client.HTTPConnection') as connection_mock:
            with self.assertRaises(ValidationError): gateway.request(self.frame(rid=2), 5)
            connection_mock.assert_not_called()

    def test_intranet_https_exact_pins_no_metadata_or_public_opt_in(self):
        spec = policy('intranet')
        spec.update(endpoint='https://llm.lab.internal:8443', allowed_addresses=['10.1.2.3'])
        validate_endpoint(spec)
        for endpoint, pins in [('http://llm.lab.internal', ['10.1.2.3']),
                               ('https://169.254.169.254', ['169.254.169.254']),
                               ('https://example.com', ['8.8.8.8']), ('https://llm.lab.internal', [])]:
            with self.assertRaises(ValidationError): validate_endpoint({**spec, 'endpoint': endpoint, 'allowed_addresses': pins})

    def test_freeze_default_is_ten_cents_and_explicit_higher_policy_works(self):
        policy_file = self.root / 'policy.json'
        history = self.root / 'history.json'
        history.write_text('[]')
        policy_file.write_text(json.dumps(self.policy))
        result = freeze_models(policy_file, self.path, 'lab', self.root / 'custom', max_output_tokens=100)
        self.assertEqual(result['status'], 'READY_FOR_REVIEW')
        spec = deepcopy(self.policy)
        del spec['per_request_micros']
        del spec['total_micros']
        policy_file.write_text(json.dumps(spec))
        result = freeze_models(policy_file, self.root / 'default.db', 'default', self.root / 'default',
                               history_path=history, history_ref='synthetic task', max_output_tokens=100)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('PER_REQUEST', result['reason'])
        self.assertEqual(load_json(result['gateway'])['budget']['policy']['per_request_micros'], 100000)
        self.assertEqual(result['model_calls'], 0)

    def test_reopen_does_not_reset_unknown_spending(self):
        ledger = self.root / 'unknown.db'
        RequestBudget.create(ledger, 'lab', 500000, 1000000,
            history=[{'id': 'prior', 'estimate_usd': None, 'source_ref': 'unknown'}], coverage_ref='fixture')
        policy_file = self.root / 'policy.json'
        policy_file.write_text(json.dumps(self.policy))
        result = freeze_models(policy_file, ledger, 'lab', self.root / 'unknown')
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('HISTORY_UNKNOWN', result['reason'])
