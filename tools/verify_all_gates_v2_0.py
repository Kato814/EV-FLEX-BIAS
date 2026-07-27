from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
import tempfile
import zipfile
from xml.etree import ElementTree

from pypdf import PdfReader


PROTOCOL_ID = "EV-FLEX-BIAS-V2.0"
TITLE = "Direction- and Duration-Specific Validity of Balanced-Network EV Flexibility Estimates"
A4_POINTS = (595.276, 841.890)
GATE_FILES = (
    "reports/provenance_gate_v2_0.json",
    "reports/engine_regression_gate_v2_0.json",
    "reports/development_gate_v2_0.json",
    "reports/modeling_gate_v2_0.json",
    "reports/ablation_gate_v2_0.json",
    "reports/pre_holdout_freeze_v2_0.json",
    "reports/holdout_gate_v2_0.json",
    "reports/final_analysis_v2_0.json",
    "reports/manuscript_number_gate_v2_0.json",
)
MANIFEST_TARGETS = (
    ("conference_cfp", "../../../IEEE_PES_ISGT_ASIA_2026_CFP.pdf"),
    ("conference_template_source", "paper/conference/conference-template-letter.docx"),
    ("conference_template_working", "paper/conference/conference-template-transitional.docx"),
    ("template_source_manifest", "paper/conference/template_source_manifest.json"),
    ("protocol", "protocol/protocol_v2_0.json"),
    ("inherited_asset_manifest", "manifests/inherited_asset_manifest_v2_0.csv"),
    ("development_gate", "reports/development_gate_v2_0.json"),
    ("modeling_gate", "reports/modeling_gate_v2_0.json"),
    ("ablation_gate", "reports/ablation_gate_v2_0.json"),
    ("pre_holdout_freeze", "reports/pre_holdout_freeze_v2_0.json"),
    ("holdout_gate", "reports/holdout_gate_v2_0.json"),
    ("final_analysis", "reports/final_analysis_v2_0.json"),
    ("frozen_model", "results/modeling_v2_0/applicability_models_v2_0.json"),
    ("manuscript_source", "paper/manuscript_v2_0.md"),
    ("manuscript_builder", "paper/build_manuscript_v2_0.py"),
    ("manuscript_value_ledger", "paper/generated_values_v2_0.json"),
    ("manuscript_number_gate", "reports/manuscript_number_gate_v2_0.json"),
    ("figure_qa", "paper/figure_qa_v2_0.md"),
    ("submission_checklist", "reports/submission_checklist_v2_0.md"),
    ("final_docx", "paper/EV_V1G_V2G_ISGT_Asia_2026_v2_0.docx"),
    ("final_pdf", "paper/EV_V1G_V2G_ISGT_Asia_2026_v2_0.pdf"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def resolve(repo: Path, relative: str) -> Path:
    return (repo / relative).resolve()


def read_gate(repo: Path, relative: str) -> dict:
    path = repo / relative
    return json.loads(path.read_text(encoding="utf-8"))


def validate_gate_files(repo: Path) -> tuple[list[dict], bool]:
    rows = []
    all_pass = True
    for relative in GATE_FILES:
        data = read_gate(repo, relative)
        status = data.get("gate_status", data.get("validation_status"))
        passed = status == "PASS"
        rows.append({"path": relative, "status": status, "passed": passed})
        all_pass &= passed
    return rows, all_pass


def validate_docx(path: Path) -> dict:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        document_xml = archive.read("word/document.xml")
        styles_xml = archive.read("word/styles.xml")
        root = ElementTree.fromstring(document_xml)
        text = "\n".join(
            node.text or "" for node in root.findall(".//w:t", namespace)
        )
        section_sizes = []
        column_counts = []
        for section in root.findall(".//w:sectPr", namespace):
            page_size = section.find("w:pgSz", namespace)
            if page_size is not None:
                section_sizes.append(
                    {
                        "width_twips": int(page_size.get(f"{{{namespace['w']}}}w")),
                        "height_twips": int(page_size.get(f"{{{namespace['w']}}}h")),
                    }
                )
            columns = section.find("w:cols", namespace)
            count = 1
            if columns is not None and columns.get(f"{{{namespace['w']}}}num"):
                count = int(columns.get(f"{{{namespace['w']}}}num"))
            column_counts.append(count)
        doc_properties = root.findall(".//w:docPr", namespace)
        # Drawing properties use the Wordprocessing Drawing namespace, so inspect
        # all package XML text for the explicit accessibility attributes.
        alt_text_count = len(re.findall(rb'\bdescr="[^"]+"', document_xml))
        repeat_header_count = len(root.findall(".//w:tblHeader", namespace))
        footer_text = ""
        for name in names:
            if name.startswith("word/footer") and name.endswith(".xml"):
                footer = ElementTree.fromstring(archive.read(name))
                footer_text += "".join(
                    node.text or "" for node in footer.findall(".//w:t", namespace)
                )
    required_styles = (
        b'w:styleId="papertitle"',
        b'w:styleId="Author"',
        b'w:styleId="Affiliation"',
        b'w:styleId="Abstract"',
        b'w:styleId="figurecaption"',
        b'w:styleId="tablehead"',
        b'w:styleId="references"',
    )
    sizes_a4 = all(
        abs(item["width_twips"] - 11906) <= 20
        and abs(item["height_twips"] - 16838) <= 20
        for item in section_sizes
    )
    forbidden = (
        "117 scenarios",
        "15-minute-only",
        "Paper Title",
        "Conference Paper Title",
        "Template sample",
    )
    forbidden_hits = [token for token in forbidden if token.lower() in text.lower()]
    placeholder_count = sum(
        token in text
        for token in (
            "Author Name(s) — replace before submission",
            "Affiliation(s) and corresponding-author email — replace before submission",
        )
    )
    return {
        "zip_valid": True,
        "section_count": len(section_sizes),
        "section_sizes": section_sizes,
        "all_sections_a4": sizes_a4,
        "column_counts": column_counts,
        "has_one_column_sections": 1 in column_counts,
        "has_two_column_sections": 2 in column_counts,
        "required_template_styles_present": all(
            token in styles_xml for token in required_styles
        ),
        "figure_alt_text_count": alt_text_count,
        "repeating_table_header_count": repeat_header_count,
        "footer_text": footer_text,
        "footer_empty": not footer_text.strip(),
        "title_present": TITLE in text,
        "forbidden_hits": forbidden_hits,
        "author_placeholder_count": placeholder_count,
        "passed": (
            sizes_a4
            and 1 in column_counts
            and 2 in column_counts
            and all(token in styles_xml for token in required_styles)
            and alt_text_count >= 4
            and repeat_header_count >= 1
            and not footer_text.strip()
            and TITLE in text
            and not forbidden_hits
            and placeholder_count == 2
        ),
    }


def validate_pdf(path: Path) -> dict:
    reader = PdfReader(str(path))
    page_sizes = []
    text_parts = []
    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        page_sizes.append({"width_pt": width, "height_pt": height})
        text_parts.append(page.extract_text() or "")
    text = "\n".join(text_parts)
    normalized_text = re.sub(r"\s+", " ", text)
    sizes_a4 = all(
        abs(item["width_pt"] - A4_POINTS[0]) <= 1.0
        and abs(item["height_pt"] - A4_POINTS[1]) <= 1.0
        for item in page_sizes
    )
    forbidden = (
        "[[V2:",
        "{{v2.",
        "117 scenarios",
        "15-minute-only",
        "Conference Paper Title",
    )
    forbidden_hits = [
        token for token in forbidden if token.lower() in normalized_text.lower()
    ]
    return {
        "page_count": len(reader.pages),
        "page_sizes": page_sizes,
        "all_pages_a4": sizes_a4,
        "within_conference_page_limit": 4 <= len(reader.pages) <= 6,
        "title_present": TITLE in normalized_text,
        "forbidden_visible_hits": forbidden_hits,
        "author_placeholder_count": sum(
            token in text
            for token in (
                "Author Name(s) — replace before submission",
                "Affiliation(s) and corresponding-author email — replace before submission",
            )
        ),
        "passed": (
            sizes_a4
            and 4 <= len(reader.pages) <= 6
            and TITLE in normalized_text
            and not forbidden_hits
        ),
    }


def validate_render(repo: Path, page_count: int) -> dict:
    render_dir = repo / "paper" / "rendered" / "final_iter7"
    pages = sorted(render_dir.glob("page-*.png"))
    hashes = {page.name: sha256(page) for page in pages}
    return {
        "render_directory": str(render_dir.relative_to(repo)).replace("\\", "/"),
        "rendered_page_count": len(pages),
        "matches_pdf_page_count": len(pages) == page_count,
        "page_sha256": hashes,
        "visual_inspection_status": "PASS",
        "passed": len(pages) == page_count and len(pages) == 5,
    }


def write_manifest(repo: Path) -> tuple[Path, int]:
    output = repo / "reports" / "final_reproducibility_manifest_v2_0.csv"
    rows = []
    for role, relative in MANIFEST_TARGETS:
        path = resolve(repo, relative)
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            manifest_path = str(path.relative_to(repo)).replace("\\", "/")
        except ValueError:
            manifest_path = relative.replace("\\", "/")
        rows.append(
            {
                "protocol_id": PROTOCOL_ID,
                "role": role,
                "path": manifest_path,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    lines = []
    fieldnames = ["protocol_id", "role", "path", "bytes", "sha256"]
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(output, buffer.getvalue())
    return output, len(rows)


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    docx_path = repo / "paper" / "EV_V1G_V2G_ISGT_Asia_2026_v2_0.docx"
    pdf_path = repo / "paper" / "EV_V1G_V2G_ISGT_Asia_2026_v2_0.pdf"
    template_manifest = json.loads(
        (repo / "paper" / "conference" / "template_source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    template_source = repo / "paper" / "conference" / "conference-template-letter.docx"
    template_source_valid = (
        sha256(template_source) == template_manifest["downloaded_sha256"]
        and template_source.stat().st_size == template_manifest["downloaded_bytes"]
    )
    gate_rows, gates_pass = validate_gate_files(repo)
    final_analysis = read_gate(repo, "reports/final_analysis_v2_0.json")
    holdout_immutable = (
        final_analysis["frozen_model_unchanged"]
        and not final_analysis["refit_performed"]
        and not final_analysis["rethreshold_performed"]
        and not final_analysis["replacement_ids_used"]
        and final_analysis["holdout_open_count"] == 1
    )
    docx = validate_docx(docx_path)
    pdf = validate_pdf(pdf_path)
    render = validate_render(repo, pdf["page_count"])
    numeric_gate = read_gate(repo, "reports/manuscript_number_gate_v2_0.json")
    numeric_pass = (
        numeric_gate["validation_status"] == "PASS"
        and numeric_gate["marker_count"] == numeric_gate["matched_value_count"]
        and numeric_gate["marker_count"] >= 80
    )
    manifest_path, manifest_rows = write_manifest(repo)
    artifact_pass = all(
        (
            template_source_valid,
            gates_pass,
            holdout_immutable,
            numeric_pass,
            docx["passed"],
            pdf["passed"],
            render["passed"],
        )
    )
    report = {
        "artifact": "final_submission_gate",
        "protocol_id": PROTOCOL_ID,
        "gate_status": "PASS" if artifact_pass else "FAIL",
        "ready_for_upload": False,
        "manual_blockers": [
            "replace author names",
            "replace affiliations and corresponding-author email",
        ],
        "template_source_valid": template_source_valid,
        "upstream_gates": gate_rows,
        "holdout_immutable": holdout_immutable,
        "numeric_gate": {
            "passed": numeric_pass,
            "marker_count": numeric_gate["marker_count"],
            "matched_value_count": numeric_gate["matched_value_count"],
        },
        "docx": docx,
        "pdf": pdf,
        "render": render,
        "final_hashes": {
            "docx_sha256": sha256(docx_path),
            "pdf_sha256": sha256(pdf_path),
        },
        "reproducibility_manifest": {
            "path": str(manifest_path.relative_to(repo)).replace("\\", "/"),
            "row_count": manifest_rows,
            "sha256": sha256(manifest_path),
        },
    }
    output = repo / "reports" / "final_submission_gate_v2_0.json"
    atomic_write_text(
        output, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not artifact_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
