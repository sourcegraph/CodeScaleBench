# csb_sdlc_test_sonnet_20260308_034803

## baseline-local-direct

- Valid tasks: `12`
- Mean reward: `0.722`
- Pass rate: `1.000`
- Scorer families: `f1_hybrid (7), repo_state_heuristic (5)`
- Output contracts: `answer_json_bridge (12)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [aspnetcore-code-review-001](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--aspnetcore-code-review-001--cef8114e38.html) | `passed` | 0.550 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 5 | traj, tx |
| [bazel-starlark-eval-test-001](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--bazel-starlark-eval-test-001--684e6a3cad.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 59 | traj, tx |
| [calcom-code-review-001](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--calcom-code-review-001--cd7dbd5b00.html) | `passed` | 0.680 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 6 | traj, tx |
| [envoy-code-review-001](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--envoy-code-review-001--23b2edcd1c.html) | `passed` | 0.700 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 12 | traj, tx |
| [ghost-code-review-001](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--ghost-code-review-001--97ce673222.html) | `passed` | 0.800 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 11 | traj, tx |
| [kafka-security-review-001](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--kafka-security-review-001--2f8d67ed59.html) | `passed` | 0.440 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 7 | traj, tx |
| [terraform-code-review-001](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--terraform-code-review-001--625ceb30e7.html) | `passed` | 0.620 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 7 | traj, tx |
| [test-coverage-gap-001](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--test-coverage-gap-001--6fa456f972.html) | `passed` | 0.860 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 56 | traj, tx |
| [test-coverage-gap-002](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--test-coverage-gap-002--f3873a3a53.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 103 | traj, tx |
| [test-unitgen-go-001](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--test-unitgen-go-001--42546eb108.html) | `passed` | 0.960 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 59 | traj, tx |
| [test-unitgen-py-001](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--test-unitgen-py-001--1fb44c3d71.html) | `passed` | 0.600 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 4 | traj, tx |
| [vscode-code-review-001](../tasks/csb_sdlc_test_sonnet_20260308_034803--baseline-local-direct--vscode-code-review-001--edbae40616.html) | `passed` | 0.450 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.000 | 10 | traj, tx |

## mcp-remote-direct

- Valid tasks: `9`
- Mean reward: `0.681`
- Pass rate: `0.889`
- Scorer families: `repo_state_heuristic (5), f1_hybrid (4)`
- Output contracts: `answer_json_bridge (9)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_envoy-code-review-001_wib9tl](../tasks/csb_sdlc_test_sonnet_20260308_034803--mcp-remote-direct--mcp_envoy-code-review-001_wib9tl--3881776b04.html) | `failed` | 0.000 | `False` | `f1_hybrid` | `answer_json_bridge` | 0.929 | 14 | traj, tx |
| [mcp_bazel-starlark-eval-test-001_zcthca](../tasks/csb_sdlc_test_sonnet_20260308_034803--mcp-remote-direct--mcp_bazel-starlark-eval-test-001_zcthca--81fe9ef602.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.793 | 58 | traj, tx |
| [mcp_calcom-code-review-001_a2szdg](../tasks/csb_sdlc_test_sonnet_20260308_034803--mcp-remote-direct--mcp_calcom-code-review-001_a2szdg--ee11cc0d9b.html) | `passed` | 0.390 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.800 | 25 | traj, tx |
| [mcp_kafka-security-review-001_uyr7dy](../tasks/csb_sdlc_test_sonnet_20260308_034803--mcp-remote-direct--mcp_kafka-security-review-001_uyr7dy--3ad55c14c3.html) | `passed` | 0.290 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.667 | 12 | traj, tx |
| [mcp_test-coverage-gap-001_iiggfo](../tasks/csb_sdlc_test_sonnet_20260308_034803--mcp-remote-direct--mcp_test-coverage-gap-001_iiggfo--182b99bbee.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.926 | 54 | traj, tx |
| [mcp_test-coverage-gap-002_bdlbu7](../tasks/csb_sdlc_test_sonnet_20260308_034803--mcp-remote-direct--mcp_test-coverage-gap-002_bdlbu7--d3809d41f5.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.936 | 47 | traj, tx |
| [mcp_test-unitgen-go-001_wuf6zf](../tasks/csb_sdlc_test_sonnet_20260308_034803--mcp-remote-direct--mcp_test-unitgen-go-001_wuf6zf--d1d64eaa01.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.261 | 23 | traj, tx |
| [mcp_test-unitgen-py-001_vkatdl](../tasks/csb_sdlc_test_sonnet_20260308_034803--mcp-remote-direct--mcp_test-unitgen-py-001_vkatdl--eb32c41640.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.263 | 19 | traj, tx |
| [mcp_vscode-code-review-001_wtkbpd](../tasks/csb_sdlc_test_sonnet_20260308_034803--mcp-remote-direct--mcp_vscode-code-review-001_wtkbpd--d52b7f46fd.html) | `passed` | 0.450 | `True` | `f1_hybrid` | `answer_json_bridge` | 0.904 | 146 | traj, tx |
