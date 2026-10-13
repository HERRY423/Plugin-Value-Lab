"""Read-only gateway budget inspection; never create a ledger or dispatch a call."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.core import ValidationError, load_json, suite_digest
from value_lab.gateway_budget import GatewayBudget, TARIFF
from value_lab.online_sandbox import validate_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sandbox', type=Path)
    args = parser.parse_args()
    result = {'tariff': TARIFF, 'tariff_sha256': suite_digest(TARIFF),
              'provider_cap_verified': False, 'model_calls': 0}
    code = 0
    if args.sandbox:
        try:
            gateway = validate_config(load_json(args.sandbox))['gateway']
            budget = GatewayBudget(gateway)
            result['ledger'] = budget.ledger.status()
            budget.preflight(gateway['max_output_tokens'])
            result['status'] = 'GATEWAY_PREFLIGHT_PASSED_NOT_EXECUTION_AUTHORIZATION'
        except (ValidationError, OSError) as exc:
            result.update(status='BLOCKED', reason=str(exc))
            code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
