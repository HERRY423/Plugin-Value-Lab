"""Manufactured cross-session/version/adapter controls; no live provider calls."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from value_lab import adapter_qualification as qualification, continuity
from value_lab.context_stream import capabilities
from value_lab.codex_context import capture
from value_lab.core import ValidationError, suite_digest
from value_lab.decision_store import DecisionStore
from value_lab.delivery import read_bundle
from value_lab.host_capabilities import SEMANTICS
from tests.test_context_stream import encoded
from tests.test_codex_context import fixture
from tests import test_interpretation_history as history

ROOT = Path(__file__).resolve().parents[1]


class ContinuityTests(unittest.TestCase):
    setUp = history.InterpretationHistoryTests.setUp
    add = history.InterpretationHistoryTests.add
    collect = history.InterpretationHistoryTests.collect
    ready = history.InterpretationHistoryTests.ready

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory()
        cls.receipt = qualification.qualify(ROOT / 'tests/fixtures/codex-context-v1.json', Path(cls.work.name) / 'qualification')

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def environment(self, host=False):
        view = self.store.snapshot()
        layer = view['explanations']
        env = {'format': continuity.FORMAT, 'checkpoint': view['checkpoint'],
               'dependencies': deepcopy(view['effective_dependencies']),
               'judgments': {jid: {k: deepcopy(j[k]) for k in ('contract', 'implementation')}
                             for jid, j in layer['judgments'].items()},
               'decisions': {did: {k: deepcopy(d[k]) for k in ('scope', 'policy')} | {'host_requirements': {}}
                             for did, d in layer['decisions'].items()}, 'host': None}
        if host:
            path = self.root / 'log.jsonl'
            path.write_bytes(encoded(fixture()))
            snapshot = capabilities(capture(path, 'session'))
            env['host'] = {'snapshot': snapshot, 'receipt': deepcopy(self.receipt),
                           'receipt_sha256': suite_digest(self.receipt), 'expected_session_id': 'session',
                           'expected_prefix_sha256': snapshot['source']['complete_prefix_sha256']}
            env['decisions']['d1']['host_requirements'] = {'usage': {'request_usage': SEMANTICS['request_usage']}}
        return env

    def inspect(self, env=None, anchored=True):
        return continuity.inspect(self.store, env or self.environment(),
                                  checkpoint=self.store.snapshot()['checkpoint'] if anchored else None)

    def test_current_local_guidance_survives_reopen_without_scoring(self):
        self.ready()
        before = self.store.snapshot()
        env = self.environment()
        with patch('value_lab.artifacts.grade_artifact', side_effect=AssertionError('no scoring')):
            report = continuity.inspect(DecisionStore(self.store.path), env, checkpoint=before['checkpoint'])
        self.assertEqual(report['compatible_recorded_decisions'], ['d1'])
        self.assertEqual(self.store.snapshot(), before)
        self.assertEqual(report['new_judgments'], 0)
        self.assertIsNone(report['scientific_sample_size'])
        self.assertFalse(report['execution_authorized'])

    def test_no_external_checkpoint_never_implies_verified_history(self):
        self.ready()
        report = self.inspect(anchored=False)
        self.assertEqual(report['compatible_recorded_decisions'], [])
        self.assertIn('HISTORY_ANCHOR_UNVERIFIED', report['decisions']['d1']['reasons'])

    def test_missing_current_identity_is_unknown_not_historical_fallback(self):
        self.ready()
        env = self.environment()
        env['judgments'] = {}
        report = self.inspect(env)
        self.assertIn('VERIFY_JUDGMENT_IDENTITY', report['decisions']['d1']['actions'])

    def test_rule_reference_domain_and_implementation_changes_need_rescore(self):
        self.ready()
        for key in ('grader', 'reference', 'domain', 'implementation'):
            with self.subTest(key=key):
                env = self.environment()
                if key == 'implementation':
                    env['judgments']['j1'][key] = 'new-implementation'
                else:
                    env['judgments']['j1']['contract'][key] = {'changed': True}
                report = self.inspect(env)
                self.assertEqual(report['judgment_comparisons']['j1']['changed'], [key])
                self.assertIn('RESCORE_RETAINED_OBSERVATIONS', report['decisions']['d1']['actions'])

    def test_policy_revision_reuses_judgment_without_rescore(self):
        self.ready()
        env = self.environment()
        env['decisions']['d1']['policy']['purpose'] = 'new intended use'
        actions = self.inspect(env)['decisions']['d1']['actions']
        self.assertIn('REDECIDE_WITH_RETAINED_JUDGMENT', actions)
        self.assertNotIn('RESCORE_RETAINED_OBSERVATIONS', actions)

    def test_new_scope_needs_applicability_not_automatic_transfer(self):
        self.ready()
        env = self.environment()
        env['decisions']['d1']['scope'] = {'task': 'another dataset'}
        self.assertIn('REVIEW_NEW_SCOPE_APPLICABILITY', self.inspect(env)['decisions']['d1']['actions'])

    def test_changed_policy_and_rule_cannot_redecide_using_old_judgment(self):
        self.ready()
        env = self.environment()
        env['decisions']['d1']['policy']['purpose'] = 'new purpose'
        env['judgments']['j1']['implementation'] = 'new grader'
        actions = self.inspect(env)['decisions']['d1']['actions']
        self.assertIn('RESCORE_RETAINED_OBSERVATIONS', actions)
        self.assertIn('REDECIDE_AFTER_JUDGMENT_REVIEW', actions)
        self.assertNotIn('REDECIDE_WITH_RETAINED_JUDGMENT', actions)

    def test_changed_qualification_code_requires_new_receipt(self):
        self.ready()
        env = self.environment(host=True)
        with patch('value_lab.adapter_qualification.implementation', return_value={'code': 'changed'}):
            self.assertIn('QUALIFICATION_IMPLEMENTATION_CHANGED', self.inspect(env)['decisions']['d1']['reasons'])

    def test_dependencies_missing_changed_added_or_unknown_need_review(self):
        self.ready()
        for change in ({}, {'host': 'new'}, {'host': None}, {'extra': 'unbound'}):
            env = self.environment()
            env['dependencies'] = change
            self.assertIn('DEPENDENCY_CHANGED_OR_UNKNOWN', self.inspect(env)['decisions']['d1']['reasons'])

    def test_fully_bound_adapter_supplies_only_required_claim(self):
        self.ready()
        report = self.inspect(self.environment(host=True))
        self.assertEqual(report['compatible_recorded_decisions'], ['d1'])
        self.assertEqual(report['host_qualification']['status'], 'LOCAL_CONFORMANCE_BOUND')
        self.assertFalse(report['host_qualification']['live_host_verified'])

    def test_host_cannot_supply_settled_currency_from_tokens(self):
        self.ready()
        env = self.environment(host=True)
        env['decisions']['d1']['host_requirements'] = {'cash': {'settled_cost': SEMANTICS['settled_cost']}}
        self.assertIn('HOST_CLAIM_EVIDENCE_INSUFFICIENT', self.inspect(env)['decisions']['d1']['reasons'])

    def test_missing_host_does_not_invalidate_unrelated_local_judgment(self):
        self.ready()
        env = self.environment(host=True)
        env['host'] = None
        report = self.inspect(env)
        self.assertIn('HOST_EVIDENCE_MISSING', report['decisions']['d1']['reasons'])
        self.assertEqual(report['judgment_comparisons']['j1']['action'], 'REUSE_RETAINED_JUDGMENT')
        env['decisions']['d1']['host_requirements'] = {}
        self.assertEqual(self.inspect(env)['compatible_recorded_decisions'], ['d1'])

    def test_wrong_host_session_or_source_cannot_be_reused(self):
        self.ready()
        for key in ('expected_session_id', 'expected_prefix_sha256'):
            env = self.environment(host=True)
            env['host'][key] = 'wrong'
            self.assertEqual(self.inspect(env)['compatible_recorded_decisions'], [])

    def test_recomputed_digest_cannot_hide_changed_or_missing_controls(self):
        self.ready()
        for change in ('checks', 'implementation', 'scope', 'format'):
            env = self.environment(host=True)
            env['host']['receipt'][change] = {} if change != 'format' else 'unsupported'
            env['host']['receipt_sha256'] = suite_digest(env['host']['receipt'])
            self.assertIn('REQUALIFY_ADAPTER', self.inspect(env)['decisions']['d1']['actions'])

    def test_mismatched_receipt_anchor_blocks_qualification(self):
        self.ready()
        env = self.environment(host=True)
        env['host']['receipt_sha256'] = '0' * 64
        self.assertIn('QUALIFICATION_ANCHOR_MISMATCH', self.inspect(env)['decisions']['d1']['reasons'])

    def test_new_host_version_does_not_inherit_old_receipt(self):
        self.ready()
        env = self.environment(host=True)
        env['host']['snapshot']['qualification']['observed_engine_version'] = 'future'
        self.assertIn('CAPTURE_OUTSIDE_QUALIFIED_SCOPE', self.inspect(env)['decisions']['d1']['reasons'])

    def test_unknown_semantic_version_does_not_match_by_name(self):
        self.ready()
        env = self.environment(host=True)
        env['decisions']['d1']['host_requirements']['usage']['request_usage'] = 'different/v2'
        self.assertIn('HOST_CLAIM_EVIDENCE_INSUFFICIENT', self.inspect(env)['decisions']['d1']['reasons'])

    def test_review_required_cannot_reactivate_just_by_matching_environment(self):
        self.ready()
        self.add('review', {'decision_id': 'd1', 'status': 'review_required', 'reason': 'pending human check'})
        self.assertEqual(self.inspect()['compatible_recorded_decisions'], [])

    def test_pending_remote_call_keeps_original_key_and_reserved_cost(self):
        from tests.test_decision_recovery import start
        self.ready()
        self.add('start', start('pending', 'plugin'))
        self.add('unknown', {'attempt_id': 'pending', 'reason': 'timeout'})
        report = self.inspect()
        self.assertEqual(report['costs']['reserved_micros'], 100000)
        self.assertIsNone(report['costs']['total_cost_micros'])
        step = next(s for s in report['next_steps'] if s['action'] == 'RECONCILE_ORIGINAL_INVOCATION')
        self.assertEqual(step['external_key'], 'external-pending')
        self.assertEqual(report['unresolved_invocations']['pending']['operation'], 'fixture GET /result')
        self.assertEqual(report['unresolved_invocations']['pending']['max_cost_micros'], 100000)

    def test_stale_environment_rejected_after_any_append(self):
        self.ready()
        env = self.environment()
        self.add('review', {'decision_id': 'd1', 'status': 'review_required', 'reason': 'new observation'})
        with self.assertRaisesRegex(ValidationError, 'STALE_ENVIRONMENT'):
            self.inspect(env)

    def test_unknown_object_and_unknown_envelope_rejected(self):
        self.ready()
        for key in ('decisions', 'judgments'):
            env = self.environment()
            env[key]['unknown'] = {}
            with self.assertRaises(ValidationError):
                self.inspect(env)
        env = self.environment()
        env['hidden_default'] = True
        with self.assertRaises(ValidationError):
            self.inspect(env)

    def test_publication_replay_and_verification_no_history_changes(self):
        self.ready()
        before = self.store.snapshot()
        env = self.environment(host=True)
        output = self.root / 'handoff'
        first = continuity.publish(self.store, env, output, checkpoint=before['checkpoint'])
        self.assertEqual(first, continuity.publish(self.store, env, output, checkpoint=before['checkpoint']))
        verified = continuity.verify(self.store, env, output, checkpoint=before['checkpoint'])
        self.assertEqual(verified['compatible_recorded_decisions'], ['d1'])
        self.assertEqual(self.store.snapshot(), before)
        changed = deepcopy(env)
        changed['dependencies']['host'] = 'different'
        with self.assertRaisesRegex(ValidationError, 'environment changed'):
            continuity.verify(self.store, changed, output, checkpoint=before['checkpoint'])

    def test_interrupted_handoff_requires_explicit_resume_and_preserves_stage(self):
        self.ready()
        env, output = self.environment(), self.root / 'handoff'
        from value_lab import delivery
        original = delivery._write
        def fail(path, data):
            original(path, data)
            raise OSError('simulated interruption after bytes')
        with patch('value_lab.delivery._write', side_effect=fail), self.assertRaises(OSError):
            continuity.publish(self.store, env, output)
        result = continuity.publish(self.store, env, output)
        self.assertEqual(result['status'], 'INCOMPLETE')
        pending = result['pending']
        self.assertEqual(continuity.publish(self.store, env, output, resume=True)['status'], 'COMMITTED')
        self.assertTrue(all(Path(p).exists() for p in pending))

    def test_new_process_after_checkpointed_restore_reads_same_handoff(self):
        self.ready()
        before = self.store.snapshot()
        env = self.environment(host=True)
        bundle = self.root / 'recovery'
        self.store.export(bundle)
        restored = DecisionStore(self.root / 'restored.sqlite')
        restored.restore(bundle, checkpoint=before['checkpoint'])
        environment_path, checkpoint_path = self.root / 'environment.json', self.root / 'anchor.json'
        environment_path.write_text(json.dumps(env))
        checkpoint_path.write_text(json.dumps(before['checkpoint']))
        command = [sys.executable, '-m', 'value_lab.continuity', '--store', str(restored.path),
                   '--environment', str(environment_path), '--checkpoint', str(checkpoint_path),
                   '--output', str(self.root / 'handoff')]
        for extra in ([], ['--verify']):
            result = subprocess.run(command + extra, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        read_bundle(self.root / 'handoff')
        self.assertEqual(restored.snapshot(), before)

    def test_changed_implementation_invalidates_saved_assessment(self):
        self.ready()
        env, output = self.environment(), self.root / 'handoff'
        continuity.publish(self.store, env, output)
        with patch('value_lab.continuity._identity', return_value={'new': 'runtime'}):
            with self.assertRaisesRegex(ValidationError, 'STALE_ASSESSMENT'):
                continuity.verify(self.store, env, output)

    def test_qualification_controls_actually_execute_and_fixture_is_pinned(self):
        self.assertEqual(self.receipt['checks'], dict.fromkeys(qualification.CHECKS, 'PASS'))
        self.assertEqual(self.receipt['status'], 'PASS')
        altered = self.root / 'altered.json'
        altered.write_text('{}')
        with self.assertRaisesRegex(ValidationError, 'pinned legacy fixture'):
            qualification.qualify(altered, self.root / 'work')

    def test_allowlist_expansion_requires_new_qualification_specification(self):
        with patch('value_lab.codex_context.SUPPORTED_VERSIONS', {'0.159.2', 'future'}):
            with self.assertRaisesRegex(ValidationError, 'scope changed'):
                qualification.qualify(ROOT / 'tests/fixtures/codex-context-v1.json', self.root / 'checks')

    def test_missing_current_decision_does_not_mean_no_host_requirements(self):
        self.ready()
        env = self.environment()
        env['decisions'] = {}
        self.assertIn('VERIFY_DECISION_CONTEXT', self.inspect(env)['decisions']['d1']['actions'])

    def test_malformed_receipt_is_not_qualified(self):
        self.ready()
        for receipt in (None, {}, {'status': 'PASS'}, self.receipt | {'qualification': []}):
            env = self.environment(host=True)
            env['host']['receipt'] = receipt
            env['host']['receipt_sha256'] = suite_digest(receipt)
            self.assertEqual(self.inspect(env)['compatible_recorded_decisions'], [])

    def test_malformed_current_policy_is_rejected(self):
        self.ready()
        for value in (True, -1, '100'):
            env = self.environment()
            env['decisions']['d1']['policy']['budget_micros'] = value
            with self.assertRaises(ValidationError):
                self.inspect(env)

    def test_superseded_guidance_remains_historical(self):
        self.ready()
        self.add('decide', history.decision('d2', 'j1', 'd1'))
        report = self.inspect()
        self.assertEqual(report['decisions']['d1']['status'], 'HISTORICAL_ONLY')
        self.assertEqual(report['compatible_recorded_decisions'], ['d2'])

    def test_judgment_without_decision_still_needs_version_review(self):
        self.collect()
        self.add('judge', history.judgment())
        env = self.environment()
        env['judgments'] = {}
        self.assertIn({'action': 'VERIFY_JUDGMENT_IDENTITY', 'judgment_id': 'j1'}, self.inspect(env)['next_steps'])

    def test_legacy_only_history_is_readable_but_not_promoted(self):
        self.collect()
        history.fixtures.RecoveryTests.interpret(self)
        view = self.store.snapshot()
        env = {'format': continuity.FORMAT, 'checkpoint': view['checkpoint'],
               'dependencies': view['effective_dependencies'], 'judgments': {}, 'decisions': {}, 'host': None}
        report = self.inspect(env)
        self.assertEqual(report['compatible_recorded_decisions'], [])
        self.assertEqual(report['legacy_interpretations_without_lifecycle'], ['score1'])

    def test_environment_schema_accepts_bound_input_rejects_hidden_fields(self):
        from jsonschema import Draft202012Validator
        self.ready()
        schema = json.loads((ROOT / 'schemas/continuity-environment.schema.json').read_bytes())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        env = self.environment(host=True)
        self.assertEqual(list(validator.iter_errors(env)), [])
        env['execute'] = True
        self.assertTrue(list(validator.iter_errors(env)))

    def test_boolean_and_integer_rule_values_are_distinct_versions(self):
        self.ready()
        old = deepcopy(self.store.snapshot()['explanations']['judgments']['j1'])
        old['contract']['grader'] = {'expected': True}
        current = {k: deepcopy(old[k]) for k in ('contract', 'implementation')}
        current['contract']['grader']['expected'] = 1
        self.assertEqual(continuity.compare_judgment(old, current)['action'], 'RESCORE_RETAINED_OBSERVATIONS')


if __name__ == '__main__':
    unittest.main()
