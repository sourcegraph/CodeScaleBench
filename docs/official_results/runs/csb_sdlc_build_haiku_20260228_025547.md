# csb_sdlc_build_haiku_20260228_025547

## baseline-local-direct

- Valid tasks: `13`
- Mean reward: `0.554`
- Pass rate: `0.692`
- Scorer families: `unknown (7), repo_state_heuristic (3), checklist (1), f1 (1), semantic_similarity (1)`
- Output contracts: `unknown (7), answer_json_bridge (5), unspecified (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [codecoverage-deps-install-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--codecoverage-deps-install-001--21f607d009.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 94 | traj, tx |
| [dotnetkoans-deps-install-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--dotnetkoans-deps-install-001--b7d9960b20.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.000 | 52 | traj, tx |
| [tensorrt-mxfp4-quant-feat-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--tensorrt-mxfp4-quant-feat-001--127bde79d7.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 88 | traj, tx |
| [vscode-stale-diagnostics-feat-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--vscode-stale-diagnostics-feat-001--e1690fecd5.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 78 | traj, tx |
| [bustub-hyperloglog-impl-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--bustub-hyperloglog-impl-001--448cfd3b42.html) | `passed` | 0.500 | `True` | `checklist` | `unspecified` | 0.000 | 106 | traj, tx |
| [dotenv-expand-deps-install-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--dotenv-expand-deps-install-001--df787cdf1a.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 29 | traj, tx |
| [envoy-grpc-server-impl-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--envoy-grpc-server-impl-001--b997995f10.html) | `passed` | 0.440 | `True` | `f1` | `answer_json_bridge` | 0.000 | 56 | traj, tx |
| [eslint-markdown-deps-install-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--eslint-markdown-deps-install-001--884b3b176b.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 52 | traj, tx |
| [flipt-flagexists-refactor-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--flipt-flagexists-refactor-001--0270661208.html) | `passed` | 0.300 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.000 | 53 | traj, tx |
| [iamactionhunter-deps-install-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--iamactionhunter-deps-install-001--5649e76f1b.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 28 | traj, tx |
| [pcap-parser-deps-install-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--pcap-parser-deps-install-001--3f72d8f59e.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 34 | traj, tx |
| [python-http-class-naming-refac-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--python-http-class-naming-refac-001--658b02a4f7.html) | `passed` | 0.960 | `True` | `semantic_similarity` | `answer_json_bridge` | 0.000 | 44 | traj, tx |
| [similar-asserts-deps-install-001](../tasks/csb_sdlc_build_haiku_20260228_025547--baseline-local-direct--similar-asserts-deps-install-001--8350399c48.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.000 | 46 | traj, tx |

## mcp-remote-direct

- Valid tasks: `10`
- Mean reward: `0.595`
- Pass rate: `0.700`
- Scorer families: `unknown (5), repo_state_heuristic (3), f1 (1), semantic_similarity (1)`
- Output contracts: `answer_json_bridge (5), unknown (5)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_codecoverage-deps-install-001_x8rcGu](../tasks/csb_sdlc_build_haiku_20260228_025547--mcp-remote-direct--mcp_codecoverage-deps-install-001_x8rcGu--dd03ff519a.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.533 | 30 | traj, tx |
| [mcp_dotenv-expand-deps-install-001_gtBAHY](../tasks/csb_sdlc_build_haiku_20260228_025547--mcp-remote-direct--mcp_dotenv-expand-deps-install-001_gtBAHY--b00dd5fb2c.html) | `failed` | 0.000 | `False` | `-` | `-` | 0.282 | 85 | traj, tx |
| [mcp_vscode-stale-diagnostics-feat-001_UBNxW5](../tasks/csb_sdlc_build_haiku_20260228_025547--mcp-remote-direct--mcp_vscode-stale-diagnostics-feat-001_UBNxW5--a4d0fe807b.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_bridge` | 0.224 | 76 | traj, tx |
| [mcp_envoy-grpc-server-impl-001_y67Otz](../tasks/csb_sdlc_build_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-grpc-server-impl-001_y67Otz--5aaa9bfafd.html) | `passed` | 0.220 | `True` | `f1` | `answer_json_bridge` | 0.969 | 32 | traj, tx |
| [mcp_flipt-flagexists-refactor-001_xDOm7g](../tasks/csb_sdlc_build_haiku_20260228_025547--mcp-remote-direct--mcp_flipt-flagexists-refactor-001_xDOm7g--09e3552e46.html) | `passed` | 0.850 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.197 | 76 | traj, tx |
| [mcp_iamactionhunter-deps-install-001_ePchSL](../tasks/csb_sdlc_build_haiku_20260228_025547--mcp-remote-direct--mcp_iamactionhunter-deps-install-001_ePchSL--c74ac6a8bd.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.479 | 73 | traj, tx |
| [mcp_pcap-parser-deps-install-001_fgSA2o](../tasks/csb_sdlc_build_haiku_20260228_025547--mcp-remote-direct--mcp_pcap-parser-deps-install-001_fgSA2o--01198a6d55.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.457 | 35 | traj, tx |
| [mcp_python-http-class-naming-refac-001_Z74daj](../tasks/csb_sdlc_build_haiku_20260228_025547--mcp-remote-direct--mcp_python-http-class-naming-refac-001_Z74daj--c1a79f935b.html) | `passed` | 0.880 | `True` | `semantic_similarity` | `answer_json_bridge` | 0.173 | 52 | traj, tx |
| [mcp_similar-asserts-deps-install-001_udUva4](../tasks/csb_sdlc_build_haiku_20260228_025547--mcp-remote-direct--mcp_similar-asserts-deps-install-001_udUva4--37234d2740.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.333 | 30 | traj, tx |
| [mcp_tensorrt-mxfp4-quant-feat-001_QgJMEd](../tasks/csb_sdlc_build_haiku_20260228_025547--mcp-remote-direct--mcp_tensorrt-mxfp4-quant-feat-001_QgJMEd--10e876c420.html) | `passed` | 1.000 | `True` | `repo_state_heuristic` | `answer_json_bridge` | 0.314 | 35 | traj, tx |
