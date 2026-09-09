# Paper directory status

This directory contains manuscript assets accumulated across several research stages. The repository preserves those historical artifacts for provenance, but they are **not all current**.

## Current accepted-paper track

The accepted IEEE PES ISGT Asia 2026 paper is:

> *Feasibility Assessment of Balanced-Model Electric Vehicle Charging-Flexibility Schedules in Unbalanced Three-Phase Distribution Networks*

- Paper ID: **9499**
- Authors: Junxing Tan, Jun Wu, Shiting Cui, Chaofan Yang, Jiangcheng Wang
- Status: **Accepted; camera-ready revision pending reviewer comments**

Current conference/camera-ready information:

- [`conference/acceptance_status_9499.md`](conference/acceptance_status_9499.md)
- [`conference/artifact.md`](conference/artifact.md)
- [`conference/template_source_manifest.json`](conference/template_source_manifest.json)

Authoritative scientific evidence for the accepted manuscript is outside this directory:

- [`../manuscript_freeze_20260813/manuscript_freeze_20260813/v2_5b_inc_only_manuscript_freeze.md`](../manuscript_freeze_20260813/manuscript_freeze_20260813/v2_5b_inc_only_manuscript_freeze.md)

## Important: historical manuscript artifacts

Files such as:

- `EV_V1G_V2G_ISGT_Asia_2026_v2_0.docx`
- `EV_V1G_V2G_ISGT_Asia_2026_v2_0.pdf`
- `EV_V1G_V2G_ISGT_Asia_2026_v2_0_中文对照版.docx`
- `build_manuscript_v2_0.py`
- `build_manuscript_v2_0_zh.py`
- `build_paper_assets_v2_0.py`

are **historical V2.0 paper-generation artifacts**. They predate the final V2.5B INC/V1G manuscript freeze and must not be mistaken for the accepted submission or the upcoming camera-ready version.

They are retained intentionally because they document the evolution of the study and may remain useful for provenance or later extensions.

## Camera-ready rule

The initial submission used A4 formatting. The acceptance notification for Paper 9499 explicitly requires the **camera-ready paper to use US Letter (21.59 cm × 27.94 cm)**.

Do not regenerate the final paper from the old V2.0 builders without first reconciling them with the accepted manuscript and reviewer comments.

## Next manuscript artifact

The next authoritative manuscript artifact should be created only after reviewer comments are processed. It should:

1. preserve the validated INC/V1G evidence unless a reviewer comment requires additional work;
2. use the official Letter camera-ready template;
3. include the accepted author list and funding acknowledgement;
4. pass final figure, reference, font, page-size, and camera-ready QA;
5. be archived here with an explicit `camera_ready` name and a short provenance/readme note.

For a clean restart of the project, begin with:

[`../docs/project_handoff_2026-09-09.md`](../docs/project_handoff_2026-09-09.md)
