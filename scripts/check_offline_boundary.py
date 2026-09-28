"""Real Linux/WSL kernel acceptance. No skips, no backend/model/network service."""
import argparse
import json
import os
from pathlib import Path
import platform
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import load_json, write_json
from value_lab.native_session import run_offline
from value_lab.replay import record_tools

PROBE = r'''
import ctypes,json,os,pathlib,socket,subprocess,sys
config=json.loads(pathlib.Path('/inputs/probe.json').read_text())
rows={}
for name,path in config['hidden'].items():
    probes=[]
    try:
        with open(path,'rb'): pass
        probes.append(False)
    except OSError: probes.append(True)
    try:
        fd=os.open(path,os.O_RDONLY); os.close(fd); probes.append(False)
    except OSError: probes.append(True)
    libc=ctypes.CDLL(None)
    fd=libc.open(path.encode(),0)
    probes.append(fd<0)
    if fd>=0: os.close(fd)
    result=subprocess.run(['/bin/cat','--',path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    probes.append(result.returncode!=0)
    alias='/tmp/link-'+name
    os.symlink(path,alias)
    try:
        with open(alias,'rb'): pass
        probes.append(False)
    except OSError: probes.append(True)
    rows[name]=all(probes)
rows['environment_cleared']='PVL_BOUNDARY_CANARY' not in os.environ
rows['wsl_interop_hidden']=not pathlib.Path('/init').exists() and not pathlib.Path('/mnt/c').exists()
rows['private_runtime_dirs_hidden']=not pathlib.Path('/run').exists() and not pathlib.Path('/home').exists()
rows['only_loopback_interface']={name for _,name in socket.if_nameindex()}=={'lo'}
with socket.socket() as s:
    s.settimeout(.5)
    rows['host_loopback_denied']=s.connect_ex(('127.0.0.1',config['port']))!=0
with socket.socket(socket.AF_UNIX) as s:
    try: s.connect(config['unix']); rows['host_unix_denied']=False
    except OSError: rows['host_unix_denied']=True
rows['no_default_route']=not any(line.split()[1]=='00000000' for line in pathlib.Path('/proc/net/route').read_text().splitlines()[1:])
rows['fresh_pid_namespace']=os.getpid()<20
try: pathlib.Path('/inputs/probe.json').write_text('bad'); rows['inputs_read_only']=False
except OSError: rows['inputs_read_only']=True
pathlib.Path('/output/probe-result.json').write_text(json.dumps(rows))
sys.exit(0 if all(rows.values()) else 1)
'''

CLIENT = r'''
import json,pathlib,sys
assert not pathlib.Path('/inputs/.replay').exists()
def request(i,method,params):
    print(json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':params}),flush=True)
    answer=json.loads(sys.stdin.readline())
    assert answer['id']==i
    return answer
request('init','initialize',{'protocolVersion':'2025-06-18'})
print(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'}),flush=True)
assert request('list','tools/list',{})['result']['tools'][0]['name']=='pseudobulk_summary'
answers=[]
for i,mode in enumerate(('success','tool_failure','protocol_failure')):
    answers.append(request(i,'tools/call',{'name':'pseudobulk_summary','arguments':{'fixture':mode}}))
assert answers[0]['result']['structuredContent']['value']==0
assert answers[1]['result']['isError'] is True
assert answers[2]['error']['code']==-32602
pathlib.Path('/output/replayed.json').write_text(json.dumps(answers))
'''


