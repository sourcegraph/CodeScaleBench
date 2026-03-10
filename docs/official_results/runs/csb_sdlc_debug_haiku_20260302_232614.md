# csb_sdlc_debug_haiku_20260302_232614

## baseline-local-direct

- Valid tasks: `2`
- Mean reward: `0.250`
- Pass rate: `0.500`
- Scorer families: `find_and_prove (2)`
- Output contracts: `answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [vuls-oval-regression-prove-001](../tasks/csb_sdlc_debug_haiku_20260302_232614--baseline-local-direct--vuls-oval-regression-prove-001--7613b392ab.html) | `failed` | 0.000 | `False` | `find_and_prove` | `answer_json_bridge` | 0.000 | 38 | traj, tx |
| [qutebrowser-url-regression-prove-001](../tasks/csb_sdlc_debug_haiku_20260302_232614--baseline-local-direct--qutebrowser-url-regression-prove-001--ecf9286f7c.html) | `passed` | 0.500 | `True` | `find_and_prove` | `answer_json_bridge` | 0.000 | 34 | traj, tx |

## mcp-remote-direct

- Valid tasks: `2`
- Mean reward: `0.500`
- Pass rate: `1.000`
- Scorer families: `find_and_prove (2)`
- Output contracts: `answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_qutebrowser-url-regression-prove-001_hofr2x](../tasks/csb_sdlc_debug_haiku_20260302_232614--mcp-remote-direct--mcp_qutebrowser-url-regression-prove-001_hofr2x--3c7949472e.html) | `passed` | 0.500 | `True` | `find_and_prove` | `answer_json_bridge` | 0.130 | 54 | traj, tx |
| [mcp_vuls-oval-regression-prove-001_ucs7gr](../tasks/csb_sdlc_debug_haiku_20260302_232614--mcp-remote-direct--mcp_vuls-oval-regression-prove-001_ucs7gr--c9d1928c63.html) | `passed` | 0.500 | `True` | `find_and_prove` | `answer_json_bridge` | 0.515 | 33 | traj, tx |
