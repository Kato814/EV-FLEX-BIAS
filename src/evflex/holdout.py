from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

import pandas as pd

from evflex.provenance import sha256_file


PROTOCOL_ID = "EV-FLEX-BIAS-V2.0"
GATE_NAMES = {
    "reports/provenance_gate_v2_0.json": "G0_PROVENANCE",
    "reports/engine_regression_gate_v2_0.json": "G1_ENGINE_REGRESSION",
    "reports/development_gate_v2_0.json": "G2_DEVELOPMENT",
    "reports/modeling_gate_v2_0.json": "G3_MODEL_THRESHOLD_FREEZE",
    "reports/ablation_gate_v2_0.json": "G4_ABLATION_FREEZE",
}
RAW_HASH_MANIFESTS = (
    "reports/development_work_unit_hashes_v2_0.csv",
    "reports/ablation_work_unit_hashes_v2_0.csv",
)
UNLOCK_RELATIVE_PATH = "state/holdout_unlock_v2_0.json"


def validate_gate_payloads(payloads: Mapping[str, Mapping[str, Any]]) -> None:
    errors = []
    for path, expected_gate in GATE_NAMES.items():
        payload = payloads.get(path)
        if payload is None:
            errors.append(f"{expected_gate}: missing report {path}")
            continue
        if str(payload.get("gate")) != expected_gate:
            errors.append(
                f"{expected_gate}: report gate is {payload.get('gate')!r}"
            )
        if str(payload.get("gate_status")) != "PASS":
            errors.append(
                f"{expected_gate}: gate_status is {payload.get('gate_status')!r}"
            )
    if errors:
        raise ValueError("pre-holdout gates are not all PASS: " + "; ".join(errors))


def load_gate_payloads(repo_root: Path) -> dict[str, dict[str, Any]]:
    repo = repo_root.resolve(strict=True)
    payloads = {}
    for relative_path in GATE_NAMES:
        path = repo / relative_path
        if not path.is_file():
            continue
        payloads[relative_path] = json.loads(path.read_text(encoding="utf-8"))
    validate_gate_payloads(payloads)
    return payloads


def verify_file_records(repo_root: Path, records: list[Mapping[str, Any]]) -> None:
    repo = repo_root.resolve(strict=True)
    errors = []
    seen = set()
    for record in records:
        relative_path = str(record["path"]).replace("\\", "/")
        if relative_path in seen:
            errors.append(f"duplicate freeze path: {relative_path}")
            continue
        seen.add(relative_path)
        path = repo / relative_path
        if not path.is_file():
            errors.append(f"missing frozen file: {relative_path}")
            continue
        actual_hash = sha256_file(path)
        if actual_hash != str(record["sha256"]).lower():
            errors.append(
                f"hash mismatch: {relative_path}: {actual_hash} != {record['sha256']}"
            )
        if path.stat().st_size != int(record["bytes"]):
            errors.append(
                f"size mismatch: {relative_path}: {path.stat().st_size} != {record['bytes']}"
            )
    if errors:
        raise ValueError("; ".join(errors))


