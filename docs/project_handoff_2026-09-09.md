# Project handoff — 2026-09-09

This file is the recommended starting point for a new chat/work session.

## 1. Current project state

The paper has been **accepted** by IEEE PES ISGT Asia 2026.

- Paper ID: **9499**
- Title: *Feasibility Assessment of Balanced-Model Electric Vehicle Charging-Flexibility Schedules in Unbalanced Three-Phase Distribution Networks*
- Authors: Junxing Tan, Jun Wu, Shiting Cui, Chaofan Yang, Jiangcheng Wang
- Conference: Oct. 30-Nov. 1, 2026, Wuhan, China
- Camera-ready deadline: **2026-10-20, Beijing Time**
- Registration deadline: **2026-10-10, Beijing Time**
- Camera-ready page size: **US Letter (21.59 cm × 27.94 cm)**

Official acceptance/camera-ready details are summarized in:

`paper/conference/acceptance_status_9499.md`

## 2. Next immediate task

**Do not reopen the scientific experiment by default.**

The next conversation should begin by receiving the reviewer comments and processing them one by one:

1. classify each comment as wording / methodology clarification / figure-table / reference / additional analysis / additional experiment;
2. decide whether the frozen evidence already answers it;
3. revise the manuscript using the smallest scientifically justified change;
4. only reopen experiments if a reviewer comment truly cannot be answered from the frozen evidence and the user explicitly agrees;
5. after content revision, rebuild the paper with the official **Letter** camera-ready template;
6. run a final camera-ready QA pass.

## 3. Authoritative scientific freeze

Use this directory as the primary manuscript evidence source:

`manuscript_freeze_20260813/manuscript_freeze_20260813/`

The key evidence summary is:

`v2_5b_inc_only_manuscript_freeze.md`

### Primary scope

- V1G / INC increasing-direction charging flexibility only.
- 46 validated cases total.
- IEEE13: 22 cases.
- LV906: 24 cases.
- The original DEC/V2G continuous net-power interpolation is not used as primary transferability evidence because the fixed-ray vehicle-feasibility verification found many invalid partial-interpolation states.

### Frozen headline results

| Scope | n | mean alpha | median alpha | alpha < 0.95 | alpha < 0.5 | alpha < 1 |
|---|---:|---:|---:|---:|---:|---:|
| Overall | 46 | 0.681 | 0.719 | 30 (65.2%) | 16 | 32 |
| IEEE13 | 22 | 0.834 | 0.999 | 9 | 2 | 11 |
| LV906 | 24 | 0.540 | 0.446 | 21 | 14 | 21 |

- IEEE13 minus LV906 mean-alpha difference: **0.294**.
- Case-level bootstrap 95% interval: **[0.144, 0.436]**.
- 32/32 limited V1G cases reproduce their feasibility boundary.
- First failure occurs in the flexibility call slot for 32/32 limited cases.

### Limiting-constraint counts

- Low voltage: 20/32
- High voltage: 2/32
- VUF: 5/32
- Transformer loading: 5/32
- Voltage magnitude or VUF: **27/32 = 84.4%**

Feeder split:

- IEEE13: 11 limited = 5 transformer + 5 VUF + 1 low voltage.
- LV906: 21 limited = 19 low voltage + 2 high voltage; 21/21 are voltage-limited.

## 4. Manuscript narrative that has already been agreed

The paper is **not** framed as a new optimization algorithm. Its central question is:

> Given a precomputed vehicle-level EV charging-flexibility schedule generated with a balanced model, how much of the scheduled adjustment remains feasible in the detailed unbalanced three-phase feeder when the original vehicle-time allocation is retained?

The method is described with standard field terminology, without inventing a special method name:

1. vehicle-feasible baseline schedule;
2. balanced-model target schedule;
3. proportional schedule scaling with a scalar `alpha`;
4. nonlinear unbalanced three-phase power flow in OpenDSS;
5. network-feasibility check;
6. largest verified feasible scaling level and first limiting constraint.

Avoid reviving terms such as:

- `trajectory-preserving` as a branded method name;
- `fixed ray` in the manuscript narrative;
- `frozen audit` / `boundary witness` / `retrospective replication` as publication prose;
- defensive sentences of the form “not X but Y” merely to protect claim boundaries.

Research boundaries should be reflected by the actual design and a compact limitations statement rather than repeated defensive language.

## 5. Current paper structure

The agreed structure is:

1. **Introduction**
2. **Network Feasibility Assessment**
   - Proportional Schedule Scaling
   - Network Feasibility Evaluation
3. **Test Systems and Study Cases**
4. **Results and Discussion**
   - Schedule Feasibility
   - Limiting Network Constraints
5. **Conclusion**

The title is fixed unless reviewer feedback requires a change:

*Feasibility Assessment of Balanced-Model Electric Vehicle Charging-Flexibility Schedules in Unbalanced Three-Phase Distribution Networks*

## 6. Figure and formatting decisions already agreed

- Body text remains two-column IEEE conference layout; only title/author area is full width.
- Fig. 2 and Fig. 3 are one-column figures placed in either the left or right text column; each contains stacked `(a)` and `(b)` panels.
- Figure width must not exceed the assigned column width.
- Captions should be short and describe what the figure shows; analysis belongs in the main text.
- Fig. 1 is the user-supplied vector workflow figure and should remain vector in LaTeX/PDF.
- Plot labels use the conference-template typography requirements; mathematical symbols should match the manuscript math style.
- Funding acknowledgement:
  `Project Supported By Smart Grid-National Science and Technology Major Project. (2025ZD0806600)`
- Authors and emails are already fixed in the accepted-submission manuscript.

## 7. Important conference-format change

Initial submission used A4 because the CFP/initial-submission guidance required A4.

The **acceptance notification explicitly requires Camera-ready in US Letter (21.59 cm × 27.94 cm)**. For the final paper, the Letter camera-ready requirement takes precedence. Do not continue using A4 for the final submission.

The conference-template tracking files under `paper/conference/` should be read before final formatting.

## 8. Historical work that should not dominate the next conversation

The repository preserves V2.0-V2.4 work, including PHiCTE and historical V1G/V2G experiments. These are useful for provenance and secondary discussion but are not the accepted paper's main scientific contribution.

PHiCTE was removed from the main-paper narrative because the validated INC-only scope does not support a universal <=5% risk guarantee; it remains a historical/exploratory artifact.

The restricted phase-repair diagnostic was also not promoted to a main contribution because its recovery was small.

## 9. Recommended opening message for the next chat

A concise start is:

> “继续 EV-FLEX-BIAS / ISGT Asia 2026 Paper ID 9499 的 camera-ready 工作。请先读取仓库中的 `docs/project_handoff_2026-09-09.md`、`paper/conference/acceptance_status_9499.md` 和 `manuscript_freeze_20260813/manuscript_freeze_20260813/v2_5b_inc_only_manuscript_freeze.md`。下面是审稿意见：……”

This should be sufficient to resume the project without reconstructing the long prior conversation.
