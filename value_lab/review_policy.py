"""Version-bound independent review protocol for positive public cards."""
from .core import ValidationError, _text
from .registry import _digest, _timestamp
from .signatures import verify, trusted_key


def validate_protocol(review):
    protocol = review.get("protocol")
    fields = {"version", "role", "plugin_version", "plugin_sha256", "suite_sha256", "disagreements", "false_refusals"}
    if not isinstance(protocol, dict) or set(protocol) != fields or protocol["version"] != "pvl-independent-review-1":
        raise ValidationError("Incomplete independent review protocol")
    if protocol["role"] not in ("domain_reviewer", "reproducer"):
        raise ValidationError("Declare a domain_reviewer or reproducer role")
    _text(protocol["plugin_version"], "reviewed plugin version")
    for field in ("plugin_sha256", "suite_sha256"):
        _digest(protocol[field])
    if not isinstance(protocol["disagreements"], list) or any(not isinstance(x, str) or not x.strip() for x in protocol["disagreements"]):
        raise ValidationError("Disagreements must be an explicit list")
    if not isinstance(protocol["false_refusals"], list):
        raise ValidationError("False refusals must be recorded explicitly, including an empty list")
    for item in protocol["false_refusals"]:
        if (not isinstance(item, dict) or set(item) != {"case_id", "arm", "repetition", "note"}
                or item["arm"] not in ("with", "without") or type(item["repetition"]) is not int or item["repetition"] < 1):
            raise ValidationError("Invalid false-refusal observation")
        _text(item["case_id"], "case_id")
        _text(item["note"], "false refusal note")
    if "signature" in review:
        verify({k: v for k, v in review.items() if k != "signature"}, review["signature"], "pvl-review-1")


def review_gate(row, suite, trust):
    valid, results = [], []
    from .core import suite_digest
    for review in row["reviews"]:
        reasons = []
        try:
            validate_protocol(review)
            p = review["protocol"]
            signature = review.get("signature")
            verify({k: v for k, v in review.items() if k != "signature"}, signature, "pvl-review-1")
            identity = trusted_key(signature, trust, p["role"])
            norm = lambda x: x.strip().casefold()
            if norm(identity["identity"]) != norm(review["reviewer"]) or norm(identity["organization"]) != norm(review["organization"]):
                reasons.append("Trusted key identity does not match reviewer declaration")
            if review["relationship"] != "independent" or review["conflicts"]:
                reasons.append("Non-author, conflict-free independent review required")
            if review["verdict"] != "support" or p["disagreements"]:
                reasons.append("Review is not unambiguous support")
            if _timestamp(review["reviewed_at"]) < _timestamp(row["observed_at"]):
                reasons.append("Review predates the submitted observations")
            if (p["plugin_version"] != suite["plugin"]["version"] or p["plugin_sha256"] != row["plugin_sha256"]
                    or p["suite_sha256"] != suite_digest(suite)):
                reasons.append("Review does not bind this exact plugin revision and suite")
            case_ids = {c["id"] for c in suite["cases"]}
            if any(f["case_id"] not in case_ids or f["repetition"] > suite["runs_per_case"] for f in p["false_refusals"]):
                reasons.append("False-refusal references are outside this study")
            if not reasons:
                valid.append(identity["identity"].strip().casefold())
        except (ValidationError, KeyError, TypeError) as exc:
            reasons.append(str(exc))
        results.append({"review_sha256": suite_digest(review), "reviewer": review["reviewer"],
                        "organization": review["organization"], "verdict": review["verdict"],
                        "protocol": review.get("protocol"), "qualifies": not reasons, "blockers": reasons})
    return {"required_non_author_reviews": 1, "qualifying_reviewers": len(set(valid)), "reviews": results,
            "scope": "Signatures bind locally enrolled keys; human identity and independence still depend on out-of-band enrollment"}
