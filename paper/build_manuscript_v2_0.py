from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Mm, Pt, RGBColor


PROTOCOL_ID = "EV-FLEX-BIAS-V2.0"
VALUE_PATTERN = re.compile(r"\{\{(?P<key>v2\.[A-Za-z0-9_.-]+)\}\}")
FIGURE_PATTERN = re.compile(r"^\[FIGURE:(?P<file>[^|]+)\|(?P<caption>.+)\]$")
TABLE_PATTERN = re.compile(r"^\[TABLE:(?P<name>[^|]+)\|(?P<caption>.+)\]$")
EQUATION_PATTERN = re.compile(r"^\[EQUATION:(?P<text>.+)\]$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("paper/conference/conference-template-transitional.docx"),
    )
    parser.add_argument(
        "--source", type=Path, default=Path("paper/manuscript_v2_0.md")
    )
    parser.add_argument(
        "--ledger", type=Path, default=Path("paper/generated_values_v2_0.json")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("paper/EV_V1G_V2G_ISGT_Asia_2026_v2_0.docx"),
    )
    return parser.parse_args()


def resolve(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def clear_template_body(doc: Document) -> None:
    body = doc._element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def clear_headers_and_footers(doc: Document) -> None:
    for part in doc.part.package.parts:
        part_name = str(part.partname)
        if not (
            part_name.startswith("/word/header")
            or part_name.startswith("/word/footer")
        ):
            continue
        element = getattr(part, "element", None)
        if element is None:
            element = getattr(part, "_element", None)
        if element is None:
            continue
        for child in list(element):
            element.remove(child)
        element.append(OxmlElement("w:p"))


def set_columns(section, count: int, space_twips: int = 360) -> None:
    sect_pr = section._sectPr
    cols = sect_pr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        sect_pr.append(cols)
    cols.set(qn("w:num"), str(count))
    cols.set(qn("w:space"), str(space_twips))
    if count == 1:
        cols.attrib.pop(qn("w:equalWidth"), None)


def set_a4_layout(section) -> None:
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Inches(0.62)
    section.right_margin = Inches(0.62)
    section.top_margin = Inches(0.75)
    section.bottom_margin = Inches(1.0)
    section.header_distance = Inches(0.3)
    section.footer_distance = Inches(0.4)


def ensure_paragraph_controls(paragraph, *, keep_next: bool = False) -> None:
    paragraph.paragraph_format.widow_control = True
    paragraph.paragraph_format.keep_with_next = keep_next


def normalize_inline_text(text: str) -> str:
    text = text.replace(r"\alpha_{\mathrm{map}}", "αₘₐₚ")
    text = re.sub(r"_\{\\mathrm\{([^{}]+)\}\}", r"\1", text)
    text = re.sub(r"_\{([^{}]+)\}", r"\1", text)
    replacements = {
        r"\alpha": "α",
        r"\mathrm{map}": "map",
        r"\mathrm{bal}": "bal",
        r"\mathrm{3ph}": "3ph",
        r"\leq": "≤",
        r"\geq": "≥",
        r"\in": "∈",
        r"\{": "{",
        r"\}": "}",
        r"\,": " ",
    }
    result = text.replace(r"\(", "").replace(r"\)", "")
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def add_text_with_values(
    paragraph,
    text: str,
    values: dict[str, dict],
    *,
    default_bold: bool = False,
) -> None:
    text = normalize_inline_text(text)
    cursor = 0
    bold = default_bold
    token_pattern = re.compile(
        r"(?P<value>\{\{v2\.[A-Za-z0-9_.-]+\}\})|(?P<bold>\*\*)"
    )
    for match in token_pattern.finditer(text):
        if match.start() > cursor:
            run = paragraph.add_run(text[cursor : match.start()])
            run.bold = bold
        token = match.group(0)
        if token == "**":
            bold = not bold
        else:
            key = token[2:-2]
            if key not in values:
                raise KeyError(f"unknown manuscript value: {key}")
            display = str(values[key]["display"])
            run = paragraph.add_run(display)
            run.bold = bold
            marker = paragraph.add_run(f" [[V2:{key}]]")
            marker.font.hidden = True
        cursor = match.end()
    if cursor < len(text):
        run = paragraph.add_run(text[cursor:])
        run.bold = bold


def switch_columns(doc: Document, count: int) -> None:
    section = doc.add_section(WD_SECTION.CONTINUOUS)
    set_columns(section, count)
    set_a4_layout(section)


def add_figure(
    doc: Document,
    figures_dir: Path,
    filename: str,
    caption: str,
    values: dict[str, dict],
) -> None:
    caption = re.sub(r"^Fig\.\s*\d+\.\s*", "", caption, flags=re.IGNORECASE)
    switch_columns(doc, 1)
    picture_paragraph = doc.add_paragraph()
    picture_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    picture_paragraph.paragraph_format.space_before = Pt(3)
    picture_paragraph.paragraph_format.space_after = Pt(1)
    picture = picture_paragraph.add_run().add_picture(
        str(figures_dir / filename), width=Mm(176)
    )
    picture._inline.docPr.set("title", filename)
    picture._inline.docPr.set("descr", normalize_inline_text(caption))
    picture_paragraph.paragraph_format.keep_together = True

    caption_paragraph = doc.add_paragraph(style="figure caption")
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    add_text_with_values(caption_paragraph, caption, values)
    caption_paragraph.paragraph_format.space_after = Pt(3)
    caption_paragraph.paragraph_format.keep_together = True
    switch_columns(doc, 2)


def set_cell_text(
    cell,
    fragments: list[tuple[str, str | None]],
    values: dict[str, dict],
    *,
    bold: bool = False,
) -> None:
    paragraph = cell.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    for literal, key in fragments:
        if key is None:
            run = paragraph.add_run(literal)
            run.bold = bold
        else:
            display = str(values[key]["display"])
            run = paragraph.add_run(display)
            run.bold = bold
            marker = paragraph.add_run(f" [[V2:{key}]]")
            marker.font.hidden = True
    for run in paragraph.runs:
        run.font.size = Pt(7.5)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def set_table_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "bottom"):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "8")
        node.set(qn("w:color"), "000000")
        borders.append(node)
    for edge in ("left", "right", "insideV", "insideH"):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:val"), "nil")
        borders.append(node)

    header = table.rows[0]._tr
    tr_pr = header.get_or_add_trPr()
    bottom = OxmlElement("w:tblBorders")
    edge = OxmlElement("w:bottom")
    edge.set(qn("w:val"), "single")
    edge.set(qn("w:sz"), "6")
    edge.set(qn("w:color"), "000000")
    bottom.append(edge)
    tr_pr.append(bottom)


