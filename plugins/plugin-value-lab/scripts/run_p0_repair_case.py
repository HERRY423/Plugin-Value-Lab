"""Reproduce and repair two selected local plugin components in isolated copies.

No model calls, installed-plugin edits, network, author impersonation or claims
of whole-workflow execution. External source bytes remain in the local output.
"""
from __future__ import annotations

import argparse
import ast
import csv
import difflib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, List, Set, Tuple, Union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from value_lab.artifacts import grade_artifact, sha
from value_lab.core import suite_digest, write_json


NGS_OLD = '''    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\\t")
        return {row["Name"]: row for row in reader}'''

NGS_NEW = '''    # Reject ambiguous or malformed quantification before creating matrices.
    import math

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\\t")
        required = {"Name", "Length", "EffectiveLength", "TPM", "NumReads"}
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or not required <= set(reader.fieldnames):
            raise ValueError("quant.sf requires unique Name, Length, EffectiveLength, TPM and NumReads columns")
        records = {}
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed quant.sf row")
            name = row["Name"]
            if not name.strip() or name in records:
                raise ValueError("Empty or duplicate transcript ID in quant.sf: " + repr(name))
            for field in ("Length", "EffectiveLength", "TPM", "NumReads"):
                value = float(row[field])
                if not math.isfinite(value) or value < 0:
                    raise ValueError("Invalid nonnegative finite quant.sf value: " + field)
            records[name] = row
        if not records:
            raise ValueError("Empty quant.sf")
        return records'''

BN_OLD = '''    min_reps = min(condition_counts.values()) if condition_counts else len(samples)
    total_reps = len(donors) if donors else len(samples)'''

BN_NEW = '''    # Row count is not independent biological replication. Only complete,
    # declared donor identities support these descriptive counts; absence is
    # represented by zero plus an explicit unresolved status, never by rows.
    donors_by_condition: Dict[str, Set[str]] = {}
    identities_complete = bool(samples)
    for sample in samples:
        condition = (sample.get("condition") or sample.get("group")
                     or sample.get("treatment") or sample.get("status")
                     or sample.get("genotype") or "default")
        donor = (sample.get("donor") or sample.get("patient")
                 or sample.get("subject") or sample.get("individual"))
        donors_by_condition.setdefault(condition, set())
        if donor:
            donors_by_condition[condition].add(donor)
        else:
            identities_complete = False
    min_reps = min(map(len, donors_by_condition.values()), default=0) if identities_complete else 0
    total_reps = len(donors) if identities_complete else 0'''


def _copy_revision(source, output, label, old, new):
    raw = Path(source).read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if text.count(old) != 1:
        raise ValueError("Source changed; review the repair against current source before running")
    fixed = text.replace(old, new)
    if label == "bionexus":
        old_field = '"biological_replicates_count": total_reps,'
        if fixed.count(old_field) != 1:
            raise ValueError("BioNexus facts shape changed; review repair")
        fixed = fixed.replace(old_field, old_field + '\n        "replicate_identity_status": "DECLARED_COMPLETE" if identities_complete else "UNRESOLVED",')
    before = output / label / "before.py"
    after = output / label / "after.py"
    before.parent.mkdir(parents=True)
    before.write_bytes(raw)
    after.write_text(fixed, encoding="utf-8", newline="\n")
    patch = "".join(difflib.unified_diff(text.splitlines(True), fixed.splitlines(True),
                                      fromfile="a/" + Path(source).name, tofile="b/" + Path(source).name))
    (output / label / "repair.patch").write_text(patch, encoding="utf-8", newline="\n")
    return before, after


