"""Inspect a submitted Codex observation without executing or trusting it.

This is a structural evidence contract, not a native-host attestation verifier.
An operator's source reference does not authenticate that source, its completeness,
the host, or isolation.  The importer must retain and resolve source references.
Synthetic packets can exercise this contract but never supply observed host facts.
"""

from datetime import datetime
from hashlib import sha256
import re


FORMAT = "pvl-codex-study-observation-1"
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_UNKNOWN_VERSIONS = {"unknown", "unspecified", "latest", "auto", "default", "n/a", "none"}
_STATES = ("completed", "failed", "cancelled")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _digest(value):
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _same_digest(left, right):
    return _digest(left) and _digest(right) and left.lower() == right.lower()


def _explicit_version(value):
    return _text(value) and value.strip().lower() not in _UNKNOWN_VERSIONS


def _object(value, path, issues):
    if not isinstance(value, dict):
        issues.append(f"{path}: object required")
        return {}
    return value


def _timestamp(value, path, issues):
    if not isinstance(value, str):
        issues.append(f"{path}: timezone-aware ISO timestamp required")
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("missing timezone")
        return result
    except (ValueError, TypeError, OverflowError):
        issues.append(f"{path}: timezone-aware ISO timestamp required")
        return None


def _tools(value, path, issues):
    if not isinstance(value, list):
        issues.append(f"{path}: complete tool list required")
        return {}
    result = {}
    for index, item in enumerate(value):
        row = _object(item, f"{path}[{index}]", issues)
        name = row.get("name")
        digest = row.get("definition_sha256")
        if not _text(name):
            issues.append(f"{path}[{index}].name: nonempty tool name required")
            continue
        if name in result:
            issues.append(f"{path}[{index}].name: duplicate tool name")
        if not _digest(digest):
            issues.append(f"{path}[{index}].definition_sha256: SHA-256 required")
        result[name] = digest.lower() if _digest(digest) else None
    return result


def _plugin(value, path, issues):
    row = _object(value, path, issues)
    for field in ("id", "version"):
        valid = _explicit_version(row.get(field)) if field == "version" else _text(row.get(field))
        if not valid:
            issues.append(f"{path}.{field}: explicit nonempty identity required")
    if not _digest(row.get("sha256")):
        issues.append(f"{path}.sha256: SHA-256 required")
    return row


def _complete(row, path, issues):
    if row.get("inventory_complete") is not True:
        issues.append(f"{path}.inventory_complete: must be explicitly true")
    if not _text(row.get("source_ref")):
        issues.append(f"{path}.source_ref: retained source reference required")
    # Extra fields are permitted, but declared pagination/truncation cannot
    # contradict a claim that the inventory is complete.
    for field in ("has_more", "truncated"):
        if field in row and row[field] is not False:
            issues.append(f"{path}.{field}: incomplete or ambiguous inventory")
    for field in ("next_cursor", "nextCursor"):
        if field in row and row[field] not in (None, ""):
            issues.append(f"{path}.{field}: unconsumed inventory page")


def _exposure(value, *, path, expected_tools, expected_plugin, arm, issues):
    start = len(issues)
    row = _object(value, path, issues)
    _complete(row, path, issues)
    if row.get("source_kind") != "host_effective_inventory":
        issues.append(f"{path}.source_kind: host effective inventory required")
    tools = _tools(row.get("tools"), f"{path}.tools", issues)
    if tools != expected_tools:
        issues.append(f"{path}.tools: effective tools differ from frozen arm inventory")
    plugins = row.get("plugins")
    if not isinstance(plugins, list):
        issues.append(f"{path}.plugins: complete plugin list required")
    elif arm == "without":
        if plugins:
            issues.append(f"{path}.plugins: baseline must have no candidate plugin exposure")
    elif arm == "with":
        if len(plugins) != 1:
            issues.append(f"{path}.plugins: candidate arm requires exactly one frozen plugin")
        for index, plugin in enumerate(plugins):
            actual = _plugin(plugin, f"{path}.plugins[{index}]", issues)
            if any(actual.get(key) != expected_plugin.get(key) for key in ("id", "version")) or not _same_digest(
                actual.get("sha256"), expected_plugin.get("sha256")
            ):
                issues.append(f"{path}.plugins[{index}]: plugin differs from frozen identity")
    else:
        issues.append(f"{path}: no valid frozen arm inventory")
    return len(issues) == start


def _seen(value, path, issues):
    if not isinstance(value, (list, tuple, set, frozenset)) or any(not _text(item) for item in value):
        issues.append(f"{path}: collection of nonempty identities required")
        return set()
    return set(value)


