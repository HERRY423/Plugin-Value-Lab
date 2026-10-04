"""Manufactured capture-to-confirmation integration; no native or paid execution."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from value_lab import codex_study as study
from value_lab.core import ValidationError, load_json, suite_digest
from test_codex_study import fixture_design, fixture_packet
from test_confirmatory import spec


class CodexConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.counter = 0

    def prepare(self, n=2, real=False, json_output=False):
        suite, contract = fixture_design()
        power = spec()
        power.update(alpha=.2, power=.5)
        power['rule']['anticipated_quality_delta'] = .95
        suite['policy'].update(power_plan=power, quality_weighting='family', min_quality_delta=.05,
                               max_case_regression=.05)
        template = suite['cases'][0]
        if json_output:
            template['graders']=[{'id':'json','type':'json_equals','path':'ok','value':True,
                                  'weight':1,'critical':False,'dimension':'outcome'}]
        suite['cases'] = []
        for i in range(n):
            prompt = f'Confirmation-only public task {i}: deliver SOURCE and LIMITS.'
            suite['cases'].append(dict(deepcopy(template), id=f'confirm-{i}', cluster=f'confirm-family-{i}',
                prompt=prompt, input_sha256=sha256(prompt.encode()).hexdigest()))
        if real:
            # Exercise the unauthenticated-operator gate with manufactured declarations.
            suite['evidence_type'] = 'local'
            power['pilot']['evidence_type'] = 'real'
        self.suite, self.contract = suite, contract
        self.directory = self.root/'study'
        self.pin = study.prepare(suite, contract, self.directory)['plan_sha256']
        self.plan = dict(load_json(self.directory/'plan.json'), plan_sha256=self.pin)

    def capture(self, index, state='completed', retry_of=None, mutate=None):
        slot = self.plan['schedule'][index]
        self.counter += 1
        attempt = study.reserve(self.directory, self.pin, slot['slot_id'], f'key-{self.counter}', retry_of=retry_of)
        aid = attempt['attempt_id']
        study.record_state(self.directory, self.pin, aid, 'dispatched', {'source_ref':'manufactured dispatch'})
        output = 'SOURCE: fixture LIMITS: synthetic' if slot['arm']=='with' else 'absent'
        packet = fixture_packet(self.plan, slot, aid, state=state, output=output)
        if self.suite['evidence_type']=='local':
            packet['origin']='operator_capture'
        if mutate:
            mutate(packet)
        path=self.root/f'capture-{self.counter}.json'
        path.write_text(json.dumps(packet),encoding='utf-8')
        result=study.capture(self.directory,self.pin,path)
        self.assertEqual(result['issues'],[])
        return aid

    def complete(self):
        for i in range(len(self.plan['schedule'])):
            self.capture(i)

    def settlement(self):
        snapshot=study._journal(self.directory,self.pin).snapshot()
        attempts=[]
        sources={}
        retry=False
        for attempt in snapshot['attempts']:
            aid=attempt['attempt_id']
            packet=load_json(self.directory/'captures'/f'{aid}.json')
            ref='manufactured-invoice-'+aid
            attempts.append({'attempt_id':aid,'request_id':packet['request_id'],
                'cost':{'model_usd':.05,'tool_usd':0,'human_minutes':0,'basis':'settled','evidence_ref':ref},
                'human_intervals':[]})
            sources[ref]='Manufactured settlement line; no cash was spent.'
            retry |= attempt['retry_of'] is not None
        return {'format':'pvl-codex-settlement-1','plan_sha256':self.pin,'journal_sha256':suite_digest(snapshot),
            'attempts':attempts,'sources':sources,'cost_ledger':{'schema_version':1,'entries':[],
                'coverage':{'judge':'not_applicable','setup':'not_applicable','retry':'itemized' if retry else 'not_applicable','other':'not_applicable'}}}

    def review(self, settlement=None):
        path=None
        if settlement is not None:
            path=self.root/'settlement.json'
            path.write_text(json.dumps(settlement),encoding='utf-8')
        return study.review(self.directory,self.pin,settlement_path=path)

    def test_real_path_calls_existing_evaluator_and_replays_original_bundle(self):
        self.prepare(n=20)
        self.complete()
        payment=self.settlement()
        review=self.review(payment)
        evaluated=review['evaluation']
        result=evaluated['report']['confirmatory_analysis']
        self.assertTrue(result['planning_target_met'])
        self.assertTrue(result['simulated_criteria_met'])
        self.assertEqual(review['confirmed_decision'],'SIMULATION_ONLY')
        self.assertFalse(result['statistical_support'])
        self.assertFalse(review['live_host_accepted'])
        self.assertEqual(evaluated['bridge_issues'],[])
        self.assertEqual(len(evaluated['records']),40)
        self.assertEqual(evaluated['report']['provenance']['local_lock'],load_json(self.directory/'protocol.lock.json'))
        self.assertAlmostEqual(review['cost']['actual_settled_usd'],2.)
        bundle=self.root/'bundle'
        exported=study.export_review(self.directory,self.pin,bundle,settlement_path=self.root/'settlement.json')
        self.assertEqual((bundle/'settlement.json').read_bytes(),(self.root/'settlement.json').read_bytes())
        verified=study.verify_review(bundle,exported['manifest_sha256'])
        self.assertEqual(verified['status'],'RECOMPUTED_LOCALLY')
        process=subprocess.run([sys.executable,'-m','value_lab.codex_study','verify',str(bundle),
            '--manifest-sha256',exported['manifest_sha256']],capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        (bundle/'settlement.json').write_text('{}',encoding='utf-8')
        with self.assertRaises(ValidationError):
            study.verify_review(bundle,exported['manifest_sha256'])

    def test_missing_estimated_or_unresolved_costs_never_confirm(self):
        self.prepare()
        self.complete()
        missing=self.review()
        self.assertEqual(missing['cost']['status'],'UNKNOWN')
        self.assertIn('SETTLEMENT_MISSING',missing['evaluation']['bridge_issues'])
        for mutation in ('estimated','missing_attempt','missing_source','reused_ref','wrong_request','unknown_amount'):
            payment=self.settlement()
            first=payment['attempts'][0]
            if mutation=='estimated': first['cost']['basis']='estimate'
            elif mutation=='missing_attempt': payment['attempts'].pop()
            elif mutation=='missing_source': payment['sources'].pop(first['cost']['evidence_ref'])
            elif mutation=='reused_ref': payment['attempts'][1]['cost']['evidence_ref']=first['cost']['evidence_ref']
            elif mutation=='wrong_request': first['request_id']='unrelated-request'
            else: first['cost']['model_usd']=None
            with self.subTest(mutation=mutation):
                result=self.review(payment)
                self.assertEqual(result['cost']['status'],'UNKNOWN')
                decision=result['evaluation']['report']['confirmatory_analysis']
                self.assertFalse(decision['statistical_support'])
                self.assertTrue(decision['reasons'])

    def test_failed_primary_retained_and_retry_is_charged_only_once(self):
        self.prepare()
        first=self.capture(0,state='failed')
        retry=self.capture(0,retry_of=first)
        for i in range(1,len(self.plan['schedule'])): self.capture(i)
        result=self.review(self.settlement())
        evaluation=result['evaluation']
        self.assertEqual(len(evaluation['records']),4)
        self.assertEqual(evaluation['records'][0]['attempt_id'],first)
        self.assertEqual(evaluation['records'][0]['status'],'error')
        self.assertNotIn(retry,[r['attempt_id'] for r in evaluation['records']])
        retry_entries=[e for e in evaluation['cost_ledger']['entries'] if e['category']=='retry']
        self.assertEqual(len(retry_entries),1)
        self.assertAlmostEqual(retry_entries[0]['amount_usd'],.05)
        self.assertAlmostEqual(result['cost']['actual_settled_usd'],.25)
        self.assertFalse(evaluation['report']['confirmatory_analysis']['statistical_support'])
        payment=self.settlement()
        payment['attempts']=[e for e in payment['attempts'] if e['attempt_id']!=retry]
        self.assertEqual(self.review(payment)['cost']['status'],'UNKNOWN')

    def test_missing_matrix_and_pilot_execution_overlap_block_confirmation(self):
        self.prepare()
        pilot_id=self.suite['policy']['power_plan']['pilot']['records'][0]['with_session_id']
        self.capture(0,mutate=lambda p:p.update(session_id=pilot_id))
        result=self.review(self.settlement())
        self.assertEqual(result['planned_slots'],4)
        self.assertEqual(len(result['evaluation']['records']),1)
        self.assertTrue(any('PILOT' in gap for gap in result['evaluation']['bridge_issues']))
        self.assertFalse(result['evaluation']['report']['summary']['comparison_eligible'])

    def test_operator_declarations_cannot_authenticate_host(self):
        self.prepare(real=True)
        self.complete()
        result=self.review(self.settlement())
        self.assertEqual(result['confirmed_decision'],'INSUFFICIENT_EVIDENCE')
        self.assertTrue(any('HOST_TRANSPORT_NOT_QUALIFIED' in gap for gap in result['evaluation']['records'][0]['import_issues']))
        self.assertFalse(result['live_host_accepted'])
        self.assertFalse(result['evaluation']['report']['confirmatory_analysis']['statistical_support'])

    def test_settlement_cannot_move_between_plans_or_journal_revisions(self):
        self.prepare()
        self.complete()
        for key in ('plan_sha256','journal_sha256'):
            payment=self.settlement()
            payment[key]='0'*64
            with self.subTest(key=key),self.assertRaises(ValidationError): self.review(payment)
        payment=self.settlement()
        payment['attempts'].append(deepcopy(payment['attempts'][0]))
        with self.assertRaises(ValidationError): self.review(payment)

    def test_disconnect_reconciles_original_attempt_before_confirming(self):
        self.prepare()
        slot=self.plan['schedule'][0]
        attempt=study.reserve(self.directory,self.pin,slot['slot_id'],'original-key')
        aid=attempt['attempt_id']
        study.record_state(self.directory,self.pin,aid,'dispatched',{'source_ref':'manufactured dispatch'})
        study.record_state(self.directory,self.pin,aid,'unknown',{'source_ref':'manufactured disconnect'})
        unresolved=self.review()
        self.assertEqual(unresolved['attempts_retained'],1)
        self.assertEqual(unresolved['cost']['status'],'UNKNOWN')
        with self.assertRaises(ValidationError):
            study.reserve(self.directory,self.pin,slot['slot_id'],'cannot-replace-unknown',retry_of=aid)
        path=self.root/'original-response.json'
        path.write_text(json.dumps(fixture_packet(self.plan,slot,aid)),encoding='utf-8')
        self.assertEqual(study.capture(self.directory,self.pin,path)['issues'],[])
        for i in range(1,len(self.plan['schedule'])): self.capture(i)
        reconciled=self.review(self.settlement())
        self.assertEqual(reconciled['attempts_retained'],4)
        self.assertEqual(reconciled['evaluation']['records'][0]['attempt_id'],aid)
        self.assertEqual(reconciled['evaluation']['bridge_issues'],[])

    def test_cancelled_primary_retry_labor_and_cash_are_separate(self):
        self.prepare()
        first=self.capture(0,state='cancelled')
        retry=self.capture(0,retry_of=first)
        for i in range(1,len(self.plan['schedule'])): self.capture(i)
        payment=self.settlement()
        row=next(r for r in payment['attempts'] if r['attempt_id']==retry)
        row['cost']['human_minutes']=1
        row['human_intervals']=[{'actor':'synthetic timer','start':'2026-10-03T00:00:00Z','end':'2026-10-03T00:01:00Z'}]
        result=self.review(payment)
        self.assertEqual(result['evaluation']['records'][0]['status'],'aborted')
        self.assertAlmostEqual(result['cost']['actual_settled_usd'],.25)
        report=result['evaluation']['report']
        valued=sum(report['cost_analysis']['arms'][arm]['total_usd'] for arm in ('with','without'))
        self.assertAlmostEqual(valued,.25+self.suite['policy']['human_hourly_usd']/60)

    def test_retry_cannot_be_hidden_or_double_itemized(self):
        self.prepare()
        first=self.capture(0,state='failed')
        self.capture(0,retry_of=first)
        for i in range(1,len(self.plan['schedule'])): self.capture(i)
        payment=self.settlement()
        payment['cost_ledger']['coverage']['retry']='not_applicable'
        result=self.review(payment)
        self.assertIn('RETRY_COVERAGE_MUST_BE_ITEMIZED',result['evaluation']['bridge_issues'])
        self.assertEqual(result['cost']['status'],'UNKNOWN')
        self.assertFalse(result['evaluation']['report']['confirmatory_analysis']['statistical_support'])
        payment=self.settlement()
        payment['cost_ledger']['entries']=[{'category':'retry'}]
        with self.assertRaises(ValidationError): self.review(payment)

    def test_deep_json_output_is_regraded_as_failure_not_a_bridge_crash(self):
        self.prepare(json_output=True)
        for i in range(len(self.plan['schedule'])):
            self.capture(i,mutate=lambda p:p.update(raw_output='['*2000+'0'+']'*2000,
                events=[{'seq':1,'kind':'final','output_sha256':sha256(('['*2000+'0'+']'*2000).encode()).hexdigest()},
                        {'seq':2,'kind':'terminal','state':'completed'}]))
        result=self.review(self.settlement())
        self.assertFalse(result['evaluation']['report']['confirmatory_analysis']['statistical_support'])

    def test_prompt_digest_and_frozen_plan_are_required(self):
        self.prepare()
        suite=deepcopy(self.suite)
        suite['cases'][0]['input_sha256']='0'*64
        with self.assertRaisesRegex(ValidationError,'inline prompt'):
            study.prepare(suite,self.contract,self.root/'bad-input')
        self.complete()
        lock=load_json(self.directory/'protocol.lock.json')
        lock['frozen_at']='2026-01-01T00:00:00Z'
        (self.directory/'protocol.lock.json').write_text(json.dumps(lock),encoding='utf-8')
        with self.assertRaises(ValidationError): self.review()


if __name__=='__main__':
    unittest.main()
