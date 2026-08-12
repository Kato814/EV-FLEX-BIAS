# Literature Management

This directory is the project-level evidence base for literature review, method selection, and novelty checking.

## Scope

Priority search window: **2023–2026**. Older papers are retained only when they are foundational or necessary to trace a method lineage.

Primary themes:

1. EV aggregator deliverable flexibility and V1G/V2G scheduling
2. Aggregate flexibility in unbalanced three-phase distribution networks
3. Dynamic/robust operating envelopes and fast approximations
4. Phase unbalance, phase allocation, coordination, redispatch, and schedule repair
5. Fast screening/surrogate methods for distribution-network feasibility
6. Statistical calibration and uncertainty quantification when directly relevant
7. Near-duplicate work relative to EV-FLEX-BIAS: balanced schedule -> fixed three-phase replay -> transferable fraction / derating

## Evidence policy

- Prefer peer-reviewed IEEE/IET/Elsevier/Springer papers and primary preprints when a peer-reviewed version is unavailable.
- For state-of-the-art claims, prioritize 2024–2026 papers.
- Older work is tagged `FOUNDATIONAL`; it is not evidence of current novelty by itself.
- Record DOI or a stable primary URL whenever available.
- Do not store copyrighted PDFs in the repository by default. Store bibliographic metadata, stable links, structured notes, and claim-level evidence instead.
- Separate what a paper explicitly demonstrates from our inference about how it relates to EV-FLEX-BIAS.
- A paper enters `CORE` only after title, authors, year, source/venue, and technical relevance are checked against a primary source.

## Canonical files

- `sota_matrix.csv`: one row per reviewed paper; canonical comparison matrix.
- `search_log.md`: dated searches, databases/sources, inclusion/exclusion decisions, and unresolved gaps.
- `references.bib`: verified BibTeX entries used or likely to be used by the manuscript.
- `notes/`: detailed notes for papers that materially affect research design or novelty.

## Status vocabulary

- `CORE`: directly affects the problem formulation, method choice, experiment design, or novelty claim.
- `SUPPORTING`: useful context or secondary methodological support.
- `FOUNDATIONAL`: older work needed to establish lineage or definitions.
- `WATCH`: recent/emerging work to revisit before submission.
- `EXCLUDED`: screened but not suitable as evidence for the intended claim; the reason must be recorded.

## Review dimensions

Each paper should be assessed, where applicable, on:

- feeder/network model
- balanced vs. unbalanced three-phase representation
- EV-specific vs. generic DER
- V1G / V2G
- single-period vs. multi-period
- fixed precomputed schedule vs. redispatch/reoptimization allowed
- flexibility region / operating envelope / schedule feasibility / screening target
- voltage limits, VUF, transformer loading, feeder loading, line thermal constraints
- coordination/phase-allocation capability
- uncertainty treatment
- method class (AC-OPF, linearized OPF, sensitivity, robust optimization, surrogate/ML, conformal/statistical calibration, etc.)
- feeders/datasets and validation scale
- runtime/computational evidence
- main contribution
- overlap with EV-FLEX-BIAS
- gap left open for this project

## Manuscript rule

No strong novelty statement should be written from memory alone. Novelty claims must be traceable to `sota_matrix.csv` and, for the most important claims, to a dedicated note in `notes/`.
