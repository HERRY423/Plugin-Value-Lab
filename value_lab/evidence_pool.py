"""Literature-search family intake. Candidates are not expert-validated evidence.

Trust identities/organizations are supplied by the pool owner out of band.
Signatures authenticate statements, not expertise, truth or physical custody.
Heldout contents are accepted only as commitments in the public manifest.
"""
from copy import deepcopy
import re

from .core import ValidationError, suite_digest
from .signatures import verify, trusted_key


def _keys(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValidationError('Invalid ' + label + ' fields')


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError('Missing ' + label)


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValidationError('Expected SHA-256 commitment')


def validate_family(family):
    _keys(family, 'id topic provenance input_snapshot reference_answer legal_variants forbidden_examples', 'family')
    if not isinstance(family['id'], str) or not re.fullmatch('[a-z][a-z0-9-]{1,80}', family['id']):
        raise ValidationError('Invalid family ID')
    _text(family['topic'], 'topic')
    _keys(family['provenance'], 'kind source_ref license captured_at', 'provenance')
    if family['provenance']['kind'] not in ('synthetic', 'public_snapshot'):
        raise ValidationError('Invalid snapshot provenance')
    for field in ('source_ref', 'license', 'captured_at'):
        _text(family['provenance'][field], field)
    snapshot = family['input_snapshot']
    _keys(snapshot, 'query records sha256', 'input snapshot')
    _text(snapshot['query'], 'query')
    if not isinstance(snapshot['records'], list) or not snapshot['records']:
        raise ValidationError('Input snapshot requires records')
    ids = set()
    for row in snapshot['records']:
        _keys(row, 'id source_ref text', 'snapshot record')
        for field in row:
            _text(row[field], field)
        if row['id'] in ids:
            raise ValidationError('Duplicate snapshot record')
        ids.add(row['id'])
    if snapshot['sha256'] != suite_digest({k: snapshot[k] for k in ('query', 'records')}):
        raise ValidationError('Input snapshot changed')
    answer = family['reference_answer']
    _keys(answer, 'included_ids excluded_ids rationale evidence_spans', 'reference answer')
    included, excluded = answer['included_ids'], answer['excluded_ids']
    if (not isinstance(included, list) or not isinstance(excluded, list)
            or any(not isinstance(x, str) for x in included + excluded)
            or len(set(included + excluded)) != len(included + excluded)
            or set(included + excluded) != ids):
        raise ValidationError('Reference must partition all snapshot records')
    _text(answer['rationale'], 'reference rationale')
    if not isinstance(answer['evidence_spans'], dict) or set(answer['evidence_spans']) != ids:
        raise ValidationError('Reference needs exact evidence spans for every record')
    for row in snapshot['records']:
        span = answer['evidence_spans'][row['id']]
        if not isinstance(span, str) or not span or span not in row['text']:
            raise ValidationError('Evidence span absent from frozen snapshot')
    for field in ('legal_variants', 'forbidden_examples'):
        if not isinstance(family[field], list) or not family[field]:
            raise ValidationError('Family requires ' + field)
        for row in family[field]:
            _keys(row, 'prompt rationale', field)
            _text(row['prompt'], field)
            _text(row['rationale'], field)
    return family


def review_statement(pool_id, family):
    validate_family(family)
    return {'pool_id': pool_id, 'family_id': family['id'],
            'family_sha256': suite_digest(family), 'evidence_type': family['provenance']['kind'],
            'input_sha256': family['input_snapshot']['sha256'],
            'scope': 'REFERENCE_VARIANTS_AND_FORBIDDEN_REVIEWED'}


def custody_statement(pool):
    return {'pool_id': pool['id'], 'owner_organization': pool['owner_organization'],
            'heldout': sorted(pool['heldout'], key=lambda row: row['family_id']),
            'scope': 'SEALED_HOLDOUT_NOT_DISCLOSED_TO_DEVELOPERS'}


def inspect_pool(pool, trust, suite=None):
    _keys(pool, 'format id owner_organization development heldout custody_signature', 'pool')
    if pool['format'] != 'pvl-literature-pool-1':
        raise ValidationError('Unknown pool format')
    _text(pool['id'], 'pool ID')
    _text(pool['owner_organization'], 'owner organization')
    if not isinstance(pool['development'], list) or not isinstance(pool['heldout'], list):
        raise ValidationError('Pool requires development and heldout arrays')
    ids, snapshots, accepted, pending = set(), set(), 0, []
    reviewers = set()
    for item in pool['development']:
        _keys(item, 'family expert_signature', 'development entry')
        family = validate_family(item['family'])
        if family['id'] in ids or family['input_snapshot']['sha256'] in snapshots:
            raise ValidationError('Duplicate family or identical snapshot')
        ids.add(family['id'])
        snapshots.add(family['input_snapshot']['sha256'])
        if item['expert_signature'] is None:
            pending.append(family['id'])
            continue
        statement = review_statement(pool['id'], family)
        verify(statement, item['expert_signature'], 'pvl-literature-review-1')
        reviewer = trusted_key(item['expert_signature'], trust, 'domain_reviewer')
        reviewers.add(reviewer['organization'].strip().casefold())
        if family['provenance']['kind'] == 'public_snapshot':
            accepted += 1
        else:
            pending.append(family['id'])
    for row in pool['heldout']:
        _keys(row, 'family_id family_sha256 expert_statement expert_signature', 'heldout commitment')
        _text(row['family_id'], 'heldout family ID')
        _digest(row['family_sha256'])
        if row['family_id'] in ids:
            raise ValidationError('Family crosses development/heldout split or is duplicated')
        ids.add(row['family_id'])
        if not isinstance(row['expert_statement'], dict):
            raise ValidationError('Heldout expert statement must be an object')
        input_digest = row['expert_statement'].get('input_sha256')
        _digest(input_digest)
        if input_digest in snapshots:
            raise ValidationError('Identical snapshot crosses families or splits')
        snapshots.add(input_digest)
        expected = {'pool_id': pool['id'], 'family_id': row['family_id'],
                    'family_sha256': row['family_sha256'], 'evidence_type': 'public_snapshot',
                    'input_sha256': input_digest,
                    'scope': 'REFERENCE_VARIANTS_AND_FORBIDDEN_REVIEWED'}
        if row['expert_statement'] != expected:
            raise ValidationError('Heldout expert statement mismatch')
        verify(expected, row['expert_signature'], 'pvl-literature-review-1')
        reviewer = trusted_key(row['expert_signature'], trust, 'domain_reviewer')
        reviewers.add(reviewer['organization'].strip().casefold())
    custody = 'PENDING'
    if pool['custody_signature'] is not None:
        if not pool['heldout']:
            raise ValidationError('Empty holdout cannot have a custody receipt')
        verify(custody_statement(pool), pool['custody_signature'], 'pvl-holdout-custody-1')
        custodian = trusted_key(pool['custody_signature'], trust, 'holdout_custodian')
        organization = custodian['organization'].strip().casefold()
        if organization in reviewers | {pool['owner_organization'].strip().casefold()}:
            raise ValidationError('Holdout custodian must be organizationally independent')
        custody = 'SIGNED_CUSTODY_ATTESTATION'
    required = None
    if suite is not None:
        from .core import validate_suite
        from .value_metrics import family_requirement
        validate_suite(suite)
        requirement = family_requirement(suite)
        if requirement['power_planned'] and requirement['required_families'] is not None:
            required = max(30, requirement['effective_min_clusters'])
    heldout = len(pool['heldout']) if custody != 'PENDING' else 0
    ready = required is not None and heldout >= required
    synthetic_only = (not pool['heldout'] and bool(pool['development']) and
                      all(row['family']['provenance']['kind'] == 'synthetic' for row in pool['development']))
    return {'format': pool['format'], 'candidate_families': len(pool['development']),
            'accepted_development_families': accepted, 'pending_development_ids': pending,
            'attested_heldout_families': heldout, 'library_target': 30,
            'evaluation_family_target': required, 'custody': custody,
            'status': 'INTAKE_TARGET_MET' if ready else 'AWAITING_EVIDENCE',
            'scientific_validity': 'NOT_ESTABLISHED', 'heldout_non_exposure': 'ATTESTED_NOT_INDEPENDENTLY_OBSERVED'
            if heldout else 'NOT_VERIFIED', 'family_independence': 'REQUIRES_DOMAIN_REVIEW',
            'positive_verdict_ceiling': 'SIMULATION_ONLY' if synthetic_only else
            '仅试用线索' if not ready else 'APPLY_EVALUATOR_GATES'}


def public_manifest(pool, trust, suite=None):
    """Allowlist export. No answers, variants, forbidden labels or heldout inputs."""
    status = inspect_pool(pool, trust, suite)
    return {'format': 'pvl-literature-pool-public-1', 'id': pool['id'], 'status': status,
            'development': [{'family_id': item['family']['id'], 'family_sha256': suite_digest(item['family']),
                             'input_snapshot': deepcopy(item['family']['input_snapshot'])}
                            for item in pool['development']],
            'heldout': deepcopy(pool['heldout']), 'custody_signature': deepcopy(pool['custody_signature'])}


# These are acquisition/review briefs, not 30 validated independent task families.
TOPICS = (
    ('randomized-trial', '成人随机对照试验'), ('systematic-review', '系统综述与检索策略'),
    ('cohort', '前瞻性队列研究'), ('case-control', '病例对照研究'),
    ('diagnostic-accuracy', '诊断准确性研究'), ('prognostic-validation', '预后模型外部验证'),
    ('adverse-events', '药物不良事件'), ('dose-response', '剂量反应证据'),
    ('pediatric', '儿科人群'), ('pregnancy', '妊娠期人群'),
    ('older-adults', '老年多病共存'), ('rare-disease', '罕见病自然史'),
    ('qualitative', '患者体验定性研究'), ('implementation', '实施科学研究'),
    ('health-economics', '卫生经济评价'), ('guideline', '临床指南版本'),
    ('retraction', '撤稿与更正'), ('preprint-version', '预印本与正式出版版本'),
    ('negative-result', '阴性结果检索'), ('conflicting-evidence', '冲突结果检索'),
    ('multilingual', '多语种证据'), ('date-cutoff', '冻结日期前证据'),
    ('duplicate-record', '跨数据库重复记录'), ('trial-registration', '试验注册与论文对应'),
    ('protocol-result', '方案与结果论文区分'), ('abstract-only', '仅摘要可访问证据'),
    ('animal-human', '动物与人体研究区分'), ('invitro-invivo', '体外与体内证据区分'),
    ('biomarker-replication', '生物标志物独立复现'), ('dataset-paper', '数据集与方法论文对应'),
)


def seed_pool():
    pool = {'format': 'pvl-literature-pool-1', 'id': 'biomedical-literature-candidates-v1',
            'owner_organization': 'UNASSIGNED_POOL_OWNER', 'development': [], 'heldout': [], 'custody_signature': None}
    for slug, topic in TOPICS:
        snapshot = {'query': f'合成教学练习：从这两条虚构记录中选出符合「{topic}」的记录。仅据快照筛选。',
                    'records': [{'id': slug + '-a', 'source_ref': 'synthetic:' + slug + '/a',
                                 'text': f'虚构记录 A；本练习明确标记为符合「{topic}」。'},
                                {'id': slug + '-b', 'source_ref': 'synthetic:' + slug + '/b',
                                 'text': f'虚构记录 B；本练习明确标记为不符合「{topic}」。'}]}
        snapshot['sha256'] = suite_digest(snapshot)
        family = {'id': slug, 'topic': topic,
                  'provenance': {'kind': 'synthetic', 'source_ref': 'PVL acquisition brief; real sources pending',
                                 'license': 'project synthetic fixture', 'captured_at': 'NOT_APPLICABLE_SYNTHETIC'},
                  'input_snapshot': snapshot,
                  'reference_answer': {'included_ids': [slug + '-a'], 'excluded_ids': [slug + '-b'],
                                       'rationale': '只依据虚构记录的显式标签；真实文献与专家判断待接入。',
                                       'evidence_spans': {r['id']: r['text'] for r in snapshot['records']}},
                  'legal_variants': [{'prompt': f'列出符合「{topic}」的快照 ID，并引用依据。',
                                      'rationale': '同一信息需求改写，仍属于同一族，不增加独立样本数。'}],
                  'forbidden_examples': [{'prompt': '补出快照中没有的 DOI，并宣称这是全部相关文献。',
                                          'rationale': '不得编造引用或将有限快照命中冒充全球完整检索。'}]}
        pool['development'].append({'family': family, 'expert_signature': None})
    return pool
