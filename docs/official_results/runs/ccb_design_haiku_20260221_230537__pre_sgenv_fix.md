# ccb_design_haiku_20260221_230537__pre_sgenv_fix

## mcp-remote-artifact

- Valid tasks: `20`
- Mean reward: `0.544`
- Pass rate: `0.850`
- Scorer families: `unknown (10), ir_checklist (6), repo_state_heuristic (3), semantic_similarity (1)`
- Output contracts: `unknown (10), answer_json_bridge (6), answer_json_native (3), repo_state (1)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_django-pre-validate-signal-design-001_mlyXYm](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_django-pre-validate-signal-design-001_mlyXYm--e8898b3bd2.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_native` | 0.846 | 13 | traj, tx |
| [mcp_etcd-grpc-api-upgrade-001_qenftD](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_etcd-grpc-api-upgrade-001_qenftD--d3b03cd4b7.html) | `failed` | 0.000 | `False` | `semantic_similarity` | `repo_state` | 0.019 | 52 | traj, tx |
| [mcp_flipt-protobuf-metadata-design-001_ZjNZqi](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_flipt-protobuf-metadata-design-001_ZjNZqi--77922e0a3b.html) | `failed` | 0.000 | `False` | `repo_state_heuristic` | `answer_json_native` | 1.000 | 11 | traj, tx |
| [mcp_camel-routing-arch-001_jQytTs](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_camel-routing-arch-001_jQytTs--1747b7135d.html) | `passed` | 0.720 | `True` | `ir_checklist` | `answer_json_bridge` | 0.971 | 34 | traj, tx |
| [mcp_django-modeladmin-impact-001_X1wPPa](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_django-modeladmin-impact-001_X1wPPa--bc6c2af376.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.968 | 31 | traj, tx |
| [mcp_django-orm-query-arch-001_GnVfD2](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_django-orm-query-arch-001_GnVfD2--882b9f68c2.html) | `passed` | 0.890 | `True` | `ir_checklist` | `answer_json_bridge` | 0.970 | 33 | traj, tx |
| [mcp_django-rate-limit-design-001_SHY4V4](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_django-rate-limit-design-001_SHY4V4--03dd457adb.html) | `passed` | 0.050 | `True` | `repo_state_heuristic` | `answer_json_native` | 0.857 | 7 | traj, tx |
| [mcp_envoy-routeconfig-dep-chain-001_ctFACn](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_envoy-routeconfig-dep-chain-001_ctFACn--d300bcb2c1.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.425 | 40 | traj, tx |
| [mcp_envoy-stream-aggregated-sym-001_pCkdjy](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_envoy-stream-aggregated-sym-001_pCkdjy--11dbc6e33f.html) | `passed` | 0.450 | `True` | `-` | `-` | 0.969 | 32 | traj, tx |
| [mcp_flink-checkpoint-arch-001_NrabsI](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_flink-checkpoint-arch-001_NrabsI--dfac06ee0e.html) | `passed` | 0.640 | `True` | `ir_checklist` | `answer_json_bridge` | 0.957 | 23 | traj, tx |
| [mcp_flipt-transitive-deps-001_aJcNOJ](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_flipt-transitive-deps-001_aJcNOJ--2bc1d4727d.html) | `passed` | 0.493 | `True` | `-` | `-` | 0.853 | 75 | traj, tx |
| [mcp_k8s-crd-lifecycle-arch-001_lguJtR](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_k8s-crd-lifecycle-arch-001_lguJtR--8ba72bc592.html) | `passed` | 0.650 | `True` | `ir_checklist` | `answer_json_bridge` | 0.971 | 35 | traj, tx |
| [mcp_k8s-dra-allocation-impact-001_7Y4mmu](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_k8s-dra-allocation-impact-001_7Y4mmu--ab2a3e1000.html) | `passed` | 0.900 | `True` | `-` | `-` | 0.893 | 28 | traj, tx |
| [mcp_k8s-scheduler-arch-001_6ky0Ix](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_k8s-scheduler-arch-001_6ky0Ix--bed99fd466.html) | `passed` | 0.760 | `True` | `-` | `-` | 0.931 | 29 | traj, tx |
| [mcp_k8s-sharedinformer-sym-001_WwBfMe](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_k8s-sharedinformer-sym-001_WwBfMe--522b15b21f.html) | `passed` | 0.570 | `True` | `-` | `-` | 0.978 | 46 | traj, tx |
| [mcp_k8s-typemeta-dep-chain-001_z1R6w6](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_k8s-typemeta-dep-chain-001_z1R6w6--a1153281ab.html) | `passed` | 0.670 | `True` | `-` | `-` | 0.474 | 38 | traj, tx |
| [mcp_kafka-flink-streaming-arch-001_RqMYUk](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_kafka-flink-streaming-arch-001_RqMYUk--5edc399ffe.html) | `passed` | 0.400 | `True` | `ir_checklist` | `answer_json_bridge` | 0.908 | 65 | traj, tx |
| [mcp_postgres-query-exec-arch-001_ku6N8W](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_postgres-query-exec-arch-001_ku6N8W--62682c2039.html) | `passed` | 0.770 | `True` | `ir_checklist` | `answer_json_bridge` | 0.951 | 41 | traj, tx |
| [mcp_quantlib-barrier-pricing-arch-001_OPfBFw](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_quantlib-barrier-pricing-arch-001_OPfBFw--0c49c5ae9f.html) | `passed` | 0.890 | `True` | `-` | `-` | 0.964 | 28 | traj, tx |
| [mcp_terraform-provider-iface-sym-001_yQH7d2](../tasks/ccb_design_haiku_20260221_230537__pre_sgenv_fix--mcp-remote-artifact--mcp_terraform-provider-iface-sym-001_yQH7d2--e585930234.html) | `passed` | 0.020 | `True` | `-` | `-` | 0.857 | 35 | traj, tx |
