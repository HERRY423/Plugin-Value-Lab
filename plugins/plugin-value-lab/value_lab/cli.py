"""Local CLI; workbench starts evaluations only after explicit UI authorization."""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .core import (ValidationError, demo_records, demo_suite, evaluate, freeze,
                   load_json, load_records, suite_digest, validate_suite, write_json)
from .report import write_reports


def _emit(data):
    print(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))


def write_records(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")


def _new_directory(path):
    path = Path(path)
    if path.exists() and any(path.iterdir()):
        raise ValidationError("Output directory must be empty; preserve previous study revisions")
    path.mkdir(parents=True, exist_ok=True)
    return path


def doctor():
    claude = shutil.which("claude")
    version = None
    if claude:
        try:
            version = subprocess.run([claude, "--version"], capture_output=True, text=True,
                                     timeout=15, shell=False).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            version = f"Version check unavailable: {exc}"
    return {"engine": __version__, "python": sys.version.split()[0], "python_executable": sys.executable,
            "offline_engine_ready": sys.version_info >= (3, 11),
            "optional_mcp_available": importlib.util.find_spec("mcp") is not None,
            "claude_executable": claude, "claude_version": version,
            "native_eval_executed": False, "host_plugin_installation_verified": False,
            "notes": ["Core, reports and review packets use only the Python standard library.",
                      "Native Windows shell-granting Claude evals need WSL2; read-only cases do not grant shell."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Plugin Value Lab — evidence-bounded paired evaluation")
    parser.add_argument("--version", action="version", version=__version__)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "demo"):
        p = subs.add_parser(name)
        p.add_argument("--output", required=True)
    p = subs.add_parser("freeze")
    p.add_argument("suite")
    p.add_argument("--lock", required=True)
    p = subs.add_parser("evaluate")
    p.add_argument("suite")
    p.add_argument("records")
    p.add_argument("--lock")
    p.add_argument("--output", required=True)
    p.add_argument("--gate", action="store_true")
    p.add_argument("--cost-ledger")
    p = subs.add_parser("check-rules")
    p.add_argument("suite")
    p.add_argument("--samples")
    p.add_argument("--output")
    p = subs.add_parser("compare-studies")
    p.add_argument("before", help="JSON object containing suite, records, lock and optional cost_ledger/context")
    p.add_argument("after")
    p.add_argument("--output", required=True)
    p = subs.add_parser("export-claude")
    p.add_argument("suite")
    p.add_argument("--output", required=True)
    p.add_argument("--plugin", required=True)
    p = subs.add_parser("import-claude")
    p.add_argument("result")
    p.add_argument("--suite", required=True)
    p.add_argument("--output", required=True)
    p = subs.add_parser("native-report")
    p.add_argument("result")
    p.add_argument("--output", required=True)
    p = subs.add_parser("review-pack")
    p.add_argument("suite")
    p.add_argument("records")
    p.add_argument("--output", required=True)
    p = subs.add_parser("apply-reviews")
    p.add_argument("suite")
    p.add_argument("records")
    p.add_argument("--mapping", required=True)
    p.add_argument("--decisions", required=True)
    p.add_argument("--output", required=True)
    p = subs.add_parser("plan-use")
    p.add_argument("context")
    p.add_argument("--output", required=True)
    p = subs.add_parser("usage-card")
    p.add_argument("suite")
    p.add_argument("records")
    p.add_argument("--lock")
    p.add_argument("--cost-ledger")
    p.add_argument("--output", required=True)
    p = subs.add_parser("research-plan", help="Validate research gaps and plan evidence-linked next tests")
    p.add_argument("context")
    p.add_argument("--output", required=True)
    p = subs.add_parser("research-example", help="Emit a synthetic research context; no observations")
    p = subs.add_parser("research-compare", help="Compare research context revisions, not scientific truth")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--output", required=True)
    p = subs.add_parser("research-followup", help="Locate directions to revisit after a submitted result")
    p.add_argument("context")
    p.add_argument("update")
    p.add_argument("--output", required=True)
    p = subs.add_parser("team-card", help="Create a new immutable team usage-card revision")
    p.add_argument("suite")
    p.add_argument("records")
    p.add_argument("--lock")
    p.add_argument("--cost-ledger")
    p.add_argument("--decision", required=True, help="JSON with actor, choice and rationale")
    p.add_argument("--research", help="Current research context JSON")
    p.add_argument("--previous", help="Previous team record JSON; omit for the first revision")
    p.add_argument("--output", required=True)
    subs.add_parser("doctor")
    subs.add_parser("serve")
    p = subs.add_parser("workbench")
    p.add_argument("--data", default="work/workbench")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--claude")
    args = parser.parse_args(argv)
    try:
        if args.command in ("init", "demo"):
            out = _new_directory(args.output)
            suite = demo_suite()
            write_json(out / "suite.json", suite)
            if args.command == "init":
                write_records(out / "runs.jsonl", [])
                (out / "START.md").write_text(
                    "# 先定义问题，再采集结果\n\n这是带教学用例的空观测项目，没有任何真实运行。\n"
                    "编辑 suite.json 中插件版本、实际模型/宿主/工具/环境/预算、任务、阈值和评分规则。\n"
                    "教学默认 evidence_type=synthetic；真实研究须在冻结前明确设置 local 或 external。\n"
                    "冻结后再采集两组新会话；原始输出和失败都写入 runs.jsonl。不要复制模拟观察充当实测。\n",
                    encoding="utf-8")
                _emit({"suite": str(out / "suite.json"), "records": str(out / "runs.jsonl"),
                       "observations": 0, "frozen": False})
            else:
                records = demo_records(suite)
                write_records(out / "runs.jsonl", records)
                lock = freeze(suite, out / "protocol.lock.json")
                report = evaluate(suite, records, lock)
                _emit({"verdict": report["verdict"], "files": write_reports(report, out),
                       "real_model_calls": 0, "real_human_observations": 0})
        elif args.command == "freeze":
            _emit(freeze(load_json(args.suite), args.lock))
        elif args.command == "evaluate":
            report = evaluate(load_json(args.suite), load_records(args.records), load_json(args.lock) if args.lock else None,
                              load_json(args.cost_ledger) if args.cost_ledger else None)
            _emit({"verdict": report["verdict"], "files": write_reports(report, args.output),
                   "blocker_count": len(report["blockers"])})
            if args.gate:
                return 0 if report["verdict"] == "PROMISING_LOCAL_SIGNAL" else (2 if report["verdict"] in ("SIMULATION_ONLY", "INSUFFICIENT_EVIDENCE") else 1)
        elif args.command == "export-claude":
            from .native import export_claude
            _emit(export_claude(load_json(args.suite), args.output, args.plugin))
        elif args.command == "import-claude":
            from .native import import_claude
            native_result = load_json(args.result)
            records = import_claude(native_result, load_json(args.suite))
            sidecar = Path(str(args.output) + ".native-source.json")
            if sidecar.exists():
                raise ValidationError("Native source sidecar already exists; choose a fresh import destination")
            write_records(args.output, records)
            write_json(sidecar, native_result)
            _emit({"records": len(records), "output": args.output, "status": "DIAGNOSTIC_IMPORT_REQUIRES_OBSERVED_EVIDENCE"})
        elif args.command == "native-report":
            from .native import native_report
            _emit(write_reports(native_report(load_json(args.result)), args.output))
        elif args.command == "review-pack":
            from .review import review_pack
            _emit(review_pack(load_json(args.suite), load_records(args.records), args.output))
        elif args.command == "apply-reviews":
            from .review import apply_reviews
            records = apply_reviews(load_json(args.suite), load_records(args.records), load_json(args.mapping), load_records(args.decisions))
            write_records(args.output, records)
            _emit({"output": args.output, "records": len(records), "source_records_preserved": True})
        elif args.command == "doctor":
            _emit(doctor())
        elif args.command == "plan-use":
            from .workflow import plan_plugin_use, write_plan
            plan = plan_plugin_use(load_json(args.context))
            _emit({"route": plan["route"], "executed": False, "files": write_plan(plan, args.output)})
        elif args.command == "usage-card":
            from .usage import build_usage_card, write_usage_card
            card = build_usage_card(load_json(args.suite), load_records(args.records), load_json(args.lock) if args.lock else None,
                                    load_json(args.cost_ledger) if args.cost_ledger else None)
            _emit({"status": card["status"], "verdict": card["verdict"], "files": write_usage_card(card, args.output)})
        elif args.command == "serve":
            from .server import serve
            serve()
        elif args.command == "research-plan":
            from .research import diagnose_research, write_research
            plan = diagnose_research(load_json(args.context))
            _emit({"status": plan["status"], "files": write_research(plan, args.output), "external_calls": 0})
        elif args.command == "research-example":
            from .research import research_example
            _emit(research_example())
        elif args.command == "research-compare":
            from .research import compare_research
            result = compare_research(load_json(args.before), load_json(args.after))
            if Path(args.output).exists():
                raise ValidationError("Output exists; preserve previous research comparisons")
            write_json(args.output, result)
            _emit({"status": result["status"], "output": args.output})
        elif args.command == "research-followup":
            from .research import assess_research_update
            result = assess_research_update(load_json(args.context), load_json(args.update))
            if Path(args.output).exists():
                raise ValidationError("Output exists; preserve previous research followups")
            write_json(args.output, result)
            _emit({"status": result["status"], "affected_direction_ids": result["affected_direction_ids"], "output": args.output})
        elif args.command == "team-card":
            from .team_record import build_team_record, write_team_record
            record = build_team_record(load_json(args.suite), load_records(args.records),
                                       load_json(args.lock) if args.lock else None, load_json(args.decision),
                                       previous=load_json(args.previous) if args.previous else None,
                                       research_context=load_json(args.research) if args.research else None,
                                       cost_ledger=load_json(args.cost_ledger) if args.cost_ledger else None)
            _emit({"revision": len(record["entries"]), "files": write_team_record(record, args.output),
                   "external_actions": 0})
        elif args.command == "workbench":
            from .workbench import serve as workbench
            workbench(args.data, args.port, args.claude)
        elif args.command == "check-rules":
            from .scoring import inspect_rules
            result = inspect_rules(load_json(args.suite), load_json(args.samples) if args.samples else None)
            if args.output:
                if Path(args.output).exists():
                    raise ValidationError("Output exists; preserve previous rule checks")
                write_json(args.output, result)
            _emit(result)
            return 0 if result["valid"] else 2
        elif args.command == "compare-studies":
            from .comparison import compare_studies
            result = compare_studies(load_json(args.before), load_json(args.after))
            if Path(args.output).exists():
                raise ValidationError("Output exists; preserve previous comparisons")
            write_json(args.output, result)
            _emit({"status": result["status"], "output": args.output, "blockers": result["blockers"]})
        return 0
    except (ValidationError, OSError, TypeError) as exc:
        print(json.dumps({"error": str(exc), "status": "INVALID_INPUT"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