def prevent_row_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)


def repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)


def add_applicability_table(
    doc: Document,
    source_csv: Path,
    caption: str,
    values: dict[str, dict],
) -> None:
    caption = re.sub(
        r"^TABLE\s+[IVX]+\.\s*", "", caption, flags=re.IGNORECASE
    )
    switch_columns(doc, 1)
    caption_paragraph = doc.add_paragraph(style="table head")
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    add_text_with_values(caption_paragraph, caption, values)
    caption_paragraph.paragraph_format.space_after = Pt(2)
    ensure_paragraph_controls(caption_paragraph, keep_next=True)

    rows = list(csv.DictReader(source_csv.open(encoding="utf-8", newline="")))
    table = doc.add_table(rows=1, cols=7)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    headers = ["Feeder", "Dir.", "min", "Selected", "False-safe", "Coverage", "Outcome"]
    widths = [Mm(24), Mm(14), Mm(14), Mm(21), Mm(33), Mm(24), Mm(46)]
    for idx, (text, width) in enumerate(zip(headers, widths)):
        table.columns[idx].width = width
        set_cell_text(table.rows[0].cells[idx], [(text, None)], values, bold=True)

    status_labels = {
        "VALIDATED": "Validated",
        "NOT_VALIDATED_FALSE_SAFE": "Rate > 5%",
        "INSUFFICIENT_HOLDOUT_N": "n < 20",
        "NO_DEVELOPMENT_RULE": "No rule",
    }
    for record in rows:
        row = table.add_row()
        feeder = "IEEE13" if record["feeder"] == "ieee13" else "LV906"
        direction = "Inc." if record["direction"] == "inc" else "Dec."
        duration = record["duration_min"]
        stem = (
            f"v2.holdout.applicability.{record['feeder']}."
            f"{record['direction']}.{duration}m"
        )
        selected_key = f"{stem}.selected_n"
        coverage_key = f"{stem}.coverage"
        set_cell_text(row.cells[0], [(feeder, None)], values)
        set_cell_text(row.cells[1], [(direction, None)], values)
        set_cell_text(row.cells[2], [(duration, None)], values)
        set_cell_text(row.cells[3], [("", selected_key)], values)
        selected_n = int(record["holdout_selected_n"])
        if selected_n:
            false_n_key = f"{stem}.false_safe_n"
            false_rate_key = f"{stem}.false_safe_rate"
            set_cell_text(
                row.cells[4],
                [("", false_n_key), (" (", None), ("", false_rate_key), (")", None)],
                values,
            )
        else:
            set_cell_text(row.cells[4], [("—", None)], values)
        set_cell_text(row.cells[5], [("", coverage_key)], values)
        set_cell_text(
            row.cells[6],
            [(status_labels[record["claim_status"]], None)],
            values,
            bold=record["claim_status"] == "VALIDATED",
        )
        if record["claim_status"] == "VALIDATED":
            for cell in row.cells:
                tc_pr = cell._tc.get_or_add_tcPr()
                shade = OxmlElement("w:shd")
                shade.set(qn("w:fill"), "EDEDED")
                tc_pr.append(shade)
        prevent_row_split(row)
    set_table_borders(table)
    table.rows[0].height = Mm(5)
    prevent_row_split(table.rows[0])
    repeat_table_header(table.rows[0])
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(0)
    switch_columns(doc, 2)


