# Reproducible Execution Checklist (Engineering Diary Assets)

| Step | Command | Expected Output |
|---|---|---|
| 1. Build or refresh unified DB | `python3 scripts/build_conversation_db.py --project-root /home/stephanie_jarmak/CodeScaleBench --full-rebuild` | Updated `data/conversations/codescalebench_conversations.db` and ingest stats |
| 2. Generate diary assets | `python3 scripts/export_engineering_diary_assets.py --db-path data/conversations/codescalebench_conversations.db --out-root docs/assets/blog/medium --start-date 2026-02-01 --end-date 2026-03-06` | New `csv/`, `figures/*.svg`, `tables/`, `quotes/`, `sql/` |
| 3. Verify key CSV counts | `wc -l docs/assets/blog/medium/csv/fig01_workstream_timeline.csv docs/assets/blog/medium/csv/fig03_decision_points.csv docs/assets/blog/medium/csv/fig05_issue_cluster_heatmap.csv` | Non-trivial row counts, no empty files |
| 4. Verify figure set | `ls docs/assets/blog/medium/figures/fig0*_*.svg` | 7 engineering-diary SVG assets |
| 5. Verify placement map | `sed -n '1,200p' docs/assets/blog/medium/tables/table06_post_asset_placement.md` | Section-to-asset mapping exists |
| 6. Verify narrative draft | `sed -n '1,260p' docs/assets/blog/medium/post_codescalebench_engineering_diary.md` | Complete technical narrative with figure/table insertion points |
| 7. Optional repo gate | `python3 scripts/repo_health.py --quick` | Green checks for docs/config-only updates |

## Required Inputs

- `data/conversations/codescalebench_conversations.db`
- `scripts/export_engineering_diary_assets.py`
- `matplotlib` available in Python environment for SVG rendering

## Notes

- Extraction intentionally excludes `external_%` agents for the engineering diary pass.
- Taxonomy and SQL seed query are in `docs/assets/blog/medium/sql/` for review and edits.
