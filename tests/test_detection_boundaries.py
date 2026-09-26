"""Known counterexamples must be separated from their legal paired controls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from value_lab.artifacts import grade_artifact, sha, validate_verifier
from value_lab.core import ValidationError, demo_suite, freeze, suite_digest, write_json
from value_lab.native_hypotheses import plugin_observations, skill_events
from value_lab.science import cluster_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from validate_seeded_defects import assess_access, freeze_case, run_phase, access_intervention, FIXTURE


class DetectionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def rule(self, kind, spec):
        g = {'id':'boundary','type':kind,'artifact':'result','dimension':'outcome','critical':True,'weight':1,'verifier':spec}
        validate_verifier(g)
        return g

    def grade(self, rule, content, suffix='.json'):
        path=self.root/('result'+suffix)
        path.write_text(content,encoding='utf-8')
        return grade_artifact(rule,{'artifacts':{'result':{'path':path.name,'sha256':sha(path)}}},self.root,self.root)

    def labels(self):
        return {'kind':'labels','id_column':'id','label_column':'label','expected':{'a':'T','b':'B'},
                'aliases':{'T':['T cell'],'B':['B cell']}}

    def test_aliases_preserve_semantics_and_exact_entity_coverage(self):
        rule=self.rule('artifact',self.labels())
        self.assertTrue(self.grade(rule,'id,label\nb,B cell\na,T cell','.csv')[0])
        for rows in ('a,B cell\nb,T cell','a,T cell','a,T cell\na,T cell\nb,B cell','a,T unknown\nb,B'):
            self.assertFalse(self.grade(rule,'id,label\n'+rows,'.csv')[0])

    def test_ambiguous_aliases_and_canonical_redefinition_rejected(self):
        for aliases in ({'T':['B']},{'T':['same'],'B':['same']},{'other':['x']},{'T':['x','x']},{'T':['']}):
            spec=self.labels(); spec['aliases']=aliases
            with self.assertRaises(ValidationError): self.rule('artifact',spec)

    def test_legacy_exact_labels_remain_exact_and_ari_remains_permutation_invariant(self):
        spec=self.labels(); del spec['aliases']
        self.assertFalse(self.grade(self.rule('artifact',spec),'id,label\na,T cell\nb,B cell','.csv')[0])
        self.assertEqual(cluster_score(['T','T','B','B'],['B','B','T','T'],'ari'),1)

    def test_alias_mapping_is_part_of_frozen_suite_identity(self):
        suite=demo_suite(); suite['cases'][0]['graders']=[self.rule('artifact',self.labels())]
        lock=freeze(suite,self.root/'lock.json')
        before=suite_digest(suite)
        suite['cases'][0]['graders'][0]['verifier']['aliases']['T'].append('new alias')
        self.assertNotEqual(before,suite_digest(suite))
        self.assertEqual(lock['suite_sha256'],before)

    def test_set_identity_order_is_explicit_duplicates_are_not_hidden(self):
        spec={'kind':'json_fields','expected':{'ids':['a','b']},'unordered_paths':['ids']}
        rule=self.rule('artifact',spec)
        self.assertTrue(self.grade(rule,'{"ids":["b","a"]}')[0])
        for obj in ({'ids':['a','a','b']},{'ids':['a']},{'ids':['a','eval']},{'ids':'ab'}):
            self.assertFalse(self.grade(rule,json.dumps(obj))[0])
        del spec['unordered_paths']
        self.assertFalse(self.grade(self.rule('artifact',spec),'{"ids":["b","a"]}')[0])

    def test_bad_set_contract_rejected(self):
        for values,paths in ((['a','a'],['ids']),([1,2],['ids']),(['a'],['missing']),(['a'],['ids','ids'])):
            with self.assertRaises(ValidationError):
                self.rule('artifact',{'kind':'json_fields','expected':{'ids':values},'unordered_paths':paths})

    def test_allow_empty_wrong_and_correct_answers_have_separate_axes(self):
        write_json(self.root/'truth.json',{'decision':'allow','rationale':'Known finite mean task'})
        decision=self.rule('over_refusal',{'truth':{'path':'truth.json','sha256':sha(self.root/'truth.json')}})
        delivery=self.rule('artifact_schema',{'format':'json','fields':{'answer':{'type':'number','nullable':False}},'allow_extra':True,'min_rows':1})
        correctness=self.rule('artifact',{'kind':'json_fields','expected':{'answer':0}})
        for answer,expected in ((None,(True,False,False)),('',(True,False,False)),(7,(True,True,False)),(0,(True,True,True))):
            content=json.dumps({'decision':'allow','answer':answer})
            grades=[self.grade(g,content) for g in (decision,delivery,correctness)]
            self.assertEqual(tuple(g[0] for g in grades),expected)
            self.assertFalse(grades[0][2]['task_success_established'])
            self.assertFalse(grades[0][2]['correctness_assessed'])

    def test_missing_decision_is_unknown_not_observed_refusal(self):
        write_json(self.root/'truth.json',{'decision':'allow','rationale':'Frozen rule'})
        rule=self.rule('over_refusal',{'truth':{'path':'truth.json','sha256':sha(self.root/'truth.json')}})
        for content in ('{}','{"decision":"maybe"}','{"decision":null}'):
            passed,_,receipt=self.grade(rule,content)
            self.assertIsNone(passed); self.assertIsNone(receipt['error'])

    def stream(self,content='candidate bytes',filename='analysis.py',error=False):
        return [{'type':'assistant','message':{'content':[{'type':'tool_use','name':'Read','id':'r',
                  'input':{'file_path':filename}}]}},
                {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'r','is_error':error,'content':content}]}},
                {'type':'result'}]

    def observe(self,events):
        return plugin_observations('\n'.join(json.dumps(e) for e in events),'trace.jsonl','plugin',
                                   {'analysis.py':hashlib.sha256(b'candidate bytes').hexdigest()})

    def test_read_is_exposure_evidence_without_execution_or_skill_claim(self):
        result=self.observe(self.stream())
        self.assertEqual(result['status'],'CANDIDATE_CONTENT_READ')
        self.assertFalse(result['skill_mechanism_observed'])
        self.assertFalse(result['execution_established_by_read'])
        self.assertEqual(result['candidate_reads'][0]['result_evidence']['line'],2)

    def test_failed_truncated_wrong_bytes_wrong_path_and_late_reads_unknown(self):
        stream=self.stream()
        for events in (self.stream(error=True),self.stream(content='wrong'),self.stream(filename='other.py'),
                       stream[:1], [stream[0],stream[2],stream[1]], [stream[0],stream[1],stream[1],stream[2]]):
            self.assertEqual(self.observe(events)['status'],'USE_UNKNOWN')

    def test_tool_id_collision_across_mechanisms_stays_unknown(self):
        events=self.stream()
        events.insert(1,{'type':'assistant','message':{'content':[{'type':'tool_use','id':'r','name':'Skill','input':{'skill':'plugin:go'}}]}})
        self.assertEqual(self.observe(events)['status'],'USE_UNKNOWN')
        self.assertEqual(skill_events('\n'.join(map(json.dumps,events)),'trace')[0]['result_status'],'UNKNOWN')

    def test_access_missing_incomplete_and_session_mismatch_remain_unknown(self):
        policy={'train':'allowed','test':'forbidden'}
        obs={'session_id':'s','collector':'reviewed-seed-host-python-audit',
             'coverage':'declared resources in reviewed Python fixture only','events':[], 'observation_complete':True}
        self.assertTrue(assess_access(obs,'s',policy)['passed'])
        for bad in ({},dict(obs,session_id='other'),dict(obs,observation_complete=False),dict(obs,events=[{'resource':'unknown'}])):
            self.assertIsNone(assess_access(bad,'s',policy)['passed'])
        obs['events']=[{'resource':'test','operation':'open_attempt','denied':True}]
        result=assess_access(obs,'s',policy)
        self.assertFalse(result['passed']); self.assertFalse(result['leakage_established'])

    def test_hidden_feature_access_and_deny_intervention_keep_clean_control(self):
        case=freeze_case(self.root,'reference-leakage',2,(FIXTURE/'plugin.py').read_text(encoding='utf-8'))
        _,rows=run_phase(self.root,case,'before')
        tested=[r for r in rows if r['profile']=='configured_workflow']
        self.assertTrue(tested[0]['alert'])
        self.assertFalse(tested[0]['without_access_alert'])
        self.assertFalse(tested[1]['alert'])
        intervention=access_intervention(self.root,case)
        self.assertNotEqual(intervention[0]['returncode'],0)
        self.assertEqual(intervention[1]['returncode'],0)
        self.assertTrue(intervention[1]['same_output'])
        self.assertTrue(all(r['same_input'] and r['same_source'] for r in intervention))


if __name__=='__main__': unittest.main()
