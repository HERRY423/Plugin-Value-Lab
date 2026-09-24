"""Offline sidecars for retained native eval workspaces, without rewriting cases.

Workspace-to-run links are operator declarations, not authenticated receipts.
Only explicitly named files are copied. Neither model output nor verifier code
is executed. Legacy aggregate imports retain their original evidence ceiling.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .artifacts import MAX_BYTES, confined, grade_artifact, sha, validate_verifier
from .core import ValidationError, load_json, suite_digest, write_json
from .native import _validate_result, _status


ALLOWED = {"pseudobulk_chain", "artifact", "artifact_schema", "numeric_tolerance", "replicate_effect",
           "abstention_correct", "over_refusal"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _fresh(path):
    path = Path(path).resolve()
    if path.exists():
        raise ValidationError("Choose a new evidence directory; existing evidence is never overwritten")
    return path


def _bytes(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValidationError("Evidence file missing or exceeds 64 MiB")
    content = path.read_bytes()
    if len(content) > MAX_BYTES:
        raise ValidationError("Evidence file exceeds 64 MiB")
    return content


def _put(root, relative, content):
    path = confined(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
    return {"path": relative, "sha256": sha(path)}


def _refs(value):
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            yield value
        else:
            for child in value.values():
                yield from _refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _refs(child)


def _separate(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    if a.is_relative_to(b) or b.is_relative_to(a):
        raise ValidationError("Scorer, plugin, workspaces and evidence output must have disjoint roots")


def validate_contract(contract):
    if not isinstance(contract, dict) or set(contract) - {"schema_version", "cases", "plugin_files", "execution_context", "diagnostic_intent"} or not {"schema_version", "cases"} <= set(contract) or type(contract["schema_version"]) is not int or contract["schema_version"] != 1:
        raise ValidationError("Native evidence contract requires schema_version 1 and cases")
    if not isinstance(contract["cases"], list) or not contract["cases"]:
        raise ValidationError("At least one case is required")
    if not isinstance(contract.get("plugin_files", []), list):
        raise ValidationError("plugin_files must be an explicit filename allowlist")
    for relative in contract.get("plugin_files", []):
        confined(Path.cwd(), relative)
    if "execution_context" in contract:
        from .native_repair import validate_context
        validate_context(contract["execution_context"])
    if "diagnostic_intent" in contract:
        intent = contract["diagnostic_intent"]
        if (not isinstance(intent, dict) or set(intent) != {"mode", "source_plan_sha256", "expected_skills"}
                or intent["mode"] != "explicit_invocation"
                or not re.fullmatch(r"[a-f0-9]{64}", str(intent["source_plan_sha256"]))
                or not isinstance(intent["expected_skills"], dict)
                or any(not isinstance(k, str) or not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", v)
                       for k, v in intent["expected_skills"].items())):
            raise ValidationError("Invalid explicit-invocation diagnostic intent")
    seen = set()
    for case in contract["cases"]:
        required = {"name", "case_directory", "repetitions", "inputs", "artifacts", "graders"}
        if not isinstance(case, dict) or not required <= set(case) or set(case) - required - {"input_sha256", "execution"}:
            raise ValidationError("Case requires name, case_directory, repetitions, inputs, artifacts and graders")
        name = case["name"]
        if not isinstance(name, str) or not name.strip() or name.casefold() in seen:
            raise ValidationError("Case names must be nonempty and unique")
        seen.add(name.casefold())
        confined(Path.cwd(), case["case_directory"])
        if type(case["repetitions"]) is not int or not 1 <= case["repetitions"] <= 50:
            raise ValidationError("repetitions must be 1..50")
        for field in ("inputs", "artifacts"):
            if not isinstance(case[field], dict):
                raise ValidationError("inputs/artifacts must map IDs to relative workspace filenames")
            for key, path in case[field].items():
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
                    raise ValidationError("Invalid artifact/input ID")
                confined(Path.cwd(), path)
        if "input_sha256" in case:
            hashes = case["input_sha256"]
            if (not isinstance(hashes, dict) or set(hashes) != set(case["inputs"])
                    or any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for v in hashes.values())):
                raise ValidationError("input_sha256 must pin every declared input")
        if "execution" in case:
            execution = case["execution"]
            if (not isinstance(execution, dict) or set(execution) != {"script_artifact", "command"}
                    or execution["script_artifact"] not in case["artifacts"]
                    or not isinstance(execution["command"], str) or not execution["command"].strip()
                    or any(c in execution["command"] for c in "\x00\r\n")):
                raise ValidationError("execution requires a collected script_artifact and exact single-line Bash command")
        if not isinstance(case["graders"], list) or not case["graders"]:
            raise ValidationError("Each case needs independent artifact graders")
        grader_ids = set()
        for grader in case["graders"]:
            if not isinstance(grader, dict) or grader.get("type") not in ALLOWED:
                raise ValidationError("Only built-in offline scientific graders are supported")
            gid = grader.get("id")
            if not isinstance(gid, str) or not gid.strip() or gid in grader_ids:
                raise ValidationError("Grader IDs must be nonempty and unique")
            grader_ids.add(gid)
            if grader.get("artifact") not in case["artifacts"]:
                raise ValidationError("Grader artifact is absent from the collection allowlist")
            validate_verifier(grader)
    suite_digest(contract)


def prepare_native_evidence(plugin, contract, output, *, references=None):
    """Freeze existing case bytes and post-run rules. Makes no model calls."""
    validate_contract(contract)
    plugin, output = Path(plugin).resolve(), _fresh(output)
    _separate(plugin, output)
    if references is not None:
        _separate(plugin, references)
        _separate(output, references)
    files = {}
    # Snapshot only case directories selected explicitly, never account/config trees.
    for case in contract["cases"]:
        directory = confined(plugin, case["case_directory"])
        if not any((directory / name).is_file() for name in ("prompt.md", "case.yaml")):
            raise ValidationError("Selected native case requires prompt.md or case.yaml")
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(plugin).as_posix()
            path = confined(plugin, relative)
            if path.is_file():
                files[relative] = _bytes(path)
    ref_files = {}
    for ref in _refs(contract):
        if references is None:
            raise ValidationError("External scorer reference root is required")
        path = confined(references, ref["path"])
        data = _bytes(path)
        if hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ValidationError("Scorer reference digest mismatch")
        ref_files[ref["path"]] = ref["sha256"]
    plugin_files = {relative: _bytes(confined(plugin, relative)) for relative in contract.get("plugin_files", [])}
    plugin_identity = None
    for relative in ("plugin.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        path = confined(plugin, relative)
        if path.is_file():
            plugin_files[relative] = _bytes(path)
            metadata = json.loads(plugin_files[relative])
            plugin_identity = {"name": metadata.get("name"), "version": metadata.get("version")}
            break
    plan = {"schema_version": 1, "kind": "native-artifact-sidecar", "created_at": _now(),
            "contract": deepcopy(contract), "contract_sha256": suite_digest(contract),
            "case_files": {}, "plugin_files": {}, "plugin_identity": plugin_identity,
            "plugin_inventory_scope": "Explicit allowlist plus first plugin manifest; other dependencies are not frozen",
            "references": ref_files, "model_calls": 0,
            "collection": {"files": "Only declared workspace inputs and artifacts, plus explicitly supplied events",
                           "purpose": "Independent post-run computational diagnosis",
                           "cost": "Offline capture and grading make no model calls. Native execution is separately authorized; estimated ceilings can overrun.",
                           "reference_isolation": "Keep this plan and scorer references outside all agent-readable paths; root separation alone is not an OS sandbox."}}
    output.mkdir(parents=True)
    for relative, data in files.items():
        plan["case_files"][relative] = _put(output, "cases/" + relative, data)["sha256"]
    for relative, data in plugin_files.items():
        plan["plugin_files"][relative] = _put(output, "plugin/" + relative, data)["sha256"]
    write_json(output / "plan.json", plan)
    return {"plan": str(output / "plan.json"), "plan_sha256": suite_digest(plan),
            "model_calls": 0, "next_step": "Run existing native cases with --keep-temp --no-publish and an explicit cost ceiling. Then supply exact case/arm/repetition workspace bindings. No command is launched by this tool."}


def _plan(directory, expected):
    root = Path(directory).resolve()
    plan = load_json(root / "plan.json")
    if suite_digest(plan) != expected:
        raise ValidationError("Frozen native evidence plan changed")
    validate_contract(plan["contract"])
    if suite_digest(plan["contract"]) != plan["contract_sha256"]:
        raise ValidationError("Contract digest mismatch")
    for relative, digest in plan["case_files"].items():
        if sha(confined(root, "cases/" + relative)) != digest:
            raise ValidationError("Frozen native case changed")
    for relative, digest in plan["plugin_files"].items():
        if sha(confined(root, "plugin/" + relative)) != digest:
            raise ValidationError("Frozen plugin file changed")
    return root, plan


def _diagnose(root, plan, records, native):
    cases = {c["name"]: c for c in plan["contract"]["cases"]}
    results = []
    for record in records:
        grades = []
        for grader in cases[record["case_id"]]["graders"]:
            passed, rationale, receipt = grade_artifact(grader, record, root, root / "references")
            grades.append({"id": grader["id"], "passed": passed, "rationale": rationale, "receipt": receipt})
        results.append({"case_id": record["case_id"], "arm": record["arm"], "repetition": record["repetition"],
                        "status": record["status"], "grades": grades, "issues": record["issues"],
                        "binding": record.get("binding"), "observations": record.get("observations")})
        case = cases[record["case_id"]]
        if "input_sha256" in case:
            results[-1]["input_integrity"] = {
                key: "MISSING" if key not in record["inputs"] else
                "MATCH" if record["inputs"][key]["sha256"] == digest else "CHANGED"
                for key, digest in case["input_sha256"].items()}
        if "execution" in case:
            from .native_execution import observe_execution
            events = confined(root, f"runs/{len(results)-1}/events.jsonl")
            results[-1]["execution"] = observe_execution(
                events.read_text(encoding="utf-8-sig") if events.is_file() else None,
                case["execution"], record["artifacts"])
        if "execution" in case or "input_sha256" in case:
            run = results[-1]
            if any(v != "MATCH" for v in run.get("input_integrity", {}).values()):
                stage, action = "INPUT_INTEGRITY", "Restore the frozen input bytes and inspect the producing/copying step before interpreting output differences."
            elif record["status"] != "completed":
                stage, action = "RUNTIME", "Inspect the preserved native error and trace; a valid partial artifact does not establish completed analysis."
            elif "execution" in run and (run["execution"]["status"] != "TOOL_REPORTED_SUCCESS" or run["execution"]["terminal_status"] != "SUCCESS" or run["execution"]["model_conflict_observed"]):
                stage, action = "EXECUTION_EVIDENCE", "Inspect the exact Bash call and its linked tool result; preserve missing, background and failed attempts."
            elif any(g["passed"] is None for g in grades):
                stage, action = "MISSING_EVIDENCE", "Recover the declared artifact or scorer material before assigning a scientific error."
            elif any(g["passed"] is False for g in grades):
                stage, action = "ARTIFACT_CONTRACT", "Inspect the failed check's artifact, rule and producing script; test that hypothesis with all original cases and controls."
            else:
                stage, action = "COMPUTATIONAL_CHECKS_PASSED", "Review the assumptions and scientific interpretation; computational agreement alone does not establish biological truth."
            run["next_check"] = {"stage": stage, "action": action, "plugin_cause_established": False}
    return {"schema_version": 1, "status": "LOCAL_ARTIFACT_DIAGNOSIS", "contract_sha256": plan["contract_sha256"],
            "runs": results, "native_partial": native.get("partial"), "native_estimated_cost_usd": native.get("costUsd"),
            "settled_cost_usd": None, "human_minutes": None, "model_calls_by_sidecar": 0,
            "plugin_identity": plan["plugin_identity"], "plugin_inventory_scope": plan["plugin_inventory_scope"],
            "comparison_eligible": False, "external_author_acceptance": None,
            "limits": ["Workspace bindings are explicit operator declarations, not authenticated host receipts.",
                       "Repetition is native array position, not established paired-run identity.",
                       "Computational checks do not establish plugin benefit, independent science or author adoption.",
                       "Missing events, costs, outputs and unstarted runs remain missing."]}


def render_diagnosis(report):
    """Human-readable facts and bounded repair hypotheses, linked to receipts."""
    lines = ["# Native scientific artifact diagnosis", "", "Local computational diagnosis; plugin benefit is not established.",
             "", "[Raw native result](native-result.json) · [Run and file bindings](records.json) · [Machine-readable diagnosis](diagnosis.json)", ""]
    for run in report["runs"]:
        lines.extend([f"## {run['case_id']} / {run['arm']} / {run['repetition']}", "", f"Observed execution status: {run['status']}", ""])
        for grade in run["grades"]:
            status = "PASS" if grade["passed"] is True else "FAIL" if grade["passed"] is False else "UNKNOWN"
            artifact = grade["receipt"].get("artifact_path")
            link = f" — [collected artifact]({artifact})" if artifact else ""
            # Use prose rather than a table: grader rationales may contain pipes.
            lines.append(f"- {grade['id']}: **{status}** — {grade['rationale']}{link}")
        for issue in run["issues"]:
            lines.append("- Evidence gap: " + issue)
        if "input_integrity" in run:
            lines.append("- Frozen input integrity: " + json.dumps(run["input_integrity"]))
        if "execution" in run:
            lines.append("- Script execution trace: " + run["execution"]["status"])
            lines.append("- " + run["execution"]["scope"])
        if "next_check" in run:
            lines.append("- Next check (" + run["next_check"]["stage"] + "): " + run["next_check"]["action"])
        lines.append("")
        if any(g["passed"] is False for g in run["grades"]):
            lines.append("Repair hypothesis: inspect the failed artifact contract and producing step. These observations alone do not establish whether loading, triggering or the method caused the failure. Keep every case and control for the complete retest.")
        elif any(g["passed"] is None for g in run["grades"]):
            lines.append("Next check: recover the missing file/reference or binding before judging scientific correctness.")
        lines.append("")
    lines.extend(["## Limits", "", *["- " + item for item in report["limits"]], ""])
    return "\n".join(lines)


def _retained_workspace(trace, cwd, root, version):
    """Resolve only an observed, version-bounded native relocation, never scan."""
    workspace = Path(cwd)
    if not workspace.is_absolute() or not workspace.is_relative_to(root):
        raise ValidationError('Native init.cwd is outside the retained root')
    confined(root, workspace.relative_to(root).as_posix())
    run_root = trace.parent.parent
    relocated = None
    if (version == '2.1.278' and trace.name == 'trace.jsonl' and trace.parent.name == 'out'
            and run_root.name.startswith('claude-eval-') and workspace == run_root / 'home/cwd'):
        candidate = run_root / 'sealed/home/cwd'
        confined(root, candidate.relative_to(root).as_posix())
        if candidate.is_dir():
            relocated = candidate
    if workspace.is_dir() and relocated is not None:
        raise ValidationError('Ambiguous native workspace: both original and relocated trees exist')
    if relocated is not None:
        return relocated, 'native_tracePath_init_cwd_sealed_layout'
    return workspace, 'native_tracePath_and_init_cwd'


def discover_native_bindings(result_path, retained_root):
    """Observed 2.1.278 profile: follow explicit tracePath and init.cwd only.

    Includes the observed Linux home/cwd -> sealed/home/cwd relocation. This
    establishes a layout link, not successful sealing or execution authenticity.
    No directory/time heuristics. This local profile is intentionally version
    bounded because tracePath is not promised by the documented v1 summary.
    """
    native = _validate_result(load_json(result_path))
    if native.get("claudeVersion") != "2.1.278":
        raise ValidationError("Automatic retained-workspace binding is verified only for Claude Code 2.1.278; supply explicit bindings for other versions")
    root = Path(retained_root).resolve()
    from .claude_collection import observe_native_events
    bindings, missing = [], []
    for case in native["cases"]:
        for arm, runs in case["arms"].items():
            for rep, run in enumerate(runs, 1):
                key = {"case_id": case["name"], "arm": arm, "repetition": rep}
                raw = run.get("tracePath")
                if not isinstance(raw, str) or not raw:
                    missing.append({**key, "reason": "Native tracePath absent"})
                    continue
                path = Path(raw)
                if not path.is_absolute() or not path.is_relative_to(root):
                    raise ValidationError("Native tracePath is outside the explicitly supplied retained root")
                relative = path.relative_to(root).as_posix()
                safe_trace = confined(root, relative)
                if not safe_trace.is_file():
                    missing.append({**key, "reason": "Retained native trace file missing"})
                    continue
                try:
                    events = observe_native_events(_bytes(safe_trace).decode("utf-8-sig"))
                except (ValidationError, UnicodeError):
                    missing.append({**key, "reason": "Retained trace is not a supported event stream"})
                    continue
                cwd = events.get("cwd")
                if not isinstance(cwd, str) or not cwd:
                    missing.append({**key, "reason": "Supported init.cwd absent"})
                    continue
                workspace, _ = _retained_workspace(safe_trace, cwd, root, native.get('claudeVersion'))
                if not workspace.is_dir():
                    missing.append({**key, "reason": "Retained workspace missing"})
                    continue
                bindings.append({**key, "workspace": str(workspace), "events": relative})
    return {"bindings": bindings, "missing": missing, "profile": "claude-code-2.1.278-tracePath-init.cwd",
            "scope": "Direct local host-export links; not cryptographic execution authentication"}


def capture_native_evidence(directory, expected_plan_sha256, plugin, result_path, bindings, output, *, references=None, retained_root=None):
    """Copy allowlisted files from explicitly mapped retained workspaces, then grade."""
    plan_root, plan = _plan(directory, expected_plan_sha256)
    output = _fresh(output)
    plugin = Path(plugin).resolve()
    _separate(plugin, output)
    _separate(plan_root, output)
    for relative, digest in plan["case_files"].items():
        if sha(confined(plugin, relative)) != digest:
            raise ValidationError("Native cases changed after freeze; freeze a new protocol")
    current_cases = {}
    for case in plan["contract"]["cases"]:
        for path in confined(plugin, case["case_directory"]).rglob("*"):
            relative = path.relative_to(plugin).as_posix()
            if confined(plugin, relative).is_file():
                current_cases[relative] = sha(path)
    if current_cases != plan["case_files"]:
        raise ValidationError("Native case inventory changed after freeze")
    for relative, digest in plan["plugin_files"].items():
        if sha(confined(plugin, relative)) != digest:
            raise ValidationError("Selected plugin file changed after freeze")
    raw = _bytes(result_path)
    native = _validate_result(json.loads(raw))
    if not isinstance(bindings, list):
        raise ValidationError("Bindings must be an array")
    cases = {c["name"]: c for c in plan["contract"]["cases"]}
    observed = {}
    for ci, case in enumerate(native["cases"]):
        if case["name"] not in cases:
            raise ValidationError("Native result contains a case outside the frozen contract")
        for arm, runs in case["arms"].items():
            if len(runs) > cases[case["name"]]["repetitions"]:
                raise ValidationError("Native result exceeds frozen repetition count")
            for i, run in enumerate(runs, 1):
                observed[(case["name"], arm, i)] = (f"/cases/{ci}/arms/{arm}/{i-1}", run)
    mapped, workspaces, event_paths = {}, set(), set()
    payloads = {"native-result.json": raw}
    for group, prefix in (("case_files", "cases"), ("plugin_files", "plugin")):
        for relative in plan[group]:
            payloads[prefix + "/" + relative] = _bytes(confined(plan_root, prefix + "/" + relative))
    if retained_root is not None:
        retained_root = Path(retained_root).resolve()
        for other in (plugin, plan_root, output):
            _separate(retained_root, other)
        if references is not None:
            _separate(retained_root, references)
    if references is not None:
        for other in (plugin, plan_root, output):
            _separate(references, other)
    for relative, digest in plan["references"].items():
        if references is None:
            raise ValidationError("Scorer references are required")
        path = confined(references, relative)
        data = _bytes(path)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValidationError("Scorer reference changed after freeze")
        payloads["references/" + relative] = data
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) - {"case_id", "arm", "repetition", "workspace", "events"} or not {"case_id", "arm", "repetition", "workspace"} <= set(binding):
            raise ValidationError("Binding requires case_id, arm, repetition, workspace and optional events")
        key = (binding["case_id"], binding["arm"], binding["repetition"])
        if type(binding["repetition"]) is not int or key not in observed or key in mapped:
            raise ValidationError("Duplicate binding or binding to an unobserved native run")
        workspace = Path(binding["workspace"]).resolve()
        if retained_root is not None:
            if not workspace.is_relative_to(retained_root):
                raise ValidationError("Workspace is outside supplied retained root")
            confined(retained_root, workspace.relative_to(retained_root).as_posix())
        if not workspace.is_dir() or workspace in workspaces:
            raise ValidationError("Each run requires a distinct existing retained workspace")
        for other in (plugin, plan_root, output, *workspaces):
            _separate(workspace, other)
        if references is not None:
            _separate(workspace, references)
        workspaces.add(workspace)
        mapped[key] = binding
    records = []
    for case in plan["contract"]["cases"]:
        for arm in ("with", "without"):
            for rep in range(1, case["repetitions"] + 1):
                key = (case["name"], arm, rep)
                record = {"case_id": key[0], "arm": arm, "repetition": rep, "status": "missing",
                          "artifacts": {}, "inputs": {}, "issues": [], "session_id": None}
                index = len(records)
                if key not in observed:
                    record["issues"].append("Native run not present; no session or output fabricated")
                else:
                    pointer, run = observed[key]
                    record.update(status=_status(run), binding={"native_json_pointer": pointer, "native_run_sha256": suite_digest(run),
                                                              "method": "operator_declared_retained_workspace"})
                    if run.get("error") or run.get("aborted"):
                        record["issues"].append("Native execution failed; local artifacts may still be diagnosable")
                    if run.get("skippedPaidGraders"):
                        record["issues"].append("Native paid graders were skipped")
                binding = mapped.get(key)
                if binding is None:
                    record["issues"].append("Retained workspace not supplied")
                else:
                    for group in ("inputs", "artifacts"):
                        for identifier, relative in case[group].items():
                            path = confined(binding["workspace"], relative)
                            if not path.is_file():
                                record["issues"].append(f"Missing {group}: {identifier}")
                                continue
                            destination = f"runs/{index}/{group}/{identifier}{path.suffix}"
                            data = _bytes(path)
                            payloads[destination] = data
                            record[group][identifier] = {"path": destination, "sha256": hashlib.sha256(data).hexdigest()}
                    if binding.get("events"):
                        # Events stay in explicitly selected roots, never arbitrary account/config paths.
                        path = confined(retained_root or binding["workspace"], binding["events"])
                        resolved = path.resolve()
                        if resolved in event_paths:
                            raise ValidationError("Native events reused across runs")
                        event_paths.add(resolved)
                        data = _bytes(path)
                        payloads[f"runs/{index}/events.jsonl"] = data
                        from .claude_collection import observe_native_events
                        record["observations"] = observe_native_events(data.decode("utf-8-sig"))
                        record["session_id"] = record["observations"]["session_id"]
                        record["issues"].extend(record["observations"]["issues"])
                        if retained_root is not None:
                            trace_path = observed[key][1].get("tracePath")
                            native_cwd = record["observations"].get("cwd")
                            if (not isinstance(trace_path, str) or Path(trace_path).resolve() != path.resolve()
                                    or not isinstance(native_cwd, str)):
                                raise ValidationError("Retained native tracePath/init.cwd do not match the supplied run binding")
                            expected_workspace, method = _retained_workspace(path, native_cwd, retained_root, native.get('claudeVersion'))
                            if expected_workspace.resolve() != Path(binding['workspace']).resolve():
                                raise ValidationError("Retained native tracePath/init.cwd do not match the supplied run binding")
                            record['binding']['method'] = method
                            if method == 'native_tracePath_init_cwd_sealed_layout':
                                record['issues'].append('Native workspace relocation observed; sealing is NOT verified. Retained contents remain untrusted and are never executed by the sidecar.')
                    else:
                        record["issues"].append("Native events unavailable; load, calls, model and session remain unknown")
                records.append(record)
    sessions = [r["session_id"] for r in records if r["session_id"]]
    if len(sessions) != len(set(sessions)):
        raise ValidationError("Native session reused across runs")
    output.mkdir(parents=True)
    manifest = {}
    for relative, data in payloads.items():
        manifest[relative] = _put(output, relative, data)["sha256"]
    for name, data in (("plan.json", plan), ("records.json", records)):
        write_json(output / name, data)
        manifest[name] = sha(output / name)
    report = _diagnose(output, plan, records, native)
    write_json(output / "diagnosis.json", report)
    manifest["diagnosis.json"] = sha(output / "diagnosis.json")
    _put(output, "DIAGNOSIS.md", render_diagnosis(report).encode("utf-8"))
    manifest["DIAGNOSIS.md"] = sha(output / "DIAGNOSIS.md")
    receipt = {"schema_version": 1, "created_at": _now(), "plan_sha256": expected_plan_sha256, "files": manifest,
               "source": "operator_supplied_native_export", "authenticated_execution": False}
    write_json(output / "receipt.json", receipt)
    return {"output": str(output), "receipt_sha256": suite_digest(receipt), "diagnosis": report}


def verify_native_evidence(directory, expected_receipt_sha256):
    """Verify bytes against an externally retained digest and recompute every grade."""
    root = Path(directory).resolve()
    receipt = load_json(root / "receipt.json")
    if suite_digest(receipt) != expected_receipt_sha256:
        raise ValidationError("Evidence receipt changed")
    for relative, digest in receipt["files"].items():
        if sha(confined(root, relative)) != digest:
            raise ValidationError("Collected evidence changed: " + relative)
    _, plan = _plan(root, receipt["plan_sha256"])
    report = _diagnose(root, plan, load_json(root / "records.json"), _validate_result(load_json(root / "native-result.json")))
    if suite_digest(report) != suite_digest(load_json(root / "diagnosis.json")):
        raise ValidationError("Independent post-run grading did not reproduce")
    return {"status": "REPRODUCED", "receipt_sha256": expected_receipt_sha256,
            "scope": "same collected bytes and computational rules; not independent execution", "diagnosis": report}
