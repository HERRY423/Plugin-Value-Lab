"""Manufactured burden decision example; no models or real researcher observations."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from value_lab.artifacts import sha
from value_lab.burden_decision import PHASES, prepare
from value_lab.core import suite_digest, write_json
from value_lab.task_selection import select_task_plan
from value_lab.workflow import plan_plugin_use, write_plan


def resources(index, human=40, cash=1, *, shared=False):
    start = datetime(2026,10,2,tzinfo=timezone.utc)+timedelta(hours=index)
    phases = {'setup':10, 'execution':human, 'review':10, 'pvl_report':20}
    if shared: phases = {'pvl_prepare':30, 'pvl_verify':20, 'pvl_report':10}
    timers, cursor = [], start
    for phase, seconds in phases.items():
        end = cursor+timedelta(seconds=seconds)
        timers.append({'id':phase,'phase':phase,'actor':'synthetic-researcher', 'start':cursor.isoformat(),
                       'end':end.isoformat(),'source_sha256':suite_digest({'timer':index,'phase':phase})})
        cursor = end
    return {'window':{'start':start.isoformat(),'end':(cursor+timedelta(seconds=30)).isoformat(),
                      'source_sha256':suite_digest({'window':index})}, 'timers':timers,
            'cash':[{'id':'cash','phase':'setup','amount_usd':cash,'basis':'settled',
                     'source_sha256':suite_digest({'bill':index}),'line_id':'line1'}],
            'coverage':{p:{'human':'complete' if p in phases else 'not_applicable',
                           'cash':'complete' if p=='setup' else 'not_applicable',
                           'note':'Manufactured coverage declaration; not real use.'} for p in PHASES}}


def fixture(root, *, synthetic=True, policy_changes=None, metric_changes=None):
    spec = importlib.util.spec_from_file_location('burden_source_fixture', Path(__file__).with_name('demo.py'))
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    context, artifacts, scorers = example.fixture(root, synthetic=synthetic)
    selection = context['task_selection']
    originals = selection['studies']
    # Make the no-plugin native plan pass all scientific fixture checks too.
    for record in originals[0]['records']:
        if record['arm'] != 'without': continue
        case = next(c for c in originals[0]['suite']['cases'] if c['id']==record['case_id'])
        verifier = case['graders'][0]['verifier']
        path = artifacts/record['artifacts']['result']['path']
        if verifier['kind']=='de_table': path.write_text('gene,p,q,effect\ng1,0.01,0.03,2\ng2,0.04,0.06,-1\ng3,0.2,0.2,0\n')
        else: write_json(path,verifier['expected'])
        record['artifacts']['result']['sha256'] = sha(path)
    selection['studies'] = []
    catalog = select_task_plan(selection)
    native = next(p['plan_sha256'] for p in catalog['plans'] if [s['component_id'] for s in p['manifest']['steps']]==['native','native'])
    policy = {'objective':'human_seconds', 'scope':'one_complete_frozen_task_no_amortization',
              'local_only':True,'incumbent_plan_sha256':native,
              'metrics':{m:{'material_delta':delta,'max_value':cap} for m,delta,cap in (
                  ('human_seconds',30,10000),('cash_usd',1,100),('elapsed_seconds',30,10000),('new_plugins',1,1),('total_plugins',1,1))}}
    policy.update(policy_changes or {})
    for metric, changes in (metric_changes or {}).items(): policy['metrics'][metric].update(changes)
    frozen = prepare(selection,policy,[s['suite'] for s in originals])
    for original, prepared in zip(originals,frozen['prepared_studies']):
        original['suite'], original['lock'] = prepared['suite'], prepared['lock']
        for record in original['records']: record['suite_sha256'] = prepared['lock']['suite_sha256']
    selection['studies'] = originals
    receipts, index = [], 0
    for study in originals:
        for arm in ('with','without'):
            records = sorted([r for r in study['records'] if r['arm']==arm],key=lambda r:r['case_id'])
            candidate = study['suite']['task_selection']['arms'][arm]
            receipts.append({'suite_sha256':study['lock']['suite_sha256'],'arm':arm,'repetition':1,
                'records_sha256':suite_digest(records),'protocol_sha256':frozen['protocol_sha256'],
                'resources':resources(index,560 if candidate==native else 40)})
            index += 1
    by_sha = {s['lock']['suite_sha256']:s for s in originals}
    ordered = [r for sha_ in sorted(by_sha) for arm in ('with','without')
               for r in sorted([r for r in by_sha[sha_]['records'] if r['arm']==arm],key=lambda r:r['case_id'])]
    # The production binding orders tuples lexicographically: 'with' before 'without'.
    assurances=[]
    for plan in catalog['plans']:
        ident=plan['plan_sha256']
        assurances.append({'plan_sha256':ident,'protocol_sha256':frozen['protocol_sha256'],
            'records_sha256':suite_digest([r for r in ordered if r['selection_plan_sha256']==ident]),
            'components_sha256':suite_digest(plan['manifest']['components']),
            'locality':{'status':'satisfied','source_sha256':suite_digest({'privacy':ident}),
                        'note':'Synthetic whole-plan locality assessment, not a real privacy audit.'},
            'reviews':{name:{'status':'accepted','reviewer':'synthetic-reviewer','source_sha256':suite_digest({'review':ident,'name':name}),
                            'note':'Manufactured review for gate testing only.'} for name in plan['required_reviews']}})
    context['burden_decision']={'action':'analyze','protocol':frozen['protocol'],'protocol_sha256':frozen['protocol_sha256'],
        'receipts':receipts,'assurances':assurances,'decision_overhead':{'protocol_sha256':frozen['protocol_sha256'],
        'observations_sha256':suite_digest(originals),'resources':resources(index,shared=True)}}
    return context,artifacts,scorers


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    output=Path(parser.parse_args().output)
    if output.exists(): parser.error('Preserve earlier evidence; choose a new output directory')
    context,artifacts,scorers=fixture(output)
    write_json(output/'context.json',context)
    plan=plan_plugin_use(context,artifact_root=artifacts,verifier_root=scorers)
    write_plan(plan,output/'plan')
    print(json.dumps({'state':plan['burden_decision']['state'],'automatic_execution':False,'output':str(output)},indent=2))
