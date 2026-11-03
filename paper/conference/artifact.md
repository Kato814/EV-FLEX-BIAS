# ISGT Asia 2026 manuscript template contract

## Status

This file tracks two different formatting stages and must not conflate them:

1. **Initial submission** — the CFP/initial-submission guidance used A4.
2. **Camera-ready after acceptance** — the acceptance notification for Paper 9499 explicitly requires **US Letter (21.59 cm × 27.94 cm)**.

The camera-ready requirement is now authoritative for the final paper.

## Reference files

- Conference site: `https://attend.ieee.org/isgt-asia-2026/`
- Retained Word template: `paper/conference/conference-template-letter.docx`
- Retained Word-template SHA-256: `4589779a1a74782dc5a7a657a9907f243c9dd54510cb6c154acaf24cc9079852`
- Retained Word-template size: 34,065 bytes
- Authoring copy: `paper/conference/conference-template-transitional.docx`
- Authoring-copy SHA-256: `058d47f060d96cba413b83741061801f5fbde4948e1bdaade79045c05f474ac8`
- Acceptance/camera-ready status: `paper/conference/acceptance_status_9499.md`

## Initial-submission page system

For the initial manuscript, the conference CFP/submission guidance required a single A4 PDF and a 4-6 page full paper. The downloaded Word template itself was internally US Letter (612 × 792 pt), so the initial-submission artifact used A4 geometry while retaining the IEEE conference typography and two-column system.

This A4 geometry was appropriate for the initial submission only.

## Camera-ready page system

The acceptance notification for Paper 9499 explicitly instructs authors to format the **Camera-ready** according to the official template and states:

- page size: **Letter**;
- physical size: **21.59 cm × 27.94 cm**;
- final upload deadline: **2026-10-20, Beijing Time**.

Therefore the final camera-ready manuscript must use US Letter geometry. The old A4 correction is no longer applicable to the final paper.

The camera-ready body should remain the standard IEEE conference **two-column** layout. Only the standard IEEE title/author region is full-width; ordinary body text should not be converted into a one-column layout. Figures should normally occupy a single text column unless a truly publication-width figure is scientifically necessary and explicitly justified.

## Typography and components

The retained IEEE conference template establishes the following practical style contract:

- primary text typeface: Times New Roman / IEEE template equivalent;
- paper title and author block: IEEE conference template styles;
- abstract and keywords: template styles, no unnecessary mathematical display content;
- main body: justified two-column IEEE conference text;
- major headings: IEEE Roman-numeral convention;
- subheadings: IEEE conference subsection style;
- figure captions: below the figure, short and descriptive;
- table titles: above the table;
- references: IEEE numbered style;
- figure labels: 8 pt Times New Roman or the template-compatible equivalent;
- mathematical symbols inside figures should visually match the manuscript's mathematical typography rather than being forced into the figure-label font.

## Accepted-paper metadata

- Paper ID: **9499**
- Title: *Feasibility Assessment of Balanced-Model Electric Vehicle Charging-Flexibility Schedules in Unbalanced Three-Phase Distribution Networks*
- Authors: Junxing Tan, Jun Wu, Shiting Cui, Chaofan Yang, Jiangcheng Wang
- Funding acknowledgement: `Project Supported By Smart Grid-National Science and Technology Major Project. (2025ZD0806600)`

The funding acknowledgement is placed in the IEEE first-page footnote area with the normal horizontal footnote rule.

## Figure/table layout contract

Current manuscript decisions to preserve unless reviewer comments require changes:

- Fig. 1: vector workflow figure, single-column width.
- Fig. 2: one-column figure; panels `(a)` and `(b)` stacked vertically.
- Fig. 3: one-column figure; panels `(a)` and `(b)` stacked vertically.
- Fig. 4: one-column result figure.
- Fig. 5: one-column result figure.
- No figure should exceed the width of the column in which it is placed.
- Captions should identify the displayed content; result interpretation belongs in the main text.
- Figures and tables must be cited before their final rendered appearance.

## Content-flow contract

The accepted-paper narrative is:

1. Introduction.
2. Network Feasibility Assessment.
   - Proportional Scaling and Vehicle Feasibility.
   - Three-Phase Network Checks.
   - Scaling-Factor Determination.
3. Test Systems and Study Cases.
4. Results and Discussion.
   - Schedule Feasibility.
   - Limiting Network Constraints.
   - Computational Time.
   - Operational Use and Extensions.
5. Conclusion.
6. References.

Scientific evidence is frozen to the validated INC/V1G scope under:

`manuscript_freeze_20260813/manuscript_freeze_20260813/`

Historical V2.0/V2.4 paper-generation assets are retained for provenance but are not authoritative for the camera-ready manuscript.

## Fidelity gates for camera-ready builds

The final camera-ready artifact must pass all of the following:

- reviewer comments addressed and response decisions documented;
- US Letter portrait geometry (21.59 cm × 27.94 cm);
- standard IEEE conference two-column body;
- no page numbers;
- title, author order, affiliations, emails, and funding text verified;
- figure and table numbering sequential and cited in text;
- figure captions below figures; table titles above tables;
- all vector figures remain vector where possible;
- raster topology figures retain effective resolution above 300 ppi;
- no clipped or overlapping figure/table text;
- no Type 3 fonts; fonts embedded;
- no undefined references or citations;
- references checked against authoritative sources;
- no old template guidance or obsolete V2.0/V2.4 manuscript prose;
- all reported experimental numbers validated against the V2.5B INC/V1G manuscript freeze.

## Acceptance-letter provenance

See `acceptance_status_9499.md` for the acceptance-letter hash, deadlines, registration requirements, copyright instructions, and official links.

## Completed delivery

Camera-ready v1.22 and its retained verification report are in the [2026-11-03 archive](../archive/2026-11-03-paper9499/README.md). The archive also includes the local LaTeX template ZIP used for the final Letter build.
