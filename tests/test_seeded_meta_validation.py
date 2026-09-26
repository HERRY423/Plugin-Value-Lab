"""Protect honest denominators and distinguish baseline alarm from seed detection."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from report_seeded_defects import metrics


class SeededMetaValidationTests(unittest.TestCase):
    def test_repeated_negative_does_not_dilute_false_positive_rate(self):
        defects=[{'id':str(i),'alert':True} for i in range(3)]
        controls=[{'id':'0','alert':False,'control_identity':'same-normal'},
                  {'id':'1','alert':False,'control_identity':'same-normal'},
                  {'id':'2','alert':True,'control_identity':'valid-alias'}]
        result=metrics(defects,controls)
        self.assertEqual(result['distinct_controls'],2)
        self.assertEqual(result['false_positive_rate'],.5)
        self.assertEqual(result['paired_specific_detections'],2)

    def test_unknown_retained_in_planned_denominator(self):
        result=metrics([{'id':'a','alert':True},{'id':'b','alert':None}],
                       [{'id':'a','alert':False,'control_identity':'a'},
                        {'id':'b','alert':None,'control_identity':'b'}])
        self.assertIsNone(result['detection_rate'])
        self.assertIsNone(result['false_positive_rate'])
        self.assertEqual(result['detection_bounds'],[.5,1.])
        self.assertEqual(result['false_positive_bounds'],[0.,.5])

    def test_preexisting_control_alarm_is_not_specific_seed_detection(self):
        result=metrics([{'id':'a','alert':True}],[{'id':'a','alert':True,'control_identity':'a'}])
        self.assertEqual(result['TP'],1)
        self.assertEqual(result['FP'],1)
        self.assertEqual(result['paired_specific_detections'],0)

    def test_inconsistent_duplicate_control_is_not_silently_overwritten(self):
        with self.assertRaisesRegex(ValueError,'inconsistent'):
            metrics([{'id':'a','alert':True}],
                    [{'id':'a','alert':True,'control_identity':'same'},
                     {'id':'b','alert':False,'control_identity':'same'}])


if __name__=='__main__': unittest.main()
