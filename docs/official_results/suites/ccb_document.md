# ccb_document

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_document_haiku_20260224_174311](../runs/ccb_document_haiku_20260224_174311.md) | `mcp-remote-direct` | 5 | 0.720 | 1.000 |
| [ccb_document_haiku_20260228_025547](../runs/ccb_document_haiku_20260228_025547.md) | `mcp-remote-direct` | 18 | 0.887 | 1.000 |
| [ccb_document_haiku_20260228_124521](../runs/ccb_document_haiku_20260228_124521.md) | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [document_haiku_20260301_071228](../runs/document_haiku_20260301_071228.md) | `baseline-local-direct` | 20 | 0.845 | 1.000 |
| [document_haiku_20260301_071228](../runs/document_haiku_20260301_071228.md) | `mcp-remote-direct` | 20 | 0.898 | 1.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [cilium-api-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--cilium-api-doc-gen-001.html) | — | `baseline-local-direct` | `passed` | 0.980 | 5 | 0.000 |
| [mcp_cilium-api-doc-gen-001_091CkA](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_cilium-api-doc-gen-001_091CkA.html) | — | `mcp-remote-direct` | `passed` | 0.970 | 5 | 0.958 |
| [sgonly_cilium-api-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_cilium-api-doc-gen-001.html) | — | `mcp-remote-direct` | `passed` | 0.960 | 5 | 0.950 |
| [docgen-changelog-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--docgen-changelog-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [mcp_docgen-changelog-001_dAdbQw](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-changelog-001_dAdbQw.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.970 |
| [sgonly_docgen-changelog-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_docgen-changelog-001.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.935 |
| [docgen-changelog-002](../tasks/document_haiku_20260301_071228--baseline-local-direct--docgen-changelog-002.html) | [source](../../../benchmarks/ccb_document/docgen-changelog-002) | `baseline-local-direct` | `passed` | 0.700 | 5 | 0.000 |
| [mcp_docgen-changelog-002_FL0OCX](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-changelog-002_FL0OCX.html) | [source](../../../benchmarks/ccb_document/docgen-changelog-002) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.704 |
| [sgonly_docgen-changelog-002](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_docgen-changelog-002.html) | [source](../../../benchmarks/ccb_document/docgen-changelog-002) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.913 |
| [docgen-inline-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--docgen-inline-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [mcp_docgen-inline-001_Iah13n](../tasks/ccb_document_haiku_20260228_124521--mcp-remote-direct--mcp_docgen-inline-001_Iah13n.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.100 |
| [sgonly_docgen-inline-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_docgen-inline-001.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.500 |
| [docgen-inline-002](../tasks/document_haiku_20260301_071228--baseline-local-direct--docgen-inline-002.html) | [source](../../../benchmarks/ccb_document/docgen-inline-002) | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [mcp_docgen-inline-002_5i12ae](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-inline-002_5i12ae.html) | [source](../../../benchmarks/ccb_document/docgen-inline-002) | `mcp-remote-direct` | `passed` | 0.880 | 5 | 0.261 |
| [sgonly_docgen-inline-002](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_docgen-inline-002.html) | [source](../../../benchmarks/ccb_document/docgen-inline-002) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.353 |
| [docgen-onboard-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--docgen-onboard-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [mcp_docgen-onboard-001_hukfPp](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-onboard-001_hukfPp.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.958 |
| [sgonly_docgen-onboard-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_docgen-onboard-001.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.947 |
| [docgen-runbook-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--docgen-runbook-001.html) | [source](../../../benchmarks/ccb_document/docgen-runbook-001) | `baseline-local-direct` | `passed` | 0.880 | 5 | 0.000 |
| [mcp_docgen-runbook-001_jYeNEv](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-runbook-001_jYeNEv.html) | [source](../../../benchmarks/ccb_document/docgen-runbook-001) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.941 |
| [sgonly_docgen-runbook-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_docgen-runbook-001.html) | [source](../../../benchmarks/ccb_document/docgen-runbook-001) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.680 |
| [docgen-runbook-002](../tasks/document_haiku_20260301_071228--baseline-local-direct--docgen-runbook-002.html) | — | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [mcp_docgen-runbook-002_DNuQLB](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-runbook-002_DNuQLB.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.944 |
| [sgonly_docgen-runbook-002](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_docgen-runbook-002.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.889 |
| [envoy-arch-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--envoy-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/envoy-arch-doc-gen-001) | `baseline-local-direct` | `passed` | 0.970 | 5 | 0.000 |
| [mcp_envoy-arch-doc-gen-001_uEBdoF](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-arch-doc-gen-001_uEBdoF.html) | [source](../../../benchmarks/ccb_document/envoy-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.955 |
| [sgonly_envoy-arch-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_envoy-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/envoy-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.960 | 5 | 0.900 |
| [envoy-migration-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--envoy-migration-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/envoy-migration-doc-gen-001) | `baseline-local-direct` | `passed` | 0.720 | 5 | 0.000 |
| [mcp_envoy-migration-doc-gen-001_RmzLDJ](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-migration-doc-gen-001_RmzLDJ.html) | [source](../../../benchmarks/ccb_document/envoy-migration-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.630 | 5 | 0.917 |
| [sgonly_envoy-migration-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_envoy-migration-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/envoy-migration-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.720 | 5 | 0.947 |
| [istio-arch-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--istio-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/istio-arch-doc-gen-001) | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [mcp_istio-arch-doc-gen-001_TsE9lp](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_istio-arch-doc-gen-001_TsE9lp.html) | [source](../../../benchmarks/ccb_document/istio-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.960 | 5 | 0.947 |
| [sgonly_istio-arch-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_istio-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/istio-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.960 | 5 | 0.958 |
| [k8s-apiserver-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--k8s-apiserver-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `baseline-local-direct` | `passed` | 0.600 | 5 | 0.000 |
| [mcp_k8s-apiserver-doc-gen-001_G2WWxT](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-apiserver-doc-gen-001_G2WWxT.html) | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.770 | 5 | 0.971 |
| [mcp_k8s-apiserver-doc-gen-001_e9qHQA](../tasks/ccb_document_haiku_20260224_174311--mcp-remote-direct--mcp_k8s-apiserver-doc-gen-001_e9qHQA.html) | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 5 | 0.875 |
| [sgonly_k8s-apiserver-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_k8s-apiserver-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 5 | 0.962 |
| [k8s-applyconfig-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--k8s-applyconfig-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `baseline-local-direct` | `passed` | 0.870 | 5 | 0.000 |
| [mcp_k8s-applyconfig-doc-gen-001_KXIqYx](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-applyconfig-doc-gen-001_KXIqYx.html) | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.947 |
| [mcp_k8s-applyconfig-doc-gen-001_JHZsM3](../tasks/ccb_document_haiku_20260224_174311--mcp-remote-direct--mcp_k8s-applyconfig-doc-gen-001_JHZsM3.html) | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.958 |
| [sgonly_k8s-applyconfig-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_k8s-applyconfig-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.960 | 5 | 0.958 |
| [k8s-clientgo-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--k8s-clientgo-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `baseline-local-direct` | `passed` | 0.830 | 5 | 0.000 |
| [mcp_k8s-clientgo-doc-gen-001_rKIpaI](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-clientgo-doc-gen-001_rKIpaI.html) | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.974 |
| [mcp_k8s-clientgo-doc-gen-001_uV7Ssw](../tasks/ccb_document_haiku_20260224_174311--mcp-remote-direct--mcp_k8s-clientgo-doc-gen-001_uV7Ssw.html) | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 5 | 0.868 |
| [sgonly_k8s-clientgo-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_k8s-clientgo-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.970 |
| [k8s-fairqueuing-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--k8s-fairqueuing-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `baseline-local-direct` | `passed` | 0.450 | 5 | 0.000 |
| [mcp_k8s-fairqueuing-doc-gen-001_62urr3](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-fairqueuing-doc-gen-001_62urr3.html) | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.520 | 5 | 0.882 |
| [mcp_k8s-fairqueuing-doc-gen-001_eRPJdR](../tasks/ccb_document_haiku_20260224_174311--mcp-remote-direct--mcp_k8s-fairqueuing-doc-gen-001_eRPJdR.html) | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 5 | 0.957 |
| [sgonly_k8s-fairqueuing-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_k8s-fairqueuing-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.450 | 5 | 0.964 |
| [k8s-kubelet-cm-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--k8s-kubelet-cm-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `baseline-local-direct` | `passed` | 0.620 | 5 | 0.000 |
| [mcp_k8s-kubelet-cm-doc-gen-001_n6VqU9](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-kubelet-cm-doc-gen-001_n6VqU9.html) | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 5 | 0.952 |
| [mcp_k8s-kubelet-cm-doc-gen-001_mVr2Xz](../tasks/ccb_document_haiku_20260224_174311--mcp-remote-direct--mcp_k8s-kubelet-cm-doc-gen-001_mVr2Xz.html) | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 5 | 0.968 |
| [sgonly_k8s-kubelet-cm-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_k8s-kubelet-cm-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.620 | 5 | 0.917 |
| [kafka-api-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--kafka-api-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/kafka-api-doc-gen-001) | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [mcp_kafka-api-doc-gen-001_Kv6biZ](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_kafka-api-doc-gen-001_Kv6biZ.html) | [source](../../../benchmarks/ccb_document/kafka-api-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.990 | 5 | 0.938 |
| [sgonly_kafka-api-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_kafka-api-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/kafka-api-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.910 | 5 | 0.952 |
| [terraform-arch-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--terraform-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/terraform-arch-doc-gen-001) | `baseline-local-direct` | `passed` | 0.270 | 5 | 0.000 |
| [mcp_terraform-arch-doc-gen-001_4HxL3B](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_terraform-arch-doc-gen-001_4HxL3B.html) | [source](../../../benchmarks/ccb_document/terraform-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.590 | 5 | 0.920 |
| [sgonly_terraform-arch-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_terraform-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/terraform-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.770 | 5 | 0.967 |
| [terraform-migration-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--terraform-migration-doc-gen-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [mcp_terraform-migration-doc-gen-001_XjPeYr](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_terraform-migration-doc-gen-001_XjPeYr.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.857 |
| [sgonly_terraform-migration-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_terraform-migration-doc-gen-001.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 5 | 0.963 |
| [vscode-api-doc-gen-001](../tasks/document_haiku_20260301_071228--baseline-local-direct--vscode-api-doc-gen-001.html) | — | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_vscode-api-doc-gen-001](../tasks/document_haiku_20260301_071228--mcp-remote-direct--sgonly_vscode-api-doc-gen-001.html) | — | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.941 |

## Multi-Run Variance

Tasks with multiple valid runs (26 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| docgen-changelog-002 | [source](../../../benchmarks/ccb_document/docgen-changelog-002) | `baseline-local-direct` | 4 | 0.850 | 0.173 | 0.700, 1.000, 1.000, 0.700 |
| docgen-changelog-002 | [source](../../../benchmarks/ccb_document/docgen-changelog-002) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| docgen-inline-002 | [source](../../../benchmarks/ccb_document/docgen-inline-002) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| docgen-inline-002 | [source](../../../benchmarks/ccb_document/docgen-inline-002) | `mcp-remote-direct` | 4 | 0.970 | 0.060 | 1.000, 0.880, 1.000, 1.000 |
| docgen-runbook-001 | [source](../../../benchmarks/ccb_document/docgen-runbook-001) | `baseline-local-direct` | 4 | 0.970 | 0.060 | 1.000, 1.000, 1.000, 0.880 |
| docgen-runbook-001 | [source](../../../benchmarks/ccb_document/docgen-runbook-001) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| envoy-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/envoy-arch-doc-gen-001) | `baseline-local-direct` | 4 | 0.968 | 0.029 | 1.000, 0.930, 0.970, 0.970 |
| envoy-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/envoy-arch-doc-gen-001) | `mcp-remote-direct` | 4 | 0.983 | 0.021 | 1.000, 1.000, 0.970, 0.960 |
| envoy-migration-doc-gen-001 | [source](../../../benchmarks/ccb_document/envoy-migration-doc-gen-001) | `baseline-local-direct` | 4 | 0.738 | 0.154 | 0.650, 0.960, 0.620, 0.720 |
| envoy-migration-doc-gen-001 | [source](../../../benchmarks/ccb_document/envoy-migration-doc-gen-001) | `mcp-remote-direct` | 4 | 0.733 | 0.076 | 0.790, 0.630, 0.790, 0.720 |
| istio-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/istio-arch-doc-gen-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| istio-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/istio-arch-doc-gen-001) | `mcp-remote-direct` | 4 | 0.970 | 0.020 | 1.000, 0.960, 0.960, 0.960 |
| k8s-apiserver-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `baseline-local-direct` | 5 | 0.622 | 0.155 | 0.650, 0.470, 0.520, 0.870, 0.600 |
| k8s-apiserver-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `mcp-remote-direct` | 5 | 0.666 | 0.098 | 0.520, 0.650, 0.770, 0.740, 0.650 |
| k8s-applyconfig-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `baseline-local-direct` | 5 | 0.900 | 0.063 | 0.900, 1.000, 0.900, 0.830, 0.870 |
| k8s-applyconfig-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `mcp-remote-direct` | 5 | 0.922 | 0.153 | 0.650, 1.000, 1.000, 1.000, 0.960 |
| k8s-clientgo-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `baseline-local-direct` | 5 | 0.896 | 0.156 | 1.000, 0.650, 1.000, 1.000, 0.830 |
| k8s-clientgo-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `mcp-remote-direct` | 5 | 0.860 | 0.192 | 0.650, 0.650, 1.000, 1.000, 1.000 |
| k8s-fairqueuing-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `baseline-local-direct` | 5 | 0.404 | 0.120 | 0.240, 0.550, 0.450, 0.330, 0.450 |
| k8s-fairqueuing-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `mcp-remote-direct` | 5 | 0.438 | 0.244 | 0.020, 0.650, 0.520, 0.550, 0.450 |
| k8s-kubelet-cm-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `baseline-local-direct` | 5 | 0.644 | 0.051 | 0.730, 0.620, 0.650, 0.600, 0.620 |
| k8s-kubelet-cm-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `mcp-remote-direct` | 5 | 0.574 | 0.154 | 0.300, 0.650, 0.650, 0.650, 0.620 |
| kafka-api-doc-gen-001 | [source](../../../benchmarks/ccb_document/kafka-api-doc-gen-001) | `baseline-local-direct` | 4 | 0.975 | 0.026 | 0.940, 0.990, 0.970, 1.000 |
| kafka-api-doc-gen-001 | [source](../../../benchmarks/ccb_document/kafka-api-doc-gen-001) | `mcp-remote-direct` | 4 | 0.945 | 0.033 | 0.940, 0.990, 0.940, 0.910 |
| terraform-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/terraform-arch-doc-gen-001) | `baseline-local-direct` | 4 | 0.365 | 0.075 | 0.420, 0.430, 0.340, 0.270 |
| terraform-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/terraform-arch-doc-gen-001) | `mcp-remote-direct` | 4 | 0.635 | 0.090 | 0.590, 0.590, 0.590, 0.770 |
