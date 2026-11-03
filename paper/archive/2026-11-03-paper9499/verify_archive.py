#!/usr/bin/env python3
"""Read-only, standard-library verification of the Paper 9499 archive.

Run ``python verify_archive.py`` from any working directory.  An alternate
archive location may be supplied with ``--root PATH``.  No extraction, build,
simulation, network access, or file writes are performed.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile


HEX256 = re.compile(r"[0-9a-fA-F]{64}\Z")
CHUNK = 1024 * 1024
ENGLISH = "output/camera_ready_v1_22"


class VerificationError(Exception):
    """An archive invariant failed."""


def require(condition, message):
    # Do not use assert: checks must also run under python -O.
    if not condition:
        raise VerificationError(message)


class Verifier:
    def __init__(self, root):
        self.root = Path(root).resolve()
        require(self.root.is_dir(), "archive directory does not exist: " + str(root))
        self.hashes = {}

    def path(self, base, name):
        require(isinstance(name, str) and bool(name.strip()), "empty file path")
        require(not any(c in name for c in "\r\n\x00"), "invalid file path")
        normalized = name.replace("\\", "/")
        require(not PurePosixPath(normalized).is_absolute() and ":" not in normalized,
                "expected a relative file path: " + name)
        target = (base / normalized).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            raise VerificationError("path escapes archive: " + name) from None
        return target

    def label(self, path):
        return path.relative_to(self.root).as_posix()

    def digest(self, path):
        require(path.is_file(), "missing file: " + self.label(path))
        if path not in self.hashes:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(CHUNK), b""):
                    digest.update(block)
            self.hashes[path] = digest.hexdigest()
        return self.hashes[path]

    def sha_list(self, relative_name, required=()):
        listing = self.path(self.root, relative_name)
        require(listing.is_file(), "missing checksum list: " + relative_name)
        entries = {}
        for number, raw in enumerate(listing.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            first = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", line)
            last = re.fullmatch(r"(.+?)\s+([0-9a-fA-F]{64})", line)
            require(first is not None or last is not None,
                    "malformed checksum at {}:{}".format(relative_name, number))
            if first:
                digest, name = first.groups()
            else:
                name, digest = last.groups()
            path = self.path(listing.parent, name)
            require(path not in entries, "duplicate checksum entry: " + self.label(path))
            entries[path] = digest.lower()
            require(self.digest(path) == digest.lower(),
                    "SHA-256 mismatch: " + self.label(path))
        require(bool(entries), "empty checksum list: " + relative_name)
        for name in required:
            path = self.path(listing.parent, name)
            require(path in entries, "checksum list omits required file: " + self.label(path))
        return entries

    def manifest(self, root_hashes):
        path = self.root / "MANIFEST.json"
        require(path.is_file(), "missing MANIFEST.json")
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
        require(isinstance(manifest, dict), "MANIFEST.json must be an object")
        files = manifest.get("files")
        require(isinstance(files, list) and bool(files), "MANIFEST.json has no files")
        seen = set()
        for index, entry in enumerate(files):
            require(isinstance(entry, dict), "invalid manifest entry: " + str(index))
            path = self.path(self.root, entry.get("path"))
            name = self.label(path)
            require(path not in seen, "duplicate manifest entry: " + name)
            seen.add(path)
            require(type(entry.get("bytes")) is int and entry["bytes"] >= 0,
                    "invalid manifest size: " + name)
            digest = entry.get("sha256")
            require(isinstance(digest, str) and HEX256.fullmatch(digest) is not None,
                    "invalid manifest SHA-256: " + name)
            require(path.is_file(), "missing manifest file: " + name)
            require(path.stat().st_size == entry["bytes"], "manifest size mismatch: " + name)
            require(self.digest(path) == digest.lower(), "manifest SHA-256 mismatch: " + name)
            require(root_hashes.get(path) == digest.lower(),
                    "manifest/root checksum disagreement: " + name)
        return len(files)

    def zip_integrity(self):
        archives = sorted(p for p in self.root.rglob("*")
                          if p.is_file() and p.suffix.lower() == ".zip")
        require(bool(archives), "archive contains no ZIP files")
        for path in archives:
            with zipfile.ZipFile(path) as archive:
                bad = archive.testzip()
                require(bad is None, "ZIP CRC failure: {} / {}".format(self.label(path), bad))
                names = [info.filename for info in archive.infolist()]
                require(len(names) == len(set(names)), "duplicate ZIP member: " + self.label(path))
        return len(archives)

    def source_zip_matches(self):
        source = self.root / ENGLISH / "source_package"
        require(source.is_dir(), "missing English source_package")
        disk = {p.relative_to(source).as_posix(): p for p in source.rglob("*") if p.is_file()}
        path = self.root / ENGLISH / "paper9499_v1_22_LaTeX.zip"
        with zipfile.ZipFile(path) as archive:
            members = {}
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                require(name not in members, "duplicate normalized source ZIP path: " + name)
                members[name] = info
            missing = sorted(set(disk) - set(members))
            extra = sorted(set(members) - set(disk))
            require(not missing and not extra,
                    "source ZIP file-set mismatch (missing={}, extra={})".format(missing, extra))
            for name, info in members.items():
                require(info.file_size == disk[name].stat().st_size,
                        "source ZIP size mismatch: " + name)
                with archive.open(info) as packed, disk[name].open("rb") as unpacked:
                    while True:
                        left, right = packed.read(CHUNK), unpacked.read(CHUNK)
                        require(left == right, "source ZIP byte mismatch: " + name)
                        if not left:
                            break
        return len(members)

    def supplementary_summary(self):
        directory = self.root / "experiments/reviewer_alpha_v3/summary"
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8-sig"))
        analysis = json.loads((directory / "analysis_summary.json").read_text(encoding="utf-8-sig"))
        require(isinstance(summary, dict) and isinstance(analysis, dict), "invalid experiment summary")
        required = [
            (summary, "complete_46_case_result", True),
            (summary, "completed_case_count", 46),
            (summary, "expected_frozen_cases", 46),
            (summary, "completed_ieee13", 22),
            (summary, "completed_lv906", 24),
            (summary, "missing_case_count", 0),
            (analysis, "complete_46_case_evidence", True),
            (analysis, "covered_cases", 46),
            (analysis, "expected_cases", 46),
            (analysis, "grid_points_checked", 23046),
            (analysis, "grid_audits_all_full_96_slots", True),
        ]
        for document, key, expected in required:
            actual = document.get(key)
            require(type(actual) is type(expected) and actual == expected,
                    "experiment summary {}: expected {!r}, got {!r}".format(key, expected, actual))
        cases = summary.get("cases")
        require(isinstance(cases, list) and len(cases) == 46
                and all(isinstance(case, str) for case in cases) and len(set(cases)) == 46,
                "experiment summary must list 46 distinct cases")
        for document in (summary, analysis):
            provenance = document.get("provenance", {})
            require(isinstance(provenance, dict) and provenance.get("n_grid") == 501
                    and provenance.get("grid_step") == 0.002, "experiment grid definition mismatch")
        require(46 * 501 == analysis["grid_points_checked"], "experiment grid total mismatch")


def verify(root):
    check = Verifier(root)
    root_hashes = check.sha_list("SHA256SUMS.txt")
    manifest_files = check.manifest(root_hashes)
    english = check.sha_list(ENGLISH + "/SHA256SUMS.txt", required=(
        "paper9499_camera_ready_v1_22.pdf", "paper9499_v1_22_LaTeX.zip",
        "README.txt", "qa/final_verification.json"))
    source = check.sha_list(ENGLISH + "/source_package/SHA256SUMS.txt")
    chinese = check.sha_list("output/chinese_v1_21/SHA256SUMS.txt", required=(
        "paper9499_v1_21_中文阅读稿.docx", "paper9499_v1_21_中文阅读稿.pdf"))
    poster = check.sha_list("output/poster_latex_v5/SHA256SUMS.txt", required=(
        "paper9499_A0_poster_v5.tex", "../pdf/paper9499_A0_poster_v5.pdf"))
    zip_count = check.zip_integrity()
    source_files = check.source_zip_matches()
    check.supplementary_summary()
    return {"status": "PASS", "manifest_files": manifest_files,
            "root_checksum_entries": len(root_hashes), "zip_files": zip_count,
            "source_zip_matching_files": source_files,
            "historical_checksum_entries": len(english) + len(source) + len(chinese) + len(poster),
            "completed_cases": 46, "grid_points_checked": 23046}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent,
                        help="archive root (default: directory containing this script)")
    parser.add_argument("--json", action="store_true", help="print result as JSON to stdout")
    args = parser.parse_args(argv)
    try:
        result = verify(args.root)
    except (VerificationError, OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        print("FAIL: " + str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    else:
        print("PASS: {manifest_files} manifest files; {root_checksum_entries} root SHA-256 entries; "
              "{zip_files} ZIPs; {source_zip_matching_files} identical source files; "
              "46 complete cases / 23,046 grid points.".format(**result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
