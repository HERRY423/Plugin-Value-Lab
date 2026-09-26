# Plugin Value Lab

Evaluate a plugin, keep negative evidence, and decide where a trial is justified. **0.6.0 · feature freeze through 2026-11-06.**

Python 3.11+, from this unpacked directory. These five commands use bundled **synthetic** observations; no installation, account or model call is needed. Use a fresh output directory on each attempt.

```sh
python scripts/value_lab.py doctor
python scripts/value_lab.py freeze examples/first-run/suite.json --lock work/first-run/protocol.lock.json
python scripts/value_lab.py evaluate examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/report
python scripts/value_lab.py usage-card examples/first-run/suite.json examples/first-run/runs.jsonl --lock work/first-run/protocol.lock.json --cost-ledger examples/first-run/cost-ledger.json --output work/first-run/usage
python scripts/value_lab.py compare-studies examples/first-run/before.json examples/first-run/after.json --output work/first-run/comparison.json
```

Open **work/first-run/usage/USAGE.md**. `ENVELOPE.html` is the single-page view. The last command compares two bundled teaching fixtures; it is not a new repair trial. Simulation or insufficient evidence is an honest result, not an installation failure.

[中文](README.zh-CN.md) · [Start / timed first use](docs/START.md) · [Operations](docs/OPERATIONS.md) · [Evidence limits](docs/EVIDENCE.md) · [Six-week freeze](docs/FREEZE.md)

**Still unestablished:** a complete natural-use plugin repair chain and non-author first-use timing. No benefit is inferred from the tutorial or seed audit. Existing specialist commands remain available; they are outside the first-run route.
