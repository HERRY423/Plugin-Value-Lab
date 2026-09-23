"""Immutable, local revisions of a team's bounded plugin-use guidance.

Each revision carries the complete prior record and a recomputed usage card.
This is an inspectable decision history, not authenticated signatures or proof
that the submitted runs and human decisions occurred.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from .core import ValidationError, suite_digest, write_json
from .research import compare_research, diagnose_research
from .usage import _markdown, build_usage_card


CHOICES = {"undecided", "trial", "keep", "pause", "retire"}


def _decision(value):
    if not isinstance(value, dict) or set(value) != {"actor", "choice", "rationale"}:
        raise ValidationError("decision requires actor, choice and rationale")
    if not all(isinstance(value[k], str) and value[k].strip() and len(value[k]) <= 10000
               for k in ("actor", "choice", "rationale")):
        raise ValidationError("decision fields must be nonempty bounded text")
    if value["choice"] not in CHOICES:
        raise ValidationError("decision.choice must be undecided, trial, keep, pause or retire")
    return deepcopy(value)


def _entry_digest(entry):
    return suite_digest({key: value for key, value in entry.items() if key != "entry_sha256"})


def validate_team_record(record):
    if not isinstance(record, dict) or record.get("schema_version") != 1 or record.get("type") != "team_usage_record":
        raise ValidationError("Expected a team usage record")
    if set(record) != {"schema_version", "type", "plugin_name", "entries", "limitations"}:
        raise ValidationError("Unexpected team record fields")
    entries = record["entries"]
    if not isinstance(entries, list) or not entries:
        raise ValidationError("Team record needs at least one entry")
    previous_hash = None
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or set(entry) != {"revision", "previous_sha256", "entry_sha256", "card", "research_context", "research_plan", "decision", "change"}:
            raise ValidationError(f"Invalid team record entry {index}")
        if entry["revision"] != index or entry["previous_sha256"] != previous_hash:
            raise ValidationError("Team record revision chain is inconsistent")
        if entry["entry_sha256"] != _entry_digest(entry):
            raise ValidationError("Team record entry digest is inconsistent")
        card = entry["card"]
        if not isinstance(card, dict) or card.get("type") != "plugin_usage_card" or card.get("plugin", {}).get("name") != record["plugin_name"]:
            raise ValidationError("Team record card does not match its plugin")
        _decision(entry["decision"])
        if entry["research_context"] is None:
            if entry["research_plan"] is not None:
                raise ValidationError("Research plan has no context")
        else:
            plan = diagnose_research(entry["research_context"])
            if suite_digest(plan) != suite_digest(entry["research_plan"]):
                raise ValidationError("Research plan does not match its context")
        previous_hash = entry["entry_sha256"]
    return record


def build_team_record(suite, records, lock, decision, *, previous=None, research_context=None, cost_ledger=None):
    """Add one explicit revision; never infer adoption from a positive score."""
    card = build_usage_card(suite, records, lock, cost_ledger)
    declared_decision = _decision(decision)
    research_plan = diagnose_research(research_context) if research_context is not None else None
    if previous is not None:
        validate_team_record(previous)
        if previous["plugin_name"] != card["plugin"]["name"]:
            raise ValidationError("A team record cannot switch plugins")
        old_entry = previous["entries"][-1]
        old_card = old_entry["card"]
        old_context = old_entry["research_context"]
        if research_context is None and old_context is not None:
            # An omitted context must never silently erase a previous research
            # scope and make the card appear independent of that question.
            research_context = deepcopy(old_context)
            research_plan = diagnose_research(research_context)
        research_change = (compare_research(old_context, research_context)
                           if old_context is not None and research_context is not None
                           and suite_digest(old_context) != suite_digest(research_context) else None)
        changed_conditions = old_card["scope"]["conditions_sha256"] != card["scope"]["conditions_sha256"]
        changed_tasks = old_card["scope"]["case_ids"] != card["scope"]["case_ids"]
        changed_study = old_card["scope"]["suite_sha256"] != card["scope"]["suite_sha256"]
        changed_evidence = old_card["scope"]["records_sha256"] != card["scope"]["records_sha256"] or old_card["scope"].get("cost_ledger_sha256") != card["scope"].get("cost_ledger_sha256")
        changed_research = old_context is None and research_context is not None or research_change is not None
        change = {"conditions_changed": changed_conditions, "tasks_changed": changed_tasks,
                  "study_changed": changed_study, "evidence_changed": changed_evidence,
                  "research_changed": changed_research, "research_comparison": research_change,
                  "previous_guidance_reassessment_required": any((changed_conditions, changed_tasks, changed_study, changed_evidence, changed_research)),
                  "previous_guidance_superseded": True,
                  "interpretation": "Prior guidance remains in history; current guidance is recomputed from the new submitted inputs. Changes do not prove improvement."}
        entries = deepcopy(previous["entries"])
        prior_hash = old_entry["entry_sha256"]
    else:
        change = {"conditions_changed": False, "tasks_changed": False, "study_changed": False,
                  "evidence_changed": False, "research_changed": False, "research_comparison": None,
                  "previous_guidance_reassessment_required": False, "previous_guidance_superseded": False,
                  "interpretation": "Initial team record; no earlier guidance was submitted."}
        entries = []
        prior_hash = None
    entry = {"revision": len(entries) + 1, "previous_sha256": prior_hash,
             "card": card, "research_context": deepcopy(research_context),
             "research_plan": research_plan, "decision": declared_decision, "change": change}
    entry["entry_sha256"] = _entry_digest(entry)
    entries.append(entry)
    result = {"schema_version": 1, "type": "team_usage_record", "plugin_name": card["plugin"]["name"],
              "entries": entries, "limitations": [
                  "This record is a local revision history; hashes detect accidental changes but do not authenticate people, sources or execution.",
                  "A team decision is a submitted statement, not permission to install, expand access, publish or execute research.",
                  "A new card does not validate prior claims or establish general benefit; each revision retains its own conditions and evidence limits.",
              ]}
    return validate_team_record(result)


def write_team_record(record, output_dir):
    validate_team_record(record)
    root = Path(output_dir)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValidationError("Team record output directory must be absent or empty")
    entry = record["entries"][-1]
    lines = ["# 团队插件使用记录", "", f"插件：{_markdown(record['plugin_name'])}", "",
             f"当前修订：{entry['revision']}；使用卡状态：{entry['card']['status']}；评测结论：{entry['card']['verdict']}", "",
             "## 当前团队决定", "",
             f"- 声明人：{_markdown(entry['decision']['actor'])}",
             f"- 选择：{_markdown(entry['decision']['choice'])}",
             f"- 理由：{_markdown(entry['decision']['rationale'])}", "",
             "决定为团队提交的记录，工具未核实身份或授权。", "",
             "## 研究背景与重新评估", "",
             f"- 当前研究上下文：{entry['research_plan']['context_sha256'] if entry['research_plan'] else '未附加'}",
             f"- 旧指导需重评：{entry['change']['previous_guidance_reassessment_required']}",
             f"- 条件变化：{entry['change']['conditions_changed']}；任务变化：{entry['change']['tasks_changed']}；运行证据变化：{entry['change']['evidence_changed']}；研究背景变化：{entry['change']['research_changed']}",
             "", "## 历次修订", ""]
    for item in record["entries"]:
        lines.append(f"- 第 {item['revision']} 版：{item['card']['status']} / {item['card']['verdict']}；团队选择 {_markdown(item['decision']['choice'])}；指纹 {item['entry_sha256'][:12]}")
    lines += ["", "完整使用卡、研究上下文、团队决定及修订比较保存在 record.json。旧版记录仍保留在其原目录。", "",
              "## 限制", ""] + [f"- {_markdown(item)}" for item in record["limitations"]]
    json.dumps(record, ensure_ascii=False, allow_nan=False)
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "record.json", record)
    (root / "TEAM.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(root / "record.json"), "md": str(root / "TEAM.md")}
