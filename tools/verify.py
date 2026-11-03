#!/usr/bin/env python3
"""Verify final deliverables and recompute summaries without running power flow.

Only the Python standard library is required. The repository is read-only;
regenerated summaries are created in, and removed with, a system temp directory.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import tempfile
import zipfile


FINAL_HASHES = {
    "paper/final.pdf": "3de6ef3433057d2407b8be3158029d7d9631aa2647ec82807238c96e9521afdc",
    "paper/chinese/reading.pdf": "195b5bf103d64f7f88e5c1a578ceb2502cbf649f3c7d3ecac6be7e9f0be0eee6",
    "paper/chinese/reading.docx": "05f53777d6caa2e069e30ffd17f6e04b0c431c2aead5ea1e974f3889e28008ad",
    "poster/final.pdf": "b2f8a26736efde64fe93963ce0ed7452d297285982f44c9405603e8e7b17b556",
}
REQUIRED_INPUTS = (
    "config/experiment.json", "config/cases.csv", "data/scenarios.csv",
    "data/vehicles.csv", "data/load_profile.csv", "src/evflex/runtime.py",
    "src/evflex/design.py", "src/evflex/fleet.py", "src/evflex/network.py",
    "src/evflex/engine.py", "src/evflex/solver/duration_engine.py",
    "src/evflex/solver/network_core.py", "tools/evaluate.py", "tools/summarize.py",
)
MASTERS = (
    "data/feeders/ieee13/IEEE13Nodeckt.dss",
    "data/feeders/lv906_core/MasterStaticAudit.dss",
)


class VerificationError(Exception):
    pass


def require(condition, message):
    # Explicit checks also work when Python is invoked with -O.
    if not condition:
        raise VerificationError(message)


def sha256(path):
    require(path.is_file(), "missing file: " + str(path))
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inside(root, path):
    path = path.resolve()
    require(path.is_relative_to(root), "file reference escapes repository: " + str(path))
    return path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def check_checksums(root):
    path = root / "SHA256SUMS.txt"
    require(path.is_file(), "missing SHA256SUMS.txt")
    entries = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", raw.strip())
        require(match is not None, "invalid SHA256SUMS.txt line " + str(line_number))
        digest, name = match.groups()
        name = name.replace("\\", "/")
        require(not PurePosixPath(name).is_absolute() and ":" not in name,
                "checksum path must be relative: " + name)
        target = inside(root, root / name)
        require(target not in entries, "duplicate checksum entry: " + name)
        require(sha256(target) == digest.lower(), "SHA-256 mismatch: " + name)
        entries[target] = digest.lower()
    require(bool(entries), "empty SHA256SUMS.txt")
    for name, expected in FINAL_HASHES.items():
        require(entries.get(root / name) == expected,
                "final artifact is missing or changed in checksum list: " + name)
        require(sha256(root / name) == expected, "final artifact differs: " + name)
    return len(entries)


def csv_records(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames
        require(columns is not None and len(columns) == len(set(columns)),
                "missing/duplicate CSV columns: " + str(path))
        rows = list(reader)
    require(all(None not in row and all(value is not None for value in row.values()) for row in rows),
            "malformed CSV row: " + str(path))
    return columns, rows


def keyed_rows(rows, key, label):
    require(all(key in row and row[key] for row in rows), "missing CSV key: " + label)
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), "duplicate CSV key: " + label)
    return result


def check_cases(root):
    _, rows = csv_records(root / "results/cases.csv")
    require(len(rows) == 46, "results/cases.csv must contain 46 cases")
    require(Counter(row["feeder"] for row in rows) == {"ieee13": 22, "lv906": 24},
            "case feeder counts must be IEEE13=22 and LV906=24")
    by_id = keyed_rows(rows, "scenario_id", "results/cases.csv")
    keyed_rows(rows, "evaluation_id", "results/cases.csv")
    alphas = [Decimal(row["alpha_transfer"]) for row in rows]
    require(all(a.is_finite() and 0 <= a <= 1 for a in alphas), "invalid alpha_transfer")
    require(sum(a < 1 for a in alphas) == 32, "expected 32 cases with alpha < 1")
    for name in ("config/cases.csv", "data/scenarios.csv"):
        _, other = csv_records(root / name)
        require(set(keyed_rows(other, "scenario_id", name)) == set(by_id),
                "scenario scope differs: " + name)
    _, vehicles = csv_records(root / "data/vehicles.csv")
    require({row["scenario_id"] for row in vehicles} == set(by_id),
            "vehicle input scope differs from final 46 cases")
    return by_id


def no_provenance(value):
    if isinstance(value, dict):
        return "provenance" not in value and all(no_provenance(v) for v in value.values())
    if isinstance(value, list):
        return all(no_provenance(v) for v in value)
    return True


def check_grid_zip(root, cases):
    expected = {case + suffix for case in cases for suffix in (".csv", ".json")}
    with zipfile.ZipFile(root / "results/alpha_grid.zip") as archive:
        names = archive.namelist()
        require(len(names) == 92 and set(names) == expected,
                "alpha_grid.zip must contain exactly 46 CSV/JSON pairs")
        require(archive.testzip() is None, "alpha_grid.zip CRC failure")
        for case in cases:
            metadata = json.loads(archive.read(case + ".json"))
            require(isinstance(metadata, dict) and no_provenance(metadata),
                    "unexpected provenance in grid JSON: " + case)
            require(metadata.get("scenario_id") == case, "grid JSON identity mismatch: " + case)
            require(metadata.get("evaluation_id") == cases[case]["evaluation_id"],
                    "grid evaluation ID mismatch: " + case)
            require(hashlib.sha256(archive.read(case + ".csv")).hexdigest()
                    == metadata.get("grid_csv_sha256"), "grid CSV hash mismatch: " + case)
    return len(expected)


def path_expression(node, names, root):
    """Resolve literal Path/join expressions; never execute numerical modules."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        value = path_expression(node.value, names, root)
        return value.parent if isinstance(value, Path) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = path_expression(node.left, names, root)
        right = path_expression(node.right, names, root)
        return left / right if isinstance(left, Path) and isinstance(right, str) else None
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "Path" and len(node.args) == 1:
            value = path_expression(node.args[0], names, root)
            return root / value if isinstance(value, (str, Path)) else None
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"resolve", "absolute"}:
            return path_expression(node.func.value, names, root)
    return None


