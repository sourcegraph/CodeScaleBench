# csb_sdlc_test_haiku_20260301_230048

## baseline-local-direct

- Valid tasks: `13`
- Mean reward: `0.644`
- Pass rate: `0.923`
- Scorer families: `f1_hybrid (7), repo_state_heuristic (3), unknown (3)`
- Output contracts: `answer_json_bridge (10), unknown (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [openhands-search-file-test-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--openhands-search-file-test-001--c4ec10396a.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 37 | traj, tx |
| [aspnetcore-code-review-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--aspnetcore-code-review-001--727ba77920.html) | `passed` | 0.550 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 5 | traj, tx |
| [calcom-code-review-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--calcom-code-review-001--599d031041.html) | `passed` | 0.680 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 5 | traj, tx |
| [curl-security-review-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--curl-security-review-001--02862a388a.html) | `passed` | 0.510 | `True` | `-` | `-` | 0.000 | 37 | traj, tx |
| [envoy-code-review-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--envoy-code-review-001--71b9cf5628.html) | `passed` | 0.750 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 21 | traj, tx |
| [ghost-code-review-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--ghost-code-review-001--50fa4fa30f.html) | `passed` | 0.800 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 5 | traj, tx |
| [kafka-security-review-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--kafka-security-review-001--a9632689b9.html) | `passed` | 0.500 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 9 | traj, tx |
| [terraform-code-review-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--terraform-code-review-001--90533ef5c8.html) | `passed` | 0.670 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 6 | traj, tx |
| [test-coverage-gap-002](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--test-coverage-gap-002--4e1a6eb568.html) | `passed` | 0.940 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 51 | traj, tx |
| [test-integration-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--test-integration-001--62f65919e7.html) | `passed` | 0.960 | `True` | `-` | `-` | 0.000 | 26 | traj, tx |
| [test-unitgen-go-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--test-unitgen-go-001--45fc983123.html) | `passed` | 0.960 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 51 | traj, tx |
| [test-unitgen-py-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--test-unitgen-py-001--694781299f.html) | `passed` | 0.600 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 10 | traj, tx |
| [vscode-code-review-001](../tasks/csb_sdlc_test_haiku_20260301_230048--baseline-local-direct--vscode-code-review-001--6300c3f596.html) | `passed` | 0.450 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 8 | traj, tx |

## mcp-remote-direct

- Valid tasks: `6`
- Mean reward: `0.798`
- Pass rate: `1.000`
- Scorer families: `repo_state_heuristic (3), unknown (2), f1_hybrid (1)`
- Output contracts: `answer_json_bridge (4), unknown (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_kafka-security-review-001_kj8zl1](../tasks/csb_sdlc_test_haiku_20260301_230048--mcp-remote-direct--mcp_kafka-security-review-001_kj8zl1--f9b88856b4.html) | `passed` | 0.290 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.857 | 7 | traj, tx |
| [mcp_openhands-search-file-test-001_a63mmd](../tasks/csb_sdlc_test_haiku_20260301_230048--mcp-remote-direct--mcp_openhands-search-file-test-001_a63mmd--27ff8d285c.html) | `passed` | 0.600 | `True` | `-` | `-` | 0.174 | 23 | traj, tx |
| [mcp_test-coverage-gap-002_plhlta](../tasks/csb_sdlc_test_haiku_20260301_230048--mcp-remote-direct--mcp_test-coverage-gap-002_plhlta--7d7e102ba8.html) | `passed` | 0.940 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.967 | 30 | traj, tx |
| [mcp_test-integration-001_d6vnuv](../tasks/csb_sdlc_test_haiku_20260301_230048--mcp-remote-direct--mcp_test-integration-001_d6vnuv--fa7c52699b.html) | `passed` | 0.960 | `True` | `-` | `-` | 0.743 | 35 | traj, tx |
| [mcp_test-unitgen-go-001_okozow](../tasks/csb_sdlc_test_haiku_20260301_230048--mcp-remote-direct--mcp_test-unitgen-go-001_okozow--36d04dee48.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.217 | 23 | traj, tx |
| [mcp_test-unitgen-py-001_znet6b](../tasks/csb_sdlc_test_haiku_20260301_230048--mcp-remote-direct--mcp_test-unitgen-py-001_znet6b--f87177209e.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.091 | 11 | traj, tx |
