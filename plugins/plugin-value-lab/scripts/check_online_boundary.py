"""Real Linux kernel + loopback/pipe broker acceptance; no actual LLM calls."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import write_json
from value_lab.online_sandbox import BRIDGE, ModelGateway, clean_environment, probe_backend, run_exchange, sandbox_command

CHILD = r'''
import ctypes,json,os,pathlib,socket,subprocess,sys,urllib.request
settings=json.loads(pathlib.Path(sys.argv[1]).read_text())
checks={}
for name,path in settings['hidden'].items():
    denied=[]
    for mode in ('rb','r+b'):
        try:
            with open(path,mode): pass
            denied.append(False)
        except OSError: denied.append(True)
    try:
        fd=os.open(path,os.O_RDONLY); os.close(fd); denied.append(False)
    except OSError: denied.append(True)
    libc=ctypes.CDLL(None); fd=libc.open(path.encode(),0)
    denied.append(fd<0)
    if fd>=0: os.close(fd)
    denied.append(subprocess.run(['/bin/cat',path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0)
    alias='/tmp/alias-'+name; os.symlink(path,alias)
    try:
        pathlib.Path(alias).read_bytes(); denied.append(False)
    except OSError: denied.append(True)
    checks[name]=all(denied)
checks['credential_and_host_env_absent']='PVL_MODEL_API_KEY' not in os.environ and 'PVL_BOUNDARY_CANARY' not in os.environ
checks['sdk_key_is_placeholder']=os.environ['ANTHROPIC_API_KEY']=='pvl-broker-placeholder-not-a-credential'
checks['host_loopback_denied']=False
try:
    with socket.create_connection(('127.0.0.1',settings['host_port']),.3): pass
except OSError: checks['host_loopback_denied']=True
checks['unshared_net_ns']=os.stat('/proc/self/ns/net').st_ino!=settings['parent_net_ns']
checks['only_loopback']={line.split(':',1)[0].strip() for line in pathlib.Path('/proc/net/dev').read_text().splitlines() if ':' in line}=={'lo'}
checks['no_wsl_interop']=not pathlib.Path('/init').exists() and not pathlib.Path('/run/WSL').exists()
try:
    pathlib.Path(sys.argv[1]).write_text('changed'); checks['public_input_readonly']=False
except OSError: checks['public_input_readonly']=True
body=json.dumps({'model':'fixture-model','max_tokens':8,'messages':[{'role':'user','content':'manufactured boundary probe'}]}).encode()
response=json.load(urllib.request.urlopen(urllib.request.Request(os.environ['ANTHROPIC_BASE_URL']+'/v1/messages',data=body,headers={'content-type':'application/json'}),timeout=5))
checks['model_rpc_roundtrip']=response=={'fixture':'provider-response'}
pathlib.Path(sys.argv[2]).write_text(json.dumps(checks))
print(json.dumps(checks),flush=True)
sys.exit(0 if all(checks.values()) else 2)
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    if sys.platform != 'linux' or not shutil.which('bwrap'):
        raise SystemExit('Required Linux kernel backend unavailable; no skip or emulation')
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    for name in ('plugin', 'runtime', 'control', 'native', 'retained', 'private'):
        (root / name).mkdir()
    secret = root / 'private' / 'reference.json'
    secret.write_text('PRIVATE_REFERENCE_CANARY')
    credential = root / 'private' / 'credentials.json'
    credential.write_text('PRIVATE_CREDENTIAL_CANARY')
    extra = root / 'undisclosed-host-copy.txt'
    extra.write_text('HOST_COPY_CANARY')
    cli = root / 'runtime/claude'
    cli.write_text('#!/usr/bin/python3\nprint("2.1.278 (Claude Code)")\n')
    cli.chmod(0o755)
    shutil.copyfile(BRIDGE, root / 'control/model_bridge.py')
    (root / 'plugin/probe.py').write_text(CHILD, encoding='utf-8')
    config = {'format': 'pvl-online-sandbox-1', 'backend': 'bubblewrap', 'runtime': str(root / 'runtime'),
              'executable': 'claude', 'gateway': {'endpoint': 'https://api.example.com', 'models': ['fixture-model'],
                  'api_key_env': 'PVL_MODEL_API_KEY', 'max_requests': 1, 'max_output_tokens': 8, 'request_timeout_seconds': 5}}
    os.environ['PVL_BOUNDARY_CANARY'] = 'must-not-inherit'
    os.environ['PVL_MODEL_API_KEY'] = 'SYNTHETIC-PARENT-ONLY-KEY'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen()
        settings = {'host_port': listener.getsockname()[1], 'parent_net_ns': os.stat('/proc/self/ns/net').st_ino,
                    'hidden': {'reference': str(secret), 'credential': str(credential), 'unlisted_copy': str(extra),
                        'parent_proc': '/proc/'+str(os.getpid())+'/root'+str(secret), 'etc_passwd': '/etc/passwd'}}
        write_json(root / 'plugin/settings.json', settings)
        # Positive control: all host files actually exist, rather than passing
        # denial tests against nonexistent names. Parent socket is also usable.
        assert all(Path(p).is_file() for p in settings['hidden'].values())
        with socket.create_connection(listener.getsockname(), 1):
            peer, _ = listener.accept(); peer.close()
        preflight = probe_backend(config, root / 'plugin', root, root / 'control', shutil.which('bwrap'), [secret, credential, extra])
        def transport(path, body, beta, timeout):
            assert path == '/v1/messages'
            assert json.loads(body)['messages'][0]['content'] == 'manufactured boundary probe'
            with socket.create_connection(listener.getsockname(), 1):
                peer, _ = listener.accept(); peer.close()
            return 200, 'application/json', b'{"fixture":"provider-response"}'
        gateway = ModelGateway(config['gateway'], os.environ['PVL_MODEL_API_KEY'], transport)
        spec = {'argv': ['/usr/bin/python3', '-I', str(root / 'plugin/probe.py'), str(root / 'plugin/settings.json'), str(root / 'native/checks.json')],
                'plugin': str(root / 'plugin'), 'retained': str(root / 'retained'), 'path': '/runtime:/usr/bin:/bin'}
        argv = sandbox_command(config, root / 'plugin', root, root / 'control',
            ['/usr/bin/python3', '-I', '/pvl-control/model_bridge.py', '--run', json.dumps(spec)], shutil.which('bwrap'))
        result = run_exchange(argv, clean_environment(root), root, root / 'process', gateway, 15)
    checks = json.loads((root / 'native/checks.json').read_text()) if (root / 'native/checks.json').exists() else {}
    success = result['status'] == 'COMPLETED' and bool(checks) and all(checks.values())
    receipt = {'status': 'PASS' if success else 'FAIL', 'platform': sys.platform, 'preflight': preflight, 'checks': checks,
               'process': result, 'real_kernel': True, 'fixture_native_cli': True, 'provider_transport': 'LOCAL_FIXTURE',
               'real_model_calls': 0, 'windows_hyperv_verified': False, 'independent_security_audit': False}
    write_json(root / 'acceptance.json', receipt)
    print(json.dumps(receipt, ensure_ascii=True, indent=2))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
