# Repo-Set Fixtures

Repo-set fixtures define which repositories are available in each MCP-unique
benchmark task. Each fixture specifies:

- **Repos**: The full set of repositories relevant to the task
- **Access modes**: Which repos are available locally (baseline) vs MCP-only
- **Cross-org flag**: Whether repos span multiple GitHub organizations
- **Sourcegraph indexing**: Whether repos are natively indexed or need mirrors

## Schema

All fixtures validate against `schemas/repo_set_fixture.schema.json`.

## Directory Structure

```
fixtures/repo_sets/
  kubernetes-ecosystem.json    # k8s core + client-go + api + etcd
  nodejs-web-stack.json        # node + express + lodash + prisma
  python-ml-stack.json         # scikit-learn + numpy + pandas + scipy
  grafana-observability.json   # grafana + loki + mimir
  multi-org-go.json            # k8s + etcd + grafana (cross-org Go)
```

## Access Mode Semantics

| Mode | Baseline Config | MCP-Full Config |
|------|----------------|-----------------|
| `local_checkout` | Full repo in `/workspace` | Truncated; agent uses MCP |
| `mcp_only` | Not available | Agent discovers via MCP |
| `both` | Full repo in `/workspace` | Also available via MCP |

## Adding a New Fixture

1. Create `fixtures/repo_sets/<name>.json` following the schema
2. Verify all repos are Sourcegraph-indexed (use `mcp__sourcegraph__keyword_search`)
3. For unindexed repos, create an `sg-benchmarks` mirror and set `sourcegraph_mirror`
4. Pin every repo to a specific `revision` (SHA or tag) for reproducibility
5. Run: `python3 -c "import json; json.load(open('fixtures/repo_sets/<name>.json'))"`
6. Validate: ensure `local_checkout_repos` and `mcp_only_repos` are consistent with repo `access_mode`

## Mirror Conventions

Repos not natively indexed in Sourcegraph use `sg-benchmarks` mirrors:
- Mirror naming: `sg-benchmarks/<org>-<repo>` (e.g. `sg-benchmarks/kubernetes-client-go`)
- Mirror revisions tracked in `configs/sg_mirror_revisions.json`
- Use orphan-commit approach for large repos (>2GB)
