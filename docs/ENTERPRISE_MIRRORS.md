# Enterprise Benchmark — Repository Mirrors

Repos used by `ccb_enterprise` tasks, with commit SHAs and Sourcegraph indexing status.

## Repos

| Task | Repo | Commit SHA | SG Mirror | Indexed |
|------|------|-----------|-----------|---------|
| multi-team-ownership-001 | django/django | `674eda1c03a3187905f48afee0f15226aa62fdf3` | `sg-benchmarks/django--674eda1c` | Yes (shared with crossrepo, governance) |
| conflicting-docs-001 | django/django | `674eda1c03a3187905f48afee0f15226aa62fdf3` | `sg-benchmarks/django--674eda1c` | Yes (shared with crossrepo, governance) |
| multi-team-ownership-002 | flipt-io/flipt | `3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8` | `sg-benchmarks/flipt--3d5a345f` | Yes (shared with swebenchpro, governance) |

## Notes

- Both repos are already indexed in Sourcegraph via existing `sg-benchmarks` mirrors — no new mirrors needed.
- Django mirror `sg-benchmarks/django--674eda1c` is shared with CrossRepo and Governance benchmark tasks.
- Flipt mirror `sg-benchmarks/flipt--3d5a345f` is shared with SWE-bench Pro and Governance benchmark tasks.
- All commits are pinned — Dockerfiles use `git checkout <SHA>`, not HEAD or tags.
- conflicting-docs-001 injects a stale `docs/architecture.md` via Dockerfile that describes a non-existent middleware registry pattern. The actual code uses `__init__(get_response)` / `__call__(request)`.
