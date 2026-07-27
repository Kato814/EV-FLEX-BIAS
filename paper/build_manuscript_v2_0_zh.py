from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from paper.build_manuscript_v2_0 import (
    PROTOCOL_ID,
    add_text_with_values,
    clear_headers_and_footers,
    clear_template_body,
    ensure_paragraph_controls,
    normalize_inline_text,
    prevent_row_split,
    repeat_table_header,
    resolve,
    set_a4_layout,
    set_cell_text,
    set_columns,
    set_table_borders,
    switch_columns,
    tokenize_source,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("paper/conference/conference-template-transitional.docx"),
    )
    parser.add_argument(
        "--source", type=Path, default=Path("paper/manuscript_v2_0_zh.md")
    )
    parser.add_argument(
        "--ledger", type=Path, default=Path("paper/generated_values_v2_0.json")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "paper/EV_V1G_V2G_ISGT_Asia_2026_v2_0_中文对照版.docx"
        ),
    )
    return parser.parse_args()


def set_chinese_run_font(run) -> None:
    run.font.name = "Times New Roman"
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.rFonts
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.insert(0, r_fonts)
    r_fonts.set(qn("w:ascii"), "Times New Roman")
    r_fonts.set(qn("w:hAnsi"), "Times New Roman")
    r_fonts.set(qn("w:eastAsia"), "SimSun")
    r_fonts.set(qn("w:cs"), "SimSun")


def apply_chinese_fonts(doc: Document) -> None:
    for paragraph in doc.paragraphs:
        for run in paragraph.runs:
            set_chinese_run_font(run)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        set_chinese_run_font(run)
    for section in doc.sections:
        for story in (section.header, section.footer):
            for paragraph in story.paragraphs:
                for run in paragraph.runs:
                    set_chinese_run_font(run)


def add_figure_zh(
    doc: Document,
    figures_dir: Path,
    filename: str,
    caption: str,
    values: dict[str, dict],
) -> None:
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

    caption_paragraph = doc.add_paragraph(style="Body Text")
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    caption_match = re.match(r"^(图\s*\d+\.)\s*(.*)$", caption)
    if caption_match:
        label = caption_paragraph.add_run(caption_match.group(1) + " ")
        label.bold = True
        add_text_with_values(caption_paragraph, caption_match.group(2), values)
    else:
        add_text_with_values(caption_paragraph, caption, values)
    for run in caption_paragraph.runs:
        run.font.size = Pt(8)
    caption_paragraph.paragraph_format.space_after = Pt(3)
    caption_paragraph.paragraph_format.keep_together = True
    switch_columns(doc, 2)


def set_cell_text_zh(
    cell,
    fragments: list[tuple[str, str | None]],
    values: dict[str, dict],
    *,
    bold: bool = False,
) -> None:
    set_cell_text(cell, fragments, values, bold=bold)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for run in cell.paragraphs[0].runs:
        set_chinese_run_font(run)


