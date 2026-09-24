"""Prepare native scientific file-analysis cases; the official host executes them."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shlex

from .artifacts import confined, sha
from .core import ValidationError, suite_digest, write_json
from .native import _component, _frontmatter, _text
from .native_evidence import _bytes, _fresh, _put, _separate, prepare_native_evidence, validate_contract
from .native_repair import validate_context


def prepare_native_analysis(recipe, plugin, inputs, output, *, references=None):
    fields = {"schema_version", "plugin_files", "execution_context", "cases"}
    if not isinstance(recipe, dict) or set(recipe) != fields or type(recipe["schema_version"]) is not int or recipe["schema_version"] != 1:
        raise ValidationError("Analysis recipe requires schema_version 1, plugin_files, execution_context and cases")
    validate_context(recipe["execution_context"])
    context = recipe["execution_context"]
    if set(context["tools"]) != {"Read", "Skill", "Write", "Bash"}:
        raise ValidationError("Analysis profile requires exactly Read, Skill, Write and Bash")
    output, plugin, inputs = _fresh(output), Path(plugin).resolve(), Path(inputs).resolve()
    for other in (plugin, inputs, references):
        if other is not None:
            _separate(output, other)
    if not isinstance(recipe["plugin_files"], list) or not recipe["plugin_files"]:
        raise ValidationError("Explicit candidate file allowlist required")
    payload = {}
    for relative in recipe["plugin_files"]:
        payload[relative] = _bytes(confined(plugin, relative))
        if relative.startswith("pvl-analysis-evals/"):
            raise ValidationError("Candidate file conflicts with generated eval directory")
    manifests = [n for n in ("plugin.json", ".claude-plugin/plugin.json") if confined(plugin, n).is_file()]
    if not manifests:
        raise ValidationError("Candidate requires a native plugin manifest")
    for name in manifests:
        payload[name] = _bytes(confined(plugin, name))
        manifest = json.loads(payload[name])
        if any(k in manifest for k in ("hooks", "mcpServers", "lspServers")):
            raise ValidationError("This analysis preparation profile requires a skill/code-only candidate")
    if any(Path(n).name in ("hooks.json", "mcp.json", ".mcp.json") or "hooks" in Path(n).parts for n in payload):
        raise ValidationError("Startup hooks and servers are outside this analysis profile")
    if len({n.casefold() for n in payload}) != len(payload):
        raise ValidationError("Candidate paths collide on case-insensitive filesystems")
    contract = {"schema_version": 1, "plugin_files": sorted(payload),
                "execution_context": deepcopy(context), "cases": []}
    if not isinstance(recipe["cases"], list) or not recipe["cases"]:
        raise ValidationError("At least one analysis case required")
    for source in recipe["cases"]:
        if not isinstance(source, dict) or set(source) != {"name", "prompt", "repetitions", "inputs", "artifacts", "graders", "execution"}:
            raise ValidationError("Analysis case requires name, prompt, repetitions, inputs, artifacts, graders and execution")
        name = _component(source["name"], "case name")
        if not isinstance(source["prompt"], str) or not source["prompt"].strip():
            raise ValidationError("Analysis prompt must be nonempty")
        directory = f"pvl-analysis-evals/{name}"
        case = {k: deepcopy(source[k]) for k in ("name", "repetitions", "artifacts", "graders", "execution")}
        case.update(case_directory=directory, inputs={}, input_sha256={})
        scaffold = ['#!/usr/bin/env bash', 'set -eu', 'source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"']
        if not isinstance(source["inputs"], dict) or not source["inputs"]:
            raise ValidationError("Analysis cases require input references")
        used_paths = set()
        for identifier, ref in source["inputs"].items():
            if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
                raise ValidationError("Each input requires relative path and exact sha256")
            relative = ref["path"]
            content = _bytes(confined(inputs, relative))
            if hashlib.sha256(content).hexdigest() != ref["sha256"]:
                raise ValidationError("Analysis input digest mismatch")
            if relative.casefold() in used_paths:
                raise ValidationError("Duplicate analysis input paths")
            used_paths.add(relative.casefold())
            # Restrict generated shell paths to portable components, independently of quoting.
            for part in relative.split("/"):
                _component(part, "input filename")
            case["inputs"][identifier] = relative
            case["input_sha256"][identifier] = ref["sha256"]
            payload[f"{directory}/resources/{relative}"] = content
            parent = Path(relative).parent.as_posix()
            scaffold.extend([f"mkdir -p -- {shlex.quote(parent)}",
                             f'cp -- "$source_dir"/{shlex.quote("resources/" + relative)} {shlex.quote(relative)}'])
        if not isinstance(case["artifacts"], dict):
            raise ValidationError("Analysis artifacts must be a mapping")
        for relative in case["artifacts"].values():
            confined(inputs, relative)
            for part in relative.split("/"):
                _component(part, "artifact filename")
            if relative.casefold() in used_paths:
                raise ValidationError("Input and artifact paths must be distinct")
            used_paths.add(relative.casefold())
        contract["cases"].append(case)
        # Validate before writing or interpolating execution requirements.
        validate_contract(contract)
        script = case["artifacts"][case["execution"]["script_artifact"]]
        body = (source["prompt"] + "\n\nInputs are already present in the workspace. Preserve their bytes. "
                f"Write the analysis script to {script} and execute exactly this foreground Bash command: "
                + case["execution"]["command"] + ". Keep the script and all outputs, including failures. "
                "Do not replace execution with a written claim.\n")
        payload[f"{directory}/prompt.md"] = _frontmatter(
            {"name": name, "runs": case["repetitions"], "model": context["model"],
             "allowed_tools": context["tools"], "max_turns": context["max_turns"],
             "timeout_seconds": context["timeout_seconds"]}, body).encode("utf-8")
        payload[f"{directory}/fixture.sh"] = ("\n".join(scaffold) + "\n").encode("utf-8")
        payload[f"{directory}/case.yaml"] = json.dumps(
            {"schema_version": "1.1", "name": name, "context": {"scaffold_script": "fixture.sh"}}, indent=2).encode("utf-8")
        for identifier, relative in case["artifacts"].items():
            _component(identifier, "artifact ID")
            payload[f"{directory}/graders/{identifier}.md"] = _frontmatter(
                {"type": "file_exists", "path": relative, "arm": "both"}).encode("utf-8")
    validate_contract(contract)
    from .native_evidence import _refs
    for ref in _refs(contract):
        if references is None:
            raise ValidationError("Separate scientific references required")
        if sha(confined(references, ref["path"])) != ref["sha256"]:
            raise ValidationError("Scientific reference digest mismatch")
    model = _text(context["model"], "model")
    if model.startswith("-"):
        raise ValidationError("Model must not begin with '-' ")
    candidate = output / "candidate"
    candidate.mkdir(parents=True)
    for relative, content in payload.items():
        _put(candidate, relative, content)
    prepared = prepare_native_evidence(candidate, contract, output / "plan", references=references)
    write_json(output / "contract.json", contract)
    command = ["claude", "plugin", "eval", str(candidate), "--eval-dir", "pvl-analysis-evals",
               "--ablation", "with-without", "--model", model, "--concurrency", "1", "--mocks", "record",
               "--scaffold", "--keep-temp", "--no-publish", "--max-cost-usd", str(context["max_cost_usd"]),
               "--output-dir", str(output / "native-results"), "--allow-tools", "Write", "Bash"]
    execution = {"argv": command, "launched": False, "shell": False,
                 "expected_host_version": context["host_version"],
                 "expected_sessions": sum(c["repetitions"] * 2 for c in contract["cases"]),
                 "plan_sha256": prepared["plan_sha256"], "recipe_sha256": suite_digest(recipe),
                 "sandbox_preflight": "NOT_VERIFIED",
                 "scope": "Run only in the native host's supported sandbox; Windows requires WSL2. Generated scaffold copies declared inputs outside the agent sandbox. This command does not authorize execution or attest isolation."}
    write_json(output / "execution-plan.json", execution)
    (output / "ANALYSIS.md").write_text(
        "# 原生科研分析交接\n\n这是准备材料，尚未运行模型。\n\n"
        "1. 在实际运行环境准备材料并核对 Claude 版本、Python 与沙箱；Windows shell 分析需要 WSL2。\n"
        "2. 检查 candidate 中选定插件文件与 fixture.sh；它只复制公开输入，但 scaffold 在 Agent 沙箱外运行。\n"
        "3. 由宿主执行 execution-plan.json 的 argv；保留 --keep-temp 与 --no-publish。费用是估算阈值。\n"
        "4. 用 native-bindings 关联保留目录，再用 capture-native-evidence 采集脚本、产物与原生事件。\n"
        "5. 只修改候选文件，在新目录准备和完整复测，再用 compare-native-repair 检查条件与退步。\n\n"
        "评分参考与 plan 始终留在 Agent 无法访问的位置；本工具未验证 OS 隔离。"
        "file_exists 仅检测交付文件；科研结论由分离的 PVL 规则复算。"
        "最终脚本摘要不证明运行瞬间的脚本字节；工具返回成功也不证明生物学正确。\n", encoding="utf-8")
    return {"output": str(output), "plan_sha256": prepared["plan_sha256"], "model_calls": 0,
            "execution_plan": execution}