def _ngs_case(script, case, directory):
    directory.mkdir(parents=True)
    quant = directory / "quant.sf"
    quant.write_text(case["table"], encoding="utf-8")
    (directory / "config.json").write_text('{"samples":{"S1":{"r1":["public-fixture.fastq"]}}}', encoding="utf-8")
    command = [sys.executable, "-I", str(script), "--config", str(directory / "config.json"),
               "--outdir", str(directory / "matrices"), "--quant", "S1=" + str(quant)]
    start = time.monotonic()
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=30, shell=False)
    elapsed = time.monotonic() - start
    (directory / "stdout.txt").write_bytes(result.stdout)
    (directory / "stderr.txt").write_bytes(result.stderr)
    matrix = directory / "matrices/num_reads.tsv"
    actual = None
    if matrix.is_file():
        with matrix.open(encoding="utf-8", newline="") as stream:
            actual = {row["transcript_id"]: float(row["S1"]) for row in csv.DictReader(stream, delimiter="\t")}
    observed = {"rejected_before_matrix": result.returncode != 0 and not matrix.exists(),
                "valid_matrix": result.returncode == 0 and actual == case.get("expected_matrix")}
    write_json(directory / "observed.json", observed)
    return {"exit_code": result.returncode, "elapsed_seconds": elapsed, "observed": observed,
            "input_sha256": sha(quant), "executed_code_sha256": sha(script),
            "artifacts": {p.relative_to(directory).as_posix(): sha(p) for p in directory.rglob("*") if p.is_file()}}


def _bn_function(source):
    # Execute the exact helper's AST with its standard-library dependencies;
    # avoid importing the entire BioNexus package or touching its active checkout.
    tree = ast.parse(Path(source).read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "parse_samplesheet")
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"csv": csv, "Path": Path, "Any": Any, "Dict": Dict, "List": List,
                 "Set": Set, "Tuple": Tuple, "Union": Union}
    exec(compile(module, str(source), "exec"), namespace)
    return namespace["parse_samplesheet"]


def _bn_case(script, case, directory):
    directory.mkdir(parents=True)
    sheet = directory / "samples.csv"
    sheet.write_text(case["table"], encoding="utf-8")
    start = time.monotonic()
    _, facts = _bn_function(script)(sheet)
    elapsed = time.monotonic() - start
    write_json(directory / "observed.json", facts)
    return {"elapsed_seconds": elapsed, "observed": facts, "input_sha256": sha(sheet),
            "executed_code_sha256": sha(script), "execution_scope": "exact helper AST, not whole package/host"}


