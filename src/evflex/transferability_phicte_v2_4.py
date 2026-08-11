from __future__ import annotations

from collections import defaultdict
import math
from typing import Any, Mapping, Sequence


FEATURE_NAMES = (
    "offer_stress",
    "voltage_margin",
    "vuf_margin",
    "transformer_margin",
    "feeder_margin",
    "feeder_lv906",
    "direction_inc",
    "duration_30",
    "duration_60",
    "time_0000",
    "time_0200",
    "time_0600",
    "lv906_x_inc",
    "lv906_x_duration_30",
    "lv906_x_duration_60",
    "inc_x_duration_30",
    "inc_x_duration_60",
)


def _required_finite(value: Any, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _required_category(
    row: Mapping[str, Any], field: str, allowed: set[Any]
) -> Any:
    value = row.get(field)
    if value not in allowed:
        raise ValueError(f"{field} must be one of {sorted(allowed, key=str)!r}")
    return value


def build_feature_row(
    row: Mapping[str, Any], *, feeder_kva: Mapping[str, float]
) -> dict[str, float]:
    """Build the allowlisted pre-call PHiCTE features for one offer."""

    feeder = _required_category(row, "feeder", {"ieee13", "lv906"})
    direction = _required_category(row, "direction", {"inc", "dec"})
    duration = _required_category(row, "duration_min", {15, 30, 60})
    call_time = _required_category(
        row, "call_time", {"19:00", "00:00", "02:00", "06:00"}
    )
    if feeder not in feeder_kva:
        raise ValueError(f"feeder_kva lacks {feeder!r}")
    rating = _required_finite(feeder_kva[feeder], f"feeder_kva[{feeder}]")
    if rating <= 0.0:
        raise ValueError(f"feeder_kva[{feeder}] must be positive")

    audit = row.get("baseline_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("baseline_audit must be a mapping")
    f_bal_kw = _required_finite(row.get("f_bal_kw"), "f_bal_kw")
    vmin = _required_finite(audit.get("vmin"), "baseline_audit.vmin")
    vmax = _required_finite(audit.get("vmax"), "baseline_audit.vmax")
    vufmax = _required_finite(audit.get("vufmax"), "baseline_audit.vufmax")
    transformer_loading = _required_finite(
        audit.get("transformer_loading_max"),
        "baseline_audit.transformer_loading_max",
    )
    feeder_loading = _required_finite(
        audit.get("feeder_loading_max"), "baseline_audit.feeder_loading_max"
    )

    lv906 = float(feeder == "lv906")
    inc = float(direction == "inc")
    duration_30 = float(duration == 30)
    duration_60 = float(duration == 60)
    values = {
        "offer_stress": abs(f_bal_kw) / rating,
        "voltage_margin": min(vmin - 0.95, 1.06 - vmax),
        "vuf_margin": 2.0 - vufmax,
        "transformer_margin": 1.0 - transformer_loading,
        "feeder_margin": 1.0 - feeder_loading,
        "feeder_lv906": lv906,
        "direction_inc": inc,
        "duration_30": duration_30,
        "duration_60": duration_60,
        "time_0000": float(call_time == "00:00"),
        "time_0200": float(call_time == "02:00"),
        "time_0600": float(call_time == "06:00"),
        "lv906_x_inc": lv906 * inc,
        "lv906_x_duration_30": lv906 * duration_30,
        "lv906_x_duration_60": lv906 * duration_60,
        "inc_x_duration_30": inc * duration_30,
        "inc_x_duration_60": inc * duration_60,
    }
    return {name: values[name] for name in FEATURE_NAMES}


def deterministic_group_folds(
    rows: Sequence[Mapping[str, Any]], *, n_splits: int
) -> list[tuple[list[int], list[int]]]:
    """Return deterministic balanced folds without splitting scenario identities."""

    if not isinstance(n_splits, int) or isinstance(n_splits, bool) or n_splits < 2:
        raise ValueError("n_splits must be an integer of at least two")
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        scenario_id = row.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise ValueError(f"row {index} has invalid scenario_id")
        grouped[scenario_id].append(index)
    if len(grouped) < n_splits:
        raise ValueError("n_splits exceeds the number of distinct scenarios")

    fold_groups: list[list[str]] = [[] for _ in range(n_splits)]
    fold_sizes = [0] * n_splits
    ordered_groups = sorted(grouped, key=lambda key: (-len(grouped[key]), key))
    for scenario_id in ordered_groups:
        destination = min(
            range(n_splits),
            key=lambda index: (
                fold_sizes[index],
                len(fold_groups[index]),
                index,
            ),
        )
        fold_groups[destination].append(scenario_id)
        fold_sizes[destination] += len(grouped[scenario_id])

    all_indices = set(range(len(rows)))
    folds: list[tuple[list[int], list[int]]] = []
    for scenarios in fold_groups:
        test = sorted(
            index for scenario_id in scenarios for index in grouped[scenario_id]
        )
        train = sorted(all_indices.difference(test))
        folds.append((train, test))
    return folds
