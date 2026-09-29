import hashlib
import json
import unittest

from value_lab.trace_diagnostics import artifact_lineage


class TraceDiagnosticsTests(unittest.TestCase):
    def trace(self, middle, terminal=True):
        rows = [{'type': 'system', 'subtype': 'init', 'cwd': '/work', 'session_id': 's'}, *middle]
        if terminal:
            rows.append({'type': 'result', 'session_id': 's'})
        return '\n'.join(json.dumps(x) for x in rows)

    def call(self, name='Write', key='w', **arg):
        return {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': key, 'name': name,
            'input': arg or {'file_path': '/work/result.csv', 'content': 'bad\n'}}]}}

    def reply(self, key='w', error=False):
        return {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': key, 'is_error': error}]}}

    def evaluate(self, rows, terminal=True):
        return artifact_lineage(self.trace(rows, terminal), 'events.jsonl', 'result.csv',
            {'path': 'result.csv', 'sha256': hashlib.sha256(b'bad\n').hexdigest()}, session_id='s')

    def test_direct_writer_and_no_inferred_skill(self):
        r = self.evaluate([self.call('Skill', 'skill', skill='plugin:analyze'), self.reply('skill'), self.call(), self.reply()])
        self.assertEqual(r['level'], 'L2.5')
        self.assertEqual(r['skill']['status'], 'UNKNOWN')
        self.assertIsNone(r['source_line'])

    def test_explicit_parent_only(self):
        call = self.call()
        call['parent_tool_use_id'] = 'skill'
        r = self.evaluate([self.call('Skill', 'skill', skill='plugin:analyze'), self.reply('skill'), call, self.reply()])
        self.assertEqual(r['skill']['status'], 'EXPLICIT_PARENT_OBSERVED')

    def test_read_is_never_write(self):
        self.assertEqual(self.evaluate([self.call('Read'), self.reply()])['status'], 'UNKNOWN')

    def test_failed_missing_duplicated_results_unknown(self):
        for rows in ([self.call(), self.reply(error=True)], [self.call()], [self.call(), self.reply(), self.reply()]):
            self.assertEqual(self.evaluate(rows)['status'], 'UNKNOWN')

    def test_later_mutation_blocks_final_writer(self):
        for later in (self.call('Bash', 'b', command='some command'), self.call('Edit', 'e', file_path='/work/result.csv')):
            self.assertEqual(self.evaluate([self.call(), self.reply(), later])['status'], 'UNKNOWN')

    def test_other_path_is_not_a_blocker_or_a_match(self):
        self.assertEqual(self.evaluate([self.call(file_path='/else/result.csv', content='bad\n'), self.reply()])['status'], 'UNKNOWN')
        self.assertEqual(self.evaluate([self.call(), self.reply(), self.call(key='x', file_path='/work/other', content='x'), self.reply('x')])['level'], 'L2.5')

    def test_incomplete_mixed_session_and_byte_mismatch(self):
        self.assertEqual(self.evaluate([self.call(), self.reply()], terminal=False)['status'], 'UNKNOWN')
        call = self.call()
        call['session_id'] = 'other'
        self.assertEqual(self.evaluate([call, self.reply()])['status'], 'UNKNOWN')
        self.assertEqual(self.evaluate([self.call(content='bad\r\n', file_path='/work/result.csv'), self.reply()])['status'], 'UNKNOWN')

    def test_wrong_write_after_matching_write_unknown(self):
        self.assertEqual(self.evaluate([self.call(), self.reply(), self.call(key='x', content='new', file_path='/work/result.csv'), self.reply('x')])['status'], 'UNKNOWN')

    def test_read_after_write_does_not_make_a_producer(self):
        r = self.evaluate([self.call(), self.reply(), self.call('Read', 'r', file_path='/work/result.csv'), self.reply('r')])
        self.assertEqual(r['producer']['tool_use_id'], 'w')


if __name__ == '__main__':
    unittest.main()