def assert_holdout_sealed(repo_root: Path) -> None:
    repo = repo_root.resolve(strict=True)
    unlock = repo / UNLOCK_RELATIVE_PATH
    if unlock.exists():
        try:
            payload = json.loads(unlock.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("holdout unlock record already exists and is unreadable") from exc
        if payload.get("status") == "UNLOCKED" or int(
            payload.get("holdout_open_count", 0)
        ) >= 1:
            raise ValueError("holdout was already opened; a second opening is prohibited")
        raise ValueError("holdout unlock record already exists")

    result_roots = (
        repo / "results" / "work_units" / "holdout",
        repo / "results" / "holdout_v2_0",
        repo / "results" / "final_analysis_v2_0",
    )
    existing = []
    for root in result_roots:
        if root.exists():
            existing.extend(path for path in root.rglob("*") if path.is_file())
    if existing:
        names = [str(path.relative_to(repo)).replace("\\", "/") for path in existing]
        raise ValueError(f"holdout result files already exist: {names[:5]}")


def build_pre_holdout_freeze(repo_root: Path, source_commit: str) -> dict[str, Any]:
    repo = repo_root.resolve(strict=True)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", source_commit):
        raise ValueError("source_commit must be a full 40-character Git commit")
    head = git(repo, "rev-parse", "HEAD")
    if head.lower() != source_commit.lower():
        raise ValueError(f"source_commit {source_commit} is not current HEAD {head}")
    dirty = git(repo, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ValueError(f"working tree must be clean before freeze: {dirty}")
    assert_holdout_sealed(repo)
    gates = load_gate_payloads(repo)
    inherited = verify_inherited_assets(repo)
    raw_manifests = verify_raw_work_unit_hashes(repo)

    tracked_paths = [
        line
        for line in git(repo, "ls-files").splitlines()
        if line and not line.startswith("state/holdout_unlock_v2_0.json")
    ]
    file_records = records_for_paths(repo, tracked_paths)
    gate_records = {
        path: {
            "gate": payload["gate"],
            "gate_status": payload["gate_status"],
            "sha256": sha256_file(repo / path),
        }
        for path, payload in gates.items()
    }
    return {
        "gate": "PRE_HOLDOUT_FREEZE",
        "gate_status": "PASS",
        "protocol_id": PROTOCOL_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit.lower(),
        "source_tree": git(repo, "show", "-s", "--format=%T", source_commit),
        "working_tree_clean_at_freeze": True,
        "dirty_status_at_freeze": [],
        "holdout_opened": False,
        "holdout_open_count": 0,
        "holdout_result_files_at_freeze": 0,
        "pre_holdout_gates": gate_records,
        "inherited_assets": inherited,
        "raw_work_unit_hash_manifests": raw_manifests,
        "tracked_files_hashed": len(file_records),
        "file_records": file_records,
        "freeze_rules": {
            "refit_after_open": False,
            "rethreshold_after_open": False,
            "second_holdout_open": False,
            "replacement_ids": False,
        },
    }


def validate_freeze_for_unlock(
    repo_root: Path,
    freeze: Mapping[str, Any],
) -> dict[str, Any]:
    repo = repo_root.resolve(strict=True)
    if freeze.get("gate_status") != "PASS" or freeze.get("gate") != "PRE_HOLDOUT_FREEZE":
        raise ValueError("pre-holdout freeze report is not PASS")
    if freeze.get("protocol_id") != PROTOCOL_ID:
        raise ValueError("pre-holdout freeze protocol mismatch")
    if bool(freeze.get("holdout_opened")) or int(freeze.get("holdout_open_count", 0)) != 0:
        raise ValueError("freeze report records a prior holdout opening")
    assert_holdout_sealed(repo)
    dirty = git(repo, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ValueError(f"working tree must be clean before holdout opening: {dirty}")
    load_gate_payloads(repo)
    verify_file_records(repo, list(freeze.get("file_records", [])))
    verify_raw_work_unit_hashes(repo)
    source_commit = str(freeze["source_commit"])
    current_head = git(repo, "rev-parse", "HEAD")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_commit, current_head],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        raise ValueError("freeze source anchor is not an ancestor of the audit commit")
    return {
        "source_commit": source_commit,
        "audit_commit": current_head,
        "verified_file_records": len(freeze["file_records"]),
    }


def create_unlock_payload(
    repo_root: Path,
    freeze_path: Path,
    freeze: Mapping[str, Any],
) -> dict[str, Any]:
    repo = repo_root.resolve(strict=True)
    verified = validate_freeze_for_unlock(repo, freeze)
    absolute_freeze = freeze_path.resolve(strict=True)
    return {
        "status": "UNLOCKED",
        "protocol_version": PROTOCOL_ID,
        "opened_at_utc": datetime.now(timezone.utc).isoformat(),
        "holdout_open_count": 1,
        "freeze_report": str(absolute_freeze.relative_to(repo)).replace("\\", "/"),
        "freeze_report_sha256": sha256_file(absolute_freeze),
        "source_commit": verified["source_commit"],
        "audit_commit": verified["audit_commit"],
        "verified_file_records": verified["verified_file_records"],
        "frozen_model_sha256": sha256_file(
            repo / "results" / "modeling_v2_0" / "applicability_models_v2_0.json"
        ),
        "refit_allowed": False,
        "rethreshold_allowed": False,
        "replacement_ids_allowed": False,
    }


def verify_inherited_assets(repo_root: Path) -> dict[str, Any]:
    repo = repo_root.resolve(strict=True)
    manifest_path = repo / "manifests" / "inherited_asset_manifest_v2_0.csv"
    manifest = pd.read_csv(manifest_path)
    errors = []
    for row in manifest.itertuples(index=False):
        path = repo / str(row.destination_path)
        if str(row.status) != "VERIFIED":
            errors.append(f"asset is not VERIFIED: {row.asset_id}")
            continue
        if not path.is_file():
            errors.append(f"missing inherited asset: {row.destination_path}")
            continue
        if path.stat().st_size != int(row.bytes):
            errors.append(f"inherited asset size mismatch: {row.destination_path}")
        if sha256_file(path) != str(row.sha256).lower():
            errors.append(f"inherited asset hash mismatch: {row.destination_path}")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "manifest": "manifests/inherited_asset_manifest_v2_0.csv",
        "manifest_sha256": sha256_file(manifest_path),
        "verified_assets": int(len(manifest)),
    }


def verify_raw_work_unit_hashes(repo_root: Path) -> list[dict[str, Any]]:
    repo = repo_root.resolve(strict=True)
    summaries = []
    for relative_manifest in RAW_HASH_MANIFESTS:
        manifest_path = repo / relative_manifest
        frame = pd.read_csv(manifest_path)
        errors = []
        for row in frame.itertuples(index=False):
            path = repo / str(row.relative_path)
            if not path.is_file():
                errors.append(f"missing raw result: {row.relative_path}")
            elif sha256_file(path) != str(row.sha256).lower():
                errors.append(f"raw result hash mismatch: {row.relative_path}")
        if errors:
            raise ValueError("; ".join(errors))
        summaries.append(
            {
                "manifest": relative_manifest,
                "manifest_sha256": sha256_file(manifest_path),
                "verified_raw_files": int(len(frame)),
            }
        )
    return summaries


def records_for_paths(repo_root: Path, relative_paths: list[str]) -> list[dict[str, Any]]:
    repo = repo_root.resolve(strict=True)
    records = []
    for relative_path in sorted(set(relative_paths), key=str.casefold):
        path = repo / relative_path
        if not path.is_file():
            raise ValueError(f"tracked freeze file is missing: {relative_path}")
        records.append(
            {
                "path": relative_path.replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def git(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()
