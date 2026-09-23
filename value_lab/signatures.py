"""Domain-separated Ed25519 signatures; trust is supplied out of band.

A verified signature establishes possession of a key, not scientific validity
or a real person's identity. Never trust a public key merely because it is embedded.
"""
import base64
import hashlib
from pathlib import Path

from .core import ValidationError, suite_digest


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        return serialization, Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature
    except ImportError as exc:
        raise ValidationError("Signing requires the optional registry dependency: cryptography") from exc


def public_identity(key):
    serialization, _, _, _ = _crypto()
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"key_id": hashlib.sha256(raw).hexdigest(), "public_key": base64.b64encode(raw).decode("ascii")}


def _message(payload, context):
    if context not in ("pvl-review-1", "pvl-public-card-1", "pvl-public-index-1"):
        raise ValidationError("Unknown signature domain")
    return (context + "\n" + suite_digest(payload)).encode("ascii")


def sign(payload, key, context):
    _, private, _, _ = _crypto()
    if not isinstance(key, private):
        raise ValidationError("Ed25519 private key required")
    return {"algorithm": "Ed25519", "context": context, **public_identity(key.public_key()),
            "payload_sha256": suite_digest(payload),
            "value": base64.b64encode(key.sign(_message(payload, context))).decode("ascii")}


def load_private(path):
    serialization, private, _, _ = _crypto()
    try:
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    except (ValueError, TypeError) as exc:
        raise ValidationError("An unencrypted local Ed25519 PEM signing key is required") from exc
    if not isinstance(key, private):
        raise ValidationError("Signing key is not Ed25519")
    return key


def verify(payload, signature, context):
    _, _, public, invalid = _crypto()
    required = {"algorithm", "context", "key_id", "public_key", "payload_sha256", "value"}
    if not isinstance(signature, dict) or set(signature) != required:
        raise ValidationError("Malformed signature envelope")
    if signature["algorithm"] != "Ed25519" or signature["context"] != context or signature["payload_sha256"] != suite_digest(payload):
        raise ValidationError("Signature domain or payload digest mismatch")
    try:
        raw = base64.b64decode(signature["public_key"], validate=True)
        key = public.from_public_bytes(raw)
        if hashlib.sha256(raw).hexdigest() != signature["key_id"]:
            raise ValueError("Key ID mismatch")
        key.verify(base64.b64decode(signature["value"], validate=True), _message(payload, context))
    except (ValueError, TypeError, invalid) as exc:
        raise ValidationError("Invalid Ed25519 signature") from exc
    return signature["key_id"]


def validate_trust(trust):
    if not isinstance(trust, dict) or set(trust) != {"keys"} or not isinstance(trust["keys"], list):
        raise ValidationError("Trust file requires a keys array")
    seen = set()
    _, _, public, _ = _crypto()
    for entry in trust["keys"]:
        if not isinstance(entry, dict) or set(entry) != {"key_id", "public_key", "identity", "organization", "roles", "revoked"}:
            raise ValidationError("Invalid trusted key declaration")
        try:
            ident = public_identity(public.from_public_bytes(base64.b64decode(entry["public_key"], validate=True)))
        except (ValueError, TypeError) as exc:
            raise ValidationError("Invalid trusted public key") from exc
        if any(entry[k] != ident[k] for k in ident) or entry["key_id"] in seen:
            raise ValidationError("Mismatched or duplicate trusted key")
        seen.add(entry["key_id"])
        if any(not isinstance(entry[k], str) or not entry[k].strip() for k in ("identity", "organization")):
            raise ValidationError("Trusted identity and organization are required")
        if (type(entry["revoked"]) is not bool or not isinstance(entry["roles"], list) or not entry["roles"]
                or any(r not in ("publisher", "domain_reviewer", "reproducer") for r in entry["roles"])):
            raise ValidationError("Invalid trusted key roles/revocation")
    return trust


def trusted_key(signature, trust, role):
    validate_trust(trust)
    for entry in trust["keys"]:
        if entry["key_id"] == signature["key_id"] and entry["public_key"] == signature["public_key"]:
            if not entry["revoked"] and role in entry["roles"]:
                return entry
    raise ValidationError("Signature key is not trusted for this role, or was revoked")
