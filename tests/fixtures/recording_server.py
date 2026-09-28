"""Real stdio fixture server; calculations are synthetic and have no external calls."""
import json
import sys
import time

for line in sys.stdin:
    request = json.loads(line)
    method, identity = request.get('method'), request.get('id')
    if identity is None:
        continue
    if method == 'initialize':
        requested = request['params']['protocolVersion']
        negotiated = requested
        response = {'result': {'protocolVersion': negotiated,
                    'capabilities': {'tools': {}}, 'serverInfo': {'name': 'synthetic-recording-fixture', 'version': '1'}}}
    elif method == 'tools/list':
        response = {'result': {'tools': [{'name': 'matrix_sum', 'inputSchema': {'type': 'object',
                    'properties': {'values': {'type': 'array', 'items': {'type': 'number'}}}}}]}}
    elif method == 'tools/call':
        arguments = request['params']['arguments']
        mode = arguments.get('mode')
        if mode == 'hang':
            time.sleep(60)
        if mode == 'crash':
            raise SystemExit(1)
        if mode == 'protocol_error':
            response = {'error': {'code': -32602, 'message': 'Synthetic bad input'}}
        else:
            result = {'sum': sum(arguments.get('values', [])), 'synthetic': True}
            if mode == 'secret':
                result['api_key'] = 'fixture-secret-must-not-persist'
            response = {'result': {'content': [{'type': 'text', 'text': json.dumps(result)}],
                                   'structuredContent': result, 'isError': mode == 'tool_error'}}
    else:
        response = {'error': {'code': -32601, 'message': 'Unsupported'}}
    print(json.dumps({'jsonrpc': '2.0', 'id': identity, **response}), flush=True)
