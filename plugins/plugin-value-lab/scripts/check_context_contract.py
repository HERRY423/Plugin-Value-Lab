"""Offline synthetic qualification of bounded parsing beyond the old file limit."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.context_stream import capture_incremental, qualification, read_checkpoint
from value_lab.codex_context import capture, MAX_BYTES
from value_lab.core import ValidationError


def line(kind, payload):
    return (json.dumps({'type': kind, 'timestamp': '2026-10-02T09:00:00Z', 'payload': payload})+'\n').encode()


def run(output):
    output = Path(output)
    if output.exists():
        raise ValidationError('Preserve the original acceptance report')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pvl-context-qualification-', dir=output.parent) as directory:
        root = Path(directory)
        path = root/'synthetic.jsonl'
        usage = {'input_tokens':200,'output_tokens':10,'total_tokens':210}
        start = [line('session_meta', {'id':'synthetic-session','originator':'codex_work_desktop','cli_version':'0.159.2'}),
                 line('turn_context', {'turn_id':'synthetic-turn','model':'synthetic-model'})]
        def response(ident):
            return line('token_usage_record', {'session_id':'synthetic-session','thread_id':'synthetic-session',
                'turn_id':'synthetic-turn','root_turn_id':'synthetic-turn','response_id':ident,'usage':usage})+line('event_msg', {
                'type':'token_count','info':{'last_token_usage':usage,'model_context_window':1000}})
        with path.open('wb') as stream:
            stream.write(b''.join(start)+response('r1'))
            ignored = line('response_item', {'text':'SYNTHETIC-PRIVATE-CONTENT-'+'x'*16384})
            while stream.tell() <= 65*1024*1024:
                stream.write(ignored)
        source_bytes = path.stat().st_size
        try:
            capture(path, 'synthetic-session')
        except ValidationError:
            legacy_rejected = True
        else:
            raise AssertionError('Legacy cap unexpectedly relaxed')
        previous, batches = None, []
        for index in range(10):
            target = root/f'batch-{index}'
            result = capture_incremental(path, 'synthetic-session', target, previous=previous, max_new_bytes=32*1024*1024)
            report = result['report']
            batches.append({k:report[k] for k in ('new_bytes_parsed','prefix_bytes_rehashed','parser_events_processed','new_response_count','more_events_available')})
            previous = target
            if not report['more_events_available']:
                break
        assert sum(b['new_bytes_parsed'] for b in batches) == source_bytes
        assert sum(b['new_response_count'] for b in batches) == 1
        assert read_checkpoint(previous)[0]['offset'] == source_bytes
        with path.open('ab') as stream:
            addition = response('r2')
            stream.write(addition)
        target = root/'append'
        appended = capture_incremental(path, 'synthetic-session', target, previous=previous)['report']
        assert appended['new_response_ids'] == ['r2']
        assert appended['new_bytes_parsed'] == len(addition)
        assert appended['parser_events_processed'] == 2
        unchanged = capture_incremental(path, 'synthetic-session', root/'unchanged', previous=target)['report']
        assert unchanged['new_response_count'] == unchanged['parser_events_processed'] == 0
        for member in target.iterdir():
            assert b'SYNTHETIC-PRIVATE-CONTENT' not in member.read_bytes()
        record = {'format':'pvl-host-capability-qualification-1','status':'PASS','evidence':'SYNTHETIC_LOCAL_ONLY',
            'qualification':qualification(),'source_bytes_before_append':source_bytes,
            'legacy_limit_bytes':MAX_BYTES,'legacy_rejected_oversized_source':legacy_rejected,
            'incremental_batch_limit_bytes':32*1024*1024,'batches':batches,
            'append':{k:appended[k] for k in ('new_bytes_parsed','prefix_bytes_rehashed','parser_events_processed','new_response_ids','total_unique_response_ids')},
            'unchanged':{k:unchanged[k] for k in ('new_bytes_parsed','parser_events_processed','new_response_count')},
            'private_text_exported':False,'model_calls':0,'actual_paid_calls':0,'installed_host_acceptance':False,
            'source_sha256':{n:hashlib.sha256((ROOT/'value_lab'/n).read_bytes()).hexdigest() for n in ('codex_context.py','context_stream.py','host_capabilities.py')}}
    with output.open('x',encoding='utf-8') as stream:
        json.dump(record,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    result = run(parser.parse_args().output)
    print(json.dumps({'status':result['status'],'source_bytes':result['source_bytes_before_append'],
                      'batches':len(result['batches']),'model_calls':0},indent=2))