def add_applicability_table_zh(
    doc: Document,
    source_csv: Path,
    caption: str,
    values: dict[str, dict],
) -> None:
    switch_columns(doc, 1)
    caption_paragraph = doc.add_paragraph(style="Body Text")
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    caption_match = re.match(r"^(表\s*[IVX]+\.)\s*(.*)$", caption)
    if caption_match:
        label = caption_paragraph.add_run(caption_match.group(1) + " ")
        label.bold = True
        add_text_with_values(caption_paragraph, caption_match.group(2), values)
    else:
        add_text_with_values(caption_paragraph, caption, values)
    for run in caption_paragraph.runs:
        run.font.size = Pt(8)
    caption_paragraph.paragraph_format.space_after = Pt(2)
    ensure_paragraph_controls(caption_paragraph, keep_next=True)

    records = list(csv.DictReader(source_csv.open(encoding="utf-8", newline="")))
    table = doc.add_table(rows=1, cols=7)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    headers = ["馈线", "方向", "时长/min", "选中数", "假安全", "覆盖率", "结论"]
    widths = [Mm(24), Mm(14), Mm(18), Mm(21), Mm(33), Mm(24), Mm(42)]
    for index, (text, width) in enumerate(zip(headers, widths)):
        table.columns[index].width = width
        set_cell_text_zh(
            table.rows[0].cells[index], [(text, None)], values, bold=True
        )

    status_labels = {
        "VALIDATED": "通过验证",
        "NOT_VALIDATED_FALSE_SAFE": "假安全率>5%",
        "INSUFFICIENT_HOLDOUT_N": "样本量<20",
        "NO_DEVELOPMENT_RULE": "无开发集规则",
    }
    for record in records:
        row = table.add_row()
        feeder = "IEEE13" if record["feeder"] == "ieee13" else "LV906"
        direction = "增" if record["direction"] == "inc" else "减"
        duration = record["duration_min"]
        stem = (
            f"v2.holdout.applicability.{record['feeder']}."
            f"{record['direction']}.{duration}m"
        )
        set_cell_text_zh(row.cells[0], [(feeder, None)], values)
        set_cell_text_zh(row.cells[1], [(direction, None)], values)
        set_cell_text_zh(row.cells[2], [(duration, None)], values)
        set_cell_text_zh(row.cells[3], [("", f"{stem}.selected_n")], values)
        selected_n = int(record["holdout_selected_n"])
        if selected_n:
            set_cell_text_zh(
                row.cells[4],
                [
                    ("", f"{stem}.false_safe_n"),
                    ("（", None),
                    ("", f"{stem}.false_safe_rate"),
                    ("）", None),
                ],
                values,
            )
        else:
            set_cell_text_zh(row.cells[4], [("—", None)], values)
        set_cell_text_zh(row.cells[5], [("", f"{stem}.coverage")], values)
        set_cell_text_zh(
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
    prevent_row_split(table.rows[0])
    repeat_table_header(table.rows[0])
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    switch_columns(doc, 2)


def build_document(
    repo: Path,
    template: Path,
    source: Path,
    ledger_path: Path,
    output: Path,
) -> None:
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger.get("protocol_id") != PROTOCOL_ID:
        raise RuntimeError("中文对照稿数值账本协议不匹配")
    values = ledger["values"]

    doc = Document(template)
    clear_template_body(doc)
    set_a4_layout(doc.sections[0])
    set_columns(doc.sections[0], 1)
    doc.core_properties.title = "平衡网络电动汽车灵活性估计的方向与时长依赖有效性"
    doc.core_properties.subject = "EV-FLEX-BIAS-V2.0 中文对照阅读版"
    doc.core_properties.keywords = "电动汽车；灵活性；不平衡网络；V1G；V2G"

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
                run.font.color.rgb = RGBColor(80, 80, 80)
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
            if content == "摘要":
                continue
            if content == "参考文献":
                in_references = True
                paragraph = doc.add_paragraph(style="Body Text")
                run = paragraph.add_run("参考文献")
                run.bold = True
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
            if "仅两个组合单元" in content:
                paragraph.paragraph_format.page_break_before = True
            continue

        if kind == "figure":
            filename, caption = content.split("|", 1)
            add_figure_zh(
                doc, repo / "paper" / "figures", filename, caption, values
            )
            continue

        if kind == "table":
            name, caption = content.split("|", 1)
            if name != "applicability":
                raise RuntimeError(f"不支持的中文稿表格：{name}")
            add_applicability_table_zh(
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
                run.font.size = Pt(9)
                run.italic = True
            paragraph.paragraph_format.keep_together = True
            continue

        if kind != "paragraph":
            raise RuntimeError(f"不支持的稿源标记：{kind}")

        if content.startswith("**关键词—**"):
            paragraph = doc.add_paragraph(style="Keywords")
        elif in_references:
            paragraph = doc.add_paragraph(style="references")
            content = re.sub(r"^\[\d+\]\s*", "", content)
        elif content.startswith("平衡网络模型能够"):
            paragraph = doc.add_paragraph(style="Abstract")
            lead = paragraph.add_run("摘要—")
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
    apply_chinese_fonts(doc)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


def main() -> None:
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = resolve(repo, args.output)
    build_document(
        repo,
        resolve(repo, args.template),
        resolve(repo, args.source),
        resolve(repo, args.ledger),
        output,
    )
    print(output)


if __name__ == "__main__":
    main()
