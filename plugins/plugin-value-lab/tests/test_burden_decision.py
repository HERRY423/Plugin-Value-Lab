"""Manufactured local-label fixtures exercise gates; no real use or benefit claim."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from value_lab.burden_decision import analyze, prepare, _relation, METRICS
from value_lab.core import ValidationError, suite_digest
from value_lab.task_selection import select_task_plan
from value_lab.workflow import plan_plugin_use, write_plan

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('burden_fixture',ROOT/'examples/task-selection/burden_demo.py')
example=importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class BurdenDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.ctx,self.artifacts,self.scorers=example.fixture(self.root,synthetic=False)
        self.selection=self.ctx['task_selection']
        self.request=self.ctx['burden_decision']

    def result(self):
        return plan_plugin_use(self.ctx,artifact_root=self.artifacts,verifier_root=self.scorers)['burden_decision']

    def row(self, report, components):
        return next(c for c in report['candidates'] if [s['component_id'] for s in c['manifest']['steps']]==components)

    def receipt(self,index,arm):
        sha=self.selection['studies'][index]['lock']['suite_sha256']
        return next(r for r in self.request['receipts'] if r['suite_sha256']==sha and r['arm']==arm)

    def assurance(self,ident): return next(a for a in self.request['assurances'] if a['plan_sha256']==ident)

    def test_more_plugins_can_reduce_complete_human_work_after_all_gates(self):
        r=self.result()
        native=self.row(r,['native','native']); plugin=self.row(r,['plugin','script'])
        self.assertEqual(r['default_dependency_choice_sha256'],native['plan_sha256'])
        self.assertEqual(r['selected_plan_sha256'],plugin['plan_sha256'])
        self.assertEqual((native['metrics']['human_seconds'],plugin['metrics']['human_seconds']),(600,80))
        self.assertTrue(r['observed_preference_established'])
        self.assertFalse(r['global_minimum_established'])
        self.assertFalse(r['execution_authorized'])
        self.assertEqual(r['statistical_guarantee'],'NONE')

    def test_old_default_policy_and_source_records_remain_unchanged(self):
        before=deepcopy(self.ctx)
        legacy=select_task_plan(self.selection,artifact_root=self.artifacts,verifier_root=self.scorers)
        self.result()
        self.assertEqual(self.ctx,before)
        self.assertEqual(select_task_plan(self.selection,artifact_root=self.artifacts,verifier_root=self.scorers),legacy)

    def test_failed_scientific_candidate_never_wins_for_being_cheap(self):
        self.receipt(0,'with')['resources']=example.resources(0,0,0)
        r=self.result(); failed=self.row(r,['plugin','plugin'])
        self.assertEqual(failed['status'],'EXCLUDED')
        self.assertIn('SCIENTIFIC_OR_APPLICABILITY_FAILURE',failed['exclusion_reasons'])
        self.assertNotEqual(r['selected_plan_sha256'],failed['plan_sha256'])

    def test_actual_artifact_tampering_blocks_existing_pass(self):
        record=self.selection['studies'][1]['records'][0]
        (self.artifacts/record['artifacts']['result']['path']).write_text('{}')
        r=self.result()
        self.assertIsNone(r['selected_plan_sha256'])
        self.assertEqual(self.row(r,['plugin','script'])['status'],'UNKNOWN')

    def test_missing_artifact_roots_never_fall_back_to_text_pass(self):
        r=plan_plugin_use(self.ctx)['burden_decision']
        self.assertIsNone(r['selected_plan_sha256'])
        self.assertIn('UNRESOLVED_CANDIDATES',r['blockers'])

    def test_privacy_violation_excludes_cheap_fast_plan(self):
        good=self.row(self.result(),['plugin','script'])
        self.assurance(good['plan_sha256'])['locality']['status']='violated'
        r=self.result()
        self.assertEqual(self.row(r,['plugin','script'])['status'],'EXCLUDED')
        self.assertEqual(r['selected_plan_sha256'],self.row(r,['native','native'])['plan_sha256'])

    def test_privacy_unknown_is_not_satisfied_or_unconditionally_excluded(self):
        good=self.row(self.result(),['plugin','script'])
        self.assurance(good['plan_sha256'])['locality']['status']='unknown'
        r=self.result()
        self.assertIsNone(r['selected_plan_sha256'])
        self.assertEqual(self.row(r,['plugin','script'])['status'],'UNKNOWN')

    def test_required_human_review_pending_blocks_preference(self):
        good=self.row(self.result(),['plugin','script'])
        review=next(iter(self.assurance(good['plan_sha256'])['reviews'].values()))
        review['status']='unknown'
        self.assertIsNone(self.result()['selected_plan_sha256'])

    def test_rejected_review_is_hard_exclusion(self):
        good=self.row(self.result(),['plugin','script'])
        next(iter(self.assurance(good['plan_sha256'])['reviews'].values()))['status']='rejected'
        self.assertEqual(self.row(self.result(),['plugin','script'])['status'],'EXCLUDED')

    def test_assurances_bind_full_plan_components_and_records(self):
        self.request['assurances'][0]['components_sha256']='f'*64
        with self.assertRaisesRegex(ValidationError,'Assurance'): self.result()

    def test_new_policy_hash_cannot_reuse_old_study_lock(self):
        self.request['protocol']['policy']['objective']='cash_usd'
        self.request['protocol_sha256']=suite_digest(self.request['protocol'])
        with self.assertRaisesRegex(ValidationError,'original study'): self.result()

    def test_frozen_policy_edit_without_rehash_rejected(self):
        self.request['protocol']['policy']['metrics']['human_seconds']['material_delta']=999
        with self.assertRaisesRegex(ValidationError,'Frozen'): self.result()

    def test_prepare_rejects_retrospective_studies(self):
        with self.assertRaisesRegex(ValidationError,'before observations'):
            prepare(self.selection,self.request['protocol']['policy'],self.request['protocol']['study_suites'])

    def test_prepare_rejects_invalid_load_comparison_before_collection(self):
        selection=deepcopy(self.selection); selection['studies']=[]
        suites=deepcopy(self.request['protocol']['study_suites'])
        suites[0]['task_selection']['arms']['without']=suites[0]['task_selection']['arms']['with']
        with self.assertRaisesRegex(ValidationError,'load semantics'):
            prepare(selection,self.request['protocol']['policy'],suites)

    def test_native_plan_must_obey_the_same_local_only_constraint(self):
        native=self.row(self.result(),['native','native'])
        self.assurance(native['plan_sha256'])['locality']['status']='violated'
        r=self.result()
        self.assertEqual(self.row(r,['native','native'])['status'],'EXCLUDED')
        self.assertEqual(r['selected_plan_sha256'],self.row(r,['plugin','script'])['plan_sha256'])

    def test_old_unbound_studies_cannot_be_silently_imported(self):
        self.selection['studies'][0]['suite'].pop('burden_decision')
        with self.assertRaisesRegex(ValidationError,'original study'): self.result()

    def test_changed_task_or_candidate_scope_rejected(self):
        self.selection['task']['facts']['paired']=False
        with self.assertRaises(ValidationError): self.result()

    def test_missing_original_study_preserves_unknown_candidate_and_budget(self):
        study=self.selection['studies'].pop(1)
        sha=study['lock']['suite_sha256']
        self.request['receipts']=[r for r in self.request['receipts'] if r['suite_sha256']!=sha]
        self.request['assurances']=[]
        self.request['decision_overhead']=None
        r=self.result()
        self.assertIn('UNOBSERVED_STUDY',r['blockers'])
        self.assertEqual(r['planned_task_trials'],10)
        self.assertEqual(r['received_task_trials'],8)
        self.assertIsNone(r['total_observed_selection_burden']['cash_usd'])

    def test_missing_burden_receipt_does_not_shrink_denominator(self):
        self.request['receipts'].pop()
        r=self.result()
        self.assertEqual((r['planned_task_trials'],r['received_task_trials']),(10,9))
        self.assertIsNone(r['selected_plan_sha256'])
        self.assertIsNone(r['total_observed_selection_burden']['cash_usd'])

    def test_failed_candidate_missing_cost_remains_in_total_burden(self):
        resource=self.receipt(0,'with')['resources']
        resource['coverage']['rework']['cash']='unknown'
        r=self.result()
        self.assertIn('TOTAL_SELECTION_BURDEN_INCOMPLETE',r['blockers'])
        self.assertIsNone(r['total_observed_selection_burden']['cash_usd'])
        self.assertIsNone(r['selected_plan_sha256'])

    def test_estimated_cash_never_becomes_settled_cash_or_zero(self):
        cash=self.receipt(1,'with')['resources']['cash'][0]
        cash.update(basis='estimate',amount_usd=.1)
        r=self.result(); p=self.row(r,['plugin','script'])
        self.assertIsNone(p['metrics']['cash_usd'])
        self.assertEqual(p['trial_details'][0]['burden']['estimated_subtotal_usd'],.1)
        self.assertIsNone(r['selected_plan_sha256'])

    def test_missing_phase_coverage_rejected(self):
        self.request['receipts'][0]['resources']['coverage'].pop('pvl_false_positive')
        with self.assertRaises(ValidationError): self.result()

    def test_not_applicable_cannot_hide_itemized_work(self):
        self.request['receipts'][0]['resources']['coverage']['execution']['human']='not_applicable'
        with self.assertRaisesRegex(ValidationError,'contradicts'): self.result()

    def test_pvl_work_can_reverse_apparent_speed_advantage(self):
        resource=example.resources(2,1000)
        resource['timers'][1]['phase']='pvl_false_positive'
        resource['coverage']['execution']['human']='not_applicable'
        resource['coverage']['pvl_false_positive']['human']='complete'
        self.receipt(1,'with')['resources']=resource
        r=self.result()
        self.assertEqual(r['selected_plan_sha256'],self.row(r,['native','native'])['plan_sha256'])

    def test_shared_pvl_overhead_is_counted_once_and_failure_costs_remain(self):
        r=self.result()
        self.assertEqual(r['decision_overhead']['metrics']['human_seconds'],60)
        self.assertEqual(r['total_observed_selection_burden'],{'human_seconds':1380,'cash_usd':11})
        self.assertEqual(self.row(r,['plugin','script'])['metrics']['human_seconds'],80)

    def test_missing_shared_decision_overhead_blocks_complete_preference(self):
        self.request['decision_overhead']=None
        r=self.result()
        self.assertIn('DECISION_OVERHEAD_UNKNOWN',r['blockers'])
        self.assertIsNone(r['selected_plan_sha256'])

    def test_cash_cannot_erase_bound_original_run_expense(self):
        # Mutate the referenced original and rebind affected declarations as a
        # synthetic repair; then the independent resource lower bound must reject.
        study=self.selection['studies'][1]
        record=next(r for r in study['records'] if r['arm']=='with')
        record['cost']['model_usd']=20
        record['cost'].update(basis='settled',evidence_ref='fixture-settled-line')
        receipt=self.receipt(1,'with')
        receipt['records_sha256']=suite_digest(sorted([r for r in study['records'] if r['arm']=='with'],key=lambda r:r['case_id']))
        with self.assertRaisesRegex(ValidationError,'lower than'): self.result()

    def test_overlapping_same_actor_work_cannot_double_count(self):
        self.request['receipts'][1]['resources']['timers'][0].update(
            start=self.request['receipts'][0]['resources']['timers'][0]['start'],
            end=self.request['receipts'][0]['resources']['timers'][0]['end'])
        self.request['receipts'][1]['resources']['window']['start']=self.request['receipts'][0]['resources']['window']['start']
        with self.assertRaisesRegex(ValidationError,'overlaps'): self.result()

    def test_settled_supplemental_cost_cannot_disappear_from_whole_task(self):
        ledger=self.selection['studies'][1]['cost_ledger']
        ledger['coverage']['setup']='itemized'
        ledger['entries'].append({'id':'setup-invoice','category':'setup','arm':'with','amount_usd':20,
            'basis':'settled','evidence_ref':'fixture-setup-line','treatment':'additional'})
        with self.assertRaisesRegex(ValidationError,'lower than'): self.result()

    def test_estimated_original_cost_is_not_a_floor_on_later_settlement(self):
        study=self.selection['studies'][1]
        record=next(r for r in study['records'] if r['arm']=='with')
        record['cost'].update(model_usd=20,basis='estimate',evidence_ref='fixture-estimate')
        receipt=self.receipt(1,'with')
        receipt['records_sha256']=suite_digest(sorted([r for r in study['records'] if r['arm']=='with'],key=lambda r:r['case_id']))
        ident=record['selection_plan_sha256']
        self.assurance(ident)['records_sha256']=suite_digest(sorted([r for r in study['records'] if r['arm']=='with'],key=lambda r:r['case_id']))
        self.request['decision_overhead']['observations_sha256']=suite_digest(self.selection['studies'])
        r=self.result()
        self.assertEqual(self.row(r,['plugin','script'])['metrics']['cash_usd'],1)

    def test_duplicate_bill_line_across_plan_and_overhead_rejected(self):
        self.request['decision_overhead']['resources']['cash'][0]=deepcopy(self.request['receipts'][0]['resources']['cash'][0])
        with self.assertRaisesRegex(ValidationError,'Settlement line reused'): self.result()

    def test_missing_window_is_not_imputed_from_cpu_or_sum_of_timers(self):
        self.receipt(1,'with')['resources']['window']=None
        r=self.result()
        self.assertIsNone(self.row(r,['plugin','script'])['metrics']['elapsed_seconds'])
        self.assertIsNone(r['selected_plan_sha256'])

    def test_aware_timer_and_valid_numbers_required(self):
        for value in (-1,True,float('nan'),float('inf')):
            self.request['receipts'][0]['resources']['cash'][0]['amount_usd']=value
            with self.subTest(value=value), self.assertRaises(ValidationError): self.result()

    def test_duplicate_receipt_rejected_not_averaged_twice(self):
        self.request['receipts'].append(deepcopy(self.request['receipts'][0]))
        with self.assertRaisesRegex(ValidationError,'duplicate'): self.result()

    def test_receipt_cannot_drop_failed_cases_from_binding(self):
        self.request['receipts'][0]['records_sha256']=suite_digest([])
        with self.assertRaisesRegex(ValidationError,'every original case'): self.result()

    def test_synthetic_preview_cannot_become_adoption(self):
        context,artifacts,scorers=example.fixture(self.root/'synthetic')
        r=plan_plugin_use(context,artifact_root=artifacts,verifier_root=scorers)['burden_decision']
        self.assertEqual(r['state'],'SIMULATION_ONLY')
        self.assertIsNone(r['selected_plan_sha256'])
        self.assertIsNotNone(r['simulation_choice_sha256'])
        self.assertFalse(r['observed_preference_established'])

    def test_material_difference_keeps_incumbent_without_hidden_tiebreak(self):
        context,a,s=example.fixture(self.root/'tied',synthetic=False,metric_changes={
            'human_seconds':{'material_delta':1000},'elapsed_seconds':{'material_delta':1000}})
        r=plan_plugin_use(context,artifact_root=a,verifier_root=s)['burden_decision']
        self.assertEqual(r['state'],'NO_MATERIAL_CHANGE_KEEP_INCUMBENT')
        self.assertEqual(r['selected_plan_sha256'],r['policy']['incumbent_plan_sha256'])

    def test_important_dependency_tradeoff_requires_choice(self):
        context,a,s=example.fixture(self.root/'tradeoff',synthetic=False,metric_changes={
            'new_plugins':{'material_delta':0},'total_plugins':{'material_delta':0}})
        r=plan_plugin_use(context,artifact_root=a,verifier_root=s)['burden_decision']
        self.assertEqual(r['state'],'CHOICE_REQUIRED')
        self.assertIsNone(r['selected_plan_sha256'])
        self.assertEqual(r['comparisons'][0]['relation'],'TRADEOFF')

    def test_caps_apply_to_each_trial_not_only_candidate_mean(self):
        context,a,s=example.fixture(self.root/'caps',synthetic=False,metric_changes={'cash_usd':{'max_value':10}})
        req=context['burden_decision']
        # Script/script has two scheduled full-task trials; (19 + 1)/2 == cap.
        sha=context['task_selection']['studies'][1]['lock']['suite_sha256']
        next(r for r in req['receipts'] if r['suite_sha256']==sha and r['arm']=='without')['resources']['cash'][0]['amount_usd']=19
        r=plan_plugin_use(context,artifact_root=a,verifier_root=s)['burden_decision']
        row=self.row(r,['script','script'])
        self.assertEqual(row['metrics']['cash_usd'],10)
        self.assertIn('BURDEN_CAP_EXCEEDED:cash_usd',row['exclusion_reasons'])

    def test_no_transitive_elimination_with_nontransitive_margin_preferences(self):
        policy=deepcopy(self.request['protocol']['policy']); policy['objective']='pareto'
        for m in METRICS: policy['metrics'][m]['material_delta']=1
        # A -> B -> C -> A; candidate order must not create an apparent minimum.
        points=[dict(zip(METRICS,values)) for values in ((0,1,2,0,0),(2,0,1,0,0),(1,2,0,0,0))]
        self.assertEqual([_relation(points[i],points[(i+1)%3],policy)[0] for i in range(3)],['LEFT_PREFERRED']*3)

    def test_preparation_through_existing_entry_returns_bound_suites(self):
        context=deepcopy(self.ctx); context['task_selection']['studies']=[]
        context['burden_decision']={'action':'prepare','policy':self.request['protocol']['policy'],
            'study_suites':self.request['protocol']['study_suites']}
        r=plan_plugin_use(context)
        self.assertEqual(r['route'],'DECIDE_TASK_BURDEN')
        self.assertEqual(r['burden_decision']['state'],'AWAITING_PROSPECTIVE_EVIDENCE')
        self.assertEqual(len(r['burden_decision']['prepared_studies']),5)
        self.assertFalse(r['handoff']['execute'])

    def test_incompatible_modes_and_explicit_provider_rejected(self):
        for key in ('risk_acquisition','evidence_acquisition','evidence_bridge','plugin_combination'):
            with self.subTest(key=key),self.assertRaises(ValidationError): plan_plugin_use({**self.ctx,key:{}})
        with self.assertRaises(ValidationError): plan_plugin_use({**self.ctx,'selected_plugin':'x'})

    def test_actual_cli_and_human_report(self):
        path=self.root/'context.json'; path.write_text(json.dumps(self.ctx),encoding='utf-8')
        p=subprocess.run([sys.executable,str(ROOT/'scripts/value_lab.py'),'plan-use',str(path),'--artifacts',str(self.artifacts),
            '--verifiers',str(self.scorers),'--output',str(self.root/'plan')],capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        report=json.loads((self.root/'plan/plan.json').read_bytes())
        self.assertEqual(report['route'],'DECIDE_TASK_BURDEN')
        text=(self.root/'plan/PLAN.md').read_text(encoding='utf-8')
        self.assertIn('共同选型开销只计一次',text)
        self.assertIn('不折算综合分',text)

    def test_schema_and_runtime_reject_hidden_weighted_score(self):
        import jsonschema
        schema=json.loads((ROOT/'schemas/burden-decision.schema.json').read_text())
        validator=jsonschema.Draft202012Validator(schema)
        validator.validate(self.request)
        self.request['protocol']['policy']['weights']={'cash_usd':1,'scientific_error':.01}
        self.assertTrue(list(validator.iter_errors(self.request)))
        with self.assertRaises(ValidationError): self.result()

    def test_resource_scope_is_complete_task_not_sum_of_parallel_actor_time(self):
        r=self.receipt(1,'with')['resources']
        other=deepcopy(r['timers'][1]); other.update(id='parallel-reviewer',actor='another-fixture-reviewer')
        r['timers'].append(other)
        result=self.row(self.result(),['plugin','script'])['metrics']
        self.assertEqual(result['human_seconds'],120)
        self.assertEqual(result['elapsed_seconds'],110)

    def test_single_case_regression_limit_cannot_be_loosened_inside_old_protocol(self):
        self.request['protocol']['study_suites'][0]['policy']['max_case_regression']=1
        self.request['protocol_sha256']=suite_digest(self.request['protocol'])
        with self.assertRaisesRegex(ValidationError,'original study'): self.result()


class BurdenMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_six_tool_stdio_preparation(self):
        from mcp import ClientSession,StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as d:
            context,_,_=example.fixture(Path(d))
            original=context['burden_decision']['protocol']
            context['task_selection']['studies']=[]
            context['burden_decision']={'action':'prepare','policy':original['policy'],'study_suites':original['study_suites']}
            params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'scripts/value_lab.py'),'serve'],env={**os.environ,'PYTHONUTF8':'1'})
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    self.assertEqual(len((await session.list_tools()).tools),6)
                    result=await session.call_tool('plan_plugin_use',{'context':context})
                    self.assertFalse(result.isError,result)
                    r=json.loads(result.content[0].text)
                    self.assertEqual(r['route'],'DECIDE_TASK_BURDEN')


if __name__=='__main__': unittest.main()
