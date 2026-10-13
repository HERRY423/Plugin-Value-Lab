import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from value_lab.core import ValidationError, suite_digest
from value_lab.gateway_budget import GatewayBudget, TARIFF, request_upper
from value_lab.online_sandbox import ModelGateway, validate_config
from value_lab.request_budget import RequestBudget


class GatewayBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'task.db'
        # Test-only policy, intentionally larger than the user's live authorization.
        self.ledger = RequestBudget.create(self.path, 'fixture-task', 300000, 600000,
                                           history=[], coverage_ref='synthetic-no-spending')
        self.config = {'endpoint': 'https://api.anthropic.com', 'models': [TARIFF['model']],
                       'api_key_env': 'PVL_MODEL_KEY', 'max_requests': 20, 'max_output_tokens': 100,
                       'request_timeout_seconds': 5, 'budget': {'ledger': str(self.path),
                       'task_id': 'fixture-task', 'tariff_sha256': suite_digest(TARIFF)}}
        self.clock = patch('value_lab.gateway_budget.datetime', wraps=datetime).start()
        self.addCleanup(patch.stopall)
        self.clock.now.return_value = datetime(2026, 10, 12, tzinfo=timezone.utc)
        self.calls = []

    def body(self, **changes):
        payload = {'model': TARIFF['model'], 'max_tokens': 20, 'messages': [{'role': 'user', 'content': 'test'}]}
        payload.update(changes)
        return json.dumps(payload).encode()

    def message(self, index=1, **changes):
        return {'kind': 'request', 'id': index, 'path': '/v1/messages', 'beta': '',
                'body': base64.b64encode(self.body(**changes)).decode()}

    def gateway(self, invocation='a' * 64, transport=None):
        def fake(*args):
            self.calls.append(args)
            # Observe persistent reservation BEFORE dispatch, including process reopen.
            self.assertGreater(RequestBudget(self.path, 'fixture-task').status()['known_reserved_subtotal_micros'], 0)
            return 200, 'application/json', b'{"usage":{"input_tokens":1,"output_tokens":1}}'
        return ModelGateway(self.config, 'fixture-key', transport or fake, invocation_id=invocation)

    def test_full_window_not_estimated_input_and_no_automatic_release(self):
        self.assertEqual(request_upper('/v1/messages', self.body(), ''), 200100)
        gateway = self.gateway()
        gateway.request(self.message(), 5)
        gateway.request(self.message(2), 5)
        with self.assertRaisesRegex(ValidationError, 'TASK_BUDGET_EXHAUSTED'):
            gateway.request(self.message(3), 5)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.ledger.status()['known_reserved_subtotal_micros'], 400200)
        self.assertFalse(gateway.events[0]['budget_reservation']['provider_cap_verified'])

    def test_reopen_and_same_session_key_cannot_send_again(self):
        self.gateway().request(self.message(), 5)
        with self.assertRaisesRegex(ValidationError, 'RECOVER_ORIGINAL'):
            self.gateway().request(self.message(), 5)
        self.assertEqual(len(self.calls), 1)
        with self.assertRaisesRegex(ValidationError, 'conflicts'):
            self.gateway().request(self.message(max_tokens=21), 5)

    def test_multiple_gateways_share_atomic_total(self):
        def attempt(i):
            try:
                self.gateway(f'{i:064x}').request(self.message(), 5)
                return True
            except ValidationError as exc:
                self.assertIn('TASK_BUDGET_EXHAUSTED', str(exc))
                return False
        with ThreadPoolExecutor(max_workers=8) as executor:
            self.assertEqual(sum(executor.map(attempt, range(8))), 2)
        self.assertEqual(len(self.calls), 2)

    def test_user_ten_cent_cap_rejects_before_transport(self):
        path = Path(self.tmp.name) / 'small.db'
        RequestBudget.create(path, 'fixture-task', 100000, 1000000, history=[], coverage_ref='fixture')
        self.config['budget']['ledger'] = str(path)
        with self.assertRaisesRegex(ValidationError, 'PER_REQUEST_CAP_EXCEEDED'):
            self.gateway().request(self.message(), 5)
        self.assertEqual(self.calls, [])

    def test_timeout_redirect_errors_keep_reservation(self):
        def timeout(*args):
            raise TimeoutError('fixture-key')
        gateway = self.gateway(transport=timeout)
        with self.assertRaises(ValidationError) as error:
            gateway.request(self.message(), 5)
        self.assertNotIn('fixture-key', str(error.exception))
        gateway = self.gateway('b' * 64, lambda *args: (307, 'text/plain', b'redirect'))
        with self.assertRaises(ValidationError):
            gateway.request(self.message(), 5)
        self.assertEqual(self.ledger.status()['known_reserved_subtotal_micros'], 400200)

    def test_unpriced_features_aliases_and_duplicate_json_refused(self):
        for changes in ({'model': 'claude-haiku-4-5'}, {'thinking': {'type': 'enabled'}},
                        {'cache_control': {'type': 'ephemeral'}}, {'inference_geo': 'us'},
                        {'tools': [{'type': 'web_search_20250305', 'name': 'web_search'}]},
                        {'messages': [{'role': 'user', 'content': [{'type': 'image', 'source': {}}]}]},
                        {'system': [{'type': 'text', 'text': 'hello', 'cache_control': {'type': 'ephemeral'}}]}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.gateway().request(self.message(**changes), 5)
        body = self.body().replace(b'"max_tokens": 20', b'"max_tokens": 20, "max_tokens": 21')
        with self.assertRaises(ValidationError):
            request_upper('/v1/messages', body, '')
        self.assertEqual(self.ledger.status()['requests'], [])

    def test_expired_tariff_origin_mutation_and_direct_https_bypass_blocked(self):
        gateway = self.gateway()
        with self.assertRaisesRegex(ValidationError, 'reservation'), patch('socket.getaddrinfo') as dns:
            gateway._https('/v1/messages', self.body(), '', 1)
        dns.assert_not_called()
        self.clock.now.return_value = datetime(2026, 10, 15, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValidationError, 'EXPIRED'):
            gateway.request(self.message(), 5)
        self.config['endpoint'] = 'https://other.example.com'
        with self.assertRaisesRegex(ValidationError, 'origin'):
            self.gateway()

    def test_budget_configuration_validation_and_unknown_history(self):
        validate_config({'format': 'pvl-online-sandbox-1', 'backend': 'bubblewrap',
                         'runtime': '/selected/runtime', 'executable': 'claude', 'gateway': self.config})
        path = Path(self.tmp.name) / 'unknown.db'
        RequestBudget.create(path, 'fixture-task', 300000, 600000, coverage_ref='fixture',
                             history=[{'id': 'old', 'estimate_usd': None, 'source_ref': 'unknown'}])
        self.config['budget']['ledger'] = str(path)
        with self.assertRaisesRegex(ValidationError, 'HISTORY_UNKNOWN'):
            self.gateway()

    def test_production_https_path_requires_reservation_before_dns(self):
        class Response:
            status = 200
            def getheader(self, name, default):
                return 'application/json'
            def read1(self, size):
                return b''
        class Connection:
            sock = None
            def request(inner, method, path, body, headers):
                self.assertEqual(self.ledger.status()['known_reserved_subtotal_micros'], 200100)
                self.assertEqual(method, 'POST')
                self.calls.append(path)
            def getresponse(self):
                return Response()
            def close(self):
                pass
        gateway = ModelGateway(self.config, 'fixture-key', invocation_id='f' * 64)
        def dns(*args, **kwargs):
            self.assertEqual(self.ledger.status()['known_reserved_subtotal_micros'], 200100)
            return [(2, 1, 6, '', ('8.8.8.8', 443))]
        with patch('socket.getaddrinfo', side_effect=dns), patch('http.client.HTTPSConnection', return_value=Connection()):
            gateway.request(self.message(), 5)
            with self.assertRaisesRegex(ValidationError, 'reservation'):
                gateway._https('/v1/messages', self.body(), '', 1)
        self.assertEqual(self.calls, ['/v1/messages'])


if __name__ == '__main__':
    unittest.main()
