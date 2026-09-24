"""Prepare a local handoff from actual retained study and optional pseudobulk material.

Never uploads, fits a model, installs dependencies, or labels a replay independent.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.artifacts import sha, confined
from value_lab.core import ValidationError, load_json, write_json, suite_digest
from value_lab.reuse import prepare_reuse
from value_lab.science import read_reference
from value_lab.pseudobulk import check, validate_spec


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("study")
    p.add_argument("--artifacts")
    p.add_argument("--verifiers")
    p.add_argument("--pseudobulk-reference")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        raise ValidationError("Preserve existing deliveries")
    for source in (args.study, args.artifacts, args.verifiers, args.pseudobulk_reference):
        if source and (output.is_relative_to(Path(source).resolve()) or Path(source).resolve().is_relative_to(output)):
            raise ValidationError("Delivery and source roots must be disjoint")
    output.mkdir(parents=True)
    receipt = prepare_reuse(args.study, output / "study", artifact_root=args.artifacts, verifier_root=args.verifiers)
    write_json(output / "EXPECTED-PACKAGE.json", receipt)
    lines = ["# 本地复用交接包", "", "本包尚未发送给外部参与者；独立外部复用仍未建立。分享前检查数据许可、提示和运行记录中的私有资料。", "",
             "## 复核旧观察", "", "先安装同一版本/源码内容的 PVL；这不是新的宿主运行。保存下面的包 ID，之后用它核对迁移副本：", "",
             receipt["package_id"], "", "```sh", f"python -B scripts/value_lab.py reuse-replay PATH_TO_DELIVERY/study --expected-id {receipt['package_id']} --output NEW_REPLAY_DIRECTORY",
             "```", "", "有独立评分材料的研究还需显式传入 `--verifiers`；交接包未自动包含原始评分目录。保留 receipt.json、report.json 和 dependencies.json。", "",
             "收到实际参与者的文件后，用 reuse-inspect 检查一致性。参与者身份、独立性及真正执行仍需外部核实。", "",
             "## 新的宿主/模型比较", "", "对新研究在采集前冻结 use_decision 的质量损失、成本、风险边界及配对理由。完整保留 WITH/WITHOUT；只改变声明的一个因素。",
             "旧研究不补写阈值。没有真实可比的新运行时，继续使用局部诊断，不产生推荐、关闭或升级决定。"]
    scientific = None
    if args.pseudobulk_reference:
        source = Path(args.pseudobulk_reference)
        spec = load_json(source / "verifier.json")
        validate_spec(spec)
        # Verify before copying. This is a non-executing check of existing results.
        result_path = source / spec["truth"]["path"]
        passed, _ = check(result_path, spec, source)
        if passed is not True:
            raise ValidationError("Pseudobulk reference does not satisfy its frozen contract")
        inputs, scorers = output / "pseudobulk/inputs", output / "pseudobulk/scorers"
        inputs.mkdir(parents=True)
        scorers.mkdir()
        copied_spec = {"absolute": spec["absolute"], "relative": spec["relative"]}
        for field in ("design", "data", "truth"):
            name = "reference.json" if field == "truth" else field + ".json"
            raw = read_reference(source, spec[field])
            (scorers / name).write_bytes(raw)
            if field != "truth":
                (inputs / name).write_bytes(raw)
            copied_spec[field] = {"path": name, "sha256": spec[field]["sha256"]}
        write_json(scorers / "verifier.json", copied_spec)
        for name in ("backend-receipt.json", "execution.json", "reference-runner.py"):
            original = confined(source, name)
            if original.is_file():
                shutil.copyfile(original, scorers / name)
        execution = load_json(confined(source, "execution.json"))
        import re
        libraries = execution.get("libraries", {})
        if not isinstance(libraries, dict) or not set(libraries) <= {"pydeseq2", "numpy", "scipy", "pandas", "anndata", "formulaic"} or any(not isinstance(v, str) or not re.fullmatch(r"[0-9][A-Za-z0-9.+!-]*", v) for v in libraries.values()):
            raise ValidationError("Unexpected dependency inventory; no arbitrary package URLs or install options")
        requirements = "\n".join(f"{k}=={v}" for k, v in sorted(execution.get("libraries", {}).items()))
        (output / "pseudobulk/observed-requirements.txt").write_text(requirements + "\n", encoding="utf-8")
        scientific = {"spec_sha256": suite_digest(copied_spec), "scope": "Same frozen data; a fresh reference fit is not a new dataset or plugin experiment",
                      "expert_review": "PENDING", "new_reference_fits": 0}
        lines += ["", "## 供体感知场景的独立复算入口", "", "public inputs 与 scorer reference 分目录；不得向 Agent 暴露评分参考。已观察依赖版本保存在 observed-requirements.txt，未声称其他平台安装已验证。", "",
                  "如只复核既有产物，pseudobulk-check 不需要拟合后端；如实际重跑参考分析，以下命令会本地运行 PyDESeq2：", "", "```sh",
                  "python -B scripts/value_lab.py pseudobulk-reference PATH_TO_DELIVERY/pseudobulk/inputs/design.json PATH_TO_DELIVERY/pseudobulk/inputs/data.json --output NEW_REFERENCE_DIRECTORY",
                  "python -B scripts/value_lab.py pseudobulk-check NEW_REFERENCE_DIRECTORY/reference.json --spec PATH_TO_DELIVERY/pseudobulk/scorers/verifier.json --verifiers PATH_TO_DELIVERY/pseudobulk/scorers",
                  "```", "", "保留实际环境、警告、失败和不同结果；不要覆盖旧目录或只传成功摘要。重跑同一数据不增加独立供体数，独立专家审阅仍待完成。"]
    (output / "REUSE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {"format": "pvl-local-delivery-1", "study_package_id": receipt["package_id"], "scientific_material": scientific,
                "files": {p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob("*")) if p.is_file()},
                "external_participants": 0, "model_calls": 0, "published": False}
    write_json(output / "DELIVERY.json", manifest)
    print(json.dumps({"output": str(output), "delivery_sha256": suite_digest(manifest), "study_package_id": receipt["package_id"], "external_participants": 0}))


if __name__ == "__main__":
    main()
