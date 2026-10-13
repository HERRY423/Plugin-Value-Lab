"""Manufactured checks of pilot-bound design and confirmatory decisions; no real study."""
from tests.optional import available, requires
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

from value_lab.core import ValidationError, demo_suite, evaluate, freeze, suite_digest, validate_suite
from value_lab.confirmatory import (assess, lower_bound, plan_sample_size, suite_plan,
                                    validate, _t_power, _bound_power)
from value_lab.report import write_reports
from value_lab.workflow import plan_plugin_use, write_plan
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCIPY = importlib.util.find_spec('scipy') is not None


def spec(method='hoeffding', objective='quality'):
    value = json.loads((ROOT/'examples/confirmatory-plan.json').read_text(encoding='utf-8'))['sample_size_plan']
    value.update(method=method, tasks_per_family=[1], repetitions_per_case=[1])
    value['rule']['anticipated_quality_delta'] = .8
    if objective == 'efficiency':
        value['rule'].update(objective='efficiency', minimum_gain=0, noninferiority_margin=.1,
                             anticipated_cost_saving_usd=.9, minimum_cost_saving_usd=.01)
    return value


def fixture(n=100, method='hoeffding', objective='quality'):
    suite = demo_suite()
    suite['policy'].update(power_plan=spec(method, objective), quality_weighting='family',
                           objective=objective, min_quality_delta=.05 if objective == 'quality' else 0,
                           max_case_regression=.05)
    suite['runs_per_case'] = 1
    template = suite['cases'][0]
    suite['cases'] = [dict(deepcopy(template), id=f'confirm-{i}', cluster=f'confirm-family-{i}',
                           input_sha256=hashlib.sha256(f'new-input-{i}'.encode()).hexdigest()) for i in range(n)]
    stamp = datetime.now(timezone.utc)
    lock = {'schema_version': 1, 'suite_sha256': suite_digest(suite), 'frozen_at': stamp.isoformat(),
            'expected_runs': 2*n, 'attestation': 'MANUFACTURED_TEST_ONLY'}
    records = []
    for i, case in enumerate(suite['cases']):
        for arm in ('with', 'without'):
            records.append({'case_id': case['id'], 'repetition': 1, 'arm': arm,
                'source': 'synthetic', 'suite_sha256': suite_digest(suite), 'conditions': deepcopy(suite['conditions']),
                'plugin_loaded': arm == 'with', 'session_id': f'manufactured-confirm-{i}-{arm}',
                'started_at': (stamp+timedelta(seconds=1)).isoformat(), 'input_sha256': case['input_sha256'],
                'status': 'completed', 'output': ('SOURCE: x LIMITS: y' if arm == 'with' else 'SOURCE: x' if i%2 else 'no support'),
                'cost': {'model_usd': .05 if arm == 'with' else .95, 'tool_usd': 0, 'human_minutes': 0,
                         'basis': 'settled', 'evidence_ref': f'manufactured-invoice-{i}-{arm}'},
                'human_intervals': [], 'duration_seconds': 1})
    ledger = {'schema_version': 1, 'entries': [],
              'coverage': {k: 'not_applicable' for k in ('judge', 'setup', 'retry', 'other')}}
    return suite, records, lock, ledger


