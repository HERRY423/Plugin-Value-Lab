"""Prepare an unexecuted, source-bound RNA-seq table audit pilot.

Real public p-values; derived small testing universe and disclosed fault
controls. This is a computational audit, not a new DE or biological study.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.artifacts import sha
from value_lab.core import write_json
from value_lab.claude_collection import prepare
from value_lab.execution import resolve_claude
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", required=True)
    p.add_argument("--skill", required=True)
    p.add_argument("--license", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    skill = Path(args.skill).read_text(encoding="utf-8")
    if "name: statistical-analysis" not in skill or "MIT" not in skill:
        raise ValueError("Expected public MIT statistical-analysis skill")
    plugin = root / "candidate"
    skill_dir = plugin / "skills/statistical-analysis"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(skill, encoding="utf-8")
    shutil.copyfile(args.license, plugin / "LICENSE")
    references = Path(args.skill).parent / "references"
    if references.is_dir():
        shutil.copytree(references, skill_dir / "references")
    scripts = Path(args.skill).parent / "scripts"
    if scripts.is_dir():
        shutil.copytree(scripts, skill_dir / "scripts")
    write_json(plugin / ".claude-plugin/plugin.json", {"name": "public-statistical-analysis-audit", "version": "0.0.0-pilot",
        "description": "Public statistical-analysis skill snapshot, read-only audit profile; not the full upstream plugin"})
    data = Path(args.data)
    rows = list(csv.DictReader(data.open(encoding="utf-8")))
    selected = []
    for row in rows:
        try:
            value, effect = float(row["pvalue"]), float(row["log2FoldChange"])
            if math.isfinite(value) and 0 <= value <= 1 and math.isfinite(effect):
                selected.append({"gene_id": row["row"], "pvalue": value, "log2FoldChange": effect})
        except (ValueError, KeyError):
            continue
        if len(selected) == 16:
            break
    if len(selected) != 16:
        raise ValueError("Need 16 real finite source rows")
    order = sorted(range(16), key=lambda i: selected[i]["pvalue"])
    minimum = 1.0
    for rank in range(16, 0, -1):
        i = order[rank-1]
        minimum = min(minimum, selected[i]["pvalue"] * 16 / rank)
        selected[i]["qvalue"] = minimum
    # Independent library agreement is a software reference check only.
    from scipy.stats import false_discovery_control
    reference = false_discovery_control([r["pvalue"] for r in selected], method="bh")
    if any(not math.isclose(float(a), r["qvalue"], abs_tol=1e-12, rel_tol=1e-12) for a, r in zip(reference, selected)):
        raise ValueError("Independent BH implementation disagrees")
    inputs = root / "inputs"
    inputs.mkdir()
    changed = [dict(r) for r in selected]
    changed[0]["qvalue"] = 0.0 if selected[0]["qvalue"] > 0 else .123
    configs = [
        ("complete-table", selected, 16, "allow", 0, True, "Derived complete 16-gene universe using real source p-values"),
        ("altered-adjustment", changed, 16, "withhold", 1, True, "Disclosed injected q-value error; real model observation on a manufactured negative control"),
        ("missing-family", selected[:8], 16, "withhold", -1, False, "Disclosed removal of half the testing family; missingness control")]
    cases = []
    for name, values, size, decision, errors, complete, note in configs:
        table = inputs / (name + ".csv")
        with table.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["gene_id", "pvalue", "log2FoldChange", "qvalue"])
            writer.writeheader()
            writer.writerows(values)
        prompt = (f"Audit the RNA-seq result table {table.name}. Use the available read-only tools to inspect the file. "
                  "If a statistical-analysis skill is available, consult it before auditing; otherwise perform the audit directly. "
                  f"The declared complete testing family contains {size} genes. qvalue must equal Benjamini-Hochberg correction "
                  "of all pvalues in that complete family, tolerance 1e-9. Decide whether this artifact can be accepted for this bounded computational contract. "
                  "If the complete family is missing, its q-values cannot be independently verified from this artifact. "
                  "This small derived family is not the original genome-wide family. Do not claim biological validation or genome-wide discoveries. "
                  "Return only one JSON object with decision (allow or withhold), observed_rows (integer), family_complete (boolean), "
                  "invalid_adjustments (integer; -1 if the family is incomplete), genome_wide_claim_supported (boolean), "
                  "and rationale (string). Do not output markdown fences. This is an automated one-shot audit with no human available for questions.")
        expected = {"decision": decision, "observed_rows": len(values), "family_complete": complete,
                    "invalid_adjustments": errors, "genome_wide_claim_supported": False}
        cases.append({"id": name, "cluster": "airway-public-source", "split": "development", "kind": "task" if decision == "allow" else "abstention",
                      "prompt": prompt, "input_scope": note, "inputs": {table.name: sha(table)},
                      "graders": [{"id": "audit-contract", "type": "artifact", "artifact": "answer", "dimension": "outcome", "weight": 1, "critical": True,
                                   "verifier": {"kind": "json_fields", "expected": expected}}]})
    executable = resolve_claude()
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
    suite = {"schema_version": 1, "id": "airway-bh-audit-native-pilot", "plugin": {"name": "public-statistical-analysis-audit", "version": "0.0.0-pilot"},
             "evidence_type": "local", "runs_per_case": 1,
             "conditions": {"host": "claude-code", "host_version": version, "model": "deepseek-flash", "model_version": "provider-alias-deepseek-flash-2026-09-23", "provider_host": "api.deepseek.com",
                            "tools": ["Read", "Skill"], "environment": "Fresh per-run Claude config and workspace; restricted read-only audit; no MCP or shell; host metadata is not provider attestation",
                            "budget": {"max_model_runs": 6, "timeout_seconds": 180, "max_turns": 6, "max_cost_usd": .75}},
             "pricing": {"input_miss_usd_per_million": .3, "input_hit_usd_per_million": .006, "output_usd_per_million": 1.2,
                         "source": "https://api-docs.deepseek.com/quick_start/pricing/", "checked_at": "2026-09-23",
                         "basis": "Published peak-rate upper estimate; actual time-band billing and settlement unverified"},
             "policy": {"min_quality_delta": .1, "quality_floor": 1, "max_case_regression": 0, "min_clusters": 2,
                        "require_cost_saving": False, "require_cost_categories": False, "human_hourly_usd": 0}, "cases": cases}
    write_json(root / "suite.json", suite)
    write_json(root / "source-provenance.json", {"source_url": "https://github.com/stephenturner/deseq-to-fgsea/blob/master/data/deseq-results-tidy-human-airway.csv",
        "source_sha256": sha(data), "source_rows": len(rows), "selection": "First 16 rows in source order with finite pvalue and log2FoldChange; no outcome-based sampling",
        "source_license": "No repository license identified; retain locally, no public redistribution authorized by this preparation",
        "skill_source": "https://github.com/kellsaro/k-dense-ai-claude-scientific-skills/tree/main/scientific-skills/statistical-analysis",
        "skill_sha256": sha(args.skill), "skill_scope": "Read-only skill profile; no full upstream plugin adoption or author participation",
        "controls": [c[-1] for c in configs], "independent_reference_check": "BH implementation agrees with scipy.stats.false_discovery_control",
        "independent_task_families": 1, "heldout_validated": False, "scientific_authorization": "NONE",
        "claim_limit": "Real model computational audit pilot with public-derived inputs and injected controls; not biological effectiveness, broad plugin value or GA"})
    result = prepare(suite, plugin, root / "study", inputs, executable)
    write_json(root / "preparation.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