def check_python_references(root):
    checked = set()
    external = {"numpy", "pandas", "scipy", "opendssdirect", "dss"}
    for source in sorted((root / "src").rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        names = {"__file__": source, "repo_root": root}
        nodes = sorted(ast.walk(tree), key=lambda node: getattr(node, "lineno", 0))
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = path_expression(node.value, names, root)
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if value is not None:
                    for target in targets:
                        if isinstance(target, ast.Name):
                            names[target.id] = value
            if isinstance(node, (ast.Call, ast.BinOp)):
                value = path_expression(node, names, root)
                if isinstance(value, Path) and value.suffix.lower() in {".py", ".csv", ".json", ".dss", ".txt"}:
                    value = inside(root, value)
                    require(value.relative_to(root).parts[0] in {"src", "data", "config"},
                            "runtime input is outside final src/data/config: " + str(value))
                    require(value.is_file(), "missing runtime input: " + str(value))
                    checked.add(value)
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                modules = [node.module]
            for module in modules:
                top = module.split(".")[0]
                if top == "evflex":
                    location = root / "src" / Path(*module.split("."))
                    require(location.with_suffix(".py").is_file() or (location / "__init__.py").is_file(),
                            "missing local Python module: " + module)
                else:
                    require(top in sys.stdlib_module_names or top in external,
                            "unresolved runtime import: " + module)
    require(bool(checked), "no final runtime input references found")
    return len(checked)


def check_dss_references(root):
    pending = [root / name for name in MASTERS]
    visited = set()
    inputs = set()
    while pending:
        source = inside(root, pending.pop())
        if source in visited:
            continue
        visited.add(source)
        require(source.is_file(), "missing DSS input: " + str(source))
        inputs.add(source)
        # Parse active DSS commands only, excluding line and block comments.
        text = re.sub(r"/\*.*?\*/", "", source.read_text(encoding="utf-8-sig"), flags=re.S)
        for line in text.splitlines():
            line = line.split("!", 1)[0].split("//", 1)[0].strip()
            if not line:
                continue
            lexer = shlex.shlex(line, posix=True)
            lexer.whitespace_split = True
            lexer.commenters = ""
            lexer.escape = ""
            tokens = list(lexer)
            if tokens and tokens[0].lower() in {"redirect", "compile", "buscoords"}:
                require(len(tokens) == 2, "unsupported DSS file command: " + line)
                name = tokens[1].strip("[]()").replace("\\", "/")
                require(not PurePosixPath(name).is_absolute() and ":" not in name,
                        "DSS input is not repository-relative: " + name)
                path = inside(root, source.parent / name)
                require(path.is_relative_to(root / "data") and path.is_file(),
                        "missing/out-of-scope DSS reference: " + str(path))
                inputs.add(path)
                if tokens[0].lower() in {"redirect", "compile"}:
                    pending.append(path)
    return len(inputs)


def semantic_cell(value):
    try:
        number = Decimal(value)
    except InvalidOperation:
        return ("text", value)
    require(number.is_finite(), "non-finite number in result CSV")
    return ("number", number)


def compare_csv(saved, generated, key):
    left_columns, left_rows = csv_records(saved)
    right_columns, right_rows = csv_records(generated)
    require(set(left_columns) == set(right_columns), "CSV columns differ: " + saved.name)
    left = keyed_rows(left_rows, key, saved.name)
    right = keyed_rows(right_rows, key, generated.name)
    require(left.keys() == right.keys(), "CSV row identities differ: " + saved.name)
    for identity in left:
        for column in left_columns:
            require(semantic_cell(left[identity][column]) == semantic_cell(right[identity][column]),
                    "recomputed CSV differs: {} / {} / {}".format(saved.name, identity, column))


def json_semantics(value):
    if isinstance(value, dict):
        return {key: json_semantics(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_semantics(item) for item in value]
    if type(value) in (int, float):
        number = Decimal(str(value))
        require(number.is_finite(), "non-finite JSON number")
        return ("number", number)
    return (type(value).__name__, value)


def check_recomputed_summaries(root):
    # The subprocess imports only standard-library code for saved-grid analysis.
    # -B prevents evaluate.py imports from writing __pycache__ in the repository.
    with tempfile.TemporaryDirectory(prefix="evflex-final-verify-") as temporary:
        output = Path(temporary).resolve()
        require(not output.is_relative_to(root), "system temp directory must be outside repository")
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process = subprocess.run(
            [sys.executable, "-B", str(root / "tools/summarize.py"), "--repo", str(root),
             "--input", str(root / "results/alpha_grid.zip"), "--output", str(output)],
            cwd=output, env=environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        require(process.returncode == 0,
                "summary recomputation failed: " + (process.stderr or process.stdout).strip()[-3000:])
        for name, key in (("case_table.csv", "scenario_id"),
                          ("boundary_comparison.csv", "scenario_id"),
                          ("feeder_runtime_summary.csv", "feeder")):
            compare_csv(root / "results" / name, output / name, key)
        saved = read_json(root / "results/summary.json")
        regenerated = read_json(output / "analysis_summary.json")
        require(isinstance(saved, dict) and "protocol" not in saved and no_provenance(saved),
                "unexpected protocol/provenance in final summary")
        require(json_semantics(saved) == json_semantics(regenerated),
                "results/summary.json differs from recomputed analysis_summary.json")
        require(saved.get("complete_46_case_evidence") is True and saved.get("covered_cases") == 46
                and saved.get("grid_points_checked") == 23046,
                "recomputed summary must cover 46 cases / 23,046 grid points")


def verify(root):
    root = Path(root).resolve()
    checksums = check_checksums(root)
    for name in REQUIRED_INPUTS:
        require((root / name).is_file(), "missing required final input: " + name)
    references = check_python_references(root)
    dss_inputs = check_dss_references(root)
    cases = check_cases(root)
    grid_files = check_grid_zip(root, cases)
    check_recomputed_summaries(root)
    return {"status": "PASS", "sha256_files": checksums, "cases": len(cases),
            "derated_cases": 32, "alpha_grid_files": grid_files, "grid_points": 23046,
            "python_input_references": references, "dss_inputs": dss_inputs,
            "recomputed_csv_files": 3, "recomputed_json_files": 1}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify(args.root)
    except (VerificationError, OSError, ValueError, KeyError, InvalidOperation,
            zipfile.BadZipFile, subprocess.TimeoutExpired) as error:
        print("FAIL: " + str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("PASS: {sha256_files} SHA-256 files; 46 cases (22 IEEE13 / 24 LV906), "
              "32 derated; 92 grid files / 23,046 points; summaries match; "
              "final artifacts and local inputs verified.".format(**result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
