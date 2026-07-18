from __future__ import annotations

import gc
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd


_DEPENDENCY = re.compile(
    r"^\s*(?:redirect|compile)\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))",
    flags=re.IGNORECASE,
)


def load_legacy_core(path: Path) -> ModuleType:
    """Load the frozen D5 network module without modifying the archived file."""
    source = path.resolve(strict=True)
    module_name = f"evflex_legacy_network_{source.stat().st_mtime_ns}"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load legacy network core: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def validate_feeder_tree(root: Path, master_name: str) -> tuple[Path, ...]:
    """Return DSS files reached by Redirect/Compile after containment checks."""
    feeder_root = root.resolve(strict=True)
    if not feeder_root.is_dir():
        raise NotADirectoryError(feeder_root)
    master = (feeder_root / master_name).resolve(strict=True)
    _assert_contained(master, feeder_root)

    visited: set[Path] = set()
    pending = [master]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        _assert_contained(current, feeder_root)
        if not current.is_file():
            raise FileNotFoundError(current)
        visited.add(current)

        for raw_line in current.read_text(encoding="utf-8-sig", errors="strict").splitlines():
            line = raw_line.split("!", 1)[0].split("//", 1)[0]
            match = _DEPENDENCY.match(line)
            if not match:
                continue
            dependency_name = next(value for value in match.groups() if value is not None)
            dependency = (current.parent / dependency_name).resolve(strict=False)
            _assert_contained(dependency, feeder_root)
            if not dependency.is_file():
                raise FileNotFoundError(
                    f"Missing DSS dependency referenced by {current.name}: {dependency}"
                )
            pending.append(dependency.resolve(strict=True))

    return tuple(sorted(visited, key=lambda path: str(path).casefold()))


def configure_core(core: ModuleType, repo_root: Path) -> None:
    """Point the archived network core at the verified V2.0 feeder copies."""
    repo = repo_root.resolve(strict=True)
    masters = {
        "ieee13": repo / "data" / "feeders" / "ieee13" / "IEEE13Nodeckt.dss",
        "lv906": repo / "data" / "feeders" / "lv906_core" / "MasterStaticAudit.dss",
    }
    for feeder, master in masters.items():
        if feeder not in core.FEEDERS:
            raise KeyError(f"Legacy core has no feeder configuration for {feeder}")
        core.FEEDERS[feeder]["master"] = master.resolve(strict=True)
    core.FEEDERS["ieee13"]["kva_limit"] = 5000.0
    core.FEEDERS["lv906"]["kva_limit"] = 800.0


def run_network_smoke(repo_root: Path) -> dict[str, Any]:
    """Compile and solve each feeder/model pair sequentially with a tiny fleet."""
    repo = repo_root.resolve(strict=True)
    core = load_legacy_core(repo / "legacy" / "d5_v1_2" / "network_core_v1_2.py")
    configure_core(core, repo)

    cases = (
        ("ieee13", "634", 0.277),
        ("lv906", "178", 0.240),
    )
    results: list[dict[str, Any]] = []
    for feeder, bus, kv_ln in cases:
        fleet = pd.DataFrame([{"bus": bus, "phase": 1, "kv_ln": kv_ln}])
        for model in ("3ph", "balanced"):
            network = core.Network(
                feeder,
                fleet,
                model,
                load_scale=1.0,
                vmin=0.95,
                vmax=1.06,
                vuf=2.0,
            )
            base = network.base
            results.append(
                {
                    "feeder": feeder,
                    "model": model,
                    "converged": bool(base["converged"]),
                    "feasible": bool(base["feasible"]),
                    "groups": len(network.groups),
                    "monitored_metrics": len(base["metrics"]),
                    "vmin_pu": _finite_or_none(base["vmin"]),
                    "vmax_pu": _finite_or_none(base["vmax"]),
                    "vuf_max_pct": _finite_or_none(base["vufmax"]),
                    "line_loading_max_pu": _finite_or_none(base["linemax"]),
                    "feeder_loading_pu": _finite_or_none(base["sload"]),
                    "violation_count": len(base["violations"]),
                }
            )
            del network
            gc.collect()

    return {
        "gate": "PASS" if all(row["converged"] for row in results) else "FAIL",
        "resource_policy": {
            "numeric_threads": 1,
            "execution": "sequential",
            "processes": 1,
        },
        "cases": results,
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON report without exposing a partially-written target."""
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _assert_contained(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"DSS dependency escapes feeder root: {path}") from exc


def _finite_or_none(value: Any) -> float | None:
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None