def inspect_observation(packet, *, plan, slot, seen_sessions=(), seen_requests=()):
    """Return fail-closed checks of one attempt, preserving its raw text output.

    ``status`` is the declared terminal state only when the *entire* structural
    contract passes, otherwise ``unknown``.  ``output`` is audit material even
    when status is unknown/failed/cancelled; callers must gate scoring on status.
    Observed flags refer solely to consistent operator-submitted observations,
    never authentication.  They are false for synthetic packets.  Imported
    grades and unknown extra fields confer no authority and are not consumed.
    """
    issues = []
    packet = _object(packet, "packet", issues)
    plan = _object(plan, "plan", issues)
    slot = _object(slot, "slot", issues)
    output = packet.get("raw_output")
    if output is not None and not isinstance(output, str):
        issues.append("packet.raw_output: string or explicit null required")
        output = None
    if "raw_output" not in packet:
        issues.append("packet.raw_output: field required, including explicit null for no output")
    output_sha256 = None
    if isinstance(output, str):
        try:
            output_sha256 = sha256(output.encode("utf-8")).hexdigest()
        except UnicodeError:
            issues.append("packet.raw_output: output is not valid UTF-8 text")

    for field in ("plan_sha256", "suite_sha256", "context_sha256"):
        if not _digest(plan.get(field)):
            issues.append(f"plan.{field}: SHA-256 required")
    frozen_at = _timestamp(plan.get("frozen_at"), "plan.frozen_at", issues)
    host_start = len(issues)
    host = _object(plan.get("host"), "plan.host", issues)
    for field, required in (("product", "codex"), ("surface", "desktop")):
        if host.get(field) != required:
            issues.append(f"plan.host.{field}: expected {required}")
    for field in ("build", "model"):
        if not _explicit_version(host.get(field)):
            issues.append(f"plan.host.{field}: explicit version required")
    if not isinstance(packet.get("host"), dict) or packet.get("host") != host:
        issues.append("packet.host: host identity differs from frozen plan")
    host_valid = len(issues) == host_start

    inventory_start = len(issues)
    plugin = _plugin(plan.get("plugin"), "plan.plugin", issues)
    common = _tools(plan.get("common_tools"), "plan.common_tools", issues)
    candidate = _tools(plan.get("candidate_tools"), "plan.candidate_tools", issues)
    if common.keys() & candidate.keys():
        issues.append("plan.candidate_tools: tool names overlap the common inventory")
    inventory_plan_valid = len(issues) == inventory_start

    for field in ("slot_id", "case_id"):
        if not _text(slot.get(field)):
            issues.append(f"slot.{field}: nonempty identity required")
    repetition = slot.get("repetition")
    if type(repetition) is not int or repetition < 1:
        issues.append("slot.repetition: positive integer required")
    arm = slot.get("arm")
    if arm not in ("with", "without"):
        issues.append("slot.arm: with or without required")
    if not _text(slot.get("prompt")):
        issues.append("slot.prompt: nonempty prompt required")
    if not _digest(slot.get("input_sha256")):
        issues.append("slot.input_sha256: SHA-256 required")
    expected_tools = dict(common)
    if arm == "with":
        expected_tools.update(candidate)

    if packet.get("format") != FORMAT:
        issues.append("packet.format: unsupported observation format")
    origin = packet.get("origin")
    if origin not in ("synthetic", "operator_capture"):
        issues.append("packet.origin: synthetic or operator_capture required")
    if not _same_digest(packet.get("plan_sha256"), plan.get("plan_sha256")):
        issues.append("packet.plan_sha256: frozen plan binding mismatch")
    for field in ("attempt_id", "slot_id", "session_id", "request_id"):
        if not _text(packet.get(field)):
            issues.append(f"packet.{field}: nonempty identity required")
    if packet.get("slot_id") != slot.get("slot_id"):
        issues.append("packet.slot_id: frozen slot binding mismatch")
    if not isinstance(packet.get("prompt"), str) or packet.get("prompt") != slot.get("prompt"):
        issues.append("packet.prompt: exact frozen prompt required")
    if not _same_digest(packet.get("input_sha256"), slot.get("input_sha256")):
        issues.append("packet.input_sha256: frozen input binding mismatch")
    session = packet.get("session_id") if _text(packet.get("session_id")) else None
    request = packet.get("request_id") if _text(packet.get("request_id")) else None
    if session in _seen(seen_sessions, "seen_sessions", issues):
        issues.append("packet.session_id: session reused across attempts")
    if request in _seen(seen_requests, "seen_requests", issues):
        issues.append("packet.request_id: request reused across attempts")

    started_at = _timestamp(packet.get("started_at"), "packet.started_at", issues)
    finished_at = _timestamp(packet.get("finished_at"), "packet.finished_at", issues)
    if started_at is not None and frozen_at is not None and started_at < frozen_at:
        issues.append("packet.started_at: attempt predates the frozen plan")
    if started_at is not None and finished_at is not None and finished_at < started_at:
        issues.append("packet.finished_at: attempt finishes before it starts")

    context_start = len(issues)
    context = _object(packet.get("context"), "packet.context", issues)
    _complete(context, "packet.context", issues)
    for field, required in (("fresh_session", True), ("memory_enabled", False), ("shared_artifacts", False)):
        if context.get(field) is not required:
            issues.append(f"packet.context.{field}: must be explicitly {required}")
    for field in ("parent_session_id", "project_id"):
        if field not in context or context[field] is not None:
            issues.append(f"packet.context.{field}: must be explicitly null")
    if type(context.get("prior_messages")) is not int or context.get("prior_messages") != 0:
        issues.append("packet.context.prior_messages: must be explicitly integer zero")
    if not _same_digest(context.get("context_sha256"), plan.get("context_sha256")):
        issues.append("packet.context.context_sha256: frozen context binding mismatch")
    context_valid = len(issues) == context_start

    exposure_valid = _exposure(
        packet.get("exposure"), path="packet.exposure", expected_tools=expected_tools,
        expected_plugin=plugin, arm=arm, issues=issues,
    ) and inventory_plan_valid
    state = packet.get("terminal_state")
    if state not in _STATES:
        issues.append("packet.terminal_state: completed, failed or cancelled required")
    if state == "completed" and not isinstance(output, str):
        issues.append("packet.raw_output: completed attempt requires raw text output")

    events = packet.get("events")
    if not isinstance(events, list) or not events:
        issues.append("packet.events: nonempty complete event list required")
        events = []
    calls, resolved = {}, set()
    finals, terminals = [], []
    for index, event in enumerate(events, start=1):
        path = f"packet.events[{index - 1}]"
        row = _object(event, path, issues)
        if type(row.get("seq")) is not int or row.get("seq") != index:
            issues.append(f"{path}.seq: contiguous sequence starting at one required")
        kind = row.get("kind")
        if terminals:
            issues.append(f"{path}: event follows terminal event")
        if finals and kind != "terminal":
            issues.append(f"{path}: nonterminal event follows final output")
        if kind == "tool_call":
            call_id, name = row.get("call_id"), row.get("name")
            if not _text(call_id):
                issues.append(f"{path}.call_id: nonempty call identity required")
            elif call_id in calls:
                issues.append(f"{path}.call_id: duplicate tool call identity")
            else:
                calls[call_id] = index
            if not _text(name) or name not in expected_tools:
                issues.append(f"{path}.name: tool absent from frozen arm inventory")
                exposure_valid = False
            elif "definition_sha256" in row and not _same_digest(
                row["definition_sha256"], expected_tools[name]
            ):
                issues.append(f"{path}.definition_sha256: tool definition mismatch")
                exposure_valid = False
        elif kind == "tool_result":
            call_id = row.get("call_id")
            if not _text(call_id) or call_id not in calls:
                issues.append(f"{path}.call_id: result has no preceding tool call")
            elif call_id in resolved:
                issues.append(f"{path}.call_id: duplicate tool result")
            else:
                resolved.add(call_id)
            if type(row.get("is_error")) is not bool:
                issues.append(f"{path}.is_error: explicit boolean required")
        elif kind == "inventory":
            current_valid = _exposure(
                row.get("exposure"), path=f"{path}.exposure", expected_tools=expected_tools,
                expected_plugin=plugin, arm=arm, issues=issues,
            )
            exposure_valid = exposure_valid and current_valid
        elif kind == "final":
            finals.append(index)
            if calls.keys() - resolved:
                issues.append(f"{path}: final output precedes unresolved tool results")
            if not _same_digest(row.get("output_sha256"), output_sha256):
                issues.append(f"{path}.output_sha256: raw output byte hash mismatch")
        elif kind == "terminal":
            terminals.append(index)
            if row.get("state") not in _STATES or row.get("state") != state:
                issues.append(f"{path}.state: terminal event disagrees with attempt state")
        else:
            issues.append(f"{path}.kind: unsupported event kind")
    if calls.keys() - resolved:
        issues.append("packet.events: unresolved tool calls; outcome is not known")
    if len(terminals) != 1 or terminals[0] != len(events):
        issues.append("packet.events: exactly one terminal event must be last")
    if len(finals) > 1 or (state == "completed" and len(finals) != 1):
        issues.append("packet.events: completed attempt requires exactly one final output event")

    observed = origin == "operator_capture" and not issues
    return {
        "issues": issues,
        "output": output,
        "status": state if not issues else "unknown",
        "session_id": session,
        "request_id": request,
        "exposure_verified": observed and exposure_valid,
        "isolation_observed": observed and context_valid,
        "host_identity_observed": observed and host_valid,
        "authenticated_host": False,
        "contract_valid": not issues,
        "evidence_scope": (
            "SYNTHETIC_ONLY" if origin == "synthetic" else
            "UNAUTHENTICATED_OPERATOR_CAPTURE" if origin == "operator_capture" else "UNKNOWN"
        ),
        "limitations": [
            "Checks only consistency of submitted records, not native host authenticity or completeness.",
            "Source references must be retained and resolved by the importer; references do not authenticate their contents.",
            "Observed isolation and inventory are operator declarations, not proof of inaccessible hidden state or tools.",
            "Synthetic fixtures never establish host observations, execution acceptance or plugin benefit.",
        ],
    }
