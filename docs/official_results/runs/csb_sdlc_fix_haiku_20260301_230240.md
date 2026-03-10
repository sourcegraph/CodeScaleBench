# csb_sdlc_fix_haiku_20260301_230240

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.537`
- Pass rate: `0.667`
- Scorer families: `test_ratio (2), unknown (1)`
- Output contracts: `answer_json_bridge (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [nodebb-plugin-validate-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_230240--baseline-local-direct--nodebb-plugin-validate-fix-001--a857cbb0d3.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.000 | 59 | traj, tx |
| [ansible-abc-imports-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_230240--baseline-local-direct--ansible-abc-imports-fix-001--a535a56eec.html) | `passed` | 0.943 | `True` | `test_ratio` | `answer_json_bridge` | 0.000 | 54 | traj, tx |
| [openlibrary-fntocli-adapter-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_230240--baseline-local-direct--openlibrary-fntocli-adapter-fix-001--1ee28a4158.html) | `passed` | 0.667 | `True` | `-` | `-` | 0.000 | 5 | traj, tx |

## mcp-remote-direct

- Valid tasks: `3`
- Mean reward: `0.667`
- Pass rate: `0.667`
- Scorer families: `test_ratio (2), unknown (1)`
- Output contracts: `answer_json_bridge (2), unknown (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_nodebb-plugin-validate-fix-001_z2fifv](../tasks/csb_sdlc_fix_haiku_20260301_230240--mcp-remote-direct--mcp_nodebb-plugin-validate-fix-001_z2fifv--21d480046e.html) | `failed` | 0.000 | `False` | `test_ratio` | `answer_json_bridge` | 0.230 | 74 | traj, tx |
| [mcp_ansible-abc-imports-fix-001_0wjglk](../tasks/csb_sdlc_fix_haiku_20260301_230240--mcp-remote-direct--mcp_ansible-abc-imports-fix-001_0wjglk--549ef63bd6.html) | `passed` | 1.000 | `True` | `test_ratio` | `answer_json_bridge` | 0.301 | 113 | traj, tx |
| [mcp_openlibrary-fntocli-adapter-fix-001_3bhd9q](../tasks/csb_sdlc_fix_haiku_20260301_230240--mcp-remote-direct--mcp_openlibrary-fntocli-adapter-fix-001_3bhd9q--282c4c958c.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.100 | 50 | traj, tx |
