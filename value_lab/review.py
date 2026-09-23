"""Create arm-masked review packets and merge attributable human decisions."""
from __future__ import annotations

import hashlib
import json
import random
import secrets
from pathlib import Path

from .core import ValidationError, suite_digest, validate_suite, write_json


def review_pack(suite, records, output_dir):
    validate_suite(suite)
    root = Path(output_dir)
    if root.exists() and any(root.iterdir()):
        raise ValidationError("Review packet directory must be empty")
    root.mkdir(parents=True, exist_ok=True)
    graders = {c["id"]: [g for g in c["graders"] if g["type"] == "human"] for c in suite["cases"]}
    prompts = {c["id"]: c["prompt"] for c in suite["cases"]}
    items, mapping = [], {}
    for index, record in enumerate(records):
        human = graders.get(record.get("case_id"), [])
        if not human:
            continue
        if not isinstance(record.get("output"), str):
            raise ValidationError("Review requires original output, not aggregate scores")
        token = secrets.token_hex(8)
        items.append({"review_id": token, "prompt": prompts[record["case_id"]], "output": record["output"],
                      "rubrics": [{"id": g["id"], "rubric": g["rubric"]} for g in human]})
        mapping[token] = {"record_index": index, "record_sha256": suite_digest(record),
                          "grader_ids": [g["id"] for g in human]}
    if not items:
        raise ValidationError("No human graders to review")
    random.SystemRandom().shuffle(items)
    write_json(root / "reviewer" / "packet.json", {"schema_version": 1, "items": items,
               "instruction": "Judge each rubric independently. Use null for disputed or insufficient evidence. Do not guess arm identity."})
    (root / "reviewer" / "decisions.jsonl").write_text("", encoding="utf-8")
    write_json(root / "operator-only" / "mapping.json", {"suite_sha256": suite_digest(suite), "mapping": mapping,
               "packet_sha256": hashlib.sha256((root / "reviewer" / "packet.json").read_bytes()).hexdigest()})
    (root / "README.md").write_text(
        "# 人工复核包\n\n只将 reviewer 文件夹交给复核者；operator-only 包含解盲映射。\n"
        "这只是去除显式组别，原始输出可能泄露身份；没有技术隔离或独立性认证。不要让执行者代填人工判断。\n\n"
        "decisions.jsonl 每行：\n"
        '`{"review_id":"packet 中的标识","grader_id":"rubric 标识","passed":null,"reviewer":"实际复核者标识","rationale":"判断依据或争议"}`\n'
        "\n不得修改原始输出以隐藏错误。身份线索或利益冲突应写入判断依据。\n", encoding="utf-8")
    return {"items": len(items), "reviewer_packet": str(root / "reviewer" / "packet.json"),
            "operator_mapping": str(root / "operator-only" / "mapping.json")}


def apply_reviews(suite, records, mapping, decisions):
    if mapping.get("suite_sha256") != suite_digest(suite):
        raise ValidationError("Review packet does not match suite")
    result = json.loads(json.dumps(records))
    seen = set()
    for decision in decisions:
        key = (decision.get("review_id"), decision.get("grader_id"))
        if not all(isinstance(x, str) for x in key) or key in seen:
            raise ValidationError("Malformed or duplicate review decision")
        seen.add(key)
        target = mapping.get("mapping", {}).get(key[0])
        if not target or key[1] not in target.get("grader_ids", []):
            raise ValidationError("Review ID or grader does not belong to packet")
        index = target.get("record_index")
        if type(index) is not int or not 0 <= index < len(result) or suite_digest(records[index]) != target.get("record_sha256"):
            raise ValidationError("Observed record changed after packet creation")
        passed = decision.get("passed")
        if passed is not None and type(passed) is not bool:
            raise ValidationError("Human decision must be true, false or null")
        if any(not isinstance(decision.get(k), str) or not decision[k].strip() for k in ("reviewer", "rationale")):
            raise ValidationError("Human decision requires reviewer and rationale")
        reviews = result[index].setdefault("reviews", {})
        if key[1] in reviews:
            raise ValidationError("Existing review cannot be silently overwritten; create an explicit revision")
        reviews[key[1]] = {k: decision[k] for k in ("passed", "reviewer", "rationale")}
    return result
