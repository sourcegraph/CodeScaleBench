# Governance Benchmark — Repository Mirrors

Repos used by `ccb_governance` tasks, with commit SHAs and Sourcegraph indexing status.

## Repos

| Task | Repo | Commit SHA | SG Mirror | Indexed |
|------|------|-----------|-----------|---------|
| repo-scoped-access-001 | django/django | `674eda1c03a3187905f48afee0f15226aa62fdf3` | `sg-benchmarks/django--674eda1c` | Yes (shared with crossrepo) |
| repo-scoped-access-002 | flipt-io/flipt | `3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8` | `sg-benchmarks/flipt--3d5a345f` | Yes (shared with swebenchpro) |
| sensitive-file-exclusion-001 | django/django | `674eda1c03a3187905f48afee0f15226aa62fdf3` | `sg-benchmarks/django--674eda1c` | Yes (shared with crossrepo) |
| cross-team-boundary-001 | django/django | `674eda1c03a3187905f48afee0f15226aa62fdf3` | `sg-benchmarks/django--674eda1c` | Yes (shared with crossrepo) |
| audit-trail-001 | django/django | `674eda1c03a3187905f48afee0f15226aa62fdf3` | `sg-benchmarks/django--674eda1c` | Yes (shared with crossrepo) |
| degraded-context-001 | flipt-io/flipt | `3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8` | `sg-benchmarks/flipt--3d5a345f` | Yes (shared with swebenchpro) |

## Notes

- Both repos are already indexed in Sourcegraph via existing `sg-benchmarks` mirrors — no new mirrors needed.
- Django mirror `sg-benchmarks/django--674eda1c` is shared with CrossRepo benchmark tasks (used by 4 governance tasks).
- Flipt mirror `sg-benchmarks/flipt--3d5a345f` is shared with SWE-bench Pro tasks (used by 2 governance tasks).
- All commits are pinned — Dockerfiles use `git checkout <SHA>`, not HEAD or tags.
- degraded-context-001 deliberately removes `internal/storage/storage.go`, `rpc/flipt/evaluation/evaluation.proto`, and `rpc/flipt/flipt.proto` from the workspace to simulate partial access. These files exist in the SG index for MCP search.
