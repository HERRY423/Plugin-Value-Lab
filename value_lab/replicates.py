"""Bounded exact inference on frozen independent-unit measurements.

This is a computational reference, not a count model, a normalization pipeline,
or proof of exchangeability. All assumptions and the complete testing family
must be supplied before inspecting a submitted result.
"""
from collections import defaultdict
import csv
import io
import itertools
import math
import sys

from .core import ValidationError, load_json
from .science import keys, number, read_reference, reference, reference_json

MAX_ASSIGNMENTS = 65536
MAX_WORK = 2000000


def validate_spec(spec):
    keys(spec, "design data alpha minimum_effect absolute relative")
    for name in ("design", "data"):
        reference(spec[name])
    if not 0 < number(spec["alpha"]) < 1:
        raise ValidationError("alpha must be strictly between zero and one")
    for name in ("minimum_effect", "absolute", "relative"):
        if number(spec[name]) < 0:
            raise ValidationError("Effect thresholds and tolerances must be nonnegative")
    if spec["absolute"] > 1e-4 or spec["relative"] > 1e-4:
        raise ValidationError("Recomputation tolerances must not exceed 1e-4")


def _names(items, name, maximum):
    if not isinstance(items, list) or not 1 <= len(items) <= maximum:
        raise ValidationError(f"{name} must contain 1..{maximum} entries")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in items) or len(set(items)) != len(items):
        raise ValidationError(f"{name} must contain unique nonempty names")


def validate_design(design):
    keys(design, "format mode control treatment features samples training_units exchangeability")
    if design["format"] != "pvl-replicate-design-1" or design["mode"] not in ("independent", "paired"):
        raise ValidationError("Unsupported replicate design")
    _names([design["control"], design["treatment"]], "contrast", 2)
    _names(design["features"], "features", 100)
    if not isinstance(design["samples"], list) or not 4 <= len(design["samples"]) <= 32:
        raise ValidationError("Design requires 4..32 independent-unit samples")
    if not isinstance(design["exchangeability"], str) or not design["exchangeability"].strip():
        raise ValidationError("An explicit exchangeability justification is required")
    training = design["training_units"]
    if training != []:
        _names(training, "training_units", 100000)
    units, blocks, ids = defaultdict(list), defaultdict(list), set()
    for sample in design["samples"]:
        keys(sample, "id unit condition block")
        for k in sample:
            if not isinstance(sample[k], str) or not sample[k].strip() or len(sample[k]) > 200:
                raise ValidationError("Sample identifiers must be nonempty strings")
        if sample["id"] in ids or sample["condition"] not in (design["control"], design["treatment"]):
            raise ValidationError("Duplicate sample or unexpected condition")
        ids.add(sample["id"])
        units[sample["unit"]].append(sample)
        blocks[sample["block"]].append(sample)
    if set(units) & set(training):
        raise ValidationError("Independent units overlap training and evaluation")
    groups = {design["control"], design["treatment"]}
    if design["mode"] == "paired":
        if any(len(v) != 2 or {s["condition"] for s in v} != groups or len({s["block"] for s in v}) != 1 for v in units.values()):
            raise ValidationError("Every paired unit requires exactly one sample per condition in the same block")
        assignments = 2 ** len(units)
    else:
        if any(len(v) != 1 for v in units.values()):
            raise ValidationError("Pseudoreplication: an independent unit appears more than once")
        if any(sum(s["condition"] == g for s in design["samples"]) < 2 for g in groups):
            raise ValidationError("At least two independent units per condition are required")
        if any({s["condition"] for s in v} != groups for v in blocks.values()):
            raise ValidationError("Condition is confounded with a block; every block must contain both conditions")
        assignments = math.prod(math.comb(len(v), sum(s["condition"] == design["treatment"] for s in v)) for v in blocks.values())
    if assignments > MAX_ASSIGNMENTS or assignments * len(design["features"]) * len(design["samples"]) > MAX_WORK:
        raise ValidationError("Exact enumeration exceeds the bounded reference budget; no approximate fallback")
    return {"independent_units": len(units), "samples": len(ids), "blocks": len(blocks), "assignments": assignments,
            "training_overlap": False, "unit_identity": "DECLARED_NOT_AUTHENTICATED",
            "exchangeability": "DECLARED_NOT_VERIFIED"}


def _data(raw, design):
    table = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if table.fieldnames != ["sample", "feature", "value"]:
        raise ValidationError("Reference CSV columns must be sample,feature,value")
    expected = {(s["id"], f) for s in design["samples"] for f in design["features"]}
    values = {}
    for row in table:
        if set(row) != {"sample", "feature", "value"} or any(v is None for v in row.values()):
            raise ValidationError("Malformed reference CSV row")
        key = row["sample"], row["feature"]
        if key not in expected or key in values:
            raise ValidationError("Unexpected or duplicate sample-feature measurement")
        if len(row["value"]) > 100:
            raise ValidationError("Measurement representation too long")
        value = float(row["value"])
        number(value)
        values[key] = value
    if set(values) != expected:
        raise ValidationError("Reference must cover every frozen sample-feature combination")
    return values


def _bh(ps):
    result, bound = [0.] * len(ps), 1.
    order = sorted(range(len(ps)), key=ps.__getitem__)
    for rank in range(len(ps), 0, -1):
        i = order[rank - 1]
        bound = min(bound, ps[i] * len(ps) / rank)
        result[i] = bound
    return result


