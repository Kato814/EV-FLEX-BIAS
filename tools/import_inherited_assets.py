from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

from evflex.provenance import sha256_file


REQUIRED_COLUMNS = (
    "asset_id",
    "source_kind",
    "source_path",
    "archive_entry",
    "destination_path",
    "expected_sha256",
    "authority",
)


def contained_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    candidate.relative_to(root)
    return candidate


def install_temp_file(temp_path: Path, destination: Path, expected_sha256: str) -> tuple[str, int]:
    actual = sha256_file(temp_path)
    if actual != expected_sha256.lower():
        raise ValueError(f"copied hash mismatch: {destination}: {actual} != {expected_sha256}")
    size = temp_path.stat().st_size
    if destination.exists():
        existing = sha256_file(destination)
        if existing != expected_sha256.lower():
            raise FileExistsError(f"destination differs: {destination}")
        temp_path.unlink()
        return existing, destination.stat().st_size
    os.replace(temp_path, destination)
    return actual, size


def copy_file(source: Path, destination: Path, expected_sha256: str) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=destination.name, suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        shutil.copyfile(source, temp_path)
        return install_temp_file(temp_path, destination, expected_sha256)
    finally:
        temp_path.unlink(missing_ok=True)


def extract_zip_entry(
    archive: Path, entry_name: str, destination: Path, expected_sha256: str
) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=destination.name, suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(archive) as bundle:
            try:
                info = bundle.getinfo(entry_name)
            except KeyError as exc:
                raise FileNotFoundError(f"archive entry missing: {archive}!{entry_name}") from exc
            if info.is_dir():
                raise ValueError(f"archive entry is a directory: {entry_name}")
            with bundle.open(info) as source, temp_path.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
        return install_temp_file(temp_path, destination, expected_sha256)
    finally:
        temp_path.unlink(missing_ok=True)


def load_requirements(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
            raise ValueError(f"unexpected requirement columns: {reader.fieldnames}")
        rows = list(reader)
    asset_ids = [row["asset_id"] for row in rows]
    destinations = [row["destination_path"] for row in rows]
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError("duplicate asset_id")
    if len(destinations) != len(set(destinations)):
        raise ValueError("duplicate destination_path")
    return rows


def write_csv_atomic(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with temp_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def import_assets(
    project_parent: Path, repo_root: Path, requirements_path: Path
) -> tuple[list[dict[str, object]], list[str]]:
    rows = load_requirements(requirements_path)
    manifest: list[dict[str, object]] = []
    errors: list[str] = []
    for row in rows:
        source = contained_path(project_parent, row["source_path"])
        destination = contained_path(repo_root, row["destination_path"])
        expected = row["expected_sha256"].lower()
        try:
            if not source.is_file():
                raise FileNotFoundError(source)
            if row["source_kind"] == "file":
                actual, byte_count = copy_file(source, destination, expected)
            elif row["source_kind"] == "zip_entry":
                actual, byte_count = extract_zip_entry(
                    source, row["archive_entry"], destination, expected
                )
            else:
                raise ValueError(f"unsupported source_kind: {row['source_kind']}")
            manifest.append(
                {
                    "asset_id": row["asset_id"],
                    "authority": row["authority"],
                    "source_kind": row["source_kind"],
                    "source_path": row["source_path"],
                    "archive_entry": row["archive_entry"],
                    "destination_path": row["destination_path"],
                    "bytes": byte_count,
                    "sha256": actual,
                    "status": "VERIFIED",
                }
            )
        except Exception as exc:
            errors.append(f"{row['asset_id']}: {type(exc).__name__}: {exc}")
    return manifest, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-parent", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    project_parent = args.project_parent.resolve()
    requirements_path = contained_path(repo_root, str(args.requirements))
    manifest_path = contained_path(repo_root, str(args.manifest))
    report_path = contained_path(repo_root, str(args.report))
    manifest, errors = import_assets(project_parent, repo_root, requirements_path)
    if manifest:
        write_csv_atomic(manifest_path, manifest)
    report = {
        "protocol_id": "EV-FLEX-BIAS-V2.0",
        "gate": "G0_PROVENANCE",
        "gate_status": "PASS" if not errors else "FAIL",
        "required_assets": len(load_requirements(requirements_path)),
        "verified_assets": len(manifest),
        "errors": errors,
    }
    write_json_atomic(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
