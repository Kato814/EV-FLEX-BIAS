from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree

from evflex.runner import atomic_write_json


PROTOCOL_ID = "EV-FLEX-BIAS-V2.0"
MARKER_PATTERN = re.compile(r"\[\[V2:(?P<key>v2\.[A-Za-z0-9_.-]+)\]\]")
MARKED_VALUE_PATTERN = re.compile(
    r"(?P<display>[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.\d+)?(?:[eE][-+]?\d+)?%?)"
    r"\s*\[\[V2:(?P<key>v2\.[A-Za-z0-9_.-]+)\]\]"
)


def validate_marked_text(text: str, values: dict[str, dict]) -> dict:
    markers = list(MARKER_PATTERN.finditer(text))
    matches = list(MARKED_VALUE_PATTERN.finditer(text))
    unknown_keys = sorted(
        {match.group("key") for match in markers if match.group("key") not in values}
    )
    mismatches = []
    observed_keys = []
    for match in matches:
        key = match.group("key")
        observed = match.group("display")
        observed_keys.append(key)
        if key not in values:
            continue
        expected = str(values[key]["display"])
        if observed != expected:
            mismatches.append(
                {"key": key, "observed": observed, "expected": expected}
            )
    missing_display_markers = []
    matched_spans = {(match.start("key"), match.end("key")) for match in matches}
    for marker in markers:
        span = (marker.start("key"), marker.end("key"))
        if span not in matched_spans:
            missing_display_markers.append(marker.group("key"))
    return {
        "marker_count": len(markers),
        "matched_value_count": len(matches),
        "unique_value_keys": sorted(set(observed_keys)),
        "unknown_keys": unknown_keys,
        "mismatches": mismatches,
        "markers_without_numeric_display": missing_display_markers,
        "validation_status": (
            "PASS"
            if not unknown_keys and not mismatches and not missing_display_markers
            else "FAIL"
        ),
    }


def extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in root.findall(".//w:p", namespace):
        parts = []
        for node in paragraph.iter():
            if node.tag.endswith("}t") and node.text:
                parts.append(node.text)
            elif node.tag.endswith("}tab"):
                parts.append("\t")
            elif node.tag.endswith("}br"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--docx", type=Path)
    source.add_argument("--text-file", type=Path)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    ledger_path = args.ledger if args.ledger.is_absolute() else repo / args.ledger
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger.get("protocol_id") != PROTOCOL_ID:
        raise SystemExit("ledger protocol mismatch")
    if args.docx is not None:
        input_path = args.docx if args.docx.is_absolute() else repo / args.docx
        text = extract_docx_text(input_path)
    else:
        input_path = (
            args.text_file if args.text_file.is_absolute() else repo / args.text_file
        )
        text = input_path.read_text(encoding="utf-8")
    report = validate_marked_text(text, ledger["values"])
    report.update(
        {
            "protocol_id": PROTOCOL_ID,
            "input_path": str(input_path.relative_to(repo)).replace("\\", "/"),
            "ledger_path": str(ledger_path.relative_to(repo)).replace("\\", "/"),
        }
    )
    if args.report is not None:
        report_path = args.report if args.report.is_absolute() else repo / args.report
        atomic_write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["validation_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
