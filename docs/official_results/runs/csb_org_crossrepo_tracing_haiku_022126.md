# csb_org_crossrepo_tracing_haiku_022126

## baseline-local-artifact

- Valid tasks: `3`
- Mean reward: `0.941`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (2), unknown (1)`
- Output contracts: `answer_json_native (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-config-trace-010](../tasks/csb_org_crossrepo_tracing_haiku_022126--baseline--ccx-config-trace-010--3753ce0dee.html) | `passed` | 1.000 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 16 | traj, tx |
| [ccx-dep-trace-001](../tasks/csb_org_crossrepo_tracing_haiku_022126--baseline--ccx-dep-trace-001--337559d0e3.html) | `passed` | 0.824 | `True` | `oracle_checks` | `answer_json_native` | 0.000 | 11 | traj, tx |
| [ccx-dep-trace-004](../tasks/csb_org_crossrepo_tracing_haiku_022126--baseline--ccx-dep-trace-004--1e25bc55ee.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 8 | traj, tx |

## mcp-remote-artifact

- Valid tasks: `3`
- Mean reward: `0.899`
- Pass rate: `1.000`
- Scorer families: `oracle_checks (2), unknown (1)`
- Output contracts: `answer_json_native (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ccx-config-trace-010](../tasks/csb_org_crossrepo_tracing_haiku_022126--mcp--ccx-config-trace-010--4f8e6e7dce.html) | `passed` | 1.000 | `True` | `oracle_checks` | `answer_json_native` | 0.750 | 4 | traj, tx |
| [ccx-dep-trace-001](../tasks/csb_org_crossrepo_tracing_haiku_022126--mcp--ccx-dep-trace-001--041a57aa0d.html) | `passed` | 0.824 | `True` | `oracle_checks` | `answer_json_native` | 0.857 | 7 | traj, tx |
| [ccx-dep-trace-004](../tasks/csb_org_crossrepo_tracing_haiku_022126--mcp--ccx-dep-trace-004--bf0414ea2e.html) | `passed` | 0.875 | `True` | `-` | `-` | 0.875 | 16 | traj, tx |
