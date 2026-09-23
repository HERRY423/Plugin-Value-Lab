"""Single-attempt Codex CLI collection in separate homes and workspaces.

Launch/configuration receipts do not authenticate model identity or skill use.
Missing provenance, human review and settled costs remain evaluation blockers.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from .core import ValidationError, freeze, load_json, load_records, suite_digest, validate_suite, write_json, evaluate
from .execution import digest, hashes, now, snapshot
from .processes import bind_tree, close_tree, terminate_tree
from .report import write_reports
from .artifacts import confined, MAX_BYTES


def preflight(executable):
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=20, check=True).stdout.strip()
    help_text = subprocess.run([executable, "exec", "--help"], capture_output=True, text=True, timeout=20, check=True).stdout
    for flag in ("--json", "--ephemeral", "--output-last-message", "--sandbox", "--skip-git-repo-check"):
        if flag not in help_text:
            raise ValidationError("Codex CLI missing required capability: " + flag)
    return {"version": version, "executable_sha256": digest(executable), "checked_at": now()}


def schedule(suite):
    return [{"case_id": case["id"], "repetition": rep, "arm": arm}
            for i, case in enumerate(suite["cases"]) for rep in range(1, suite["runs_per_case"] + 1)
            for arm in (("with", "without") if (i + rep) % 2 else ("without", "with"))]


def prepare(suite, plugin, output, executable=None, input_root=None):
    validate_suite(suite)
    if suite["conditions"]["host"] != "codex-cli":
        raise ValidationError("Codex collection requires conditions.host=codex-cli")
    budget = suite["conditions"]["budget"]
    if type(budget.get("timeout_seconds")) is not int or not 1 <= budget["timeout_seconds"] <= 600:
        raise ValidationError("Set timeout_seconds in 1..600")
    if type(budget.get("max_model_runs")) is not int or budget["max_model_runs"] < len(suite["cases"]) * suite["runs_per_case"] * 2:
        raise ValidationError("max_model_runs must cover the complete paired design")
    # CLI has no dollar spending cap. Never pretend it enforces one.
    if "max_cost_usd" in budget:
        raise ValidationError("Codex CLI cannot enforce a dollar cap; use explicit run/time limits")
    mode = suite["conditions"].get("sandbox", "read-only")
    if mode not in ("read-only", "workspace-write"):
        raise ValidationError("Codex sandbox must be read-only or workspace-write")
    inputs = {}
    for case in suite["cases"]:
        if not isinstance(case.get("inputs", {}), dict) or not isinstance(case.get("output_artifacts", {}), dict):
            raise ValidationError("Case inputs and output_artifacts must be mappings")
        for relative, expected in case.get("inputs", {}).items():
            if input_root is None:
                raise ValidationError("Case input files require an explicit --inputs root")
            path = confined(input_root, relative)
            if path.stat().st_size > MAX_BYTES or digest(path) != expected:
                raise ValidationError("Input file missing, changed or oversized: " + relative)
            if relative.split("/")[0].casefold() in (".git", ".agents", ".codex") or Path(relative).name.upper() == "AGENTS.MD":
                raise ValidationError("Task inputs must not inject host configuration or instructions")
            inputs[relative] = (path, expected)
        for artifact_id, relative in case.get("output_artifacts", {}).items():
            if not isinstance(artifact_id, str) or not artifact_id or artifact_id == "answer":
                raise ValidationError("Output artifact ID must be nonempty; answer is reserved")
            confined(Path.cwd(), relative)
    executable = str(Path(executable or shutil.which("codex") or "").resolve())
    if not Path(executable).is_file():
        raise ValidationError("Codex CLI executable unavailable")
    checked = preflight(executable)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValidationError("Use a new empty Codex study directory")
    frozen_plugin = output / "plugin"
    package = snapshot(plugin, frozen_plugin)
    if package["plugin"] != suite["plugin"]:
        raise ValidationError("Suite plugin name/version differs from selected package")
    write_json(output / "suite.json", suite)
    freeze(suite, output / "protocol.lock.json")
    write_json(output / "snapshot.json", package)
    for relative, (source, expected) in inputs.items():
        target = output / "inputs" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if digest(target) != expected:
            raise ValidationError("Input changed during snapshot")
    # Counterbalance at pair level, without changing or adapting the task list.
    planned = schedule(suite)
    plan = {"backend": "codex-cli", "executable": executable, "preflight": checked,
            "input_files": {relative: expected for relative, (_, expected) in inputs.items()},
            "suite_sha256": suite_digest(suite), "plugin_files": package["files"], "schedule": planned,
            "limits": {"max_model_runs": budget["max_model_runs"], "timeout_seconds": budget["timeout_seconds"],
                       "settled_cost_usd": None, "dollar_cap_supported": False},
            "scope": "Native local CLI collection; model/plugin load identity still requires independent observation"}
    write_json(output / "plan.json", plan)
    return {"study": str(output), "plan_sha256": digest(output / "plan.json"), "planned_runs": len(planned), "model_calls": 0}


def parse_events(path):
    session = None
    messages = []
    usage = None
    completed = False
    errors = []
    tools = []
    try:
        events = load_records(path)
    except ValidationError as exc:
        return {"session_id": None, "output": None, "usage": None, "completed": False,
                "errors": [str(exc)], "tool_events": []}
    for event in events:
        kind = event.get("type")
        if kind == "thread.started":
            if session is not None:
                errors.append("Multiple thread identities in one planned execution")
            session = event.get("thread_id")
            if not isinstance(session, str) or not session.strip():
                errors.append("Invalid native session identity")
        elif kind == "turn.completed":
            if completed or session is None:
                errors.append("Completion duplicated or precedes native session")
            completed = True
            usage = event.get("usage")
        elif kind in ("turn.failed", "error"):
            errors.append(str(event.get("error", event.get("message", "Unknown Codex failure"))))
        elif kind == "item.completed":
            item = event.get("item", {})
            if not isinstance(item, dict):
                errors.append("Malformed native item")
            elif item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    messages.append(text)
                else:
                    errors.append("Malformed native answer")
            elif item.get("type") in ("command_execution", "mcp_tool_call", "tool_call"):
                tools.append(item)
    return {"session_id": session, "output": messages[-1] if messages else None, "usage": usage,
            "completed": completed and isinstance(session, str) and bool(messages) and not errors, "errors": errors, "tool_events": tools}


def _command(executable, model, workspace, output, sandbox="read-only"):
    return [executable, "-a", "never", "exec", "--json", "--ephemeral", "--color", "never",
            "--skip-git-repo-check", "--sandbox", sandbox, "--model", model,
            "--cd", str(workspace), "--output-last-message", str(output), "-"]


def _run(command, env, cwd, prompt, log, timeout):
    started = time.monotonic()
    process = None
    timed_out = False
    with Path(str(log) + ".jsonl").open("xb") as stdout, Path(str(log) + ".stderr").open("xb") as stderr:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=stdout,
                stderr=stderr, start_new_session=os.name != "nt", shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
            bind_tree(process)
            try:
                process.communicate(prompt.encode("utf-8"), timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                terminate_tree(process)
                process.wait(timeout=15)
            return {"exit_code": process.returncode, "timed_out": timed_out,
                    "duration_seconds": time.monotonic() - started}
        finally:
            if process is not None:
                close_tree(process)


def run(directory, expected_plan_sha256, auth_home):
    root = Path(directory).resolve()
    plan = load_json(root / "plan.json")
    suite = load_json(root / "suite.json")
    validate_suite(suite)
    if digest(root / "plan.json") != expected_plan_sha256 or suite_digest(suite) != plan["suite_sha256"]:
        raise ValidationError("Frozen plan or suite changed")
    if (plan.get("schedule") != schedule(suite) or plan.get("backend") != "codex-cli"
            or plan["limits"].get("max_model_runs") != suite["conditions"]["budget"].get("max_model_runs")
            or plan["limits"].get("timeout_seconds") != suite["conditions"]["budget"].get("timeout_seconds")):
        raise ValidationError("Execution schedule/limits must exactly match the frozen paired design")
    if hashes(root / "plugin") != plan["plugin_files"] or digest(plan["executable"]) != plan["preflight"]["executable_sha256"]:
        raise ValidationError("Frozen plugin or executable changed")
    if load_json(root / "protocol.lock.json")["suite_sha256"] != plan["suite_sha256"]:
        raise ValidationError("Frozen lock changed")
    for relative, expected in plan.get("input_files", {}).items():
        if digest(confined(root / "inputs", relative)) != expected:
            raise ValidationError("Frozen input bytes changed")
    auth = Path(auth_home).resolve() / "auth.json"
    if not auth.is_file():
        raise ValidationError("Explicit auth home must contain existing Codex auth.json; no credentials are invented")
    # Atomic claim. Crashes/unknown charges never automatically retry this plan.
    with (root / "execution-started.json").open("x", encoding="utf-8") as stream:
        json.dump({"started_at": now(), "plan_sha256": expected_plan_sha256,
                   "settled_cost_usd": None, "automatic_retry": False}, stream)
    records = []
    home_paths = []
    try:
        market = root / "marketplace"
        market.mkdir()
        (market / ".agents/plugins").mkdir(parents=True)
        (market / "plugins").mkdir()
        shutil.copytree(root / "plugin", market / "plugins/candidate")
        name = suite["plugin"]["name"]
        write_json(market / ".agents/plugins/marketplace.json", {"name": "value-lab-study",
            "interface": {"displayName": "Local paired study"}, "plugins": [{"name": name,
            "source": {"source": "local", "path": "./plugins/candidate"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}}]})
        for index, planned in enumerate(plan["schedule"]):
            label = f"{index + 1:04d}-{planned['case_id']}-{planned['arm']}"
            run_dir = root / "runs" / label
            workspace, home = run_dir / "workspace", run_dir / "home"
            workspace.mkdir(parents=True)
            (workspace / ".git").mkdir()  # Explicit project boundary; no inherited repository instructions.
            home.mkdir()
            home_paths.append(home)
            (home / "config.toml").write_text('cli_auth_credentials_store = "file"\n', encoding="utf-8")
            env = dict(os.environ, CODEX_HOME=str(home), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            # Never inherit API-key overrides into an account-authenticated study.
            for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY"):
                env.pop(key, None)
            case = next(c for c in suite["cases"] if c["id"] == planned["case_id"])
            for relative, expected in case.get("inputs", {}).items():
                target = confined(workspace, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(confined(root / "inputs", relative), target)
            setup = []
            setup_ok = True
            if planned["arm"] == "with":
                for args in (["plugin", "marketplace", "add", str(market), "--json"],
                             ["plugin", "add", name + "@value-lab-study", "--json"]):
                    try:
                        result = subprocess.run([plan["executable"], *args], cwd=workspace, env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                    except (OSError, subprocess.SubprocessError) as exc:
                        setup.append({"args": args, "exit_code": None, "error": str(exc)})
                        setup_ok = False
                        break
                    setup.append({"args": args, "exit_code": result.returncode,
                                  "stdout": result.stdout, "stderr": result.stderr})
                    if result.returncode:
                        setup_ok = False
                        break
            write_json(run_dir / "setup.json", setup)
            record = {**planned, "source": "codex", "suite_sha256": plan["suite_sha256"],
                "conditions": None, "requested_conditions": deepcopy(suite["conditions"]),
                "plugin_loaded": None, "session_id": None, "status": "error", "failure_kind": "infrastructure",
                "output": None, "cost": {"model_usd": None, "tool_usd": None, "human_minutes": None, "basis": "estimate"},
                "human_intervals": None, "import_issues": [
                    "CLI requested settings do not independently establish observed model/tools/conditions",
                    "Plugin installation is not proof of actual model-side loading or uncontaminated baseline"],
                "artifacts": {}, "input_sha256": dict(case.get("inputs", {}))}
            if setup_ok:
                command = _command(plan["executable"], suite["conditions"]["model"], workspace, run_dir / "answer.txt", suite["conditions"].get("sandbox", "read-only"))
                write_json(run_dir / "launch.json", {"command": command, "started_at": now(), "automatic_retry": False})
                (run_dir / "prompt.txt").write_text(case["prompt"], encoding="utf-8")
                shutil.copyfile(auth, home / "auth.json")
                try:
                    os.chmod(home / "auth.json", 0o600)
                    try:
                        receipt = _run(command, env, workspace, case["prompt"], run_dir / "events", plan["limits"]["timeout_seconds"])
                    except (OSError, subprocess.SubprocessError) as exc:
                        receipt = {"exit_code": None, "timed_out": False, "duration_seconds": None, "error": str(exc)}
                finally:
                    (home / "auth.json").unlink(missing_ok=True)
                observed = parse_events(run_dir / "events.jsonl")
                record.update(session_id=observed["session_id"], output=observed["output"],
                              duration_seconds=receipt["duration_seconds"], token_usage=observed["usage"])
                record["status"] = "timeout" if receipt["timed_out"] else ("completed" if receipt["exit_code"] == 0 and observed["completed"] and observed["output"] is not None else "error")
                record["error"] = "; ".join(observed["errors"]) or (None if record["status"] == "completed" else "CLI did not complete the planned run")
                if observed["output"] is not None:
                    (run_dir / "output.json").write_text(observed["output"], encoding="utf-8")
                    record["artifacts"]["answer"] = {"path": (run_dir / "output.json").relative_to(root).as_posix(), "sha256": digest(run_dir / "output.json")}
                for artifact_id, relative in case.get("output_artifacts", {}).items():
                    artifact = confined(workspace, relative)
                    if artifact.is_file() and artifact.stat().st_size <= MAX_BYTES:
                        record["artifacts"][artifact_id] = {"path": artifact.relative_to(root).as_posix(), "sha256": digest(artifact)}
                write_json(run_dir / "receipt.json", {**receipt, "session_id": observed["session_id"],
                    "turn_completed": observed["completed"], "token_usage": observed["usage"], "settled_cost_usd": None,
                    "tool_event_count": len(observed["tool_events"]), "source_sha256": digest(run_dir / "events.jsonl") if (run_dir / "events.jsonl").exists() else None})
            else:
                record["error"] = "Native plugin installation failed; model not launched"
            evidence = {p.name: digest(p) for p in run_dir.iterdir() if p.is_file()}
            collector_receipt = {"format": "pvl-codex-collection-1", "plan_sha256": expected_plan_sha256,
                "suite_sha256": plan["suite_sha256"], "planned": planned, "session_id": record["session_id"],
                "cli_version": plan["preflight"]["version"], "cli_sha256": plan["preflight"]["executable_sha256"],
                "plugin_files_sha256": suite_digest(plan["plugin_files"]), "input_sha256": record["input_sha256"],
                "files": evidence, "artifacts": record["artifacts"], "status": record["status"],
                "scope": "Collector file consistency only; actual model/plugin identity and costs remain separately required"}
            write_json(run_dir / "collection-receipt.json", collector_receipt)
            record["collection_receipt"] = {"path": (run_dir / "collection-receipt.json").relative_to(root).as_posix(),
                                            "sha256": digest(run_dir / "collection-receipt.json")}
            records.append(record)
            with (root / "runs.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            # Stop on infrastructure/unknown outcome, retaining remaining planned runs as missing.
            if record["status"] != "completed":
                break
    finally:
        for home in home_paths:
            (home / "auth.json").unlink(missing_ok=True)
        report = evaluate(suite, records, load_json(root / "protocol.lock.json"), artifact_root=root)
        write_reports(report, root / "report")
        write_json(root / "execution-summary.json", {"finished_at": now(), "recorded_runs": len(records),
            "completed_model_runs": sum(r["status"] == "completed" for r in records),
            "expected_runs": len(plan["schedule"]), "settled_cost_usd": None, "verdict": report["verdict"],
            "scope": "Real CLI attempts only; this is not independent host adoption or demonstrated benefit"})
    return load_json(root / "execution-summary.json")


def verify_collection(directory):
    """Verify local native evidence without filling in missing scientific provenance."""
    root = Path(directory).resolve()
    plan = load_json(root / "plan.json")
    suite = load_json(root / "suite.json")
    if suite_digest(suite) != plan["suite_sha256"] or plan["schedule"] != schedule(suite):
        raise ValidationError("Collection plan no longer matches suite")
    if (load_json(root / "protocol.lock.json").get("suite_sha256") != plan["suite_sha256"] or
            load_json(root / "execution-started.json").get("plan_sha256") != digest(root / "plan.json")):
        raise ValidationError("Executed plan or protocol lock changed")
    if hashes(root / "plugin") != plan["plugin_files"]:
        raise ValidationError("Collected plugin snapshot changed")
    for name, expected in plan.get("input_files", {}).items():
        if digest(confined(root / "inputs", name)) != expected:
            raise ValidationError("Collected input snapshot changed")
    records = load_records(root / "runs.jsonl")
    if len(records) > len(plan["schedule"]):
        raise ValidationError("More collected runs than planned")
    sessions = set()
    for i, record in enumerate(records):
        ref = record.get("collection_receipt")
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise ValidationError("Run lacks a collection receipt")
        path = confined(root, ref["path"])
        planned = plan["schedule"][i]
        run_dir = root / "runs" / f"{i + 1:04d}-{planned['case_id']}-{planned['arm']}"
        if path != run_dir / "collection-receipt.json":
            raise ValidationError("Collection receipt does not identify the planned run directory")
        if digest(path) != ref["sha256"]:
            raise ValidationError("Collection receipt changed")
        receipt = load_json(path)
        planned = plan["schedule"][i]
        if (receipt["plan_sha256"] != digest(root / "plan.json") or receipt["suite_sha256"] != plan["suite_sha256"]
                or receipt["planned"] != planned or any(record.get(k) != v for k, v in planned.items())
                or receipt["session_id"] != record["session_id"] or receipt["status"] != record["status"]
                or receipt["artifacts"] != record["artifacts"] or receipt["input_sha256"] != record["input_sha256"]):
            raise ValidationError("Collection receipt does not bind the record")
        for name, expected in receipt["files"].items():
            if digest(confined(path.parent, name)) != expected:
                raise ValidationError("Native execution evidence changed")
        for artifact in record["artifacts"].values():
            if digest(confined(root, artifact["path"])) != artifact["sha256"]:
                raise ValidationError("Collected output changed")
        if (record.get("source") != "codex" or record.get("suite_sha256") != plan["suite_sha256"] or
                record.get("requested_conditions") != suite["conditions"]):
            raise ValidationError("Record source or requested conditions changed")
        # The native event schema does not observe these fields. A later human
        # supplement must be a separate reviewed revision, never a silent edit.
        if record.get("conditions") is not None or record.get("plugin_loaded") is not None:
            raise ValidationError("Unobserved model/plugin identity was promoted from requested settings")
        if record.get("cost") != {"model_usd": None, "tool_usd": None, "human_minutes": None, "basis": "estimate"} or record.get("human_intervals") is not None:
            raise ValidationError("Unknown native costs or human time were silently replaced")
        required_issues = ["CLI requested settings do not independently establish observed model/tools/conditions",
                           "Plugin installation is not proof of actual model-side loading or uncontaminated baseline"]
        if record.get("import_issues") != required_issues:
            raise ValidationError("Native evidence limitations changed")
        case = next(c for c in suite["cases"] if c["id"] == planned["case_id"])
        if record["input_sha256"] != case.get("inputs", {}):
            raise ValidationError("Run input contract differs from frozen case")
        for name, expected in case.get("inputs", {}).items():
            if digest(confined(run_dir / "workspace", name)) != expected:
                raise ValidationError("Executed workspace input changed")
        if (run_dir / "home/auth.json").exists():
            raise ValidationError("Temporary credential copy was not removed")
        if "receipt.json" in receipt["files"]:
            native = parse_events(run_dir / "events.jsonl")
            process = load_json(run_dir / "receipt.json")
            expected_status = "timeout" if process["timed_out"] else "completed" if process["exit_code"] == 0 and native["completed"] else "error"
            for field, expected in (("output", native["output"]), ("session_id", native["session_id"]),
                                    ("token_usage", native["usage"]), ("status", expected_status),
                                    ("duration_seconds", process["duration_seconds"])):
                if suite_digest(record.get(field)) != suite_digest(expected):
                    raise ValidationError("Record differs from native execution evidence: " + field)
            if process["source_sha256"] != (digest(run_dir / "events.jsonl") if (run_dir / "events.jsonl").exists() else None):
                raise ValidationError("Native event commitment changed")
            if native["session_id"] in sessions:
                raise ValidationError("Native session reused")
            if native["session_id"] is not None:
                sessions.add(native["session_id"])
            answer = record["artifacts"].get("answer")
            if native["output"] is not None and (not answer or confined(root, answer["path"]).read_text(encoding="utf-8") != native["output"]):
                raise ValidationError("Scored answer differs from native output")
            if (run_dir / "prompt.txt").read_text(encoding="utf-8") != case["prompt"]:
                raise ValidationError("Executed prompt changed")
        elif record.get("output") is not None or record.get("session_id") is not None or record.get("status") != "error":
            raise ValidationError("Installation failure cannot supply a successful model result")
    return {"status": "LOCAL_BYTES_CONSISTENT", "records": len(records), "planned": len(plan["schedule"]),
            "missing": len(plan["schedule"]) - len(records), "complete": len(records) == len(plan["schedule"]),
            "observed_identity_authenticated": False, "benefit_established": False}