class PlanningTests(unittest.TestCase):
    @requires('scipy')
    @unittest.skipUnless(available('scipy'), "requires: scipy")
    @unittest.skipUnless(SCIPY, 'optional planning dependency')
    def test_power_targets_practical_gain_not_zero(self):
        s = spec('paired_t')
        s['rule']['anticipated_quality_delta'] = .15
        practical = plan_sample_size(s)
        s['rule']['minimum_gain'] = 0
        zero = plan_sample_size(s)
        self.assertGreater(practical['recommended_design']['required_families'], zero['recommended_design']['required_families'])
        row = practical['recommended_design']
        self.assertEqual(practical['quality_null_boundary'], .05)
        self.assertGreaterEqual(_t_power(row['required_families'], .1, row['family_mean_sd'], .05), .8)
        self.assertLess(_t_power(row['required_families']-1, .1, row['family_mean_sd'], .05), .8)

    @requires('scipy')
    @unittest.skipUnless(available('scipy'), "requires: scipy")
    @unittest.skipUnless(SCIPY, 'optional planning dependency')
    def test_one_sided_t_matches_direct_noncentral_reference(self):
        from scipy.stats import nct, t
        expected = nct.sf(t.ppf(.95, 29), 29, .1*math.sqrt(30)/.2)
        self.assertAlmostEqual(_t_power(30, .1, .2, .05), expected, places=12)
        # Independently generated statsmodels one-sided TTestPower references.
        for n, gap, sd, alpha, reference in [(34,.1,.2,.05,.8868653118499608),
                (80,.04,.2,.025,.4235335265054895), (9,.2,.2,.05,.8618137116646404)]:
            self.assertAlmostEqual(_t_power(n,gap,sd,alpha),reference,places=10)
        self.assertAlmostEqual(lower_bound([.02,.04,.06,.08], .05, 'paired_t')['lower'],
                               .05 - t.ppf(.95,3)*math.sqrt(.002/3)/2, places=12)

    def test_hoeffding_required_n_matches_analytic_power_bound(self):
        s = spec()
        s['rule']['anticipated_quality_delta'] = .3
        row = plan_sample_size(s)['recommended_design']
        expected = math.ceil(2*(math.sqrt(math.log(20))+math.sqrt(math.log(5)))**2/.25**2)
        self.assertEqual(row['required_families'], expected)
        self.assertGreaterEqual(_bound_power(expected, .25, .05, 1), .8)

    @requires('scipy')
    @unittest.skipUnless(available('scipy'), "requires: scipy")
    @unittest.skipUnless(SCIPY, 'optional planning dependency')
    def test_efficiency_joint_error_and_power_budget(self):
        result = plan_sample_size(spec('paired_t', 'efficiency'))
        row = result['recommended_design']
        self.assertEqual(result['named_hypotheses'], ['quality','total_cost_saving'])
        self.assertEqual(row['endpoint_alpha'], .025)
        self.assertAlmostEqual(row['endpoint_beta'], .1)
        self.assertGreaterEqual(row['conditional_power'], .8)
        self.assertGreaterEqual(row['required_families'], row['required_cost_families'])

    def test_effect_at_boundary_and_invalid_stopping_rejected(self):
        for key,value in [('anticipated_quality_delta',.05), ('stopping','stop_when_significant'),
                          ('confirmation_not_started',False), ('cost_per_run_bound_usd',0)]:
            with self.subTest(key=key):
                s=spec(); s['rule'][key]=value
                with self.assertRaises(ValidationError): validate(s)

    def test_budget_and_search_limit_are_not_feasible_designs(self):
        for kind in ('budget','families'):
            s=spec()
            if kind=='budget': s['rule']['max_total_cost_usd']=.01
            else: s['max_families']=2
            result=plan_sample_size(s)
            self.assertIsNone(result['recommended_design'])
            self.assertEqual(result['status'],'NO_FEASIBLE_DESIGN_IN_GRID')

    @requires('scipy')
    @unittest.skipUnless(available('scipy'), "requires: scipy")
    @unittest.skipUnless(SCIPY, 'optional planning dependency')
    def test_pilot_variance_recomputed_not_copied_from_result(self):
        s=spec('paired_t')
        a=plan_sample_size(s)
        for row in s['pilot']['records']:
            row['with_score']=row['without_score']+(row['with_score']-row['without_score'])*.5
        b=plan_sample_size(s)
        self.assertGreater(a['planning_sd']['between_family_sd'], b['planning_sd']['between_family_sd'])
        self.assertGreater(a['recommended_design']['required_families'], b['recommended_design']['required_families'])

    def test_degenerate_pilot_requires_explicit_positive_floor(self):
        s=spec()
        for row in s['pilot']['records']: row['with_score']=row['without_score']
        s['variance_policy']['sd_floor']={key:0 for key in s['variance_policy']['sd_floor']}
        with self.assertRaisesRegex(ValidationError,'positive SD floor'): validate(s)

    @requires('numpy', 'scipy')
    @unittest.skipUnless(available('numpy', 'scipy'), "requires: numpy, scipy")
    @unittest.skipUnless(SCIPY, 'optional planning dependency')
    def test_independent_monte_carlo_at_practical_boundary_and_target(self):
        import numpy as np
        from scipy.stats import t
        s=spec('paired_t'); s['rule']['anticipated_quality_delta']=.15
        row=plan_sample_size(s)['recommended_design']
        n,sd=row['required_families'],row['family_mean_sd']
        # Manufactured normal-family sampling verifies nominal behavior under
        # the stated model; no real task-population or pilot validation claim.
        noise=np.random.default_rng(5639).normal(0,sd,(20000,n))
        critical=t.ppf(.95,n-1)
        se=noise.std(axis=1,ddof=1)/math.sqrt(n)
        at_boundary=(noise.mean(axis=1)>critical*se).mean()
        at_target=(noise.mean(axis=1)+.1>critical*se).mean()
        self.assertLess(abs(at_boundary-.05),.008)
        self.assertLess(abs(at_target-row['conditional_power']),.015)

    @requires('jsonschema')
    @unittest.skipUnless(available('jsonschema'), "requires: jsonschema")
    def test_schema_and_runtime_reject_invalid_contracts(self):
        import jsonschema
        schema=json.loads((ROOT/'schemas/confirmatory-plan.schema.json').read_text(encoding='utf-8'))
        pilot_schema=json.loads((ROOT/'schemas/pilot-data.schema.json').read_text(encoding='utf-8'))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator.check_schema(pilot_schema)
        jsonschema.validate(spec(),schema)
        jsonschema.validate(spec()['pilot'],pilot_schema)
        for path,value in [('cost_bound_rationale',''),('stopping','optional'),('confirmation_not_started',False)]:
            s=spec(); s['rule'][path]=value
            with self.assertRaises(jsonschema.ValidationError): jsonschema.validate(s,schema)
            with self.assertRaises(ValidationError): validate(s)
        with self.assertRaises(jsonschema.ValidationError): jsonschema.validate(dict(spec(),version=True),schema)


