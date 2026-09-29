"""RFC3161 external time for frozen bytes; reviewer signatures are separate.

No online action occurs here. Request publication is explicit and sends only the
message imprint and nonce. Git author dates and locally signed tags are not time
authorities. A timestamp cannot prove an author's prior knowledge or independence.
"""
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import subprocess

from .artifacts import sha
from .core import ValidationError, suite_digest, write_json


def _openssl(executable, arguments):
    result = subprocess.run([str(executable), *map(str, arguments)], capture_output=True,
                            stdin=subprocess.DEVNULL, timeout=30, shell=False,
                            env={**os.environ, 'OPENSSL_CONF': os.devnull})
    text = (result.stdout + result.stderr).decode('utf-8', errors='replace')
    if result.returncode:
        raise ValidationError('OpenSSL verification failed: ' + text[-1500:])
    return text


def prepare_timestamp(lock, output, openssl):
    root, lock = Path(output), Path(lock)
    if not lock.is_file() or lock.stat().st_size > 8 * 1024 * 1024:
        raise ValidationError('Bounded frozen lock file required')
    root.mkdir(parents=True, exist_ok=False)
    (root / 'frozen-lock.json').write_bytes(lock.read_bytes())
    _openssl(openssl, ['ts', '-query', '-data', root / 'frozen-lock.json', '-sha256', '-cert', '-out', root / 'request.tsq'])
    result = {'format': 'pvl-timestamp-request-1', 'lock_sha256': sha(root / 'frozen-lock.json'),
              'request_sha256': sha(root / 'request.tsq'), 'state': 'NOT_SUBMITTED',
              'disclosure': 'RFC3161 SHA256 imprint and nonce only; no file contents', 'automatic_retry': False}
    write_json(root / 'request.json', result)
    return result


def verify_timestamp(directory, lock_sha256, ca_file, ca_sha256, openssl):
    root, ca = Path(directory), Path(ca_file)
    if sha(root / 'frozen-lock.json') != lock_sha256 or sha(ca) != ca_sha256:
        raise ValidationError('Lock or independently supplied CA bundle changed')
    # Check both the exact file digest and the stored request's nonce/imprint.
    common = ['ts', '-verify', '-in', root / 'response.tsr', '-CAfile', ca]
    evidence = [_openssl(openssl, common + ['-data', root / 'frozen-lock.json']),
                _openssl(openssl, common + ['-queryfile', root / 'request.tsq'])]
    description = _openssl(openssl, ['ts', '-reply', '-in', root / 'response.tsr', '-text'])
    match = re.search(r'Time stamp:\s+(\w{3})\s+(\d{1,2})\s+(\d\d):(\d\d):(\d\d)(?:\.(\d+))?\s+(\d{4})\s+GMT', description)
    if not match:
        raise ValidationError('Verified timestamp has unsupported time representation')
    month, day, hour, minute, second, fraction, year = match.groups()
    stamp = datetime(int(year), ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'].index(month)+1,
                     int(day), int(hour), int(minute), int(second), int((fraction or '').ljust(6,'0')[:6] or 0), tzinfo=timezone.utc)
    receipt = {'format': 'pvl-external-time-1', 'status': 'EXTERNAL_TIME_VERIFIED',
        'lock_sha256': lock_sha256, 'request_sha256': sha(root / 'request.tsq'),
        'response_sha256': sha(root / 'response.tsr'), 'ca_bundle_sha256': ca_sha256,
        'tsa_time_utc': stamp.isoformat(), 'openssl_sha256': sha(openssl),
        'author_prior_knowledge': 'NOT_ESTABLISHED', 'reviewer_identity': 'NOT_ESTABLISHED',
        'billing_authenticity': 'NOT_ESTABLISHED', 'revocation_checked': False,
        'scope': 'TSA signature, certificate chain under supplied trust roots, file imprint and request nonce verified; existence by TSA time only.'}
    (root / 'verification.txt').write_text('\n'.join(evidence) + '\n' + description, encoding='utf-8')
    write_json(root / 'receipt.json', receipt)
    return receipt


def verify_reviewer(statement, signature, trust, expected):
    """The caller pins the review target; no generated key can assert a person."""
    from .signatures import verify, trusted_key
    required = {'format', 'reviewer_id', 'suite_sha256', 'report_sha256', 'registration_sha256', 'decision', 'basis'}
    if not isinstance(statement, dict) or set(statement) != required or statement['format'] != 'pvl-study-review-1':
        raise ValidationError('Complete separate reviewer statement required')
    if statement['decision'] not in ('accept', 'reject', 'unknown') or not isinstance(statement['basis'], str) or not statement['basis'].strip():
        raise ValidationError('Reviewer decision and basis required')
    if (not isinstance(expected, dict) or set(expected) != {'suite_sha256', 'report_sha256', 'registration_sha256'}
            or any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v) for v in expected.values())
            or any(statement[k] != v for k, v in expected.items())):
        raise ValidationError('Reviewer statement does not bind the expected study, report and registration')
    verify(statement, signature, 'pvl-review-1')
    identity = trusted_key(signature, trust, 'domain_reviewer')
    if identity['identity'] != statement['reviewer_id']:
        raise ValidationError('Reviewer identity differs from independently supplied trust record')
    return {'status': 'REVIEW_SIGNATURE_VERIFIED', 'reviewer_id': statement['reviewer_id'],
            'statement_sha256': suite_digest(statement), 'decision': statement['decision'],
            'identity_basis': 'Caller-supplied out-of-band key trust; no independent person authentication by PVL'}
