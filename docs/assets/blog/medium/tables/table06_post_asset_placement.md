# Post Asset Placement Guide

All figures are available as both `.svg` and `.png` under `docs/assets/blog/medium/figures/`. Use SVG for Webflow where possible and PNG as fallback.

| Post Section | Figure | Supporting Table | Placement Note |
|---|---|---|---|
| Intro and scope (`The benchmark design came first`) | `fig01_workstream_timeline.svg` | `table01_milestone_ledger.md` | Place right after the opening section to establish timeline and workload intensity. |
| Curator and verifier architecture (`Curator calibration` + `Deterministic verification`) | `fig02_architecture_evolution.svg` | `table04_architecture_evolution.md` | Place after the curator section, before verifier internals, to show system composition before deep details. |
| Decision layer (`Retrieval, cost, timing, DOE`) | `fig03_decision_theme_mix.svg` | `table02_decisions_tradeoffs.md` | Place immediately before DOE discussion to anchor tradeoffs in concrete decisions. |
| Reliability operations (`Harness and infra work`) | `fig04_issue_resolution_timeline.svg` | `table03_issue_resolution_playbook.md` | Place after the first infra subsection to show issue pressure and closure rate over time. |
| Failure taxonomy (`Harness and infra work`) | `fig05_issue_cluster_heatmap.svg` | `table03_issue_resolution_playbook.md` | Place directly after figure 4 as a paired view of issue volume by cluster. |
| Reusable blueprint (`What was reusable`) | `fig06_reusable_components.svg` | `table05_reusable_components.md` | Place at the start of the reusable section to frame the concrete takeaways by build stage. |
| Closing momentum (`What was reusable` end) | `fig07_commit_signal.svg` | `table05_reusable_components.md` | Place near the end as a final signal of sustained build iteration and maintenance work. |
