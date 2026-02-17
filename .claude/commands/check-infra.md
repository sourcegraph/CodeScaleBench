Verify infrastructure readiness before benchmark runs.

Checks: OAuth tokens (all accounts), Docker, disk space, harbor CLI, runs/official/, runs/staging/.

## Steps

1. Run the infrastructure check:
```bash
python3 scripts/check_infra.py
```

2. Review results — FAIL items must be fixed before running benchmarks
3. If staging_dir shows pending promotions, mention that runs are awaiting promotion (use /promote-run)
4. If tokens are expired, suggest running headless login:
```bash
python3 scripts/headless_login.py --all-accounts
```

## Arguments

$ARGUMENTS — none expected
