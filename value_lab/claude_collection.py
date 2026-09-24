"""Bounded native Claude print collection for read-only scientific audits.

Native metadata is local host evidence, not provider attestation. No model
identity or plugin exposure is inferred from the requested command alone.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlparse

from .artifacts import confined, sha, MAX_BYTES
from .codex import schedule, _run
from .core import ValidationError, validate_suite, load_json, load_records, write_json, suite_digest, freeze, evaluate
from .execution import snapshot, hashes, now, resolve_claude
from .report import write_reports


def observe_native_events(text):
    """Read an optional exported stream without inventing expected conditions.

    A native eval aggregate does not promise this stream format. Unsupported or
    incomplete streams remain raw evidence with unknown observations.
    """
    try:
        events = [json.loads(line) for line in text.splitlines() if line.strip()]
    except (ValueError, TypeError) as exc:
        raise ValidationError("Malformed exported native event stream") from exc
    if any(not isinstance(e, dict) for e in events):
        raise ValidationError("Native events must be JSON objects")
    starts = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
    ends = [e for e in events if e.get("type") == "result"]
    unknown = {"session_id": None, "model": None, "plugins": None, "tools": None,
               "skill_calls": None, "final_output": None, "issues": ["No supported, consistent init/result stream"]}
    if len(starts) != 1 or len(ends) > 1:
        return unknown
    start, end = starts[0], ends[0] if ends else {}
    sid = start.get("session_id")
    if not isinstance(sid, str) or not sid.strip() or (ends and end.get("session_id") != sid):
        return unknown
    calls = []
    for event in events:
        if event.get("session_id") not in (None, sid):
            return unknown
        message = event.get("message")
        if event.get("type") != "assistant" or not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list):
            calls.extend(block.get("input") for block in content if isinstance(block, dict)
                         and block.get("type") == "tool_use" and block.get("name") == "Skill")
    return {"session_id": sid, "model": start.get("model"), "plugins": start.get("plugins"),
            "cwd": start.get("cwd"), "claude_code_version": start.get("claude_code_version"),
            "tools": start.get("tools"), "skill_calls": calls,
            "final_output": end.get("result"), "trace_complete": bool(ends),
            "issues": [] if ends else ["Native result event missing; init observations do not establish completion"],
            "scope": "observed in operator-supplied stream, not provider attestation"}


def parse_events(path, suite, arm):
    events = load_records(path)
    starts = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
    ends = [e for e in events if e.get("type") == "result"]
    issues = []
    if len(starts) != 1 or len(ends) != 1:
        return {"issues": ["Exactly one native init and result are required"], "session_id": None,
                "output": None, "model_usd": None, "completed": False, "conditions": None, "plugin_loaded": None}
    start, end = starts[0], ends[0]
    sid = start.get("session_id")
    if not isinstance(sid, str) or not sid.strip() or end.get("session_id") != sid:
        issues.append("Missing or inconsistent native session")
    model = start.get("model")
    if model != suite["conditions"]["model"]:
        issues.append("Observed native model differs from frozen model")
    observed_models = {e.get("message", {}).get("model") for e in events if e.get("type") == "assistant" and isinstance(e.get("message"), dict)} - {None}
    if observed_models and observed_models != {model}:
        issues.append("Assistant model identity changed")
    plugins = start.get("plugins")
    names = [p.get("name") for p in plugins if isinstance(p, dict)] if isinstance(plugins, list) else None
    expected = [suite["plugin"]["name"]] if arm == "with" else []
    if names != expected:
        issues.append("Native plugin exposure missing, unexpected, or baseline contaminated")
    observed_tools = start.get("tools")
    if not isinstance(observed_tools, list) or set(observed_tools) != set(suite["conditions"]["tools"]):
        issues.append("Native tool availability exceeds or omits observable contract")
    cost = end.get("total_cost_usd")
    native_cost = cost
    pricing = suite.get("pricing")
    if pricing is not None:
        usage = end.get("usage")
        fields = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
        models = end.get("modelUsage")
        mapping = dict(zip(fields, ("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens", "outputTokens")))
        if (isinstance(usage, dict) and all(type(usage.get(k, 0)) is int and usage.get(k, 0) >= 0 for k in fields)
                and "input_tokens" in usage and "output_tokens" in usage
                and isinstance(models, dict) and set(models) == {model}
                and all(type(models[model].get(v)) is int and models[model][v] >= 0 for v in mapping.values())):
            # Some native error results omit the final turn from aggregate usage.
            # Preserve both raw ledgers and conservatively price their envelope.
            priced = {k: max(usage.get(k, 0), models[model][v]) for k, v in mapping.items()}
            cost = ((priced["input_tokens"] + priced["cache_creation_input_tokens"]) * pricing["input_miss_usd_per_million"]
                    + priced["cache_read_input_tokens"] * pricing["input_hit_usd_per_million"]
                    + priced["output_tokens"] * pricing["output_usd_per_million"]) / 1_000_000
        else:
            cost = None
    if isinstance(cost, bool) or not isinstance(cost, (float, int)) or not math.isfinite(cost) or cost < 0:
        cost = None
        issues.append("Native model price estimate unavailable")
    output = end.get("result")
    completed = end.get("subtype") == "success" and end.get("is_error") is False and isinstance(output, str)
    if not completed:
        issues.append("Native result did not complete successfully")
    if end.get("permission_denials"):
        issues.append("Native tool permission denial requires inspection")
    # Other condition fields describe the frozen local collector controls; the
    # model and plugin fields above come from the emitted native init event.
    conditions = deepcopy(suite["conditions"]) if not issues else None
    return {"issues": issues, "session_id": sid, "output": output, "model_usd": cost,
            "completed": completed, "conditions": conditions,
            "plugin_loaded": (arm == "with") if names == expected else None,
            "observed_model": model, "observed_plugins": names, "observed_tools": observed_tools,
            "native_cost_usd": native_cost, "price_basis": pricing or "native_list_price_estimate",
            "usage": end.get("usage"), "model_usage": end.get("modelUsage"),
            "skill_calls": [b.get("input") for e in events if e.get("type") == "assistant"
                            for b in e.get("message", {}).get("content", [])
                            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill"]}


def prepare(suite, plugin, output, inputs, executable=None):
    validate_suite(suite)
    conditions = suite["conditions"]
    if conditions["host"] != "claude-code" or conditions["tools"] != ["Read", "Skill"]:
        raise ValidationError("This collector supports claude-code read-only Read/Skill audits only")
    budget = conditions["budget"]
    if "pricing" in suite:
        from .core import _number, _text
        for field in ("input_miss_usd_per_million", "input_hit_usd_per_million", "output_usd_per_million"):
            _number(suite["pricing"].get(field), "pricing." + field)
        for field in ("source", "basis", "checked_at"):
            _text(suite["pricing"].get(field), "pricing." + field)
    for field in ("max_model_runs", "timeout_seconds", "max_turns"):
        if type(budget.get(field)) is not int or budget[field] <= 0:
            raise ValidationError("Explicit positive run/time/turn limits required")
    price = budget.get("max_cost_usd")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise ValidationError("Explicit positive native price-estimate ceiling required")
    planned = schedule(suite)
    if budget["max_model_runs"] != len(planned) or budget["timeout_seconds"] > 600 or budget["max_turns"] > 20:
        raise ValidationError("Run count must equal the complete schedule, timeout <=600s and turns <=20")
    executable = resolve_claude(executable)
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=20, check=True).stdout.strip()
    help_text = subprocess.run([executable, "--help"], capture_output=True, text=True, encoding="utf-8", timeout=20, check=True).stdout
    for flag in ("--restricted", "--plugin-dir", "--setting-sources", "--max-budget-usd", "--strict-mcp-config"):
        if flag not in help_text:
            raise ValidationError("Native host lacks " + flag)
    if conditions.get("host_version") != version:
        raise ValidationError("Freeze the observed CLI version in conditions.host_version")
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValidationError("Use a new empty study directory")
    package = snapshot(plugin, root / "plugin")
    if package["plugin"] != suite["plugin"]:
        raise ValidationError("Selected plugin differs from suite")
    manifest = load_json(root / "plugin/.claude-plugin/plugin.json") if (root / "plugin/.claude-plugin/plugin.json").exists() else load_json(root / "plugin/plugin.json")
    if any(k in manifest for k in ("hooks", "mcpServers", "lspServers")) or any(
            Path(n).name in ("hooks.json", ".mcp.json", "mcp.json") or "hooks" in Path(n).parts for n in package["files"]):
        raise ValidationError("Read-only collection requires a skill-only plugin without startup hooks or servers")
    for n in package["files"]:
        if Path(n).name == "SKILL.md":
            text = (root / "plugin" / n).read_text(encoding="utf-8")
            if any(line.lstrip().startswith(("!`", "hooks:")) for line in text.splitlines()):
                raise ValidationError("Dynamic skill commands or hooks are outside read-only collection")
    input_hashes = {}
    for case in suite["cases"]:
        if not isinstance(case.get("inputs"), dict) or not case["inputs"]:
            raise ValidationError("Scientific audit cases must commit actual input files")
        for relative, expected in case["inputs"].items():
            if any(p.casefold() in (".git", ".claude", ".agents", "claude.md", "agents.md") for p in Path(relative).parts):
                raise ValidationError("Input must not inject host configuration")
            source = confined(inputs, relative)
            if source.stat().st_size > MAX_BYTES or sha(source) != expected:
                raise ValidationError("Input bytes differ from frozen hash")
            target = confined(root / "inputs", relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            input_hashes[relative] = expected
    write_json(root / "suite.json", suite)
    freeze(suite, root / "protocol.lock.json")
    plan = {"format": "pvl-claude-collection-1", "suite_sha256": suite_digest(suite),
            "collector_sha256": sha(__file__),
            "executable": executable, "executable_sha256": sha(executable), "host_version": version,
            "plugin_files": package["files"], "inputs": input_hashes, "schedule": planned,
            "limits": budget, "settled_cost_usd": None, "automatic_retry": False,
            "scope": "Read-only local native collection. Native USD is an estimate, not settlement or a hard account cap."}
    write_json(root / "plan.json", plan)
    return {"study": str(root), "plan_sha256": sha(root / "plan.json"), "planned_runs": len(planned), "model_calls": 0}


def _continuation_records(root, plan):
    """Only a known terminated prefix can leave unstarted work to continue."""
    checked = verify_collection(root)
    records = load_records(root / "runs.jsonl")
    if not records or len(records) >= len(plan["schedule"]):
        raise ValidationError("No unstarted scheduled executions to continue")
    for index, planned in enumerate(plan["schedule"]):
        run_dir = root / "runs" / f"{index+1:04d}-{planned['case_id']}-{planned['arm']}"
        if index >= len(records):
            if run_dir.exists():
                raise ValidationError("Unrecorded execution directory: process or charge state is unknown")
        else:
            receipt = load_json(run_dir / "receipt.json")
            if receipt.get("exit_code") is None or receipt.get("timed_out") or receipt["native"].get("model_usd") is None:
                raise ValidationError("Unresolved process or cost state prevents continuation")
    return records, checked


def run(directory, expected_plan_sha256, auth_home, *, continue_unstarted=False, previous_collector=None):
    root = Path(directory).resolve()
    plan, suite = load_json(root / "plan.json"), load_json(root / "suite.json")
    validate_suite(suite)
    collector_matches = sha(__file__) == plan["collector_sha256"]
    if continue_unstarted and previous_collector is not None:
        collector_matches = sha(previous_collector) == plan["collector_sha256"]
    if (sha(root / "plan.json") != expected_plan_sha256 or suite_digest(suite) != plan["suite_sha256"]
            or not collector_matches
            or load_json(root / "protocol.lock.json")["suite_sha256"] != plan["suite_sha256"]
            or plan["schedule"] != schedule(suite) or plan["limits"] != suite["conditions"]["budget"]
            or hashes(root / "plugin") != plan["plugin_files"] or sha(plan["executable"]) != plan["executable_sha256"]):
        raise ValidationError("Frozen collector plan, protocol, plugin or executable changed")
    for relative, expected in plan["inputs"].items():
        if sha(confined(root / "inputs", relative)) != expected:
            raise ValidationError("Frozen input changed")
    records, verified_prefix = _continuation_records(root, plan) if continue_unstarted else ([], None)
    auth_root = Path(auth_home).resolve()
    auth = auth_root / ".credentials.json"
    settings = load_json(auth_root / "settings.json") if (auth_root / "settings.json").exists() else {}
    configured = settings.get("env", {})
    provider_env = {k: configured[k] for k in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL") if isinstance(configured.get(k), str)}
    if provider_env:
        provider_url = urlparse(provider_env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"))
        if provider_url.scheme != "https" or provider_url.hostname != suite["conditions"].get("provider_host"):
            raise ValidationError("Configured provider differs from frozen provider host")
        if not any(provider_env.get(k) for k in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")):
            raise ValidationError("Configured provider credential missing")
    else:
        stored = load_json(auth) if auth.is_file() else {}
        if not isinstance(stored.get("claudeAiOauth"), dict):
            raise ValidationError("No supported existing Claude OAuth or explicit provider credentials; unrelated MCP credentials are never copied")
    # One durable claim; never automatically repeat uncertain model charges.
    marker = "continuation-" + str(len(records)) + ".json" if continue_unstarted else "execution-started.json"
    with (root / marker).open("x", encoding="utf-8") as stream:
        json.dump({"started_at": now(), "plan_sha256": expected_plan_sha256, "automatic_retry": False,
                   "collector_sha256": sha(__file__), "verified_prefix": verified_prefix,
                   "prior_summary": load_json(root / "execution-summary.json") if continue_unstarted else None}, stream)
    for index in range(len(records), len(plan["schedule"])):
        planned = plan["schedule"][index]
        run_dir = root / "runs" / f"{index+1:04d}-{planned['case_id']}-{planned['arm']}"
        workspace, home = run_dir / "workspace", run_dir / "home"
        workspace.mkdir(parents=True)
        (workspace / ".git").mkdir()
        home.mkdir()
        case = next(c for c in suite["cases"] if c["id"] == planned["case_id"])
        for relative in case["inputs"]:
            target = confined(workspace, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(confined(root / "inputs", relative), target)
        (workspace / "CLAUDE.md").write_text("Only the supplied public task inputs are in scope. Do not read outside this workspace.\n", encoding="utf-8")
        command = [plan["executable"], "--print", "--verbose", "--output-format", "stream-json",
                   "--model", suite["conditions"]["model"], "--effort", "low", "--restricted",
                   "--permission-mode", "dontAsk", "--tools", "Read,Skill", "--allowedTools", "Read,Skill",
                   "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "",
                   "--no-session-persistence", "--max-budget-usd", str(plan["limits"]["max_cost_usd"]),
                   "--max-turns", str(plan["limits"]["max_turns"])]
        if planned["arm"] == "with":
            command += ["--plugin-dir", str(root / "plugin")]
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(home), PYTHONUTF8="1")
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDECODE"):
            env.pop(k, None)
        for k in list(env):
            if k.startswith("ANTHROPIC_"):
                env.pop(k)
        env.update(provider_env)
        env.update(CLAUDE_CODE_MAX_OUTPUT_TOKENS="1500", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
        write_json(run_dir / "launch.json", {"command": command, "started_at": now(), "input_sha256": case["inputs"]})
        if not provider_env:
            write_json(home / ".credentials.json", {"claudeAiOauth": stored["claudeAiOauth"]})
            os.chmod(home / ".credentials.json", 0o600)
        observed = None
        try:
            receipt = _run(command, env, workspace, case["prompt"], run_dir / "events", plan["limits"]["timeout_seconds"])
            observed = parse_events(run_dir / "events.jsonl", suite, planned["arm"])
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            receipt = {"exit_code": None, "duration_seconds": None, "timed_out": False, "error": str(exc)}
        finally:
            (home / ".credentials.json").unlink(missing_ok=True)
        observed = observed or {"session_id": None, "output": None, "conditions": None, "plugin_loaded": None,
                                "completed": False, "model_usd": None, "issues": ["Native evidence unavailable"]}
        status = "timeout" if receipt["timed_out"] else "completed" if receipt["exit_code"] == 0 and observed["completed"] else "error"
        record = {**planned, "source": "claude", "suite_sha256": plan["suite_sha256"], "session_id": observed["session_id"],
                  "conditions": observed["conditions"], "plugin_loaded": observed["plugin_loaded"], "status": status,
                  "failure_kind": "infrastructure", "output": observed["output"], "import_issues": observed["issues"],
                  "cost": {"model_usd": observed["model_usd"], "tool_usd": 0, "human_minutes": 0, "basis": "estimate"},
                  "human_intervals": [], "duration_seconds": receipt["duration_seconds"], "artifacts": {},
                  "cost_scope": "Automated read-only run: no human interactions or paid local tools; preparation overhead and account settlement remain unknown"}
        if observed["output"] is not None:
            output = run_dir / "answer.json"
            output.write_text(observed["output"], encoding="utf-8")
            record["artifacts"]["answer"] = {"path": output.relative_to(root).as_posix(), "sha256": sha(output)}
        write_json(run_dir / "receipt.json", {**receipt, "native": observed, "events_sha256": sha(run_dir / "events.jsonl") if (run_dir / "events.jsonl").exists() else None,
                                               "settled_cost_usd": None, "identity_scope": "Local native metadata, not independent provider attestation"})
        records.append(record)
        with (root / "runs.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        write_reports(evaluate(suite, records, load_json(root / "protocol.lock.json"), artifact_root=root), root / "report")
        if status != "completed":
            break
    summary = {"expected_runs": len(plan["schedule"]), "observed_runs": len(records),
               "completed_runs": sum(r["status"] == "completed" for r in records),
               "known_native_estimate_usd": sum(r["cost"]["model_usd"] or 0 for r in records),
               "unknown_native_cost_runs": sum(r["cost"]["model_usd"] is None for r in records),
               "settled_cost_usd": None, "automatic_retry": False, "finished_at": now()}
    write_json(root / "execution-summary.json", summary)
    return summary


def verify_collection(directory):
    root = Path(directory).resolve()
    plan, suite = load_json(root / "plan.json"), load_json(root / "suite.json")
    if suite_digest(suite) != plan["suite_sha256"] or load_json(root / "protocol.lock.json")["suite_sha256"] != plan["suite_sha256"] or plan["schedule"] != schedule(suite):
        raise ValidationError("Collection protocol changed")
    if hashes(root / "plugin") != plan["plugin_files"]:
        raise ValidationError("Collected plugin snapshot changed")
    if load_json(root / "execution-started.json")["plan_sha256"] != sha(root / "plan.json"):
        raise ValidationError("Executed plan changed")
    for relative, expected in plan["inputs"].items():
        if sha(confined(root / "inputs", relative)) != expected:
            raise ValidationError("Collected input changed")
    records = load_records(root / "runs.jsonl")
    if len(records) > len(plan["schedule"]):
        raise ValidationError("Unplanned runs")
    sessions = set()
    for index, record in enumerate(records):
        planned = plan["schedule"][index]
        if any(record.get(k) != v for k, v in planned.items()) or record.get("suite_sha256") != plan["suite_sha256"]:
            raise ValidationError("Record does not match planned execution")
        run_dir = root / "runs" / f"{index+1:04d}-{planned['case_id']}-{planned['arm']}"
        receipt = load_json(run_dir / "receipt.json")
        if receipt["events_sha256"] != sha(run_dir / "events.jsonl"):
            raise ValidationError("Native event bytes changed")
        native = parse_events(run_dir / "events.jsonl", suite, planned["arm"])
        if native != receipt["native"]:
            raise ValidationError("Native receipt differs from events")
        for field in ("session_id", "output", "conditions", "plugin_loaded"):
            if record.get(field) != native[field]:
                raise ValidationError("Record differs from native evidence: " + field)
        if record["cost"]["model_usd"] != native["model_usd"] or record["import_issues"] != native["issues"]:
            raise ValidationError("Record costs or evidence issues changed")
        expected_status = "timeout" if receipt["timed_out"] else "completed" if receipt["exit_code"] == 0 and native["completed"] else "error"
        if record.get("status") != expected_status or record.get("duration_seconds") != receipt["duration_seconds"]:
            raise ValidationError("Record completion or timing differs from process receipt")
        case = next(c for c in suite["cases"] if c["id"] == planned["case_id"])
        launch = load_json(run_dir / "launch.json")
        if launch.get("input_sha256") != case["inputs"]:
            raise ValidationError("Launched input contract changed")
        for relative, expected in case["inputs"].items():
            if sha(confined(run_dir / "workspace", relative)) != expected:
                raise ValidationError("Executed workspace input changed")
        sid = native["session_id"]
        if sid and sid in sessions:
            raise ValidationError("Native session reused")
        if sid:
            sessions.add(sid)
        for ref in record["artifacts"].values():
            if sha(confined(root, ref["path"])) != ref["sha256"]:
                raise ValidationError("Collected artifact changed")
        if native["output"] is not None:
            answer = record["artifacts"].get("answer")
            if not answer or confined(root, answer["path"]).read_text(encoding="utf-8") != native["output"]:
                raise ValidationError("Scored answer differs from native output")
        if (run_dir / "home/.credentials.json").exists():
            raise ValidationError("Temporary credential copy was not removed")
    return {"verified_records": len(records), "expected_runs": len(plan["schedule"]),
            "schedule_fully_observed": len(records) == len(plan["schedule"]),
            "successful_runs": sum(r["status"] == "completed" for r in records),
            "failed_runs": sum(r["status"] != "completed" for r in records),
            "complete": len(records) == len(plan["schedule"]) and all(r["status"] == "completed" for r in records),
            "scope": "Local native evidence consistency; no independent identity, biological validity or settled-cost attestation"}