def tokenize_source(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    paragraph: list[str] = []
    in_comment = False

    def flush() -> None:
        if paragraph:
            tokens.append(("paragraph", " ".join(part.strip() for part in paragraph)))
            paragraph.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.startswith("<!--"):
            flush()
            if "-->" not in line:
                in_comment = True
            continue
        if not line:
            flush()
            continue
        figure = FIGURE_PATTERN.match(line)
        table = TABLE_PATTERN.match(line)
        equation = EQUATION_PATTERN.match(line)
        if line.startswith("#"):
            flush()
            level = len(line) - len(line.lstrip("#"))
            tokens.append((f"heading{level}", line[level:].strip()))
        elif figure:
            flush()
            tokens.append(("figure", f"{figure.group('file')}|{figure.group('caption')}"))
        elif table:
            flush()
            tokens.append(("table", f"{table.group('name')}|{table.group('caption')}"))
        elif equation:
            flush()
            tokens.append(("equation", equation.group("text")))
        else:
            paragraph.append(line)
    flush()
    return tokens


def build_document(
    repo: Path,
    template: Path,
    source: Path,
    ledger_path: Path,
    output: Path,
) -> None:
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger.get("protocol_id") != PROTOCOL_ID:
        raise RuntimeError("manuscript ledger protocol mismatch")
    values = ledger["values"]

    doc = Document(template)
    clear_template_body(doc)
    set_a4_layout(doc.sections[0])
    set_columns(doc.sections[0], 1)
    doc.core_properties.title = (
        "Direction- and Duration-Specific Validity of Balanced-Network "
        "EV Flexibility Estimates"
    )
    doc.core_properties.subject = "EV-FLEX-BIAS-V2.0; IEEE PES ISGT Asia 2026"
    doc.core_properties.keywords = (
        "electric vehicles; flexibility; unbalanced networks; V1G; V2G"
    )

    tokens = tokenize_source(source.read_text(encoding="utf-8"))
    title_seen = False
    author_lines = 0
    body_started = False
    in_references = False
    for kind, content in tokens:
        if kind == "heading1" and not title_seen:
            paragraph = doc.add_paragraph(style="paper title")
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_text_with_values(paragraph, content, values)
            paragraph.paragraph_format.space_after = Pt(6)
            title_seen = True
            continue
        if title_seen and not body_started and kind == "paragraph" and author_lines < 2:
            style = "Author" if author_lines == 0 else "Affiliation"
            paragraph = doc.add_paragraph(style=style)
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_text_with_values(paragraph, content, values)
            for run in paragraph.runs:
                run.font.color.rgb = RGBColor(96, 96, 96)
                if author_lines == 1:
                    run.italic = True
            paragraph.paragraph_format.space_after = Pt(2)
            author_lines += 1
            if author_lines == 2:
                switch_columns(doc, 2)
                body_started = True
            continue
        if kind.startswith("heading"):
            level = int(kind[-1])
            if content == "Abstract":
                continue
            if content == "References":
                in_references = True
                paragraph = doc.add_paragraph(style="Body Text")
                run = paragraph.add_run("REFERENCES")
                run.bold = True
                run.font.small_caps = True
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                ensure_paragraph_controls(paragraph, keep_next=True)
                continue
            style = "Heading 1" if level == 2 else "Heading 2"
            paragraph = doc.add_paragraph(style=style)
            if level == 2:
                content = re.sub(r"^[IVX]+\.\s+", "", content)
            else:
                content = re.sub(r"^[A-Z]\.\s+", "", content)
            add_text_with_values(paragraph, content, values)
            ensure_paragraph_controls(paragraph, keep_next=True)
            if "Applicability Rules Validate" in content:
                paragraph.paragraph_format.page_break_before = True
            continue
        if kind == "figure":
            filename, caption = content.split("|", 1)
            add_figure(doc, repo / "paper" / "figures", filename, caption, values)
            continue
        if kind == "table":
            name, caption = content.split("|", 1)
            if name != "applicability":
                raise RuntimeError(f"unsupported manuscript table: {name}")
            add_applicability_table(
                doc,
                repo / "paper" / "data" / "table2_applicability_v2_0.csv",
                caption,
                values,
            )
            continue
        if kind == "equation":
            paragraph = doc.add_paragraph(style="Body Text")
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_text_with_values(paragraph, content, values)
            for run in paragraph.runs:
                run.font.name = "Times New Roman"
                run.font.size = Pt(9)
                run.italic = True
            paragraph.paragraph_format.keep_together = True
            continue
        if kind != "paragraph":
            raise RuntimeError(f"unsupported token: {kind}")

        if content.startswith("**Index Terms—**"):
            paragraph = doc.add_paragraph(style="Keywords")
        elif in_references:
            paragraph = doc.add_paragraph(style="references")
            content = re.sub(r"^\[\d+\]\s*", "", content)
        elif content.startswith("Balanced-network models enable"):
            paragraph = doc.add_paragraph(style="Abstract")
            lead = paragraph.add_run("Abstract—")
            lead.bold = True
        else:
            paragraph = doc.add_paragraph(style="Body Text")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        add_text_with_values(paragraph, content, values)
        paragraph.paragraph_format.space_after = Pt(1.5 if not in_references else 0)
        paragraph.paragraph_format.keep_together = in_references
        paragraph.paragraph_format.widow_control = True

    for section in doc.sections:
        set_a4_layout(section)
    switch_columns(doc, 1)
    clear_headers_and_footers(doc)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


def main() -> None:
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    template = resolve(repo, args.template)
    source = resolve(repo, args.source)
    ledger = resolve(repo, args.ledger)
    output = resolve(repo, args.output)
    build_document(repo, template, source, ledger, output)
    print(output)


if __name__ == "__main__":
    main()
