"""Reconstruct one representative schedule and check its two network-boundary samples."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
for name in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
             'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS']:
    os.environ[name] = '1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['ieee13_1900_28', 'lv906_1900_28'], default='ieee13_1900_28')
    args = parser.parse_args()
    import numpy as np
    from evflex.design import load_design
    from evflex.runtime import (_create_real_pilot_runtime, _normalize_raw_balanced_result,
                                _compact_audit_summary, canonical_schedule_sha256)
    config, cases = load_design(ROOT)
    row = cases[cases.scenario_id == args.case].iloc[0].to_dict()
    saved = next(r for r in json.loads((ROOT / 'results/evaluations.json').read_text(encoding='utf-8'))
                 if r['scenario_id'] == args.case)
    runtime = _create_real_pilot_runtime(ROOT, row, config)
    baseline = np.asarray(runtime.baseline, dtype=float)
    normalized = _normalize_raw_balanced_result(runtime.generate_balanced_raw(15, 'balanced'),
                                                15, runtime.fleet, baseline, direction='inc')
    target = normalized['schedule']
    require(normalized['physical_feasible'] is True, 'Target vehicle constraints failed')
    require(canonical_schedule_sha256(runtime.fleet, baseline) == saved['baseline_schedule_sha256'], 'Baseline hash differs')
    require(canonical_schedule_sha256(runtime.fleet, target) == saved['schedule_sha256'], 'Target hash differs')
    require(abs(float(normalized['flex_kw']) - float(saved['f_bal_kw'])) < 1e-5, 'Scheduled offer differs')
    cache = runtime.create_corrected_truth_cache()
    base_audit = runtime.audit_corrected(baseline, cache, baseline_slot_results=None,
                                        stop_on_violation=False, retain_slot_results=True)
    alpha_l = float(saved['alpha_transfer'])
    points = []
    for alpha, expected in [(0.0, True), (alpha_l, True), (round(alpha_l + 0.002, 3), False), (1.0, False)]:
        info = _compact_audit_summary(runtime.audit_corrected(baseline + alpha * (target - baseline),
            cache, baseline_slot_results=base_audit['slot_results'], stop_on_violation=False, retain_slot_results=False))
        require(info['checked_intervals'] == 96 and info['complete_coverage'], 'Incomplete time coverage')
        require(info['nonconverged_checks'] == 0 and info['numerical_failure_checks'] == 0, 'Numerical failure')
        require(info['feasible'] == expected, f'Feasibility differs at alpha={alpha}')
        points.append({'alpha': alpha, 'feasible': info['feasible']})
    print(json.dumps({'status': 'PASS', 'case': args.case, 'endpoint_hashes_match': True, 'points': points}, indent=2))


if __name__ == '__main__':
    main()
