from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import traceback
from typing import Any, Callable, Iterator, Mapping


WORK_TERMINAL_STATUSES = {"SUCCESS", "SCIENTIFIC_TERMINAL", "UNHANDLED_FAILURE"}
SCIENTIFIC_PATTERNS = (
    ("3ph baseline infeasible", "THREE_PHASE_BASELINE_INFEASIBLE"),
    ("balanced baseline infeasible", "BALANCED_BASELINE_INFEASIBLE"),
    ("base network failed", "NETWORK_BASE_INFEASIBLE"),
    ("Trajectory alpha LP failed", "TRAJECTORY_INFEASIBLE"),
    ("point optimization failed", "POINT_OPTIMIZATION_INFEASIBLE"),
)


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    lock = path.resolve(strict=False)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    acquired = True
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        fd = -1
        yield
    finally:
        if fd >= 0:
            os.close(fd)
        if acquired:
            lock.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=target.name, suffix=".tmp", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def run_work_unit(
    work_unit: Mapping[str, Any],
    result_path: Path,
    lock_path: Path,
    compute: Callable[[Mapping[str, Any], int], Any],
    *,
    resume: bool,
    max_attempts: int = 3,
    attempt_state_path: Path | None = None,
) -> dict[str, Any]:
    """Run one immutable work unit, retrying only infrastructure exceptions."""
    unit = dict(work_unit)
    result = result_path.resolve(strict=False)
    if result.exists():
        if not resume:
            raise FileExistsError(f"Result already exists: {result}")
        completed = _read_and_validate_completed(result, unit)
        return {**completed, "runner_status": "SKIPPED_COMPLETED"}

    state_path = attempt_state_path or (
        result.parent / ".attempts" / f"{_unit_id(unit)}.json"
    )
    with exclusive_lock(lock_path):
        if result.exists():
            if not resume:
                raise FileExistsError(f"Result already exists: {result}")
            completed = _read_and_validate_completed(result, unit)
            return {**completed, "runner_status": "SKIPPED_COMPLETED"}

        state = _load_attempt_state(state_path) if resume else {"attempt_count": 0, "errors": []}
        attempt_count = int(state.get("attempt_count", 0))
        errors = list(state.get("errors", []))
        if attempt_count >= max_attempts:
            payload = _failure_payload(unit, attempt_count, errors)
            atomic_write_json(result, payload)
            state_path.unlink(missing_ok=True)
            return {**payload, "runner_status": "WROTE_TERMINAL"}

        while attempt_count < max_attempts:
            attempt_count += 1
            atomic_write_json(
                state_path,
                {
                    "work_unit_id": _unit_id(unit),
                    "scenario_seed": _seed(unit),
                    "attempt_count": attempt_count,
                    "errors": errors,
                },
            )
            try:
                computed = compute(unit, attempt_count)
                payload = _success_or_scientific_payload(unit, computed, attempt_count)
                validate_completed_payload(payload, unit)
                atomic_write_json(result, payload)
                state_path.unlink(missing_ok=True)
                return {**payload, "runner_status": "WROTE_TERMINAL"}
            except Exception as exc:
                scientific_status = classify_scientific_exception(exc)
                if scientific_status is not None:
                    payload = _scientific_payload(
                        unit, attempt_count, scientific_status, str(exc)
                    )
                    validate_completed_payload(payload, unit)
                    atomic_write_json(result, payload)
                    state_path.unlink(missing_ok=True)
                    return {**payload, "runner_status": "WROTE_TERMINAL"}
                errors.append(
                    {
                        "attempt": attempt_count,
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
                atomic_write_json(
                    state_path,
                    {
                        "work_unit_id": _unit_id(unit),
                        "scenario_seed": _seed(unit),
                        "attempt_count": attempt_count,
                        "errors": errors,
                    },
                )

        payload = _failure_payload(unit, attempt_count, errors)
        validate_completed_payload(payload, unit)
        atomic_write_json(result, payload)
        state_path.unlink(missing_ok=True)
        return {**payload, "runner_status": "WROTE_TERMINAL"}


def validate_completed_payload(
    payload: Mapping[str, Any], work_unit: Mapping[str, Any]
) -> None:
    if str(payload.get("status")) not in WORK_TERMINAL_STATUSES:
        raise ValueError(f"Nonterminal work-unit status: {payload.get('status')}")
    if str(payload.get("work_unit_id")) != _unit_id(work_unit):
        raise ValueError("Completed result work-unit ID mismatch")
    if int(payload.get("scenario_seed")) != _seed(work_unit):
        raise ValueError("Completed result seed mismatch")
    expected = expected_evaluation_ids(work_unit)
    evaluations = payload.get("evaluations")
    if not isinstance(evaluations, list) or len(evaluations) != len(expected):
        raise ValueError(
            f"Completed result must contain {len(expected)} evaluations"
        )
    actual = [str(row.get("evaluation_id")) for row in evaluations]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError("Completed evaluation IDs do not match the manifest")
    if any(not str(row.get("status")) for row in evaluations):
        raise ValueError("Every evaluation must have a terminal status")


def expected_evaluation_ids(work_unit: Mapping[str, Any]) -> list[str]:
    if "evaluation_ids" in work_unit:
        raw = work_unit["evaluation_ids"]
        values = json.loads(raw) if isinstance(raw, str) else list(raw)
        if len(values) != 3:
            raise ValueError("Core work unit must have exactly three evaluation IDs")
        return [str(value) for value in values]
    if "ablation_id" in work_unit:
        return [str(work_unit["ablation_id"])]
    raise ValueError("Unknown work-unit schema")


def classify_scientific_exception(exc: Exception) -> str | None:
    if not isinstance(exc, RuntimeError):
        return None
    message = str(exc)
    for pattern, status in SCIENTIFIC_PATTERNS:
        if pattern in message:
            return status
    return None


def _read_and_validate_completed(
    path: Path, work_unit: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Existing result is unreadable and will not be overwritten: {path}") from exc
    validate_completed_payload(payload, work_unit)
    return payload


def _success_or_scientific_payload(
    work_unit: Mapping[str, Any], computed: Any, attempt_count: int
) -> dict[str, Any]:
    if isinstance(computed, list):
        evaluations = computed
        base: dict[str, Any] = {}
    elif isinstance(computed, Mapping) and isinstance(computed.get("evaluations"), list):
        evaluations = list(computed["evaluations"])
        base = dict(computed)
        base.pop("evaluations", None)
    else:
        raise TypeError("Engine must return an evaluation list or a payload with evaluations")
    status = (
        "SUCCESS"
        if all(str(row.get("status")) == "SUCCESS" for row in evaluations)
        else "SCIENTIFIC_TERMINAL"
    )
    return {
        **base,
        "protocol_version": str(work_unit.get("protocol_version", "EV-FLEX-BIAS-V2.0")),
        "work_unit_id": _unit_id(work_unit),
        "scenario_seed": _seed(work_unit),
        "data_role": str(work_unit["data_role"]),
        "status": status,
        "attempt_count": attempt_count,
        "evaluations": evaluations,
    }


def _scientific_payload(
    work_unit: Mapping[str, Any], attempt_count: int, status: str, message: str
) -> dict[str, Any]:
    evaluations = [
        _minimal_evaluation(work_unit, evaluation_id, status)
        for evaluation_id in expected_evaluation_ids(work_unit)
    ]
    return {
        "protocol_version": str(work_unit.get("protocol_version", "EV-FLEX-BIAS-V2.0")),
        "work_unit_id": _unit_id(work_unit),
        "scenario_seed": _seed(work_unit),
        "data_role": str(work_unit["data_role"]),
        "status": "SCIENTIFIC_TERMINAL",
        "scientific_status": status,
        "message": message,
        "attempt_count": attempt_count,
        "evaluations": evaluations,
    }


def _failure_payload(
    work_unit: Mapping[str, Any], attempt_count: int, errors: list[dict[str, Any]]
) -> dict[str, Any]:
    evaluations = [
        _minimal_evaluation(work_unit, evaluation_id, "UNHANDLED_FAILURE")
        for evaluation_id in expected_evaluation_ids(work_unit)
    ]
    return {
        "protocol_version": str(work_unit.get("protocol_version", "EV-FLEX-BIAS-V2.0")),
        "work_unit_id": _unit_id(work_unit),
        "scenario_seed": _seed(work_unit),
        "data_role": str(work_unit["data_role"]),
        "status": "UNHANDLED_FAILURE",
        "attempt_count": attempt_count,
        "errors": errors,
        "evaluations": evaluations,
    }


def _minimal_evaluation(
    work_unit: Mapping[str, Any], evaluation_id: str, status: str
) -> dict[str, Any]:
    duration = None
    for candidate in (15, 30, 60):
        if evaluation_id.endswith(f"__{candidate}m"):
            duration = candidate
            break
    return {
        "evaluation_id": evaluation_id,
        "scenario_id": work_unit.get("scenario_id"),
        "feeder": work_unit.get("feeder"),
        "call_time": work_unit.get("call_time"),
        "direction": work_unit.get("direction"),
        "duration_min": duration if duration is not None else work_unit.get("duration_min"),
        "status": status,
    }


def _load_attempt_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"attempt_count": 0, "errors": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Attempt state is unreadable: {path}") from exc
    return payload


def _unit_id(work_unit: Mapping[str, Any]) -> str:
    if "work_unit_id" in work_unit:
        return str(work_unit["work_unit_id"])
    if "ablation_id" in work_unit:
        return str(work_unit["ablation_id"])
    raise ValueError("Work unit has no stable ID")


def _seed(work_unit: Mapping[str, Any]) -> int:
    if "scenario_seed" in work_unit:
        return int(work_unit["scenario_seed"])
    if "seed" in work_unit:
        return int(work_unit["seed"])
    raise ValueError("Work unit has no frozen seed")