class DecisionTests(unittest.TestCase):
    @requires('scipy')
    @unittest.skipUnless(available('scipy'), "requires: scipy")
    @unittest.skipUnless(SCIPY, 'optional planning dependency')
    def test_user_four_points_does_not_establish_five_points(self):
        bounds=lower_bound([-.06,.01,.05,.16],.05,'paired_t')
        self.assertAlmostEqual(bounds['estimate'],.04)
        self.assertLess(bounds['lower'],.05)
        s,records,lock,ledger=fixture(method='paired_t')
        report=evaluate(s,records,lock,ledger)
        for i,case in enumerate(report['cases']): case['delta']=[.01,.03,.05,.07][i%4]
        decision=assess(s,report,records)
        self.assertFalse(decision['criteria']['quality_lower_exceeds_threshold'])
        self.assertFalse(decision['statistical_support'])

    def test_full_evaluator_keeps_synthetic_and_legacy_separate(self):
        s,records,lock,ledger=fixture()
        report=evaluate(s,records,lock,ledger)
        result=report['confirmatory_analysis']
        self.assertEqual(report['verdict'],'SIMULATION_ONLY')
        self.assertEqual(result['status'],'SIMULATION_ONLY')
        self.assertTrue(result['simulated_criteria_met'])
        self.assertFalse(result['adoption_authorized'])
        self.assertFalse(result['statistical_support'])
        self.assertFalse(result['changes_legacy_verdict'])
        from value_lab.claim_scope import verify_report
        bound=verify_report(report)
        claim=next(c for c in bound['claims'] if c['id']=='/confirmatory_analysis/statistical_support')
        self.assertFalse(claim['value'])
        self.assertIn('broader_adoption',claim['scope']['explicitly_unsupported'])

    def test_preserves_methodology_limits_and_required_cost_gate(self):
        s,records,lock,ledger=fixture()
        report=evaluate(s,records,lock,ledger)
        report['methodology']['violations']=[{'observed_rate':.2,'maximum':.1}]
        result=assess(s,report,records)
        self.assertFalse(result['criteria']['methodology_limits_met'])
        self.assertFalse(result['simulated_criteria_met'])
        s['policy']['require_cost_saving']=True
        lock['suite_sha256']=suite_digest(s)
        for row in records:
            row['suite_sha256']=suite_digest(s)
            row['cost']['model_usd']=.95 if row['arm']=='with' else .05
        report=evaluate(s,records,lock,ledger)
        self.assertFalse(report['summary']['cost_gate_met'])
        self.assertFalse(report['confirmatory_analysis']['criteria']['legacy_cost_gate'])
        self.assertFalse(report['confirmatory_analysis']['simulated_criteria_met'])

    @requires('scipy')
    @unittest.skipUnless(available('scipy'), "requires: scipy")
    @unittest.skipUnless(SCIPY, 'optional planning dependency')
    def test_zero_variance_cannot_manufacture_t_certainty(self):
        self.assertEqual(lower_bound([.5]*100,.05,'paired_t')['status'],'UNAVAILABLE')

    def test_conditional_status_never_becomes_adoption_authorization(self):
        # Exercise non-simulation routing with manufactured declarations only.
        # These bytes are not saved as a real evidence artifact.
        s,records,lock,ledger=fixture()
        report=evaluate(s,records,lock,ledger)
        s['policy']['power_plan']['pilot']['evidence_type']='real'
        report['evidence_type']='real'
        report['provenance']['local_lock']['suite_sha256']=suite_digest(s)
        result=assess(s,report,records)
        self.assertEqual(result['status'],'CONDITIONALLY_SUPPORTED')
        self.assertTrue(result['statistical_support'])
        self.assertFalse(result['adoption_authorized'])

    def test_confirmation_controls_downstream_guidance_and_ci(self):
        from value_lab.ci_gate import gate_code
        from value_lab.value_metrics import decision_review, positive_signal
        from value_lab.usage import build_usage_card
        s,records,lock,ledger=fixture()
        report=evaluate(s,records,lock,ledger)
        # Inject a manufactured report with a positive old descriptive signal
        # and failed confirmation; check downstream interfaces cannot ignore it.
        report.update(verdict='PROMISING_LOCAL_SIGNAL',evidence_type='submitted')
        report['confirmatory_analysis'].update(status='NOT_CONFIRMED',statistical_support=False)
        self.assertFalse(positive_signal(report))
        self.assertEqual(gate_code(report),1)
        self.assertEqual(decision_review(report)['controlled_trial']['status'],'NO_POSITIVE_RECOMMENDATION')
        with patch('value_lab.usage.evaluate',return_value=report):
            card=build_usage_card(s,records,lock,ledger)
        self.assertEqual(card['use_when'],[])
        self.assertEqual(card['status'],'REVIEW_REQUIRED')
        s['usage_scopes']=[{'id':'favorable-subset','families':['confirm-family-0'],
            'rationale':'Manufactured frozen subset','min_clusters':1,'min_complete_pairs':1}]
        with patch('value_lab.usage.evaluate',return_value=report):
            scoped=build_usage_card(s,records,lock,ledger)
        self.assertFalse(scoped['scope_assessments'][0]['supported'])
        self.assertTrue(any('confirmation' in why for why in scoped['scope_assessments'][0]['blockers']))
        report['confirmatory_analysis'].update(status='INSUFFICIENT_EVIDENCE',statistical_support=False)
        self.assertEqual(gate_code(report),2)
        report['confirmatory_analysis'].update(status='CONDITIONALLY_SUPPORTED',statistical_support=True)
        self.assertEqual(gate_code(report),0)
        report['verdict']='NO_DEMONSTRATED_GAIN'  # NI can permit a small decline.
        self.assertTrue(positive_signal(report))
        self.assertEqual(gate_code(report),0)
        report['blockers']=['external integrity gap']
        self.assertEqual(gate_code(report),2)

    def test_missing_or_partial_confirmation_never_falls_back_to_legacy(self):
        from value_lab.ci_gate import gate_code
        from value_lab.value_metrics import positive_signal
        from value_lab.report import _verdict
        from value_lab.usage import build_usage_card
        s,records,lock,ledger=fixture()
        report=evaluate(s,records,lock,ledger)
        report.update(verdict='PROMISING_LOCAL_SIGNAL',evidence_type='local')
        good=deepcopy(report['confirmatory_analysis'])
        good.update(status='CONDITIONALLY_SUPPORTED',statistical_support=True)
        incomplete=[]
        for key in good['criteria']:
            item=deepcopy(good); del item['criteria'][key]; incomplete.append(item)
        no_objective=deepcopy(good); no_objective['rule']={}; incomplete.append(no_objective)
        for missing in (None, {}, {'status':'CONDITIONALLY_SUPPORTED','statistical_support':True}, *incomplete):
            report['confirmatory_analysis']=missing
            self.assertFalse(positive_signal(report))
            self.assertEqual(gate_code(report),2)
            self.assertEqual(_verdict(report),'确认性证据不足')
            with patch('value_lab.usage.evaluate',return_value=report):
                card=build_usage_card(s,records,lock,ledger)
            self.assertEqual(card['use_when'],[])
            self.assertEqual(card['status'],'REVIEW_REQUIRED')
        del report['confirmatory_analysis']
        self.assertFalse(positive_signal(report))
        self.assertEqual(gate_code(report),2)

    def test_single_pair_confirmation_rejects_multifactor_and_multiarm_reuse(self):
        from value_lab.component_studies import plan as component_plan
        from value_lab.plugin_combinations import plan as combination_plan
        s,_,_,_=fixture(n=3)
        with self.assertRaisesRegex(ValidationError,'single-plugin'):
            component_plan(s,{})
        combined={key:None for key in ('stage','inputs','plugins','rationale','policy','compare_orders','seed')}
        with self.assertRaisesRegex(ValidationError,'single-plugin'):
            combination_plan(dict(combined,suite=s))

    def test_fixed_confirmation_cannot_become_adaptive_batches(self):
        from value_lab.evidence_acquisition import _validate, FORMAT, RULE, STOP
        s,_,_,_=fixture(n=3)
        protocol={'format':FORMAT,'catalog_sha256':'c'*64,'selection_rule':RULE,'stopping_rule':STOP,
            'budget':{'max_usd':1,'max_batches':1},'checks':[{'id':'confirmation-check','phase':'confirmation',
            'suite':s,'inputs':{},'decision_case_ids':[s['cases'][0]['id']],'cost_upper_bound_usd':1}]}
        with self.assertRaisesRegex(ValidationError,'fixed sampling'):
            _validate({'studies':[],'task':{'cases':[]}},
                      {'protocol':protocol,'protocol_sha256':suite_digest(protocol),'batches':[]},
                      {'catalog_sha256':'c'*64,'plans':[]})

    def test_efficiency_requires_both_noninferiority_and_reliable_saving(self):
        s,records,lock,ledger=fixture(objective='efficiency')
        result=evaluate(s,records,lock,ledger)['confirmatory_analysis']
        self.assertTrue(result['simulated_criteria_met'])
        self.assertTrue(result['criteria']['cost_lower_exceeds_threshold'])
        records[0]['cost']['basis']='estimate'
        result=evaluate(s,records,lock,ledger)['confirmatory_analysis']
        self.assertFalse(result['statistical_support'])
        self.assertTrue(any('settled' in x for x in result['reasons']))

    def test_noninferiority_and_no_cost_saving_each_fail(self):
        for kind in ('quality','cost'):
            s,records,lock,ledger=fixture(objective='efficiency')
            report=evaluate(s,records,lock,ledger)
            if kind=='quality':
                for case in report['cases']: case['delta']=-.15
            else:
                for case in report['cases']:
                    for r in case['runs']: r['cost_usd']=.5
            result=assess(s,report,records)
            key='quality_lower_exceeds_threshold' if kind=='quality' else 'cost_lower_exceeds_threshold'
            self.assertFalse(result['criteria'][key])

    def test_actual_cost_bound_and_critical_failure_fail(self):
        for kind in ('cost','critical'):
            s,records,lock,ledger=fixture()
            if kind=='cost': records[0]['cost']['model_usd']=2
            report=evaluate(s,records,lock,ledger)
            if kind=='critical': report['summary']['critical_failures']=['manufactured failure']
            result=assess(s,report,records)
            key='per_run_cost_within_bound' if kind=='cost' else 'no_critical_failure'
            self.assertFalse(result['criteria'][key])
            self.assertFalse(result.get('simulated_criteria_met'))

    def test_pilot_case_family_input_and_run_leakage_rejected(self):
        for field in ('id','cluster','input_sha256'):
            s,_,_,_=fixture()
            p=s['policy']['power_plan']['pilot']['records'][0]
            s['cases'][0][field]=p[{'id':'task_id','cluster':'family_id','input_sha256':'input_sha256'}[field]]
            with self.assertRaises(ValidationError): validate_suite(s)
        s,records,lock,ledger=fixture()
        records[0]['session_id']=s['policy']['power_plan']['pilot']['records'][0]['with_run_id']
        result=evaluate(s,records,lock,ledger)['confirmatory_analysis']
        self.assertTrue(any('OVERLAP' in why for why in result['reasons']))

    def test_missing_posthoc_and_underpowered_cannot_confirm(self):
        for kind in ('missing','retrospective','changed_rule','input','underpowered'):
            s,records,lock,ledger=fixture(n=3 if kind=='underpowered' else 100)
            if kind=='missing': records.pop()
            if kind=='retrospective': lock['frozen_at']='2099-01-01T00:00:00+00:00'
            if kind=='changed_rule': s['policy']['power_plan']['rule']['anticipated_quality_delta']=.9
            if kind=='input': records[0]['input_sha256']='0'*64
            result=evaluate(s,records,lock,ledger)['confirmatory_analysis']
            self.assertFalse(result['statistical_support'],kind)
            self.assertTrue(result['reasons'],kind)

    def test_global_overhead_not_independent_cost_observation(self):
        s,records,lock,ledger=fixture(objective='efficiency')
        ledger['coverage']['setup']='itemized'
        ledger['entries']=[{'id':'setup','category':'setup','arm':'with','amount_usd':1,
                           'basis':'settled','evidence_ref':'setup-line','treatment':'additional'}]
        result=evaluate(s,records,lock,ledger)['confirmatory_analysis']
        self.assertTrue(any('shared/global' in why for why in result['reasons']))

    def test_plan_report_and_json_deliver_pilot_and_rules(self):
        s,records,lock,ledger=fixture()
        plan=plan_plugin_use({'schema_version':1,'intent':'evaluate','task':'Manufactured confirmation',
                              'sample_size_plan':s['policy']['power_plan']})
        with tempfile.TemporaryDirectory() as tmp:
            write_plan(plan,Path(tmp)/'design')
            text=(Path(tmp)/'design/PLAN.md').read_text(encoding='utf-8')
            self.assertIn('先导交接与确认规则',text)
            self.assertIn('确认性目标',text)
            report=evaluate(s,records,lock,ledger)
            write_reports(report,Path(tmp)/'report')
            for name in ('report.md','report.html'):
                content=(Path(tmp)/'report'/name).read_text(encoding='utf-8')
                self.assertIn('确认性判断',content)
                self.assertIn('下置信界',content)
                self.assertNotIn('条件置信区间未给出',content)

    def test_cli_v3_plan_validation_freeze_and_evaluation(self):
        s,records,lock,ledger=fixture(n=3)
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            suite=base/'suite.json'; suite.write_text(json.dumps(s),encoding='utf-8')
            context=base/'context.json'; context.write_text(json.dumps({'schema_version':1,'intent':'evaluate',
                'task':'Manufactured confirmation','sample_size_plan':s['policy']['power_plan']}),encoding='utf-8')
            def run(*args):
                result=subprocess.run([sys.executable,str(ROOT/'scripts/value_lab.py'),*map(str,args)],capture_output=True,timeout=45)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                return result
            run('plan-use',context,'--output',base/'design')
            machine=json.loads((base/'design/plan.json').read_text(encoding='utf-8'))
            self.assertEqual(machine['sample_size']['format'],'pvl-sample-size-3')
            run('suite-check',suite)
            run('freeze',suite,'--lock',base/'frozen.json')
            observations=base/'records.jsonl'; observations.write_text('',encoding='utf-8')
            run('evaluate',suite,observations,'--lock',base/'frozen.json','--output',base/'report')
            report=json.loads((base/'report/report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['confirmatory_analysis']['status'],'SIMULATION_ONLY')
            self.assertFalse(report['confirmatory_analysis']['statistical_support'])


if __name__=='__main__':
    unittest.main()
