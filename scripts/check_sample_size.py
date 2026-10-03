"""Cross-check paired power against statsmodels and independent Gaussian sampling.

Manufactured statistical-model validation only; no plugin or scientific benefit.
Requires validation-environment scipy/numpy/statsmodels; core normal planning does not.
"""
import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from value_lab.sample_size import plan_sample_size


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    import numpy as np
    import scipy
    from scipy import stats
    import statsmodels
    from statsmodels.stats.power import TTestPower
    base = {'version': 2, 'minimum_detectable_delta': .1, 'alpha': .05, 'power': .8,
            'between_family_sd': .2, 'between_task_sd': 0, 'within_task_sd': 0,
            'tasks_per_family': [1], 'repetitions_per_case': [1], 'max_families': 10000,
            'variance_source': 'Manufactured Gaussian model, not pilot data',
            'sampling_basis': 'independent_representative_families', 'method': 'paired_t',
            'comparisons': 1, 'sd_multipliers': [1]}
    checks = []
    for standardized_effect in (.2, .5, .8):
        for alpha in (.01, .05):
            for power in (.8, .9):
                spec = {**base, 'minimum_detectable_delta': .2*standardized_effect, 'alpha': alpha, 'power': power}
                row = plan_sample_size(spec)['recommended_design']
                reference = math.ceil(TTestPower().solve_power(effect_size=standardized_effect, alpha=alpha, power=power))
                checks.append({'standardized_effect': standardized_effect, 'alpha': alpha, 'power': power,
                               'pvl_families': row['required_families'], 'statsmodels_families': reference,
                               'match': row['required_families'] == reference})
    rng = np.random.default_rng(20261003)
    simulations, n = 20000, 34
    errors = rng.normal(0, .2, size=(simulations, n))
    critical = float(stats.t.isf(.025, n-1))
    se = errors.std(axis=1, ddof=1)/math.sqrt(n)
    null_means = errors.mean(axis=1)
    power = float(np.mean(np.abs((null_means+.1)/se) > critical))
    type1 = float(np.mean(np.abs(null_means/se) > critical))
    coverage = float(np.mean(np.abs(null_means) <= critical*se))
    # Hoeffding uses bounded observations, a separate simulation from normal t.
    bounded = rng.uniform(-.4, .8, size=(simulations, 100))
    half = math.sqrt(2*math.log(40)/100)
    hoeffding_coverage = float(np.mean(np.abs(bounded.mean(axis=1)-.2) <= half))
    def wilson(rate):
        z, denominator = 1.959963984540054, 1+1.959963984540054**2/simulations
        center = (rate+z*z/(2*simulations))/denominator
        h = z*math.sqrt(rate*(1-rate)/simulations+z*z/(4*simulations**2))/denominator
        return [center-h, center+h]
    expected = plan_sample_size(base)['recommended_design']['conditional_power']
    hierarchical_spec = {**base, 'between_family_sd': .15, 'between_task_sd': .1, 'within_task_sd': .2,
                         'tasks_per_family': [2], 'repetitions_per_case': [3]}
    hierarchical_design = plan_sample_size(hierarchical_spec)['recommended_design']
    f = hierarchical_design['required_families']
    family = rng.normal(0, .15, size=(simulations, f, 1, 1))
    task = rng.normal(0, .1, size=(simulations, f, 2, 1))
    repeat = rng.normal(0, .2, size=(simulations, f, 2, 3))
    family_means = (.1 + family + task + repeat).mean(axis=(2, 3))
    hierarchical_t = family_means.mean(axis=1)/(family_means.std(axis=1, ddof=1)/math.sqrt(f))
    hierarchical_power = float(np.mean(np.abs(hierarchical_t) > stats.t.isf(.025, f-1)))
    passed = (all(c['match'] for c in checks) and abs(power-expected) < .015 and .035 <= type1 <= .065
              and .935 <= coverage <= .965 and hoeffding_coverage >= .95
              and abs(hierarchical_power-hierarchical_design['conditional_power']) < .015)
    result = {'status': 'PASS' if passed else 'FAIL', 'scope': 'MANUFACTURED_STATISTICAL_MODEL_VALIDATION',
              'versions': {'numpy': np.__version__, 'scipy': scipy.__version__, 'statsmodels': statsmodels.__version__},
              'reference_cases': checks, 'monte_carlo': {'seed': 20261003, 'replicates': simulations, 'families': n,
                  'expected_t_power': expected, 'observed_t_power': power, 'power_mc95': wilson(power),
                  'null_rejection': type1, 'null_rejection_mc95': wilson(type1), 't_interval_coverage': coverage,
                  't_coverage_mc95': wilson(coverage), 'hoeffding_uniform_coverage': hoeffding_coverage,
                  'hoeffding_coverage_mc95': wilson(hoeffding_coverage)},
              'hierarchical_monte_carlo': {'replicates': simulations, 'families': f, 'tasks_per_family': 2,
                  'repetitions_per_case_per_arm': 3, 'expected_power': hierarchical_design['conditional_power'],
                  'observed_power': hierarchical_power, 'power_mc95': wilson(hierarchical_power)},
              'real_model_calls': 0, 'scientific_validity_established': False,
              'limitations': ['Reference calculations may share SciPy internals; simulation checks a separate sampling path.',
                              'Gaussian model validation does not establish robustness on skewed or dependent laboratory tasks.']}
    (root/'validation.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
