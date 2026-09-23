"""Test a built wheel from an isolated temporary import location, without pip/network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def main():
    wheel = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="value-lab-wheel-") as temp:
        directory = Path(temp)
        package = directory / "package"
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                target = (package / name).resolve()
                if not target.is_relative_to(package.resolve()):
                    raise ValueError("Unsafe wheel member")
            archive.extractall(package)
        env = dict(os.environ, PYTHONPATH=str(package), PYTHONIOENCODING="utf-8")
        location = subprocess.run([sys.executable, "-c", "import value_lab; print(value_lab.__file__)"],
                                  cwd=directory, env=env, capture_output=True, text=True, encoding="utf-8", check=True)
        assert Path(location.stdout.strip()).resolve().is_relative_to(package.resolve())
        for asset in ("index.html", "app.js", "analysis.js", "research.js", "style.css"):
            assert (package / "value_lab/static" / asset).is_file(), asset
        workbench_check = subprocess.run([sys.executable, "-c",
            "from value_lab.execution import Engine; from value_lab.workbench import create_server; "
            "e=Engine('workbench-check'); s=create_server(e,0); s.server_close(); e.close(); print('workbench-ready')"],
            cwd=directory, env=env, capture_output=True, text=True, encoding="utf-8", check=True)
        assert "workbench-ready" in workbench_check.stdout
        result = subprocess.run([sys.executable, "-m", "value_lab.cli", "demo", "--output", str(directory / "demo")],
                                cwd=directory, env=env, capture_output=True, text=True, encoding="utf-8", check=True)
        report = json.loads((directory / "demo" / "report.json").read_text(encoding="utf-8"))
        assert report["verdict"] == "SIMULATION_ONLY"
        assert report["summary"]["expected_runs"] == 18
        context = {"schema_version": 1, "intent": "choose", "task": {"summary": "Offline wheel test", "capability": "text summary"},
                   "native_fit": "sufficient", "connected_fit": "unknown", "plugin_management_available": False}
        (directory / "context.json").write_text(json.dumps(context), encoding="utf-8")
        planned = subprocess.run([sys.executable, "-m", "value_lab.cli", "plan-use", str(directory / "context.json"),
                                  "--output", str(directory / "plan")], cwd=directory, env=env, capture_output=True,
                                  text=True, encoding="utf-8", check=True)
        assert json.loads(planned.stdout)["route"] == "USE_NATIVE"
        card = subprocess.run([sys.executable, "-m", "value_lab.cli", "usage-card", str(directory / "demo" / "suite.json"),
                               str(directory / "demo" / "runs.jsonl"), "--lock", str(directory / "demo" / "protocol.lock.json"),
                               "--output", str(directory / "card")], cwd=directory, env=env, capture_output=True,
                               text=True, encoding="utf-8", check=True)
        assert json.loads(card.stdout)["status"] == "TRIAL_GUIDANCE_ONLY"
        research_example = subprocess.run([sys.executable, "-m", "value_lab.cli", "research-example"],
            cwd=directory, env=env, capture_output=True, text=True, encoding="utf-8", check=True)
        context_path = directory / "research-context.json"
        context_path.write_text(research_example.stdout, encoding="utf-8")
        research = subprocess.run([sys.executable, "-m", "value_lab.cli", "research-plan", str(context_path),
            "--output", str(directory / "research")], cwd=directory, env=env, capture_output=True,
            text=True, encoding="utf-8", check=True)
        assert json.loads(research.stdout)["status"] == "RESEARCH_DIAGNOSIS_ONLY"
        plan = json.loads((directory / "research/research-plan.json").read_text(encoding="utf-8"))
        assert plan["evidence_type"] == "synthetic"
        assert not plan["resource_plan"]["execution_authorized"]
        print(json.dumps({"wheel": wheel.name, "isolated_wheel_demo": "passed", "source_tree_import": False,
                          "isolated_plan_and_usage_card": "passed", "workbench_assets_and_server": "passed",
                          "isolated_research_context_and_plan": "passed",
                          "real_model_calls": 0, "verdict": report["verdict"]}, indent=2))


if __name__ == "__main__":
    main()
