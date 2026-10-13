"""Action losses, simultaneous rank bounds and counterbalanced assignments."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from tests.optional import available, requires
from scripts.check_risk_acquisition import protocol
from tests.test_risk_acquisition import context, results
from value_lab.action_decision import action_report, selection_uncertainty
from value_lab.core import ValidationError, suite_digest
from value_lab.risk_acquisition import analyze, plan_risk_acquisition, validate_protocol
from value_lab.workflow import plan_plugin_use, write_plan

NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)


def loss_policy(ids):
    return {'researcher_id': 'EXAMPLE_NOT_REAL_PREFERENCES', 'loss_unit': 'preference_points',
            'false_adoption_cost': 100, 'missed_use_cost': 80, 'time_cost_per_hour': 1,
            'scope': 'Frozen literature task and version only',
            'valid_from': '2026-10-01T00:00:00Z', 'valid_until': '2026-11-01T00:00:00Z',
            'minimum_gain': .05, 'confirmation_family_floor': 30,
            'candidates': {i: {'adopt_hours': 2, 'trial_hours': 1, 'evidence_hours': 1,
                'trial_exposure': .5, 'trial_residual_harm': .1, 'guardrails': ['Human checks every citation; no external write'],
                'prohibited': False, 'prohibition_reason': None} for i in ids},
            'shrinkage': {'target': .5, 'strength': 8, 'rationale': 'Illustrative frozen regularization, not learned evidence'}}


def spec_v2(k=4):
    spec = protocol(k)
    spec.update(format='pvl-risk-acquisition-2', allocation='round_robin', rotation_seed=7, batch_units=k,
                max_units_per_candidate=32, evidence_type='submitted_observations')
    spec['assumptions']['no_order_or_carryover'] = True
    spec['decision_policy'] = loss_policy([c['id'] for c in spec['candidates'][1:]])
    return spec


def request_for(spec):
    return {'protocol': spec, 'protocol_sha256': suite_digest(spec), 'batches': []}


def advance(request):
    spec = request['protocol']
    plan = analyze(request)['next_block']
    rows = results(plan, spec, {c['id']: .5 for c in spec['candidates']})
    for row in rows:
        order = next(o['candidate_ids'] for o in plan['execution_orders'] if o['unit_id'] == row['unit_id'])
        row['execution_position'] = order.index(row['candidate_id'])+1
    request['batches'].append({'plan': plan, 'result': rows})
    return analyze(request)


class ActionDecisionTests(unittest.TestCase):
    def test_confirmation_adapter_recomputes_and_enforces_independence_alpha_and_floor(self):
        from unittest.mock import patch
        from value_lab.risk_acquisition import _confirmations
        p=spec_v2(3);p['utility_contract']['measure']='equal_family_quality'
        suite={'task_selection':{'arms':{'with':p['candidates'][1]['plan_sha256'],'without':p['candidates'][0]['plan_sha256']}},
               'cases':[{'cluster':f'heldout-{i}','input_sha256':suite_digest(i)} for i in range(30)],
               'policy':{'quality_weighting':'family','power_plan':{'version':3,'alpha':.025,'rule':{'objective':'quality','minimum_gain':.05}}}}
        # Isolate the adapter's gates; the authoritative evaluator has its own tests.
        for change in ('valid','synthetic','alpha','floor','overlap','unplanned','estimand'):
            s=deepcopy(suite);report={'evidence_type':'submitted_observations'}
            if change=='synthetic':report['evidence_type']='synthetic'
            if change=='alpha':s['policy']['power_plan']['alpha']=.05
            if change=='floor':s['cases'].pop()
            if change=='unplanned':s['policy']['power_plan']['version']=2
            if change=='estimand':s['policy']['quality_weighting']='case'
            raw=[{'session_id':'confirm-session','input_sha256':'d'*64}]
            req=request_for(p);req['batches']=[{'result':[{'session_id':'screen-session','input_sha256':'d'*64 if change=='overlap' else 'e'*64,'unit_id':'u1'}]}]
            req['confirmation_studies']=[{'suite':s,'records':raw,'lock':{}}]
            checked={'studies':[{'suite_sha256':suite_digest(s),'blockers':[]}]}
            with patch('value_lab.risk_acquisition.select_task_plan',return_value=checked), patch('value_lab.core.evaluate',return_value=report) as recompute, patch('value_lab.value_metrics.positive_signal',return_value=True), patch('value_lab.value_metrics.requires_confirmation',return_value=True):
                result=_confirmations({'studies':[]},req,None,None)
                recompute.assert_called_once()
                self.assertEqual(result['c1']['supported'],change=='valid',change)

    def test_three_alternatives_plus_baseline_balanced_and_replayable(self):
        req = request_for(spec_v2())
        plan = analyze(req)['next_block']
        self.assertEqual(len(plan['candidate_ids']), 4)
        for c in plan['candidate_ids']:
            self.assertEqual(sorted(o['candidate_ids'].index(c) for o in plan['execution_orders']), list(range(4)))
        view = advance(req)
        self.assertEqual(view, analyze(deepcopy(req)))
        self.assertEqual(view['candidate_units_resolved'], 16)
        self.assertTrue(all(r['rank_interval']==[1,4] for r in view['selection_uncertainty']['candidates']))

    def test_loss_changes_action_without_changing_intervals(self):
        req = request_for(spec_v2()); view=advance(req)
        a = action_report(req['protocol'], view, now=NOW)['candidates'][0]
        self.assertEqual(a['action'], '带护栏试用')
        low = deepcopy(req['protocol']); low['decision_policy']['missed_use_cost']=1
        b = action_report(low, view, now=NOW)['candidates'][0]
        self.assertEqual(b['action'], '默认基线')
        self.assertIn('默认基线=',b['reason'])
        self.assertIn('带护栏试用=',b['reason'])
        self.assertEqual(a['delta_interval'], b['delta_interval'])
        self.assertEqual(len(a['options']), 4)
        self.assertTrue(all(x['reason'] and x['valid_until'] and x['next_evidence_action'] for x in a['options']))

    def test_no_probability_imputed_and_priority_accounts_for_time(self):
        req=request_for(spec_v2());view=advance(req)
        p=req['protocol']['decision_policy']
        p['candidates']['c1']['evidence_hours']=100
        actions=action_report(req['protocol'],view,now=NOW)
        self.assertNotEqual(actions['next_evidence']['candidate_id'],'c1')
        self.assertEqual(actions['candidates'][0]['benefit_states'],[0,1])
        self.assertNotIn('probability',actions['candidates'][0])

    def test_only_baseline_allowed_does_not_hide_loss_or_value_of_confirmation(self):
        req=request_for(spec_v2());view=advance(req)
        req['protocol']['decision_policy']['candidates']['c1']['guardrails']=[]
        row=action_report(req['protocol'],view,now=NOW)['candidates'][0]
        self.assertEqual(row['action'],'默认基线')
        self.assertEqual(row['worst_regret'],0)
        self.assertEqual(row['worst_state_loss'],80)
        self.assertGreater(row['next_evidence']['avoidable_regret_upper_bound'],0)

    def test_synthetic_unknown_expired_and_missing_guardrails_never_adopt(self):
        req=request_for(spec_v2()); view=advance(req)
        for mutation in ('synthetic','unknown','expired','guardrails'):
            p=deepcopy(req['protocol']);r=deepcopy(view);clock=NOW
            if mutation=='synthetic':r['evidence_status']='SIMULATION_ONLY'
            if mutation=='unknown':r['state']='REPAIR_EVIDENCE'
            if mutation=='expired':clock=datetime(2026,11,2,tzinfo=timezone.utc)
            if mutation=='guardrails':p['decision_policy']['candidates']['c1']['guardrails']=[]
            self.assertEqual(action_report(p,r,now=clock)['candidates'][0]['action'],'默认基线')

    def test_prohibition_and_below_floor_use_avoid(self):
        req=request_for(spec_v2());view=advance(req)
        prefs=req['protocol']['decision_policy']['candidates']['c1']
        prefs.update(prohibited=True,prohibition_reason='License excludes this use')
        self.assertEqual(action_report(req['protocol'],view,now=NOW)['candidates'][0]['action'],'不使用')
        prefs.update(prohibited=False,prohibition_reason=None)
        view['intervals']['c1']['upper']=.1
        self.assertEqual(action_report(req['protocol'],view,now=NOW)['candidates'][0]['action'],'不使用')

    def test_adoption_requires_internal_confirmation_and_material_gain(self):
        req=request_for(spec_v2());view=advance(req)
        view['intervals']['c0'].update(lower=.3,upper=.4)
        view['intervals']['c1'].update(lower=.8,upper=.9)
        self.assertNotEqual(action_report(req['protocol'],view,now=NOW)['candidates'][0]['action'],'采用(限域)')
        self.assertEqual(action_report(req['protocol'],view,confirmations={'c1':True},now=NOW)['candidates'][0]['action'],'采用(限域)')
        req['confirmation_passed']=True
        with self.assertRaises(ValidationError):analyze(req)

    def test_shrinkage_does_not_narrow_or_promote_ranks(self):
        p=spec_v2(3)
        rows={'c0':{'n':10,'mean':.1,'lower':0,'upper':.2},
              'c1':{'n':10,'mean':.9,'lower':.8,'upper':1},
              'c2':{'n':10,'mean':.5,'lower':.4,'upper':.6}}
        u=selection_uncertainty(p,rows)
        self.assertEqual([r['rank_interval'] for r in u['candidates']],[[3,3],[1,1],[2,2]])
        self.assertLess(u['candidates'][1]['shrunk_mean'],.9)
        self.assertFalse(u['shrinkage']['used_for_certification'])
        self.assertEqual(selection_uncertainty(p,rows,False)['candidates'][1]['rank_interval'],[1,3])

    def test_rank_projection_contains_all_orders_allowed_by_rectangle(self):
        import itertools
        p=spec_v2(3)
        rows={f'c{i}':{'n':8,'mean':(lo+hi)/2,'lower':lo,'upper':hi} for i,(lo,hi) in enumerate(((.1,.6),(.4,.9),(.5,.7)))}
        ranks=selection_uncertainty(p,rows)['candidates']
        for values in itertools.product(*[(r['lower'],r['upper']) for r in rows.values()]):
            for i,x in enumerate(values):
                best=1+sum(y>x for y in values);worst=3-sum(y<x for y in values)
                self.assertLessEqual(ranks[i]['rank_interval'][0],best)
                self.assertGreaterEqual(ranks[i]['rank_interval'][1],worst)

    def test_frozen_losses_seed_candidates_and_order_tamper_rejected(self):
        for mutation in ('loss','seed','candidate','position','plan'):
            req=request_for(spec_v2());advance(req)
            if mutation=='loss':req['protocol']['decision_policy']['false_adoption_cost']=200
            if mutation=='seed':req['protocol']['rotation_seed']=10
            if mutation=='candidate':req['protocol']['candidates'].pop()
            if mutation=='position':req['batches'][0]['result'][0]['execution_position']=99
            if mutation=='plan':req['batches'][0]['plan']['execution_orders'][0]['candidate_ids'].reverse()
            with self.assertRaises(ValidationError):analyze(req)

    def test_strict_loss_input_and_versioning(self):
        for value in (True,-1,float('nan'),float('inf')):
            p=spec_v2();p['decision_policy']['missed_use_cost']=value
            with self.assertRaises(ValidationError):validate_protocol(p)
        p=spec_v2();p['format']='pvl-risk-acquisition-1'
        with self.assertRaises(ValidationError):validate_protocol(p)
        p=spec_v2();p['decision_policy']['valid_until']='2026-10-12'
        with self.assertRaises(ValidationError):validate_protocol(p)

    def test_order_assumptions_and_whole_block_budget(self):
        p=spec_v2();p['assumptions']['no_order_or_carryover']=None
        self.assertIsNone(analyze(request_for(p))['next_block'])
        p=spec_v2();p['budget_micros']=1
        r=analyze(request_for(p));self.assertEqual(r['state'],'STOP_BUDGET_UNRESOLVED')
        self.assertIsNone(r['next_block'])

    @requires('jsonschema')
    @unittest.skipUnless(available('jsonschema'),'requires: jsonschema')
    def test_schema_supports_both_versions_and_rejects_fake_loss(self):
        import jsonschema
        schema=json.loads(Path('schemas/risk-acquisition.schema.json').read_text(encoding='utf-8'))
        jsonschema.Draft202012Validator.check_schema(schema)
        req=request_for(spec_v2());advance(req)
        jsonschema.validate(req,schema)
        jsonschema.validate(request_for(protocol(3)),schema)
        req['protocol']['decision_policy']['hidden_probability']=.9
        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(req,schema)

    def test_workflow_render_and_confirmation_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx=context(Path(temp));p=ctx['risk_acquisition']['protocol']
            p.update(format='pvl-risk-acquisition-2',allocation='round_robin',rotation_seed=3)
            p['assumptions']['no_order_or_carryover']=True
            p['decision_policy']=loss_policy(['c1','c2'])
            ctx['risk_acquisition']['protocol_sha256']=suite_digest(p)
            plan=plan_plugin_use(ctx,now=NOW)
            self.assertEqual(plan['risk_acquisition']['action_decision']['status'],'RESEARCHER_LOSS_ACTIONS')
            write_plan(plan,Path(temp)/'out')
            text=(Path(temp)/'out'/'PLAN.md').read_text(encoding='utf-8')
            self.assertIn('名次区间',text);self.assertIn('有效至',text);self.assertIn('默认基线',text)
            ctx['risk_acquisition']['confirmation_studies']=[{'passed':True}]
            with self.assertRaises(ValidationError):plan_plugin_use(ctx,now=NOW)


if __name__=='__main__':unittest.main()
