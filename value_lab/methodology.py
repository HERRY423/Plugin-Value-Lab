"""Frozen two-direction decision-error limits, separate from task quality."""

METRICS = {"unsupported_acceptance", "over_refusal"}


def audit_detector(manifest_path, *, verifier_root=None):
    """Run built-in detectors against separately supplied labels, preserving misses.

    This is a descriptive corpus audit, not representative or independent accuracy.
    Missing artifacts, crashes and hash mismatches remain in planned denominators.
    """
    from pathlib import Path
    from .core import ValidationError, load_json, suite_digest
    from .artifacts import confined, grade_artifact, validate_verifier
    import re
    path = Path(manifest_path).resolve()
    manifest = load_json(path)
    if (not isinstance(manifest, dict) or manifest.get('format') != 'pvl-detector-corpus-1' or not isinstance(manifest.get('cases'), list)
            or not manifest['cases'] or not isinstance(manifest.get('families'), list)
            or not manifest['families'] or any(not isinstance(x, str) or not x.strip() for x in manifest['families'])
            or len(set(manifest['families'])) != len(manifest['families'])):
        raise ValidationError('Detector corpus needs cases and an explicit unique coverage-family inventory')
    ids, identities, rows = set(), set(), []
    for case in manifest['cases']:
        if not isinstance(case, dict):
            raise ValidationError('Corpus cases must be objects')
        for key in ('id', 'family', 'label_reason', 'source'):
            if not isinstance(case.get(key), str) or not case[key].strip():
                raise ValidationError('Case needs nonempty ' + key)
        if case['id'] in ids or case['family'] not in manifest['families']:
            raise ValidationError('Duplicate case or undeclared family')
        ids.add(case['id'])
        if case.get('label') not in ('defect', 'valid', 'disputed'):
            raise ValidationError('Label must be defect, valid or disputed')
        if case.get('basis') not in ('task_contract', 'scientific_adjudication', 'operator_preference'):
            raise ValidationError('Separate task requirements, scientific labels and operator preferences')
        if case.get('origin') not in ('synthetic', 'replayed_real', 'external_incident'):
            raise ValidationError('Declare synthetic, replayed_real or external_incident origin')
        grader = case.get('grader')
        if not isinstance(grader, dict) or grader.get('type') != 'artifact':
            raise ValidationError('Detector audit accepts built-in artifact graders only')
        validate_verifier(grader)
        artifact = case.get('artifact')
        if (not isinstance(artifact, dict) or set(artifact) != {'path', 'sha256'}
                or not isinstance(artifact['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', artifact['sha256'])):
            raise ValidationError('Each planned artifact requires a path and frozen SHA-256, even if unavailable')
        confined(path.parent, artifact['path'])
        identity = (artifact['sha256'], suite_digest({'type': grader['type'], 'verifier': grader['verifier']}))
        if identity in identities:
            raise ValidationError('Repeated artifact/check pair would inflate the denominator')
        identities.add(identity)
        passed, reason, evidence = grade_artifact(grader, {'artifacts': {grader['artifact']: artifact}}, path.parent, verifier_root)
        label = case['label']
        eligible = label != 'disputed' and case['basis'] != 'operator_preference'
        classification = ('EXCLUDED_LABEL' if not eligible else 'UNKNOWN' if passed is None else
                          ('TP' if passed is False else 'FN') if label == 'defect' else
                          ('FP' if passed is False else 'TN'))
        rows.append({**case, 'passed': passed, 'classification': classification,
                     'reason': reason, 'evidence': evidence})

    def metrics(items):
        counts = {key: sum(r['classification'] == key for r in items)
                  for key in ('TP', 'FN', 'FP', 'TN', 'UNKNOWN', 'EXCLUDED_LABEL')}
        defects = [r for r in items if r['label'] == 'defect' and r['classification'] != 'EXCLUDED_LABEL']
        valid = [r for r in items if r['label'] == 'valid' and r['classification'] != 'EXCLUDED_LABEL']
        def bounds(group, detected):
            n = len(group)
            unknown = sum(r['classification'] == 'UNKNOWN' for r in group)
            return {'planned': n, 'unknown': unknown,
                    'rate': detected / n if n and not unknown else None,
                    'lower': detected / n if n else None,
                    'upper': (detected + unknown) / n if n else None}
        return {**counts, 'cases': len(items), 'detection': bounds(defects, counts['TP']),
                'false_positive': bounds(valid, counts['FP']),
                'distinct_families': len({r['family'] for r in items})}
    untested = [f for f in manifest['families'] if not any(r['family'] == f for r in rows)]
    return {'status': 'DESCRIPTIVE_DETECTOR_AUDIT', 'manifest_sha256': suite_digest(manifest),
            'cases': rows, 'summary': metrics(rows),
            'by_family': {f: metrics([r for r in rows if r['family'] == f]) for f in manifest['families']},
            'by_origin': {o: metrics([r for r in rows if r['origin'] == o]) for o in sorted({r['origin'] for r in rows})},
            'blind_spots': {'observed_misses': [r['id'] for r in rows if r['classification'] == 'FN'],
                           'false_alarms': [r['id'] for r in rows if r['classification'] == 'FP'],
                           'unresolved': [r['id'] for r in rows if r['classification'] == 'UNKNOWN'],
                           'untested_families': untested},
            'independent_label_verification': 'NOT_ESTABLISHED', 'representative_accuracy': None,
            'heldout_generalization': 'NOT_ESTABLISHED',
            'scope': 'Labels are supplied independently of detector outputs but not authenticated. Cases can share causes and are not independent population samples. Bounds are missing-result bounds, not confidence intervals. Preferences and disputes are excluded labels, not successes.'}


def validate_limits(policy):
    from .core import ValidationError, _number
    if "decision_error_limits" not in policy:
        return
    limits = policy["decision_error_limits"]
    if not isinstance(limits, dict) or set(limits) != METRICS:
        raise ValidationError("decision_error_limits must specify unsupported_acceptance and over_refusal")
    for name, threshold in limits.items():
        _number(threshold, name, 0, 1)


def assess_limits(policy, sources):
    limits = policy.get("decision_error_limits")
    result = {"status": "NOT_CONFIGURED", "limits": limits, "blockers": [], "violations": [],
              "scope": "Frozen per-split WITH-arm error ceilings; both arms require complete observations. No significance claim."}
    if limits is None:
        return result
    rows = [dict(row, source=name) for name, source in sources.items() if source for row in source["metrics"]]
    for metric in sorted(METRICS):
        for arm in ("with", "without"):
            matching = [row for row in rows if row["metric"] == metric and row["arm"] == arm and row["planned"] > 0]
            if not matching:
                result["blockers"].append(f"Decision limit requires planned {metric} observations for {arm}")
            for row in matching:
                label = f"{row['source']}/{row['split']}/{arm}/{metric}"
                if row["unknown"] or row["rate"] is None:
                    result["blockers"].append("Decision error rate unresolved: " + label)
                elif arm == "with" and row["rate"] > limits[metric] + 1e-12:
                    result["violations"].append({"metric": metric, "split": row["split"], "source": row["source"],
                                                "observed_rate": row["rate"], "maximum": limits[metric]})
    result["status"] = "UNRESOLVED" if result["blockers"] else "VIOLATED" if result["violations"] else "WITHIN_FROZEN_LIMITS"
    return result
