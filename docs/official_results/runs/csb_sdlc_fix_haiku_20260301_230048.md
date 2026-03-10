# csb_sdlc_fix_haiku_20260301_230048

## baseline-local-direct

- Valid tasks: `3`
- Mean reward: `0.413`
- Pass rate: `0.667`
- Scorer families: `diff_similarity (2), repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [pytorch-release-210-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_230048--baseline-local-direct--pytorch-release-210-fix-001--270516ee75.html) | `failed` | 0.000 | `False` | `diff_similarity` | `answer_json_bridge` | 0.000 | 111 | traj, tx |
| [flink-window-late-data-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_230048--baseline-local-direct--flink-window-late-data-fix-001--596b059830.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 82 | traj, tx |
| [pytorch-relu-gelu-fusion-fix-001](../tasks/csb_sdlc_fix_haiku_20260301_230048--baseline-local-direct--pytorch-relu-gelu-fusion-fix-001--3b9ca65190.html) | `passed` | 0.740 | `True` | `diff_similarity` | `answer_json_bridge` | 0.000 | 48 | traj, tx |

## mcp-remote-direct

- Valid tasks: `1`
- Mean reward: `0.500`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (1)`
- Output contracts: `answer_json_bridge (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_flink-window-late-data-fix-001_4rhqc0](../tasks/csb_sdlc_fix_haiku_20260301_230048--mcp-remote-direct--mcp_flink-window-late-data-fix-001_4rhqc0--6034fbd62b.html) | `passed` | 0.500 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.519 | 54 | traj, tx |