def recompute(design, raw, spec):
    """Exact, two-sided doubled-min-tail tests; contrast is treatment-control."""
    validate_spec(spec)
    audit = validate_design(design)
    values = _data(raw, design)
    samples = sorted(design["samples"], key=lambda s: s["id"])
    treatment = [i for i, s in enumerate(samples) if s["condition"] == design["treatment"]]
    control = [i for i, s in enumerate(samples) if s["condition"] == design["control"]]
    pairs, block_indices = defaultdict(dict), defaultdict(list)
    for i, s in enumerate(samples):
        pairs[s["unit"]][s["condition"]] = i
        block_indices[s["block"]].append(i)
    if design["mode"] == "independent":
        options = [list(itertools.combinations(indices, sum(i in treatment for i in indices)))
                   for _, indices in sorted(block_indices.items())]
        assignments = [tuple(itertools.chain.from_iterable(choice)) for choice in itertools.product(*options)]
    else:
        assignments = list(itertools.product((-1, 1), repeat=len(pairs)))
    results = []
    for feature in design["features"]:
        original = [values[s["id"], feature] for s in samples]
        scale = max(map(abs, original)) or 1.
        x = [v / scale for v in original]
        if design["mode"] == "paired":
            differences = [x[p[design["treatment"]]] - x[p[design["control"]]] for _, p in sorted(pairs.items())]
            observed = math.fsum(differences) / len(differences)
            null = (math.fsum(v * sign for v, sign in zip(differences, signs)) / len(differences) for signs in assignments)
            loo = [math.fsum(differences[:i] + differences[i+1:]) / (len(differences)-1) for i in range(len(differences))]
        else:
            def statistic(selected, excluded=None):
                a = [x[i] for i in selected if i != excluded]
                b = [v for i, v in enumerate(x) if i not in selected and i != excluded]
                return math.fsum(a)/len(a) - math.fsum(b)/len(b)
            observed = statistic(treatment)
            null = (statistic(selected) for selected in assignments)
            loo = [statistic(treatment, i) for i in range(len(samples))]
        # Tie handling is specified, never chosen after viewing a result.
        tolerance = 100 * sys.float_info.epsilon * max(1., abs(observed))
        lower = upper = 0
        for v in null:
            lower += v <= observed + tolerance
            upper += v >= observed - tolerance
        p_value = min(1., 2 * min(lower, upper) / len(assignments))
        numbers = [observed * scale, min(loo) * scale, max(loo) * scale]
        for v in numbers:
            number(v)
        results.append({"feature": feature, "effect": numbers[0], "p_value": p_value,
                        "n_control": len(control), "n_treatment": len(treatment),
                        "loo_effect_min": numbers[1], "loo_effect_max": numbers[2]})
    for result, q in zip(results, _bh([r["p_value"] for r in results])):
        result["q_value"] = q
        result["decision"] = "supported" if q <= spec["alpha"] and abs(result["effect"]) >= spec["minimum_effect"] and result["effect"] != 0 else "not_supported"
    return {"format": "pvl-replicate-result-1", "method": "exact-blocked-permutation-bh",
            "analysis_unit": "independent_unit", "mode": design["mode"],
            "contrast": [design["control"], design["treatment"]], "alternative": "two-sided-doubled-min-tail",
            "design_sha256": spec["design"]["sha256"], "data_sha256": spec["data"]["sha256"],
            "alpha": spec["alpha"], "minimum_effect": spec["minimum_effect"], "results": results}, audit


def check(path, spec, root):
    try:
        design = reference_json(root, spec["design"])
        expected, audit = recompute(design, read_reference(root, spec["data"]), spec)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise OSError("Invalid or unsupported frozen replicate reference: " + str(exc)) from exc
    submitted = load_json(path)
    detail = {"design_audit": audit, "design_sha256": spec["design"]["sha256"], "data_sha256": spec["data"]["sha256"],
              "method": expected["method"], "testing_family_size": len(expected["results"]), "mismatches": [],
              "scope": "Recomputed supplied unit-level measurements; normalization, independence and biological validity not established"}
    if not isinstance(submitted, dict) or set(submitted) != set(expected):
        detail["mismatches"].append("result_contract")
        return False, detail
    for key in sorted(expected.keys() - {"results"}):
        if type(submitted[key]) is not type(expected[key]) and key not in ("alpha", "minimum_effect"):
            detail["mismatches"].append(key)
        elif key in ("alpha", "minimum_effect"):
            if type(submitted[key]) not in (int, float) or submitted[key] != expected[key]:
                detail["mismatches"].append(key)
        elif submitted[key] != expected[key]:
            detail["mismatches"].append(key)
    rows = submitted["results"]
    if (not isinstance(rows, list) or len(rows) != len(expected["results"]) or
            any(not isinstance(r, dict) or not isinstance(r.get("feature"), str) for r in rows) or
            len({r["feature"] for r in rows}) != len(rows) or
            {r["feature"] for r in rows} != {r["feature"] for r in expected["results"]}):
        detail["mismatches"].append("complete_testing_family")
        return False, detail
    observed = {r["feature"]: r for r in rows}
    for truth in expected["results"]:
        actual = observed[truth["feature"]]
        if set(actual) != set(truth):
            detail["mismatches"].append(truth["feature"] + "/fields")
            continue
        for k, v in truth.items():
            a = actual[k]
            if k in ("effect", "p_value", "q_value", "loo_effect_min", "loo_effect_max"):
                try:
                    number(a)
                    ok = abs(a-v) <= spec["absolute"] + spec["relative"] * abs(v)
                except (ValueError, OverflowError):
                    ok = False
                if k in ("p_value", "q_value"):
                    ok = ok and 0 <= a <= 1
            else:
                ok = type(a) is type(v) and a == v
            if not ok:
                detail["mismatches"].append(truth["feature"] + "/" + k)
    return not detail["mismatches"], detail
