"""File-producing event links, with explicit gaps rather than inferred causality."""
import hashlib
import json
import ntpath
import posixpath
from pathlib import Path

from .artifacts import confined, sha
from .core import ValidationError, load_json, suite_digest, write_json


def _path(value, cwd):
    if not isinstance(value, str) or not value or not isinstance(cwd, str) or not cwd:
        return None
    module = ntpath if ntpath.splitdrive(cwd)[0] else posixpath
    if '..' in value.replace('\\', '/').split('/'):
        return None
    return module.normcase(module.normpath(value if module.isabs(value) else module.join(cwd, value)))


def artifact_lineage(text, event_path, workspace_path, artifact, *, cwd=None, session_id=None):
    """Observe a Write and its result matching retained bytes; never parse shell prose.

    This is an exported-event assertion, not an authenticated filesystem monitor.
    Unknown later mutators prevent assigning the final producer. Read is not write.
    """
    from .native_hypotheses import _tool_events
    result = {'status': 'UNKNOWN', 'level': 'L2', 'artifact': artifact,
              'workspace_path': workspace_path, 'producer': None, 'write_attempts': [],
              'skill': {'status': 'UNKNOWN', 'call': None}, 'observed_skill_calls': [],
              'source_line': None, 'cause_established': False,
              'scope': 'Operator-supplied host events; no source-code root cause or authenticated exclusive writer.'}
    if not text:
        result['reason'] = 'No retained event stream'
        return result
    result['events'] = {'path': event_path, 'decoded_text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
    try:
        events = [(i, json.loads(raw)) for i, raw in enumerate(text.splitlines(), 1) if raw.strip()]
        if any(not isinstance(e, dict) for _, e in events):
            raise ValueError('event object required')
        sessions = {e['session_id'] for _, e in events if isinstance(e.get('session_id'), str)}
        if len(sessions) != 1 or (session_id is not None and sessions != {session_id}):
            raise ValueError('Single bound session required')
        inits = [e['cwd'] for _, e in events if e.get('type') == 'system' and e.get('subtype') == 'init' and isinstance(e.get('cwd'), str)]
        if len(inits) != 1 or not (ntpath.isabs(inits[0]) or posixpath.isabs(inits[0])) or (cwd is not None and _path(cwd, cwd) != _path(inits[0], inits[0])):
            raise ValueError('Single matching init.cwd required')
        cwd = inits[0]
        if sum(e.get('type') == 'result' for _, e in events) != 1:
            raise ValueError('Single terminal result required')
        if next(e for _, e in events if e.get('type') == 'result').get('session_id') not in sessions:
            raise ValueError('Terminal session must match init')
        calls = _tool_events(text, event_path)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        result['reason'] = 'Unsupported or ambiguous trace: ' + str(exc)
        return result
    result['session_id'] = next(iter(sessions))
    target = _path(workspace_path, cwd)
    if target is None:
        result['reason'] = 'Workspace path unavailable'
        return result
    skills = {c['tool_use_id']: c for c in calls if c['name'] == 'Skill' and c['result_status'] == 'TOOL_REPORTED_SUCCESS'}
    def public(call):
        return {k: call[k] for k in ('name', 'tool_use_id', 'evidence', 'result_status', 'result_evidence') if k in call}
    result['observed_skill_calls'] = [dict(public(c), skill=c['skill']) for c in skills.values()]
    matches = []
    for call in calls:
        arg = call['input']
        if call['name'] != 'Write' or not isinstance(arg, dict) or _path(arg.get('file_path'), cwd) != target:
            continue
        content = arg.get('content')
        digest = hashlib.sha256(content.encode('utf-8')).hexdigest() if isinstance(content, str) else None
        attempt = dict(public(call), content_sha256=digest, matches_retained_bytes=digest == artifact.get('sha256'))
        result['write_attempts'].append(attempt)
        if attempt['matches_retained_bytes'] and call['result_status'] == 'TOOL_REPORTED_SUCCESS':
            matches.append((call, attempt))
    if not matches:
        result['reason'] = 'No successful Write with the exact retained artifact bytes'
        return result
    call, producer = matches[-1]
    # Even a failed later mutation may partially modify a file. Unknown tools
    # are conservatively mutators; a fixed read-only list is not a shell parser.
    readonly = {'Read', 'Glob', 'Grep'}
    blockers = [public(c) for c in calls if c['evidence']['line'] > call['evidence']['line']
                and c['name'] not in readonly and not
                (c['name'] in {'Write', 'Edit'} and isinstance(c['input'], dict)
                 and _path(c['input'].get('file_path'), cwd) not in (None, target))]
    if blockers:
        result.update(reason='Later potentially mutating calls leave final producer unresolved', later_calls=blockers)
        return result
    result.update(status='DIRECT_WRITE_OBSERVED', level='L2.5', producer=producer,
                  reason='Exact Write bytes and linked successful tool result match the retained artifact')
    event = dict(events)[call['evidence']['line']]
    parent = event.get('parent_tool_use_id')
    if isinstance(parent, str) and parent in skills and skills[parent]['evidence']['line'] < call['evidence']['line']:
        result['skill'] = {'status': 'EXPLICIT_PARENT_OBSERVED', 'call': dict(public(skills[parent]), skill=skills[parent]['skill']),
                           'scope': 'Host-export parent relation, not proof of scientific contribution'}
    return result


def link_run(root, case, record, index):
    root = Path(root)
    path = f'runs/{index}/events.jsonl'
    source = confined(root, path)
    text = source.read_text(encoding='utf-8-sig') if source.is_file() else None
    linked = {}
    for identifier, relative in case['artifacts'].items():
        artifact = record.get('artifacts', {}).get(identifier)
        if artifact is None:
            linked[identifier] = {'status': 'UNKNOWN', 'level': 'L2', 'reason': 'Artifact missing', 'producer': None,
                                  'skill': {'status': 'UNKNOWN', 'call': None}}
            continue
        actual = confined(root, artifact['path'])
        if not actual.is_file() or sha(actual) != artifact['sha256']:
            linked[identifier] = {'status': 'UNKNOWN', 'level': 'L2', 'reason': 'Artifact integrity failed', 'producer': None,
                                  'skill': {'status': 'UNKNOWN', 'call': None}}
            continue
        linked[identifier] = artifact_lineage(text, path, relative, artifact,
            cwd=(record.get('observations') or {}).get('cwd'), session_id=record.get('session_id'))
        if source.is_file():
            linked[identifier]['event_file_sha256'] = sha(source)
    return [{'grader_id': g['id'], 'artifact_id': g['artifact'], **linked[g['artifact']]} for g in case['graders']]


def diagnose_retained(directory, expected_receipt_sha256, output):
    """Add a separate versioned view without modifying or invalidating old receipts."""
    from .native_evidence import _fresh, _separate, verify_native_evidence, render_diagnosis
    root, target = Path(directory).resolve(), _fresh(output)
    _separate(root, target)
    verify_native_evidence(root, expected_receipt_sha256)
    plan, records, report = (load_json(root / p) for p in ('plan.json', 'records.json', 'diagnosis.json'))
    cases = {c['name']: c for c in plan['contract']['cases']}
    for index, (run, record) in enumerate(zip(report['runs'], records)):
        run['lineage'] = link_run(root, cases[record['case_id']], record, index)
    report['diagnostic_schema'] = 'pvl-trace-diagnosis-1'
    report['source_receipt_sha256'] = sha(root / 'receipt.json')
    report['source_root'] = str(root)
    target.mkdir(parents=True)
    write_json(target / 'diagnosis.json', report)
    (target / 'diagnosis.md').write_text(render_diagnosis(report), encoding='utf-8')
    return {'report': str(target / 'diagnosis.json'), 'report_sha256': suite_digest(report),
            'source_receipt_sha256': report['source_receipt_sha256'], 'model_calls': 0}
