# ISGT Asia 2026 manuscript template contract

## Reference

- Authoritative conference page: `https://attend.ieee.org/isgt-asia-2026/submission/`
- Retained conference template: `paper/conference/conference-template-letter.docx`
- Retained template SHA-256: `4589779a1a74782dc5a7a657a9907f243c9dd54510cb6c154acaf24cc9079852`
- Retained template size: 34,065 bytes
- Render evidence: three pages inspected from the official template at 100% zoom.
- Structure evidence: seven sections; template styles, headings, drawing, fields, notes, and controls audited.
- Authoring copy: `paper/conference/conference-template-transitional.docx`
- Authoring-copy SHA-256: `058d47f060d96cba413b83741061801f5fbde4948e1bdaade79045c05f474ac8`
- Normalization: Microsoft Word read-only open followed by Save As DOCX converted Strict OOXML relationship namespaces to Transitional OOXML. The retained conference download was not modified.

## Page system

- The conference page requires a single A4 PDF and a 4-6 page full paper.
- The downloaded Word file is internally US Letter (612 x 792 pt), despite the conference page's A4 requirement and its filename `conference-template-letter.docx`.
- The final manuscript must therefore use A4 portrait (210 x 297 mm) while retaining the downloaded template's type styles, column system, and paragraph rhythm.
- Baseline margins from the downloaded file are 0.62 in left/right, 0.75 in top, and 1.00 in bottom.
- The paper body uses two columns separated by 0.25 in. Continuous one-column sections may be used for the title/author block and publication-width figures or tables.
- No page numbers are inserted.

## Typography and components

- Primary typeface: Times New Roman.
- Paper title: template style `paper title`, 24 pt, centered, 6 pt after.
- Author line: template style `Author`, centered.
- Affiliation line: template style `Affiliation`, centered.
- Abstract: template style `Abstract`, 9 pt, justified, 10 pt after.
- Keywords: template style `Keywords`, derived from `Abstract`, italic label treatment, 6 pt after.
- Main body: template style `Body Text`, justified, approximately 0.95 line spacing.
- Major headings: template style `Heading 1`, centered Roman numeral convention.
- Subheadings: template style `Heading 2`, italic, left aligned.
- Figure captions: template style `figure caption`, 8 pt, below the figure.
- Table titles: template style `table head`, 8 pt, above the table.
- References: template style `references`, 8 pt, justified, 2.5 pt after.
- Figures are inline, not floating, and carry alternative text.
- Tables use explicit widths, cell margins, and repeating header rows; fixed row heights are prohibited.

## Content flow

1. Title, author placeholder, and affiliation placeholder.
2. Abstract and index terms.
3. Introduction and positioning.
4. Same-input multi-period audit method.
5. Frozen protocol and applicability modeling.
6. Development, controlled-ablation, and one-pass holdout results.
7. Limitations, engineering implications, and conclusion.
8. References.

## Slot map

- Title: replace all template guidance with the V2.0 working title.
- Author and affiliation: use explicit placeholders because no verified author identity or affiliation exists in the project files; never invent identifying information.
- Abstract and keywords: replace completely with V2.0 text.
- Body, tables, figures, captions, and references: replace all template guidance completely.
- Footer: remove the sample copyright placeholder and funding text; no conference-specific copyright code has been provided.
- Template warning text, sample equations, sample references, and instructional prose: remove completely.

## Package preservation and intentional deviations

- Preserve the template-derived styles, theme, numbering definitions needed by the manuscript, and footer relationship topology where practical.
- The Strict-to-Transitional normalization necessarily rewrites namespace-bearing XML parts; this is recorded and the retained source remains byte-for-byte unchanged.
- The Letter-to-A4 geometry change is mandatory because the conference page explicitly requires A4.
- The manuscript may remove unused sample relationships and guidance content; no sample guidance may survive into the submission files.

## Fidelity gates

- The retained conference download must still match its recorded SHA-256.
- Every final section must report A4 portrait geometry.
- The final paper must contain 4-6 pages, use two-column IEEE body layout, and have no page numbers.
- Every page of the latest DOCX render and final PDF render must pass visual inspection.
- No template guidance, old 117-scenario statistic, old 15-minute-only claim, manuscript marker, or internal tool token may be visible.
- All experimental numbers must validate against `paper/generated_values_v2_0.json`.
