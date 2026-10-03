"""Reproducible synthetic burden tradeoffs, not researcher efficiency evidence."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from value_lab.core import ValidationError
from value_lab.workflow import plan_plugin_use


def run(output):
    output=Path(output)
    if output.exists(): raise ValidationError('Preserve earlier acceptance records')
    output.parent.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('burden_demo',ROOT/'examples/task-selection/burden_demo.py')
    demo=importlib.util.module_from_spec(spec); spec.loader.exec_module(demo)
    scenarios=[('more_dependencies_less_work',{},None,'PREFERRED_IN_OBSERVED_CATALOG'),
        ('dependency_tradeoff',{'metric_changes':{'new_plugins':{'material_delta':0},'total_plugins':{'material_delta':0}}},None,'CHOICE_REQUIRED'),
        ('below_material_threshold',{'metric_changes':{'human_seconds':{'material_delta':1000},'elapsed_seconds':{'material_delta':1000}}},None,'NO_MATERIAL_CHANGE_KEEP_INCUMBENT'),
        ('pvl_rework_reverses_choice',{},'pvl_work','PREFERRED_IN_OBSERVED_CATALOG'),
        ('privacy_violation',{},'privacy','PREFERRED_IN_OBSERVED_CATALOG'),
        ('review_pending',{},'review','EVIDENCE_REQUIRED'),
        ('unknown_failure_cost',{},'cost','EVIDENCE_REQUIRED'),
        ('cash_goal_has_no_cash_gain',{'policy_changes':{'objective':'cash_usd'}},None,'CHOICE_REQUIRED')]
    rows=[]
    with tempfile.TemporaryDirectory(dir=output.parent,prefix='pvl-burden-qualification-') as tmp:
        for name,options,mutation,expected in scenarios:
            ctx,a,s=demo.fixture(Path(tmp)/name,**options)
            req=ctx['burden_decision']
            sha=ctx['task_selection']['studies'][1]['lock']['suite_sha256']
            receipt=next(r for r in req['receipts'] if r['suite_sha256']==sha and r['arm']=='with')
            plan_id=ctx['task_selection']['studies'][1]['suite']['task_selection']['arms']['with']
            assurance=next(r for r in req['assurances'] if r['plan_sha256']==plan_id)
            if mutation=='pvl_work':
                resource=demo.resources(2,1000)
                resource['timers'][1]['phase']='pvl_false_positive'
                resource['coverage']['execution']['human']='not_applicable'
                resource['coverage']['pvl_false_positive']['human']='complete'
                receipt['resources']=resource
            elif mutation=='privacy': assurance['locality']['status']='violated'
            elif mutation=='review': next(iter(assurance['reviews'].values()))['status']='unknown'
            elif mutation=='cost': req['receipts'][0]['resources']['coverage']['rework']['cash']='unknown'
            report=plan_plugin_use(ctx,artifact_root=a,verifier_root=s)['burden_decision']
            assert report['computed_state']==expected,(name,report['computed_state'])
            assert report['state']=='SIMULATION_ONLY' and report['selected_plan_sha256'] is None
            chosen=next((r for r in report['candidates'] if r['plan_sha256']==report['simulation_choice_sha256']),None)
            rows.append({'scenario':name,'expected_computed_state':expected,'computed_state':report['computed_state'],
                'evidence_status':report['evidence_status'],'simulation_choice_components':
                    [s['component_id'] for s in chosen['manifest']['steps']] if chosen else None,
                'candidate_metrics':[{'components':[s['component_id'] for s in r['manifest']['steps']],
                                     'status':r['status'],'metrics':r['metrics']} for r in report['candidates']
                                     if [s['component_id'] for s in r['manifest']['steps']] in (['native','native'],['plugin','script'])],
                'blockers':report['blockers'],'total_observed_selection_burden':report['total_observed_selection_burden'],
                'known_settled_subtotal_usd':report['known_settled_subtotal_usd'],
                'execution_authorized':False,'statistical_guarantee':'NONE'})
    result={'format':'pvl-burden-decision-qualification-1','evidence':'SIMULATION_ONLY','status':'PASS',
            'scenarios':rows,'real_researcher_benefit_established':False,'paid_calls':0,
            'source_sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in
                ('value_lab/burden_decision.py','value_lab/workflow.py','examples/task-selection/burden_demo.py')}}
    with output.open('x',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,indent=2); f.write('\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--output',required=True)
    r=run(parser.parse_args().output)
    print(json.dumps({'status':r['status'],'scenarios':len(r['scenarios']),'evidence':r['evidence']},indent=2))