def run(ngs_source, bionexus_source, output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a fresh repair evidence directory")
    output.mkdir(parents=True)
    header = "Name\tLength\tEffectiveLength\tTPM\tNumReads\n"
    row = "tx1\t100\t80\t100\t10\n"
    cases = {
        "ngs": [
            {"id": "duplicate_transcript", "table": header + row + "tx1\t100\t80\t200\t20\n", "expected": {"rejected_before_matrix": True}},
            {"id": "nonfinite_reads", "table": header + "tx1\t100\t80\t100\tNaN\n", "expected": {"rejected_before_matrix": True}},
            {"id": "negative_reads", "table": header + "tx1\t100\t80\t100\t-1\n", "expected": {"rejected_before_matrix": True}},
            {"id": "empty_table", "table": header, "expected": {"rejected_before_matrix": True}},
            {"id": "duplicate_header", "table": header.rstrip() + "\tName\n" + row.rstrip() + "\ttx2\n", "expected": {"rejected_before_matrix": True}},
            {"id": "valid_fractional_counts", "table": header + "tx2\t100\t80\t200\t20.25\n" + row,
             "expected": {"valid_matrix": True}, "expected_matrix": {"tx1": 10, "tx2": 20.25}},
            {"id": "valid_zero_counts", "table": header + "tx1\t100\t0\t0\t0\n",
             "expected": {"valid_matrix": True}, "expected_matrix": {"tx1": 0}},
        ],
        "bionexus": [
            {"id": "technical_rows", "table": "sample,condition,donor\na,control,d1\nb,control,d1\nc,treated,d2\nd,treated,d2\n",
             "expected": {"sample_count": 4, "min_replicates_per_condition": 1, "biological_replicates_count": 2}},
            {"id": "independent_donors", "table": "sample,condition,donor\na,control,d1\nb,control,d2\nc,treated,d3\nd,treated,d4\n",
             "expected": {"sample_count": 4, "min_replicates_per_condition": 2, "biological_replicates_count": 4}},
            {"id": "paired_donors", "table": "sample,condition,donor\na,control,d1\nb,control,d2\nc,treated,d1\nd,treated,d2\n",
             "expected": {"sample_count": 4, "min_replicates_per_condition": 2, "biological_replicates_count": 2}},
            {"id": "missing_donors", "table": "sample,condition\na,control\nb,control\nc,treated\nd,treated\n",
             "expected": {"sample_count": 4, "min_replicates_per_condition": 0, "biological_replicates_count": 0, "replicate_identity_status": "UNRESOLVED"}},
            {"id": "partial_donors", "table": "sample,condition,donor\na,control,d1\nb,control,\nc,treated,d2\nd,treated,d2\n",
             "expected": {"sample_count": 4, "min_replicates_per_condition": 0, "biological_replicates_count": 0, "replicate_identity_status": "UNRESOLVED"}},
        ],
    }
    # Freeze all development controls, including valid controls, before either
    # revision runs. These are disclosed adversarial fixtures, not real samples.
    protocol = {"schema_version": 1, "evidence_type": "real_local_component_execution_on_synthetic_inputs",
                "cases": cases, "repetitions": 1, "model_calls": 0, "independent_holdout": False,
                "scope": "deterministic local component regression, not paired plugin/model benefit"}
    write_json(output / "protocol.json", protocol)
    revisions = {"ngs": _copy_revision(ngs_source, output, "ngs", NGS_OLD, NGS_NEW),
                 "bionexus": _copy_revision(bionexus_source, output, "bionexus", BN_OLD, BN_NEW)}
    results = []
    for plugin, pair in revisions.items():
        for revision, script in zip(("before", "after"), pair):
            for case in cases[plugin]:
                directory = output / plugin / revision / case["id"]
                observed = (_ngs_case if plugin == "ngs" else _bn_case)(script, case, directory)
                grader = {"id": "frozen-expected-behavior", "type": "artifact", "artifact": "result",
                          "verifier": {"kind": "json_fields", "expected": case["expected"]}}
                artifact = directory / "observed.json"
                record = {"artifacts": {"result": {"path": artifact.relative_to(output).as_posix(), "sha256": sha(artifact)}}}
                passed, rationale, receipt = grade_artifact(grader, record, output)
                results.append({"plugin": plugin, "revision": revision, "case_id": case["id"],
                                "passed": passed, "rationale": rationale, "receipt": receipt, **observed})
    summary = {"schema_version": 1, "protocol_sha256": sha(output / "protocol.json"),
               "status": "LOCAL_REPAIR_RETESTED_AUTHOR_VALIDATION_PENDING", "results": results,
               "coverage": {plugin: {revision: {"passed": sum(r["passed"] is True for r in results if r["plugin"] == plugin and r["revision"] == revision),
                                                "total": len(cases[plugin])} for revision in ("before", "after")} for plugin in cases},
               "installed_plugins_modified": False, "native_host_eval_executed": False,
               "actual_model_calls": 0, "paid_catalog_calls": 0, "settled_external_spend_usd": 0,
               "human_minutes": None, "full_project_cost_usd": None,
               "author_feedback": None, "author_adopted_diagnosis": None, "negative_feedback": None,
               "limits": ["NGS executes the complete copied aggregation script; no FASTQ or whole workflow run.",
                          "BioNexus executes the exact copied helper AST; the current harvest path does not call it.",
                          "Fixtures were designed during code review; not blinded or held out.",
                          "Independent maintainer feedback and application to installed source remain pending."]}
    write_json(output / "repair-report.json", summary)
    write_json(output / "author-feedback.template.json", {"schema_version": 1,
        "repair_report_sha256": sha(output / "repair-report.json"), "author": None,
        "diagnosis_adopted": None, "repair_applied_revision": None, "human_minutes": None,
        "additional_model_calls": None, "misdiagnoses": None, "negative_feedback": None,
        "next_issue_reuse": None, "status": "AWAITING_ACTUAL_AUTHOR_INPUT"})
    manifest = {p.relative_to(output).as_posix(): sha(p) for p in output.rglob("*") if p.is_file()}
    write_json(output / "files.sha256.json", manifest)
    return {"output": str(output), "manifest_sha256": sha(output / "files.sha256.json"),
            "status": summary["status"], "coverage": summary["coverage"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngs-source", required=True)
    parser.add_argument("--bionexus-source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.ngs_source, args.bionexus_source, args.output), indent=2))