def check(output):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    public, private = root / 'public', root / 'private'
    public.mkdir()
    private.mkdir()
    secret = private / 'reference with spaces\nand newline.txt'
    secret.write_text('Manufactured secret canary; not a scientific answer key.', encoding='utf-8')
    (public / 'probe.py').write_text(PROBE, encoding='utf-8')
    (public / 'client.py').write_text(CLIENT, encoding='utf-8')
    (public / 'timeout.py').write_text('import time; time.sleep(20)\n')
    (public / 'malformed.py').write_text("print('not-json',flush=True)\n")
    (public / 'mismatch.py').write_text(CLIENT.replace("('success','tool_failure','protocol_failure')", "('unexpected','tool_failure','protocol_failure')"))
    (public / 'incomplete.py').write_text("pass\n")
    (public / 'unread.py').write_text("import json,sys,time\nprint(json.dumps({'jsonrpc':'2.0','id':'init','method':'initialize','params':{'protocolVersion':'2025-06-18'}}),flush=True)\njson.loads(sys.stdin.readline())\nprint(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'}),flush=True)\nprint(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list'}),flush=True)\ntime.sleep(20)\n")
    tools = [{'name': 'pseudobulk_summary', 'inputSchema': {'type': 'object'},
              'description': 'Manufactured cassette; PyDESeq2 was NOT run'}]
    responses = [
        {'result': {'content': [{'type': 'text', 'text': 'manufactured zero'}], 'structuredContent': {'value': 0}, 'isError': False}},
        {'result': {'content': [{'type': 'text', 'text': 'recorded failure'}], 'isError': True}},
        {'error': {'code': -32602, 'message': 'recorded argument error'}}]
    exchanges = [{'request': {'name': 'pseudobulk_summary', 'arguments': {'fixture': mode}}, 'response': response}
                 for mode, response in zip(('success', 'tool_failure', 'protocol_failure'), responses)]
    cassette = private / '.replay'
    pin = record_tools(cassette, tools, exchanges, provenance={'origin': 'manufactured',
        'description': 'Offline software gate; no real scientific computation'})['cassette_sha256']
    old = os.environ.get('PVL_BOUNDARY_CANARY')
    os.environ['PVL_BOUNDARY_CANARY'] = 'must-not-inherit'
    # Sockets exist outside the sandbox; connecting to these performs no external I/O.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='pvl-socket-') as sockets, socket.socket() as host, socket.socket(socket.AF_UNIX) as unix:
        host.bind(('127.0.0.1', 0))
        host.listen()
        unix_path = str(Path(sockets) / 'canary.sock')
        unix.bind(unix_path)
        unix.listen()
        write_json(public / 'probe.json', {'hidden': {'direct': str(secret),
            'parent_proc': f'/proc/{os.getpid()}/root{secret}', 'cassette': str(cassette / 'cassette.json')},
            'port': host.getsockname()[1], 'unix': unix_path})
        try:
            boundary = run_offline(public, ['probe.py', 'probe.json'], ['/usr/bin/python3', '-I', '/inputs/probe.py'], root / 'boundary')
        finally:
            if old is None:
                os.environ.pop('PVL_BOUNDARY_CANARY', None)
            else:
                os.environ['PVL_BOUNDARY_CANARY'] = old
    if boundary['status'] != 'COMPLETED':
        raise RuntimeError('Real isolation unavailable/failed; inspect boundary logs, no skip or fallback')
    observations = load_json(root / 'boundary/artifacts/probe-result.json')
    if not all(observations.values()):
        raise AssertionError(observations)
    runs = []
    for i in range(2):
        run = run_offline(public, ['client.py'], ['/usr/bin/python3', '-I', '/inputs/client.py'], root / f'replay-{i}',
                          cassette=cassette, expected_id=pin)
        assert run['status'] == 'COMPLETED', run
        runs.append((root / f'replay-{i}/artifacts/replayed.json').read_bytes())
    assert runs[0] == runs[1]
    failures = {}
    for name in ('timeout', 'malformed', 'mismatch', 'incomplete'):
        result = run_offline(public, [name + '.py'], ['/usr/bin/python3', '-I', '/inputs/' + name + '.py'], root / name,
                             cassette=cassette, expected_id=pin, timeout_seconds=1)
        assert result['status'] == 'FAILED', result
        failures[name] = result
    # A full pipe must not pin the broker forever when a child refuses to read.
    tools[0]['description'] = 'x' * 100000
    large = private / 'large-cassette'
    large_pin = record_tools(large, tools, exchanges, provenance={'origin': 'manufactured', 'description': 'Pipe deadline test'})['cassette_sha256']
    result = run_offline(public, ['unread.py'], ['/usr/bin/python3', '-I', '/inputs/unread.py'], root / 'unread',
                         cassette=large, expected_id=large_pin, timeout_seconds=1)
    assert result['status'] == 'FAILED' and 'response timed out' in result['error'], result
    failures['unread_pipe'] = result
    receipt = {'status': 'PASS', 'kernel': platform.release(), 'python': platform.python_version(),
               'boundary_checks': observations, 'repeat_replay_bytes_identical': True,
               'expected_failures': list(failures), 'model_calls': 0, 'backend_calls': 0,
               'scientific_execution': False, 'new_observations': 0,
               'scope': 'Manufactured local kernel and protocol acceptance; not independent security review'}
    write_json(root / 'acceptance.json', receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.output), ensure_ascii=True))
