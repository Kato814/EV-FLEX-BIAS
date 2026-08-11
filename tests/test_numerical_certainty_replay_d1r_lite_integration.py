from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from evflex.numerical_certainty_replay_d1r_lite import (
    apply_solver_setting,
    execute_replay_case,
    load_replay_config,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class _FakeSolution:
    def __init__(self) -> None:
        self.tolerance = 1e-4
        self.max_iterations = 15
        self.max_control_iterations = 100
        self.iterations = 0

    def Convergence(self, value: float | None = None) -> float:
        if value is not None:
            self.tolerance = float(value)
        return self.tolerance

    def MaxIterations(self, value: int | None = None) -> int:
        if value is not None:
            self.max_iterations = int(value)
        return self.max_iterations

    def MaxControlIterations(self, value: int | None = None) -> int:
        if value is not None:
            self.max_control_iterations = int(value)
        return self.max_control_iterations

    def Iterations(self) -> int:
        return self.iterations


class _FakeContext:
    def __init__(self) -> None:
        self.Solution = _FakeSolution()


class _FakeNetwork:
    def __init__(self, metric_id: str, value: float) -> None:
        self.ctx = _FakeContext()
        self.groups = [("bus", 1)]
        self.metric_id = metric_id
        self.value = value

    def evaluate(self, _power: object) -> dict[str, object]:
        import numpy as np

        self.ctx.Solution.iterations = 3
        selected = bool(np.any(np.asarray(_power, dtype=float) != 0.0))
        value = self.value if selected else 1.0
        violations = (
            [
                {
                    "kind": "physical_constraint",
                    "metric": self.metric_id,
                    "value": value,
                    "limit": 1.06,
                    "direction": "hi",
                }
            ]
            if selected
            else []
        )
        return {
            "metrics": {self.metric_id: value},
            "violations": violations,
            "converged": True,
            "numerical_failure": False,
            "vmin": min(1.0, value),
            "vmax": max(1.0, value),
            "line_thermal_in_scope": False,
        }


def test_apply_solver_setting_sets_and_reads_all_three_controls() -> None:
    network = _FakeNetwork("V:test.1", 1.061)
    setting = {
        "label": "TIGHT_1E6",
        "convergence_tolerance": 1e-6,
        "max_iterations": 100,
        "max_control_iterations": 100,
    }

    observed = apply_solver_setting(network, setting)

    assert observed == {
        "convergence_tolerance": 1e-6,
        "max_iterations": 100,
        "max_control_iterations": 100,
    }


def test_execute_replay_case_uses_fresh_network_and_exact_boundary_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import numpy as np
    import evflex.numerical_certainty_replay_d1r_lite as replay

    config = load_replay_config(REPO_ROOT)
    selection = deepcopy(config["selected_cases"][0])
    baseline = np.zeros((1, 96), dtype=float)
    schedule = np.ones((1, 96), dtype=float)
    fleet = [object()]
    group_calls: list[float] = []

    class FakeEngine:
        @staticmethod
        def static_fleet_frame(_fleet: list[object]) -> str:
            return "fixed-frame"

        @staticmethod
        def group_vector(
            _fleet: list[object], power: object, groups: object, model: str
        ) -> object:
            assert groups == [("bus", 1)]
            assert model == "3ph"
            value = float(np.asarray(power)[0])
            group_calls.append(value)
            return np.array([value], dtype=float)

    class FakeRuntime:
        archived_engine = FakeEngine()

    reconstructed = {
        "runtime": FakeRuntime(),
        "fleet": fleet,
        "baseline": baseline,
        "schedule": schedule,
        "load_scales": np.arange(1, 97, dtype=float),
    }
    network_ids: list[int] = []
    values = [
        float(selection["value"]),
        float(selection["value"]) + 2e-8,
        float(selection["value"]) + 2.5e-8,
    ]

    def reconstruct(_root: Path, _case: dict[str, object]) -> dict[str, object]:
        return reconstructed

    def factory(**_kwargs: object) -> _FakeNetwork:
        network = _FakeNetwork(str(selection["metric_id"]), values[len(network_ids)])
        network_ids.append(id(network))
        return network

    monkeypatch.setattr(
        replay,
        "_canonical_schedule_hash",
        lambda _fleet, _schedule: selection["audited_schedule_sha256"],
    )

    artifact = execute_replay_case(
        REPO_ROOT,
        selection,
        config,
        reconstruct_fn=reconstruct,
        network_factory=factory,
    )

    assert artifact["assessment"]["case_decision"] == "NUMERICALLY_STABLE_WITNESS"
    assert len(network_ids) == 3
    assert group_calls == [
        pytest.approx(0.0),
        pytest.approx(float(selection["alpha"])),
    ] * 3
    assert [row["selected_slot"] for row in artifact["observations"]] == [28, 28, 28]
    assert all(row["independent_context"] for row in artifact["observations"])


def test_real_pair_01_replay_matches_archived_native_witness() -> None:
    config = load_replay_config(REPO_ROOT)
    selection = deepcopy(config["selected_cases"][0])

    artifact = execute_replay_case(REPO_ROOT, selection, config)
    native = artifact["observations"][0]

    assert native["setting_label"] == "NATIVE_1E4"
    assert native["observed_solver_settings"] == {
        "convergence_tolerance": 1e-4,
        "max_iterations": 15,
        "max_control_iterations": 100,
    }
    assert native["converged"] is True
    assert native["metric_id"] == "V:860.1"
    assert native["selected_slot"] == 28
    assert native["audited_schedule_sha256"] == selection["audited_schedule_sha256"]
    assert artifact["assessment"]["native_replay_abs_diff_pu"] <= 1e-9
