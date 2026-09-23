"""Single-attempt native execution with frozen inputs and durable local evidence.

This adapter executes Claude's harness; it does not invent missing observations
from its aggregate JSON. No model is called while preparing or reading a study.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid

from .core import ValidationError, demo_records, demo_suite, evaluate, freeze, validate_suite, load_records, load_json, suite_digest
from .native import EVAL_DIR, build_command, export_claude, import_claude, native_report
from .report import write_reports
from .usage import build_usage_card, write_usage_card


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return load_json(path)


def save(path, value, *, exclusive=False):
    path = Path(path)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(data)
    else:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(data, encoding="utf-8")
        os.replace(temporary, path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_file(root, relative):
    root = Path(root).resolve()
    path = root / relative
    if any(p in ("..", "") for p in Path(relative).parts) or not path.resolve().is_relative_to(root):
        raise ValidationError("Path escapes the evidence directory")
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
           for p in [path, *path.parents] if p != root and p.is_relative_to(root)):
        raise ValidationError("Linked evidence paths are not supported")
    return path


def hashes(root):
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(Path(root).rglob("*"))
            if p.is_file() and safe_file(root, p.relative_to(root)).is_file()}


def resolve_claude(explicit=None):
    candidates = [Path(explicit)] if explicit else []
    if not explicit:
        found = shutil.which("claude")
        if found:
            candidates.append(Path(found))
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe")
    for candidate in candidates:
        if candidate.is_file() and (os.name != "nt" or candidate.suffix.lower() == ".exe"):
            return str(candidate.resolve())
    raise ValidationError("找不到 Claude 可执行程序；请安装 Claude Code，或启动工作台时指定 --claude 的 .exe 路径。")


def preflight(executable):
    results = []
    for arguments in (["--version"], ["plugin", "eval", "--help"]):
        result = subprocess.run([executable, *arguments], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=20, shell=False)
        if result.returncode:
            raise ValidationError("Claude 版本/评估接口检查失败：" + result.stderr[:500])
        results.append(result.stdout)
    version = re.search(r"(\d+)\.(\d+)\.(\d+)", results[0])
    if not version or tuple(map(int, version.groups())) < (2, 1, 269):
        raise ValidationError("需要 Claude Code 2.1.269 或更新版本")
    for flag in ("--json", "--trust-plugin", "--no-publish", "--max-cost-usd", "--ablation"):
        if flag not in results[1]:
            raise ValidationError("本机评估接口缺少 " + flag)
    return {"version": results[0].strip(), "checked_at": now(), "authentication_verified": False,
            "model_access_verified": False, "executable_sha256": digest(executable)}


EXCLUDED = {".git", ".venv", "venv", "node_modules", "__pycache__", "work", "dist", "build", "plugins", ".pytest_cache"}


def snapshot(source, destination):
    source = Path(source).resolve()
    if not source.is_dir() or not any((source / n).is_file() for n in ("plugin.json", ".claude-plugin/plugin.json")):
        raise ValidationError("请选择包含 plugin.json 或 .claude-plugin/plugin.json 的插件文件夹")
    if destination.resolve().is_relative_to(source) and destination.relative_to(source).parts[0] not in EXCLUDED:
        raise ValidationError("工作台数据目录不能嵌套在待测插件中；可使用插件 work/ 下的目录")
    manifest_path = source / ("plugin.json" if (source / "plugin.json").is_file() else ".claude-plugin/plugin.json")
    manifest = read(manifest_path)
    selected = []
    omitted = []
    total = 0
    for current, dirs, files in os.walk(source, followlinks=False):
        current = Path(current)
        for name in list(dirs):
            p = current / name
            if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
                raise ValidationError("插件含链接目录，无法冻结：" + str(p.relative_to(source)))
            if name in EXCLUDED or name == EVAL_DIR:
                dirs.remove(name)
                omitted.append(p.relative_to(source).as_posix())
        for name in files:
            p = current / name
            if p.is_symlink():
                raise ValidationError("插件含链接文件，无法冻结")
            if name == ".env" or name.startswith(".env.") or p.suffix.lower() in (".pem", ".key"):
                raise ValidationError("插件目录含凭据候选文件；请提供不含凭据的独立插件包")
            if p.suffix in (".pyc", ".pyo"):
                continue
            total += p.stat().st_size
            selected.append(p)
            if len(selected) > 5000 or total > 100 * 1024 * 1024:
                raise ValidationError("插件包超过 5000 文件或 100 MB；请使用独立发布包")
    destination.mkdir()
    for p in selected:
        target = destination / p.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
    return {"source": str(source), "plugin": {"name": manifest.get("name"), "version": manifest.get("version", "unknown")},
            "excluded_paths": omitted, "files": hashes(destination),
            "scope": "Frozen selected package bytes; excluded dependencies are not provisioned"}


def form_suite(data):
    """Small human-facing form; advanced clients may submit the full suite."""
    if "suite" in data:
        suite = deepcopy(data["suite"])
        validate_suite(suite)
        return suite
    cases = []
    for i, case in enumerate(data.get("cases", []), 1):
        kind = case.get("kind", "task")
        grader_type = case.get("grader_type", "contains")
        grader = {"id": "outcome", "type": grader_type, "dimension": "outcome", "weight": 1,
                  "critical": case.get("critical", False)}
        grader["rubric" if grader_type == "human" else "value"] = case.get("criterion", "")
        cases.append({"id": f"case-{i}", "cluster": case.get("cluster") or f"family-{i}",
                      "kind": kind, "prompt": case.get("prompt", ""), "graders": deepcopy(case.get("graders", [grader]))})
    suite = {"schema_version": 1, "id": "study-" + uuid.uuid4().hex[:10],
             "plugin": {"name": "pending-snapshot", "version": "unknown"}, "evidence_type": "local",
             "runs_per_case": data.get("runs", 3),
             "conditions": {"model": data.get("model", ""), "host": "claude-native-eval",
                            "environment": "native-isolated-workspace; MCP mocked; no shell grants",
                            "tools": ["Read", "Glob", "Grep", "Skill"],
                            "budget": {"max_cost_usd": data.get("budget_usd"), "max_turns": 10, "timeout_seconds": 180}},
             "policy": {"min_quality_delta": 0.1, "quality_floor": 0.8, "max_case_regression": 0,
                        "min_clusters": 2, "require_cost_saving": False, "require_cost_categories": True,
                        "human_hourly_usd": data.get("human_hourly_usd", 0)}, "cases": cases}
    validate_suite(suite)
    return suite


class Engine:
    def __init__(self, root, executable=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # Lifetime OS lock: releases on crash, prevents a second workbench from
        # treating another process's running jobs as interrupted.
        self.owner = (self.root / ".owner.lock").open("a+b")
        self.owner.seek(0)
        self.owner.write(b"0")
        self.owner.flush()
        self.owner.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.owner.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.owner.close()
            raise ValidationError("此数据目录已有工作台运行") from exc
        self.executable = executable
        self.mutex = threading.RLock()
        self.processes = {}
        self.stops = {}
        self.threads = []
        for path in self.root.glob("*/state.json"):
            state = read(path)
            if state["status"] in ("running", "stopping"):
                state.update(status="interrupted", error="工作台中断；子进程/费用状态未知。先核对原始结果，禁止自动重试。")
                save(path, state)

    def directory(self, job):
        if not re.fullmatch(r"[a-f0-9]{32}", job):
            raise ValidationError("Invalid study ID")
        path = safe_file(self.root, job)
        if not (path / "state.json").is_file():
            raise ValidationError("Study not found")
        return path

    def list(self):
        with self.mutex:
            return sorted([read(p) for p in self.root.glob("*/state.json")], key=lambda x: x["created_at"], reverse=True)

    def event(self, path, kind, **data):
        with (path / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": now(), "event": kind, **data}, ensure_ascii=False) + "\n")

    def prepare(self, data):
        with self.mutex:
            suite = form_suite(data)
            # This first backend deliberately exposes only the native read-only,
            # mocked environment. Never silently discard advanced tool grants.
            if set(suite["conditions"]["tools"]) - {"Read", "Glob", "Grep", "NotebookRead", "Skill", "TodoWrite"}:
                raise ValidationError("首版执行器仅支持只读工具与 MCP 模拟；写入、Shell、真实 MCP 请另建明确授权的执行适配器")
            maximum = suite["conditions"]["budget"].get("max_cost_usd")
            build_command(".", ".", suite["conditions"]["model"], maximum, suite["runs_per_case"])
            executable = resolve_claude(self.executable)
            check = preflight(executable)
            job = uuid.uuid4().hex
            path = self.root / job
            path.mkdir()
            try:
                package = snapshot(data.get("plugin_path", ""), path / "plugin")
                suite["plugin"] = package["plugin"]
                validate_suite(suite)
                export = export_claude(suite, path / "export", path / "plugin")
                shutil.copytree(path / "export/evals", path / "plugin" / EVAL_DIR)
                save(path / "suite.json", suite, exclusive=True)
                from .scoring import inspect_rules
                save(path / "scoring-check.json", inspect_rules(suite), exclusive=True)
                freeze(suite, path / "protocol.lock.json")
                command = export["command"]
                command[0] = executable
                command += ["--json", str(path / "native-result.json"), "--trust-plugin", "--verbose", "--keep-temp"]
                command[1:1] = ["--debug-file", str(path / "trace.log")]
                save(path / "snapshot.json", package, exclusive=True)
                frozen = {"command": command, "preflight": check, "files": {
                    **{"plugin/" + k: v for k, v in hashes(path / "plugin").items()},
                    "suite.json": digest(path / "suite.json"), "protocol.lock.json": digest(path / "protocol.lock.json")},
                    "timeout_seconds": min(86400, len(suite["cases"]) * suite["runs_per_case"] * 2 *
                                           (suite["conditions"]["budget"].get("timeout_seconds", 180) + 120)),
                    "warnings": export["warnings"], "estimated_ceiling_usd": maximum}
                save(path / "frozen.json", frozen, exclusive=True)
                state = {"id": job, "created_at": now(), "status": "frozen", "mode": "claude",
                         "plugin": suite["plugin"], "planned_runs": len(suite["cases"]) * suite["runs_per_case"] * 2,
                         "estimated_ceiling_usd": maximum, "estimated_cost_usd": None, "settled_cost_usd": None,
                         "frozen_sha256": digest(path / "frozen.json"), "source_plugin": package["source"],
                         "error": None, "verdict": None}
                save(path / "state.json", state)
                self.event(path, "frozen", model_calls=0)
                return self.detail(job)
            except Exception as exc:
                save(path / "preparation-error.json", {"error": str(exc), "model_calls": 0}, exclusive=True)
                raise

    def demo(self):
        with self.mutex:
            job = uuid.uuid4().hex
            path = self.root / job
            path.mkdir()
            suite = demo_suite()
            records = demo_records(suite)
            save(path / "suite.json", suite, exclusive=True)
            lock = freeze(suite, path / "protocol.lock.json")
            self.products(path, suite, records, lock)
            state = {"id": job, "created_at": now(), "status": "completed", "mode": "synthetic",
                     "plugin": suite["plugin"], "planned_runs": len(records), "estimated_cost_usd": None,
                     "settled_cost_usd": None, "real_model_calls": 0, "verdict": "SIMULATION_ONLY", "error": None}
            save(path / "state.json", state)
            self.event(path, "synthetic_demo", real_model_calls=0)
            self.seal(path)
            return self.detail(job)

    def products(self, path, suite, records, lock):
        with (path / "runs.jsonl").open("x", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        report = evaluate(suite, records, lock)
        write_reports(report, path / "report")
        write_usage_card(build_usage_card(suite, records, lock), path / "usage-card")
        return report

    def verify(self, path, state):
        if digest(path / "frozen.json") != state["frozen_sha256"]:
            raise ValidationError("冻结计划已改变，不能启动；请创建新评估")
        frozen = read(path / "frozen.json")
        observed = {"plugin/" + k: v for k, v in hashes(path / "plugin").items()}
        observed.update({k: digest(path / k) for k in ("suite.json", "protocol.lock.json")})
        if observed != frozen["files"]:
            raise ValidationError("冻结文件已改变，不能启动；请创建新评估")
        if digest(frozen["command"][0]) != frozen["preflight"]["executable_sha256"]:
            raise ValidationError("Claude 执行器已更新；请重新冻结方案")
        return frozen

    def start(self, job, approval):
        with self.mutex:
            path = self.directory(job)
            state = read(path / "state.json")
            if state["status"] != "frozen":
                raise ValidationError("每个冻结方案只能启动一次；不会重跑或覆盖已有执行")
            if any(s["status"] in ("running", "stopping") for s in self.list()):
                raise ValidationError("已有评估运行中，请等待结束")
            if any(s["status"] == "interrupted" for s in self.list()):
                raise ValidationError("存在状态不明的中断评估；请先核对其子进程和账单，不能自动继续付费运行")
            if approval.get("frozen_sha256") != state["frozen_sha256"] or approval.get("authorize_execution") is not True:
                raise ValidationError("启动需要针对当前冻结方案的明确授权")
            frozen = self.verify(path, state)
            save(path / "authorization.json", {"at": now(), "frozen_sha256": state["frozen_sha256"],
                 "estimated_ceiling_usd": frozen["estimated_ceiling_usd"], "plugin_trust": True,
                 "scope": "Run this snapshot once using the configured Claude account; prompts/plugin sent to its model provider; hooks may execute locally; estimate may overrun; no publishing"}, exclusive=True)
            state.update(status="running", started_at=now())
            save(path / "state.json", state)
            stop = threading.Event()
            self.stops[job] = stop
            thread = threading.Thread(target=self._run, args=(job, frozen, stop), daemon=True)
            self.threads.append(thread)
            thread.start()
            return state

    @staticmethod
    def terminate(process):
        from .processes import terminate_tree
        terminate_tree(process)

    def stop(self, job):
        with self.mutex:
            path = self.directory(job)
            state = read(path / "state.json")
            if state["status"] not in ("running", "stopping"):
                raise ValidationError("此评估未在运行")
            self.stops[job].set()
            state["status"] = "stopping"
            save(path / "state.json", state)
            self.event(path, "stop_requested")
            return state

    def _run(self, job, frozen, stop):
        path = self.root / job
        process = None
        exit_code = None
        outcome = "failed"
        error = None
        started = time.monotonic()
        try:
            (path / "tmp").mkdir()
            environment = dict(os.environ)
            environment.update(TMP=str(path / "tmp"), TEMP=str(path / "tmp"), TMPDIR=str(path / "tmp"))
            # Credential values are inherited for Claude, never serialized.
            with (path / "stdout.log").open("xb") as stdout, (path / "stderr.log").open("xb") as stderr:
                process = subprocess.Popen(frozen["command"], cwd=path / "plugin", env=environment,
                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, shell=False,
                    start_new_session=os.name != "nt",
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
                from .processes import bind_tree
                bind_tree(process)
                with self.mutex:
                    self.processes[job] = process
                    self.event(path, "process_started", pid=process.pid)
                while process.poll() is None:
                    if stop.wait(0.15) or time.monotonic() - started > frozen["timeout_seconds"]:
                        outcome = "cancelled" if stop.is_set() else "timed_out"
                        self.terminate(process)
                        process.wait(timeout=15)
                        break
                exit_code = process.returncode
                if outcome not in ("cancelled", "timed_out"):
                    outcome = "collected" if (path / "native-result.json").is_file() else "failed"
        except Exception as exc:
            error = str(exc)
            if process and process.poll() is None:
                try:
                    self.terminate(process)
                    process.wait(timeout=15)
                except Exception:
                    outcome = "interrupted"
        finally:
            if process is not None:
                try:
                    from .processes import close_tree
                    close_tree(process)
                except Exception as exc:
                    outcome, error = "interrupted", "Process cleanup unconfirmed: " + str(exc)
            with self.mutex:
                state = read(path / "state.json")
                state.update(status=outcome, finished_at=now(), exit_code=exit_code, error=error,
                             duration_seconds=round(time.monotonic() - started, 3))
                save(path / "execution-receipt.json", {**state, "command": frozen["command"],
                     "observation_scope": "Local process launch/exit and captured files; not per-run session or plugin-load attestation",
                     "settled_cost_usd": None}, exclusive=True)
                try:
                    suite = read(path / "suite.json")
                    records = []
                    if (path / "native-result.json").is_file():
                        result = read(path / "native-result.json")
                        records = import_claude(result, suite)
                        write_reports(native_report(result), path / "native-diagnostic")
                        state.update(estimated_cost_usd=result.get("costUsd"), partial=result.get("partial", False),
                                     observed_runs=len(records))
                        if state["status"] == "collected":
                            state["status"] = "partial" if result.get("partial") else "needs_evidence"
                    else:
                        state["error"] = state["error"] or "执行器没有返回 JSON 结果；请检查 stderr.log，费用未知。"
                    report = self.products(path, suite, records, read(path / "protocol.lock.json"))
                    state["verdict"] = report["verdict"]
                except Exception as exc:
                    state.update(error="证据解析失败，原始文件已保留：" + str(exc))
                    if state["status"] not in ("cancelled", "timed_out", "interrupted"):
                        state["status"] = "collection_failed"
                save(path / "state.json", state)
                self.event(path, "execution_finished", status=state["status"], exit_code=exit_code)
                try:
                    self.seal(path)
                except Exception as exc:
                    state.update(status="collection_failed", error="证据封存失败：" + str(exc))
                    save(path / "state.json", state)
                self.processes.pop(job, None)

    def seal(self, path):
        files = {}
        for p in path.rglob("*"):
            if p.is_file() and p.relative_to(path).parts[0] not in ("plugin", "tmp") and p.name not in ("state.json", "evidence-manifest.json"):
                safe_file(path, p.relative_to(path))
                files[p.relative_to(path).as_posix()] = digest(p)
        save(path / "evidence-manifest.json", {"sealed_at": now(), "files": files,
             "scope": "Local byte consistency only; no independent execution or authorship proof; temporary workspaces retained separately"}, exclusive=True)

    def detail(self, job):
        with self.mutex:
            path = self.directory(job)
            state = read(path / "state.json")
            data = {"state": state, "suite": read(path / "suite.json"), "files": []}
            for name in ("frozen.json", "snapshot.json", "report/report.json", "native-diagnostic/report.json", "usage-card/card.json"):
                if (path / name).is_file():
                    data[name] = read(path / name)
            for p in path.rglob("*"):
                if p.is_file() and p.relative_to(path).parts[0] not in ("plugin", "tmp") and p.name != "state.tmp":
                    data["files"].append(p.relative_to(path).as_posix())
            if (path / "evidence-manifest.json").is_file():
                manifest = read(path / "evidence-manifest.json")
                data["integrity"] = {"scope": manifest["scope"], "mismatches": [name for name, h in manifest["files"].items()
                    if not safe_file(path, name).is_file() or digest(path / name) != h]}
            revision = state.get("latest_analysis_id")
            if revision:
                analysis_path = safe_file(path, "analyses/" + revision)
                manifest = read(analysis_path / "manifest.json")
                data["analysis_integrity_issues"] = [name for name, h in manifest["files"].items()
                    if not safe_file(path, name).is_file() or digest(path / name) != h]
                data["analysis"] = {"id": revision, "ledger": read(analysis_path / "cost-ledger.json"),
                                    "report": read(analysis_path / "report/report.json"),
                                    "card": read(analysis_path / "usage-card/card.json")}
            return data

    def study_inputs(self, job):
        detail = self.detail(job)
        path = self.directory(job)
        package = detail.get("snapshot.json", {})
        context = {"plugin_sha256": suite_digest(package["files"]) if package.get("files") else None,
                   "claude_version": detail.get("frozen.json", {}).get("preflight", {}).get("version"),
                   "integrity_issues": detail.get("integrity", {}).get("mismatches", []) + detail.get("analysis_integrity_issues", [])}
        return {"suite": detail["suite"], "records": load_records(path / "runs.jsonl") if (path / "runs.jsonl").is_file() else [],
                "lock": read(path / "protocol.lock.json"), "cost_ledger": detail.get("analysis", {}).get("ledger"), "context": context}

    def compare(self, before, after):
        from .comparison import compare_studies
        with self.mutex:
            if before == after:
                raise ValidationError("请选择两项不同的研究")
            result = compare_studies(self.study_inputs(before), self.study_inputs(after))
            result["study_ids"] = {"before": before, "after": after}
            return result

    def team_records(self):
        from .team_record import validate_team_record
        with self.mutex:
            root = self.root / "team-records"
            rows = []
            if root.exists():
                for path in root.glob("*/record.json"):
                    record = validate_team_record(read(path))
                    entry = record["entries"][-1]
                    rows.append({"id": path.parent.name, "plugin_name": record["plugin_name"],
                                 "revision": entry["revision"], "choice": entry["decision"]["choice"],
                                 "status": entry["card"]["status"], "study_id": entry["card"]["study_id"]})
            return sorted(rows, key=lambda row: (row["plugin_name"], row["revision"], row["id"]))

    def team_record(self, job, decision, previous_id=None, research_context=None):
        from .team_record import build_team_record, write_team_record
        with self.mutex:
            inputs = self.study_inputs(job)
            if inputs["context"]["integrity_issues"]:
                raise ValidationError("原始评测文件完整性检查未通过，不能写入团队使用记录")
            previous = None
            if previous_id is not None:
                if not isinstance(previous_id, str) or not re.fullmatch(r"[a-f0-9]{32}", previous_id):
                    raise ValidationError("Invalid prior team record ID")
                old = safe_file(self.root / "team-records", previous_id + "/record.json")
                if not old.is_file():
                    raise ValidationError("Prior team record not found")
                previous = read(old)
            record = build_team_record(inputs["suite"], inputs["records"], inputs["lock"], decision,
                                       previous=previous, research_context=research_context,
                                       cost_ledger=inputs["cost_ledger"])
            ident = uuid.uuid4().hex
            output = self.root / "team-records" / ident
            files = write_team_record(record, output)
            return {"id": ident, "revision": len(record["entries"]), "record": record,
                    "files": files, "model_calls": 0, "external_actions": 0}

    def costs(self, job):
        from .costs import analyze_costs
        with self.mutex:
            inputs = self.study_inputs(job)
            report = evaluate(inputs["suite"], inputs["records"], inputs["lock"], inputs["cost_ledger"])
            state = read(self.directory(job) / "state.json")
            result = analyze_costs(inputs["suite"], inputs["records"], inputs["cost_ledger"], report, state.get("estimated_cost_usd"))
            if inputs["context"]["integrity_issues"]:
                result["saving_claim_eligible"] = False
                result["issues"].append("来源文件完整性检查未通过")
            return result

    def revise_costs(self, job, ledger):
        with self.mutex:
            path = self.directory(job)
            state = read(path / "state.json")
            if state["status"] in ("frozen", "running", "stopping", "interrupted"):
                raise ValidationError("请等待执行结束并确认状态，再补充成本；不修改冻结方案")
            inputs = self.study_inputs(job)
            if inputs["context"]["integrity_issues"]:
                raise ValidationError("已有证据被改动，不能把补充成本当作修复原始证据")
            report = evaluate(inputs["suite"], inputs["records"], inputs["lock"], ledger)
            card = build_usage_card(inputs["suite"], inputs["records"], inputs["lock"], ledger)
            revision = uuid.uuid4().hex
            destination = path / "analyses" / revision
            destination.mkdir(parents=True)
            save(destination / "cost-ledger.json", ledger, exclusive=True)
            write_reports(report, destination / "report")
            write_usage_card(card, destination / "usage-card")
            bound = {name: digest(path / name) for name in ("suite.json", "runs.jsonl", "protocol.lock.json")}
            bound.update({"analyses/" + revision + "/" + name: h for name, h in hashes(destination).items()})
            save(destination / "manifest.json", {"created_at": now(), "previous_analysis": state.get("latest_analysis_id"),
                 "files": bound, "scope": "Additional declared costs; original execution files preserved"}, exclusive=True)
            state.update(latest_analysis_id=revision, latest_verdict=report["verdict"])
            save(path / "state.json", state)
            return self.detail(job)

    def close(self):
        for stop in self.stops.values():
            stop.set()
        for thread in self.threads:
            thread.join(timeout=35)
        if any(thread.is_alive() for thread in self.threads):
            raise RuntimeError("Execution shutdown incomplete; keep data-directory lock")
        self.owner.close()
