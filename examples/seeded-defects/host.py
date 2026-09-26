"""Controlled LOCAL host, not an LLM or authenticated Claude/Codex host.

Observe actual function calls with Python profiling and emit a compatible event
transport for exercising PVL's production collector. Event roles are adapters,
not assertions that a model or Bash generated them. Only our reviewed fixture is
executed; the PVL collector never executes submitted artifacts.
"""
import importlib.util
import json
from pathlib import Path
import sys


def main():
    task = json.loads(Path('input.json').read_text(encoding='utf-8'))
    metadata = json.loads(Path('host-context.json').read_text(encoding='utf-8'))
    source = Path('analysis.py').resolve()
    calls = []
    accesses = []
    resources = {'reference-data.json': 'training', 'evaluation-labels.json': 'evaluation_labels',
                 'evaluation-features.json': 'evaluation_features'}

    def audit(event, args):
        if event != 'open' or not args or not isinstance(args[0], str):
            return
        opened = Path(args[0]).resolve()
        if opened.parent != source.parent or opened.name not in resources:
            return
        forbidden = resources[opened.name] != 'training'
        denied = forbidden and metadata.get('deny_evaluation') is True
        accesses.append({'resource': opened.name, 'operation': 'open_attempt', 'denied': denied})
        if denied:
            raise PermissionError('Controlled intervention denied evaluation resource')

    # Reviewed fixture only: an in-process hook is not an adversarial OS sandbox.
    sys.addaudithook(audit)

    def observe(frame, event, arg):
        if event == 'call' and Path(frame.f_code.co_filename).resolve() == source:
            calls.append(frame.f_code.co_name)

    spec = importlib.util.spec_from_file_location('seed_plugin', source)
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    sys.setprofile(observe)
    route = plugin.dispatch(task)
    events = [{'type': 'system', 'subtype': 'init', 'session_id': metadata['session_id'],
               'model': 'deterministic-no-model', 'claude_code_version': 'seed-host-1',
               'tools': ['Read', 'Skill', 'Write', 'Bash'],
               'plugins': [{'name': 'pvl-seed'}] if metadata['arm'] == 'with' else []}]
    if metadata['arm'] == 'with' and route not in ('', 'direct'):
        events.extend([
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Skill',
                'id': 'skill1', 'input': {'skill': 'pvl-seed:analyze' if route == 'error' else route}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'skill1',
                'is_error': route == 'error', 'content': 'Controlled local routing observation'}]}}])
    elif metadata['arm'] == 'with' and route == 'direct':
        events.extend([
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read',
                'id': 'read1', 'input': {'file_path': 'analysis.py'}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'read1',
                'is_error': False, 'content': source.read_text(encoding='utf-8')}]}}])
    completed = False
    try:
        if task['family'] == 'trigger' and route in ('', 'error', 'pvl-seed:other'):
            # A working host fallback masks the output consequence of bad routing.
            Path('result.json').write_text('{"ok":true}', encoding='utf-8')
        else:
            plugin.analyze(task)
        completed = True
    finally:
        sys.setprofile(None)
        Path('access-observation.json').write_text(json.dumps({
            'session_id': metadata['session_id'], 'collector': 'reviewed-seed-host-python-audit',
            'coverage': 'declared resources in reviewed Python fixture only',
            'events': accesses, 'observation_complete': completed, 'deny_evaluation': metadata.get('deny_evaluation', False),
            'os_isolation': False, 'authenticated_collector': False}), encoding='utf-8')
    events.extend([
        {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash',
            'id': 'execution1', 'input': {'command': 'python -I host.py'}}]}},
        {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'execution1',
            'is_error': False, 'content': 'Reviewed local fixture executed; synthetic transport only'}]}},
        {'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': metadata['session_id'],
         'result': 'SYNTHETIC_LOCAL_HOST; no model request'}])
    Path('events.jsonl').write_text('\n'.join(json.dumps(e) for e in events)+'\n', encoding='utf-8')
    Path('host-observation.json').write_text(json.dumps({'calls': calls, 'route': route,
        'source_sha256': __import__('hashlib').sha256(source.read_bytes()).hexdigest(),
        'scope': 'Synthetic controlled host with actual local fixture execution'}), encoding='utf-8')


if __name__ == '__main__':
    main()
