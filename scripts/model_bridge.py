"""Runs INSIDE the networkless guest. No provider credentials or host imports.

Loopback HTTP adapts the native SDK to bounded pipe RPC. Provider SSE responses
are buffered by the controller, then forwarded unchanged; not a general proxy.
"""
import base64
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

LOCK = threading.Lock()
MAX_FRAME = 4 * 1024 * 1024


def emit(value):
    with LOCK:
        sys.stdout.write(json.dumps(value, ensure_ascii=True, allow_nan=False) + '\n')
        sys.stdout.flush()


def visible_tree_is_allowlisted(root, allowed):
    """Allow only mount roots and the empty directory scaffolding reaching them.

    A guest /home can exist because a selected /home/runner/... plugin is
    mounted there. Its existence alone does not expose the host's home tree.
    Never traverse an allowed mount's contents; reject every unlisted sibling,
    including hidden files and symlinks in the scaffolding.
    """
    root = Path(root)
    allowed = [Path(p) for p in allowed]
    if root.is_symlink():
        return False
    if not root.exists():
        return True
    if root in allowed:
        return True
    if not root.is_dir() or not any(p.is_relative_to(root) for p in allowed):
        return False
    try:
        return all(visible_tree_is_allowlisted(p, allowed) for p in root.iterdir())
    except OSError:
        return False


def probe(spec):
    checks = {}
    for i, name in enumerate(spec['targets']):
        try:
            with open(name, 'rb'):
                pass
            checks['private_' + str(i)] = False
        except OSError:
            checks['private_' + str(i)] = True
    checks['clean_environment'] = not any(k in os.environ for k in ('PVL_BOUNDARY_CANARY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'HTTP_PROXY', 'HTTPS_PROXY', 'WSL_INTEROP'))
    checks['no_direct_network'] = True
    for host in ('1.1.1.1', '169.254.169.254'):
        try:
            with socket.create_connection((host, 80), .2):
                checks['no_direct_network'] = False
        except OSError:
            pass
    if spec['windows']:
        # Backend additionally requires a Windows daemon, immutable Windows image
        # and Hyper-V + network=none; a TCP failure alone is not this guarantee.
        checks['native_windows_kernel'] = os.name == 'nt'
    else:
        devices = {line.split(':', 1)[0].strip() for line in Path('/proc/net/dev').read_text().splitlines() if ':' in line}
        checks['only_loopback'] = devices == {'lo'}
        checks['private_network_namespace'] = os.stat('/proc/self/ns/net').st_ino != spec['parent_net_ns']
        allowed = spec.get('allowed_mounts', [])
        checks['no_host_mounts'] = (not Path('/init').exists() and not Path('/run/WSL').exists()
            and '/home' not in allowed and visible_tree_is_allowlisted('/home', allowed))
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        server.listen()
        with socket.create_connection(server.getsockname(), 1):
            peer, _ = server.accept()
            peer.close()
    checks['guest_loopback_available'] = True
    version = subprocess.run([spec['executable'], '--version'], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
    checks['cli_starts'] = version.returncode == 0
    print(json.dumps({'checks': checks, 'version': version.stdout.strip(), 'model_calls': 0}))


def main(spec):
    class Handler(http.server.BaseHTTPRequestHandler):
        counter = 0
        def log_message(self, *args):
            pass
        def do_POST(self):
            # Single-threaded server, exactly one framed request in flight.
            try:
                if (self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1
                        or not self.headers['Content-Length'].isdigit()):
                    raise ValueError('fixed framing required')
                size = int(self.headers['Content-Length'])
                if not 0 < size <= 2 * 1024 * 1024:
                    raise ValueError('body limit')
                body = self.rfile.read(size)
                if len(body) != size:
                    raise ValueError('incomplete body')
                Handler.counter += 1
                rid = Handler.counter
                emit({'kind': 'request', 'id': rid, 'path': self.path,
                      'beta': self.headers.get('anthropic-beta', ''), 'body': base64.b64encode(body).decode('ascii')})
                def receive():
                    line = sys.stdin.buffer.readline(MAX_FRAME + 1)
                    if not line.endswith(b'\n') or len(line) > MAX_FRAME:
                        raise ValueError('invalid response framing')
                    frame = json.loads(line)
                    if frame.get('id') != rid:
                        raise ValueError('wrong response ID')
                    return frame
                header = receive()
                if header['kind'] != 'response' or not 0 <= header['length'] <= 8 * 1024 * 1024:
                    raise ValueError('response limit')
                self.send_response(header['status'])
                self.send_header('Content-Type', header['content_type'])
                self.send_header('Content-Length', str(header['length']))
                self.send_header('Connection', 'close')
                self.end_headers()
                received = 0
                while True:
                    frame = receive()
                    if frame['kind'] == 'end':
                        if received != header['length']:
                            raise ValueError('truncated response')
                        break
                    if frame['kind'] != 'data':
                        raise ValueError('unexpected frame')
                    data = base64.b64decode(frame['data'], validate=True)
                    received += len(data)
                    if received > header['length']:
                        raise ValueError('response overflow')
                    self.wfile.write(data)
                self.wfile.flush()
            except (ValueError, OSError, KeyError):
                # Controller kills the entire sandbox on protocol/provider failure.
                self.close_connection = True
        def do_CONNECT(self):
            self.send_error(403)
        def do_GET(self):
            self.send_error(403)
        def setup(self):
            super().setup()
            self.connection.settimeout(120)
    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    home = Path(spec['retained']) / 'host-home'
    home.mkdir(exist_ok=True)
    env = {'PATH': spec['path'], 'HOME': str(home), 'USERPROFILE': str(home), 'CLAUDE_CONFIG_DIR': str(home / '.claude'),
           'TMPDIR': spec['retained'], 'TMP': spec['retained'], 'TEMP': spec['retained'],
           'ANTHROPIC_BASE_URL': 'http://127.0.0.1:' + str(server.server_port),
           'ANTHROPIC_API_KEY': 'pvl-broker-placeholder-not-a-credential',
           'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1', 'DISABLE_AUTOUPDATER': '1', 'LANG': 'C.UTF-8'}
    if os.name == 'nt':
        env['SystemRoot'] = os.environ.get('SystemRoot', r'C:\Windows')
    process = subprocess.Popen(spec['argv'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env, cwd=spec['plugin'], shell=False, close_fds=True)
    def relay(pipe, stream):
        while True:
            chunk = pipe.read(32768)
            if not chunk:
                break
            emit({'kind': 'log', 'stream': stream, 'data': base64.b64encode(chunk).decode('ascii')})
    threads = [threading.Thread(target=relay, args=(pipe, stream), daemon=True) for pipe, stream in
               ((process.stdout, 'stdout'), (process.stderr, 'stderr'))]
    for thread in threads:
        thread.start()
    code = process.wait()
    for thread in threads:
        thread.join(timeout=2)
    server.shutdown()
    emit({'kind': 'exit', 'code': code})


if __name__ == '__main__':
    spec = json.loads(sys.argv[2])
    if sys.argv[1] == '--probe':
        probe(spec)
    elif sys.argv[1] == '--run':
        main(spec)
    else:
        raise SystemExit('Unknown bridge mode')
