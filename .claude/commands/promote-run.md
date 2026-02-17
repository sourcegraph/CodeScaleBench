Promote validated benchmark runs from staging to official.

## Workflow

1. List staging runs: `python3 scripts/promote_run.py --list`
2. Review the output — look for READY status (0 criticals, all tasks completed)
3. Dry-run a specific run: `python3 scripts/promote_run.py <run_name>`
4. If gates pass, promote: `python3 scripts/promote_run.py --execute <run_name>`
5. To promote all eligible: `python3 scripts/promote_run.py --execute --all`

## Promotion Gates

- 0 critical validation issues (hard gate)
- All tasks have result.json (no running/missing tasks)
- Warnings <= 10 (configurable with --max-warnings)
- Use --force to bypass gates

## After Promotion

- Run is moved from runs/staging/ to runs/official/
- MANIFEST.json is automatically regenerated
- Run `python3 scripts/aggregate_status.py` to verify the promoted run appears

## Arguments

$ARGUMENTS — optional: run directory name(s) to promote, or --all for all eligible

## Steps

1. Run `python3 scripts/promote_run.py --list` to show current staging runs
2. If the user provided a run name or $ARGUMENTS, dry-run validate it: `python3 scripts/promote_run.py <name>`
3. Show the validation results and ask if the user wants to proceed with `--execute`
4. If confirmed, run `python3 scripts/promote_run.py --execute <name>`
