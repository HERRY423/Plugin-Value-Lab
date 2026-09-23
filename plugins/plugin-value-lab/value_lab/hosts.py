"""Freeze the same scientific protocol across hosts without running a model."""
from copy import deepcopy
from pathlib import Path
import tempfile

from .core import ValidationError, freeze, suite_digest, validate_suite, write_json


HOSTS = {"codex-cli": "CODEX_ADAPTER_AVAILABLE",
         "claude-code": "NATIVE_TEXT_EVAL_ONLY_SCIENTIFIC_COLLECTOR_REQUIRED",
         "gemini-cli": "EXECUTION_ADAPTER_NOT_IMPLEMENTED",
         "opencode": "EXECUTION_ADAPTER_NOT_IMPLEMENTED"}


def prepare_matrix(template, hosts, output):
    validate_suite(template)
    if not isinstance(hosts, list) or len(hosts) < 2:
        raise ValidationError("A cross-host design requires at least two hosts")
    seen = set()
    suites = []
    for host in hosts:
        if not isinstance(host, dict) or set(host) != {"host", "host_version"} or host["host"] not in HOSTS:
            raise ValidationError("Host cell requires a supported host and explicit host_version")
        if host["host"] in seen or not isinstance(host["host_version"], str) or not host["host_version"].strip():
            raise ValidationError("Host cells must be unique and have a version")
        seen.add(host["host"])
        suite = deepcopy(template)
        suite["id"] = template["id"][:65] + "-" + host["host"]
        suite["conditions"].update(host)
        validate_suite(suite)
        suites.append(suite)
    output = Path(output).resolve()
    if output.exists():
        raise ValidationError("Matrix destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".host-matrix-", dir=output.parent) as temp:
        stage = Path(temp) / "matrix"
        stage.mkdir()
        cells = []
        for suite in suites:
            host = suite["conditions"]["host"]
            directory = stage / host
            directory.mkdir()
            write_json(directory / "suite.json", suite)
            lock = freeze(suite, directory / "protocol.lock.json")
            cells.append({"host": host, "host_version": suite["conditions"]["host_version"],
                          "suite_sha256": suite_digest(suite), "expected_runs": lock["expected_runs"],
                          "adapter_status": HOSTS[host], "collected_runs": 0})
        shared = deepcopy(template)
        shared.pop("id")
        for field in ("host", "host_version"):
            shared["conditions"].pop(field, None)
        plan = {"format": "pvl-host-matrix-1", "shared_protocol_sha256": suite_digest(shared), "cells": cells,
                "planned_runs": sum(c["expected_runs"] for c in cells), "model_calls": 0,
                "requires": ["Same actual model/version in every cell", "Identical plugin bytes, tasks, input hashes, scoring and budgets",
                             "Isolated WITH/WITHOUT sessions, observed host/plugin identity and complete cost records"],
                "scope": "Design only; host versions are requested declarations until observed during collection"}
        write_json(stage / "matrix.json", plan)
        stage.rename(output)
    return plan
