"""Run the public seeded-defect meta-validation without a model or network.

All labels, inputs, mutations and checker contracts are frozen before execution.
Runs use isolated copies of our reviewed fixture, not arbitrary submitted code.
The compatible host-event transport is synthetic and never evidence of native
model use, external adoption, representative accuracy or plugin benefit.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import difflib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.artifacts import grade_artifact, sha
from value_lab.core import load_json, suite_digest, write_json
from value_lab.native_analysis import prepare_native_analysis
from value_lab.native_evidence import capture_native_evidence, verify_native_evidence
from value_lab.native_hypotheses import build_native_hypotheses
from value_lab.native_repair import compare_native_repair
from value_lab.usage import diagnose

FIXTURE = ROOT / 'examples/seeded-defects'
FAMILIES = {
    'multiple-testing': '多重检验错误', 'id-alignment': 'ID 错位',
    'pseudoreplication': '伪重复', 'reference-leakage': '参考泄漏',
    'backend-fallback': '静默后端回退', 'label-semantics': '标签语义互换',
    'over-refusal': '过度拒答', 'trigger': '触发失败',
}
PROFILES = ('artifact_only', 'configured_workflow')
CONTEXT = {'host_version': 'seed-host-1', 'model': 'deterministic-no-model',
    'model_version': 'no-weights', 'environment': 'SYNTHETIC_LOCAL_FIXTURE; stdlib only; no provider',
    'tools': ['Read', 'Skill', 'Write', 'Bash'], 'max_turns': 8,
    'timeout_seconds': 30, 'max_cost_usd': .01}


def mutation(family, variant):
    rows = "        rows = [dict(row) for row in task['rows']]"
    q = "        q = bh([r['p'] for r in rows])"
    train = '        trained = read_reference(task)'
    declared = '        declared = trained[:]'
    labels = "        labels = task['labels'][:]"
    route = "    route = 'direct' if task['family'] == 'trigger' and task['variant'] == 2 else 'pvl-seed:analyze'"
    entries = {
      'multiple-testing': [
        ('raw-p-as-q', [(q, "        q = [r['p'] for r in rows]")]),
        ('half-family-factor', [(q, "        q = [v / 2 for v in bh([r['p'] for r in rows])]")]),
        ('filter-before-bh', [(rows, rows+"\n        rows = rows[:-1]")])],
      'id-alignment': [
        ('rotate-p-values', [(rows, rows+"\n        for i, row in enumerate(rows):\n            row['p'] = task['rows'][(i+1) % len(rows)]['p']")]),
        ('rotate-identifiers', [(rows, rows+"\n        for i, row in enumerate(rows):\n            row['id'] = task['rows'][(i+1) % len(rows)]['id']")]),
        ('overwrite-then-drop', [(rows, rows+"\n        rows[0]['id'] = rows[1]['id']\n        rows = list({r['id']: r for r in rows}.values())")])],
      'pseudoreplication': [
        ('cells-as-units', [('        n_units = len(units)', "        n_units = len(task['measurements'])")]),
        ('technical-samples-as-units', [('        n_units = len(units)', "        n_units = len({r['sample'] for r in task['measurements']})")]),
        ('cell-level-standard-error', [('        values = list(units.values())', "        values = [r['value'] for r in task['measurements']]")])],
      'reference-leakage': [
        ('declared-evaluation-overlap', [(train, '        trained = read_eval_reference(task)')]),
        ('hidden-label-leakage', [(train, '        trained = read_eval_reference(task)'), (declared, "        declared = task['reference_ids'][:]")]),
        ('hidden-feature-leakage', [(train, '        trained = read_eval_features(task)'), (declared, "        declared = task['reference_ids'][:]")])],
      'backend-fallback': [
        ('rounded-fallback', [("        value = exact_backend(task['values'])", "        value = fallback_backend(task['values'])")]),
        ('legacy-same-numeric-result', [("        value = exact_backend(task['values'])", "        value = legacy_backend(task['values'])")]),
        ('exception-masked-by-equivalent-fallback', [("        value = exact_backend(task['values'])", "        try:\n            raise ImportError('seeded missing exact backend')\n        except ImportError:\n            value = fallback_backend(task['values'])")])],
      'label-semantics': [
        ('swap-t-b', [(labels, labels+"\n        labels = [task['swap'][v] for v in labels]")]),
        ('swap-cd4-cd8', [(labels, labels+"\n        labels = [task['swap'][v] for v in labels]")]),
        ('swap-immune-stromal', [(labels, labels+"\n        labels = [task['swap'][v] for v in labels]")])],
      'over-refusal': [
        ('unconditional-refusal', [("        decision = 'allow' if len(task['values']) >= 3 else 'withhold'", "        decision = 'withhold'")]),
        ('invented-sample-threshold', [("        decision = 'allow' if len(task['values']) >= 3 else 'withhold'", "        decision = 'allow' if len(task['values']) >= 100 else 'withhold'")]),
        ('allow-stamp-empty-answer', [("        answer = mean(task['values']) if decision == 'allow' else None", '        answer = None')])],
      'trigger': [
        ('route-omission', [(route, "    route = ''")]),
        ('wrong-skill-route', [(route, "    route = 'pvl-seed:other'")]),
        ('skill-error-with-host-fallback', [(route, "    route = 'error'")])],
    }
    return entries[family][variant]


def write_csv(path, fields, rows):
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def rule(identifier, kind, spec):
    return {'id': identifier, 'type': kind, 'artifact': 'result', 'verifier': spec}


def freeze_case(root, family, variant, clean):
    name, edits = mutation(family, variant)
    identifier = f'{family}-{variant+1}'
    home = root/'cases'/identifier
    (home/'inputs').mkdir(parents=True)
    refs = home/'references'; refs.mkdir()
    pair = [('T cell','B cell'), ('CD4 T cell','CD8 T cell'), ('immune','stromal')][variant]
    task = {'family': family, 'variant': variant,
        'rows': [{'id': f'g{i+1}', 'p': p, 'effect': float(i+1)} for i,p in enumerate([.001,.02,.08,.5])],
        'measurements': [{'donor': f'd{i}', 'sample': f'd{i}-r{j}', 'value': value}
            for i,value in enumerate([1.,2.,9.]) for j in range(2)],
        'reference_ids': ['ref-a','ref-b'], 'evaluation_ids': ['eval-a','eval-b'],
        'values': [1.+variant,2.+variant,4.+variant] if variant<2 else [3.,4.,5.],
        'ids': ['cell1','cell2','cell3','cell4'], 'labels': [pair[0],pair[0],pair[1],pair[1]],
        'swap': {pair[0]:pair[1],pair[1]:pair[0]},
        'aliases': {pair[0]:pair[0]+' alias',pair[1]:pair[1]+' alias'}}
    write_json(home/'inputs/input.json', task)
    csv_result = family in ('multiple-testing','id-alignment','label-semantics')
    basic, configured = [], []
    def ref(filename, data):
        write_json(refs/filename, data)
        return {'path': filename, 'sha256': sha(refs/filename)}
    if family in ('multiple-testing','id-alignment'):
        spec={'kind':'de_table','id_column':'id','p_column':'p','q_column':'q','effect_column':'effect','min_rows':1,'bh_tolerance':1e-8}
        basic=[rule('basic-bh', 'artifact', spec)]
        full=deepcopy(spec); full['testing_family']=ref('family.json',{'ids':['g1','g2','g3','g4']})
        configured=[rule('task-family-bh','artifact',full)]
        if family=='id-alignment':
            write_csv(refs/'truth.csv',['id','p'],[{'id':r['id'],'p':r['p']} for r in task['rows']])
            configured.append(rule('task-id-value','numeric_tolerance',{'metric':'absolute_relative',
                'truth':{'path':'truth.csv','sha256':sha(refs/'truth.csv')},'id_column':'id','value_column':'p',
                'threshold':1,'absolute':1e-12,'relative':1e-12}))
    elif family=='label-semantics':
        write_csv(refs/'truth.csv',['id','label'],[{'id':i,'label':v} for i,v in zip(task['ids'],task['labels'])])
        basic=[rule('basic-partition-ari','numeric_tolerance',{'metric':'ari','truth':{'path':'truth.csv','sha256':sha(refs/'truth.csv')},
            'id_column':'id','value_column':'label','threshold':1,'absolute':0,'relative':0})]
        configured=[rule('task-exact-labels','artifact',{'kind':'labels','id_column':'id','label_column':'label',
            'expected':dict(zip(task['ids'],task['labels']))})]
    else:
        field={'pseudoreplication':('n_units','integer'),'reference-leakage':('score','number'),
               'backend-fallback':('value','number'),'over-refusal':('decision','string'),'trigger':('ok','boolean')}[family]
        basic=[rule('basic-schema','artifact_schema',{'format':'json','fields':{field[0]:{'type':field[1],'nullable':False}},'allow_extra':True,'min_rows':1})]
        if family=='pseudoreplication':
            # Literal independently calculated SEM: sqrt((49+16+121)/9) / sqrt(2)?
            # Values 1,2,9: sample variance = 19; SEM = sqrt(19/3).
            configured=[rule('task-units','artifact',{'kind':'json_fields','expected':{'n_units':3,'analysis_unit':'donor'}}),
                rule('task-standard-error','artifact',{'kind':'json_fields','expected':{'se':math.sqrt(19.)/math.sqrt(3.)}})]
        elif family=='reference-leakage':
            configured=[rule('task-declared-training','artifact',{'kind':'json_fields','expected':{'training_ids':['ref-a','ref-b']}})]
        elif family=='over-refusal':
            configured=[rule('task-over-refusal','over_refusal',{'truth':ref('decision.json',{'decision':'allow','rationale':'At least three numbers supplied; mean requested, no unsupported scientific inference.'})})]
        elif family=='backend-fallback':
            configured=[rule('task-declared-backend','artifact',{'kind':'json_fields','expected':{'backend':'exact','version':'1'}})]
        else:
            configured=[rule('task-answer','artifact',{'kind':'json_fields','expected':{'ok':True}})]
    mutated=clean
    for old,new in edits:
        if mutated.count(old)!=1: raise ValueError('Mutation is not unique: '+identifier)
        mutated=mutated.replace(old,new)
    for phase,content in [('before',mutated),('after',clean)]:
        source=home/phase/'source'; source.mkdir(parents=True)
        (source/'analysis.py').write_text(content,encoding='utf-8')
        (source/'host.py').write_bytes((FIXTURE/'host.py').read_bytes())
        (source/'SKILL.md').write_text('---\nname: analyze\ndescription: Public deterministic seed fixture.\n---\nSYNTHETIC ONLY\n',encoding='utf-8')
        write_json(source/'plugin.json',{'name':'pvl-seed','version':'1'})
    (home/'mutation.diff').write_text(''.join(difflib.unified_diff(clean.splitlines(True),mutated.splitlines(True),fromfile='clean/analysis.py',tofile='mutated/analysis.py')),encoding='utf-8')
    recipe={'schema_version':1,'plugin_files':['analysis.py','host.py','SKILL.md'],'execution_context':CONTEXT,
        'cases':[{'name':identifier,'prompt':'Perform the supplied task with declared identities and semantics; retain the result. Synthetic local meta-validation only.',
            'repetitions':1,'inputs':{'task':{'path':'input.json','sha256':sha(home/'inputs/input.json')}},
            'artifacts':{'result':'result.csv' if csv_result else 'result.json','script':'analysis.py'},
            'execution':{'script_artifact':'script','command':'python -I host.py'},'graders':basic+configured}]}
    write_json(home/'recipe.json',recipe)
    oracle={'label':'defect','basis':'seeded task-contract violation, independent of PVL verdict',
        'family':family,'variant':variant,'mutation':name,'control_label':'valid','repair_label':'valid',
        'valid_aliases':task['aliases'],'training_order_semantic':False,
        'allowed_direct_plugin_use':True,'expected_reference_ids':task['reference_ids'],
        'expected_bh':[.004,.04,.10666666666666667,.5],
        'expected_units':3,'expected_sem':math.sqrt(19.)/math.sqrt(3.),
        'checker_limit':'Literal reference order and exact canonical labels cannot express every allowed normal variation; count their false alarms.',
        'backend_identity_requires':'extra observer receipt; not accepted by native-sidecar contract'}
    write_json(home/'oracle.json',oracle)
    return {'id':identifier,'family':family,'variant':variant,'mutation':name,
            'source_before_sha256':sha(home/'before/source/analysis.py'),'source_after_sha256':sha(home/'after/source/analysis.py'),
            'recipe_sha256':suite_digest(recipe),'oracle_sha256':suite_digest(oracle)}


def oracle_check(home, task):
    import csv
    obs=load_json(home/'host-observation.json')
    family=task['family']
    if family in ('multiple-testing','id-alignment','label-semantics'):
        with (home/'result.csv').open(encoding='utf-8',newline='') as stream: rows=list(csv.DictReader(stream))
        by_id={r['id']:r for r in rows}
        if len(by_id)!=len(rows): return False
        if family=='multiple-testing':
            expected=dict(zip(['g1','g2','g3','g4'],[.004,.04,.10666666666666667,.5]))
            return set(by_id)==set(expected) and all(abs(float(by_id[k]['q'])-v)<1e-12 for k,v in expected.items())
        if family=='id-alignment':
            return set(by_id)=={r['id'] for r in task['rows']} and all(abs(float(by_id[r['id']]['p'])-r['p'])<1e-12 for r in task['rows'])
        return set(by_id)==set(task['ids']) and all(by_id[k]['label'] in (v,task['aliases'][v]) for k,v in zip(task['ids'],task['labels']))
    obj=load_json(home/'result.json')
    if family=='pseudoreplication': return obj['n_units']==3 and math.isclose(obj['se'],math.sqrt(19/3),rel_tol=1e-12)
    if family=='reference-leakage': return set(load_json(home/'model-state.json')['used_ids'])==set(task['reference_ids'])
    if family=='backend-fallback': return 'exact_backend' in obs['calls'] and not {'fallback_backend','legacy_backend'} & set(obs['calls'])
    if family=='over-refusal': return obj['decision']=='allow' and obj['answer'] is not None and math.isclose(obj['answer'],sum(task['values'])/len(task['values']))
    return obs['route'] in ('pvl-seed:analyze','direct') and 'analyze' in obs['calls']


def run_phase(root, case, phase):
    home=root/'cases'/case['id']; directory=home/phase
    recipe=load_json(home/'recipe.json')
    prepared=prepare_native_analysis(recipe,directory/'source',home/'inputs',directory/'prepared',references=home/'references')
    bindings=[]; raw={'schemaVersion':1,'claudeVersion':'seed-host-1','partial':False,'costUsd':0,
        'cases':[{'name':case['id'],'arms':{'with':[],'without':[]}}]}
    runs=[]
    for arm in ('with','without'):
        workspace=directory/'workspaces'/arm; workspace.mkdir(parents=True)
        source=directory/'source' if arm=='with' else home/'after/source'
        for name in ('analysis.py','host.py'): shutil.copyfile(source/name,workspace/name)
        shutil.copyfile(home/'inputs/input.json',workspace/'input.json')
        sid=f'synthetic-{case["id"]}-{phase}-{arm}'
        write_json(workspace/'host-context.json',{'session_id':sid,'arm':arm})
        env={key:value for key,value in os.environ.items() if key.upper() in ('SYSTEMROOT','WINDIR','COMSPEC')}
        env.update(TEMP=str(workspace),TMP=str(workspace))
        started=time.perf_counter()
        process=subprocess.run([sys.executable,'-I',str(workspace/'host.py')],cwd=workspace,
            env=env,capture_output=True,timeout=30,shell=False)
        (workspace/'stdout.log').write_bytes(process.stdout); (workspace/'stderr.log').write_bytes(process.stderr)
        write_json(workspace/'process.json',{'returncode':process.returncode,'seconds':time.perf_counter()-started,'model_calls':0})
        if process.returncode: raise RuntimeError('Fixture failed; retain output and use a new run root: '+str(workspace))
        clean=oracle_check(workspace,load_json(workspace/'input.json'))
        expected=not (phase=='before' and arm=='with')
        write_json(workspace/'oracle-witness.json',{'contract_satisfied':clean,'expected_clean':expected,'independent_of_detector':True})
        if clean != expected: raise RuntimeError('Inactive seed or invalid control: '+str(workspace))
        raw['cases'][0]['arms'][arm].append({'error':None,'costUsd':0})
        bindings.append({'case_id':case['id'],'arm':arm,'repetition':1,'workspace':str(workspace),'events':'events.jsonl'})
        runs.append(workspace)
    write_json(directory/'synthetic-native-result.json',raw)
    captured=capture_native_evidence(directory/'prepared/plan',prepared['plan_sha256'],directory/'prepared/candidate',
        directory/'synthetic-native-result.json',bindings,directory/'capture',references=home/'references')
    write_json(directory/'capture-pin.json',{'receipt_sha256':captured['receipt_sha256'],'synthetic':True})
    verify_native_evidence(directory/'capture',captured['receipt_sha256'])
    diagnose(directory/'capture',directory/'author-diagnosis',receipt=captured['receipt_sha256'])
    expectations={'cases':{case['id']:{'expected_skills':['pvl-seed:analyze'],'conclusion_grader_ids':[]}}}
    hypotheses=build_native_hypotheses(directory/'capture',captured['receipt_sha256'],expectations)
    write_json(directory/'hypotheses.json',hypotheses)
    result=[]
    for index,run in enumerate(captured['diagnosis']['runs']):
        workspace=runs[index]; obs=load_json(workspace/'host-observation.json')
        grades=run['grades']
        extra=None
        if case['family']=='backend-fallback':
            calls=obs['calls']; backend='fallback' if 'fallback_backend' in calls else 'legacy' if 'legacy_backend' in calls else 'exact'
            path=workspace/'result.json'
            receipt={'backend':backend,'version':'1' if backend=='exact' else '0','entrypoint':backend+'_backend',
                'fallback':backend!='exact','session_id':f'synthetic-{case["id"]}-{phase}-{run["arm"]}',
                'artifact_sha256':sha(path),'collector':'seeded-local-python-profile','basis':'runtime_observation'}
            write_json(workspace/'backend-receipt.json',receipt)
            extra=grade_artifact(rule('runtime-backend','backend_identity',{'backend':'exact','version':'1','entrypoint':'exact_backend'}),
                {'session_id':receipt['session_id'],'artifacts':{'result':{'path':'result.json','sha256':sha(path)}},
                 'backend_receipt':{'path':'backend-receipt.json','sha256':sha(workspace/'backend-receipt.json')}},workspace,workspace)
        diagnosis=load_json(directory/'author-diagnosis/diagnosis.json')
        invocation_gap=run['arm']=='with' and any(f.get('kind')=='invocation_evidence_gap' for f in diagnosis['findings'])
        for profile in PROFILES:
            selected=[g for g in grades if g['id'].startswith('basic-' if profile=='artifact_only' else 'task-')]
            verdicts=[g['passed'] for g in selected]
            levels=[]
            if any(v is False for v in verdicts): levels.append('artifact/contract')
            if profile=='configured_workflow' and invocation_gap:
                verdicts.append(False); levels.append('trigger/invocation-gap')
            if profile=='configured_workflow' and extra:
                verdicts.append(extra[0])
                if extra[0] is False: levels.append('execution/backend-identity')
            alert=True if False in verdicts else None if None in verdicts or not verdicts else False
            result.append({'id':case['id'],'family':case['family'],'mutation':case['mutation'],'phase':phase,'arm':run['arm'],
                'profile':profile,'alert':alert,'localization':levels,'grades':selected,'runtime_backend':extra if profile=='configured_workflow' else None,
                'machine_diagnosis_seconds':diagnosis['timing']['machine_seconds_to_diagnosis'],
                'human_diagnosis_seconds':None,'receipt_sha256':captured['receipt_sha256'],
                'oracle_contract_satisfied':load_json(workspace/'oracle-witness.json')['contract_satisfied']})
    return captured['receipt_sha256'],result


def classify(alert, defect):
    if alert is None: return 'UNKNOWN'
    return ('TP' if alert else 'FN') if defect else ('FP' if alert else 'TN')


def summarize(rows):
    output={}
    for profile in PROFILES:
        families={}
        for family in FAMILIES:
            selected=[r for r in rows if r['profile']==profile and r['family']==family and r['phase']=='before']
            counts=Counter(classify(r['alert'],r['arm']=='with') for r in selected)
            defects=[r for r in selected if r['arm']=='with']; controls=[r for r in selected if r['arm']=='without']
            # The unmutated WITHOUT slot lacks plugin exposure by design. For
            # invocation specificity use restored WITH, the valid direct-use control.
            if family=='trigger':
                controls=[r for r in rows if r['profile']==profile and r['family']==family and r['phase']=='after' and r['arm']=='with']
                counts=Counter([classify(r['alert'],True) for r in defects]+[classify(r['alert'],False) for r in controls])
            by_id={r['id']:r for r in controls}
            unknown_d=sum(r['alert'] is None for r in defects); unknown_c=sum(r['alert'] is None for r in controls)
            paired=sum(r['alert'] is True and by_id[r['id']]['alert'] is False for r in defects)
            families[family]={**{k:counts[k] for k in ('TP','FN','FP','TN','UNKNOWN')},'defects':len(defects),'controls':len(controls),
                'detection_rate':None if unknown_d else counts['TP']/len(defects),
                'false_positive_rate':None if unknown_c else counts['FP']/len(controls),
                'detection_bounds':[counts['TP']/len(defects),(counts['TP']+unknown_d)/len(defects)],
                'false_positive_bounds':[counts['FP']/len(controls),(counts['FP']+unknown_c)/len(controls)],
                'paired_specific_detections':paired,'localization':sorted({v for r in defects for v in r['localization']})}
        output[profile]=families
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); root=args.output.resolve()
    if root.exists(): raise SystemExit('Preserve earlier attempts; choose a new output directory')
    root.mkdir(parents=True)
    clean=(FIXTURE/'plugin.py').read_text(encoding='utf-8')
    cases=[freeze_case(root,f,v,clean) for f in FAMILIES for v in range(3)]
    pvl_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in sorted((ROOT/'value_lab').glob('*.py'))}
    frozen={'format':'pvl-seeded-defects-1','cases':cases,'pvl_files':pvl_hashes,'runner_sha256':sha(Path(__file__)),
        'host_sha256':sha(FIXTURE/'host.py'),'clean_plugin_sha256':sha(FIXTURE/'plugin.py'),
        'profiles':PROFILES,'planned_faults':24,'planned_controls':24,'planned_processes':96,
        'basis':'SYNTHETIC_TASK_CONTRACT','not_held_out':True,'model_calls':0,
        'controls':'Each fault has its own unmutated counterpart. Trigger specificity uses restored WITH so direct use is retained.',
        'no_post_outcome_detector_tuning':True,'operator_training_and_alias_order_preferences_are_not_defects':True}
    write_json(root/'protocol.lock.json',frozen)
    pin=sha(root/'protocol.lock.json'); (root/'protocol.sha256').write_text(pin+'\n',encoding='ascii')
    rows=[]
    for case in cases:
        before,a=run_phase(root,case,'before'); after,b=run_phase(root,case,'after'); rows.extend(a+b)
        home=root/'cases'/case['id']
        compare_native_repair(home/'before/capture',before,home/'after/capture',after,home/'repair-comparison')
        write_json(root/'partial-results.json',rows)
        print(case['id']+' executed, collected, diagnosed and restored',flush=True)
    if sha(root/'protocol.lock.json')!=pin or any(sha(ROOT/p)!=digest for p,digest in pvl_hashes.items()):
        raise RuntimeError('Frozen detector or protocol changed during validation')
    result={'format':'pvl-detection-validity-1','protocol_sha256':pin,'summary':summarize(rows),'runs':rows,
        'observed_processes':96,'defect_cases':24,'unique_control_cases':24,'restored_cases':24,
        'model_calls':0,'provider_cost_usd':0,'scientific_population_accuracy':None,'independent_adjudication':False,
        'natural_model_trigger_rate':None,'external_adoption':None,'source_files_unchanged':True,
        'localization_ceiling':'Named failing contract, trigger evidence gap or observed backend identity. No automatic faulty-line localization.'}
    write_json(root/'results.json',result)
    checksums={p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
    write_json(root/'SHA256SUMS.json',checksums)
    print(json.dumps({'output':str(root),'protocol_sha256':pin,'summary':result['summary']},ensure_ascii=False,indent=2))


if __name__=='__main__': main()
