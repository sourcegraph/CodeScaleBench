# ccb_document

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_document_haiku_20260224_174311](../runs/ccb_document_haiku_20260224_174311.md) | `mcp-remote-direct` | 5 | 0.720 | 1.000 |
| [ccb_document_haiku_20260228_025547](../runs/ccb_document_haiku_20260228_025547.md) | `baseline-local-direct` | 18 | 0.879 | 1.000 |
| [ccb_document_haiku_20260228_025547](../runs/ccb_document_haiku_20260228_025547.md) | `mcp-remote-direct` | 18 | 0.887 | 1.000 |
| [ccb_document_haiku_20260228_124521](../runs/ccb_document_haiku_20260228_124521.md) | `mcp-remote-direct` | 1 | 1.000 | 1.000 |
| [document_haiku_20260223_164240](../runs/document_haiku_20260223_164240.md) | `baseline-local-direct` | 1 | 0.980 | 1.000 |
| [document_haiku_20260223_164240](../runs/document_haiku_20260223_164240.md) | `mcp-remote-direct` | 20 | 0.822 | 1.000 |
| [document_haiku_20260226_013910](../runs/document_haiku_20260226_013910.md) | `baseline-local-direct` | 1 | 1.000 | 1.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [cilium-api-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--cilium-api-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/cilium-api-doc-gen-001) | `baseline-local-direct` | `passed` | 0.990 | 3 | 0.000 |
| [mcp_cilium-api-doc-gen-001_091CkA](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_cilium-api-doc-gen-001_091CkA.html) | [source](../../../benchmarks/ccb_document/cilium-api-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.970 | 3 | 0.958 |
| [sgonly_cilium-api-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_cilium-api-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/cilium-api-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.980 | 3 | 0.929 |
| [docgen-changelog-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--docgen-changelog-001.html) | [source](../../../benchmarks/ccb_document/docgen-changelog-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_docgen-changelog-001_dAdbQw](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-changelog-001_dAdbQw.html) | [source](../../../benchmarks/ccb_document/docgen-changelog-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.970 |
| [sgonly_docgen-changelog-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_docgen-changelog-001.html) | [source](../../../benchmarks/ccb_document/docgen-changelog-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.921 |
| [docgen-changelog-002](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--docgen-changelog-002.html) | [source](../../../benchmarks/ccb_document/docgen-changelog-002) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_docgen-changelog-002_FL0OCX](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-changelog-002_FL0OCX.html) | [source](../../../benchmarks/ccb_document/docgen-changelog-002) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.704 |
| [sgonly_docgen-changelog-002](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_docgen-changelog-002.html) | [source](../../../benchmarks/ccb_document/docgen-changelog-002) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.909 |
| [docgen-inline-001](../tasks/document_haiku_20260226_013910--baseline-local-direct--docgen-inline-001.html) | [source](../../../benchmarks/ccb_document/docgen-inline-001) | `baseline-local-direct` | `passed` | 1.000 | 2 | 0.000 |
| [mcp_docgen-inline-001_Iah13n](../tasks/ccb_document_haiku_20260228_124521--mcp-remote-direct--mcp_docgen-inline-001_Iah13n.html) | [source](../../../benchmarks/ccb_document/docgen-inline-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.100 |
| [sgonly_docgen-inline-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_docgen-inline-001.html) | [source](../../../benchmarks/ccb_document/docgen-inline-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.357 |
| [docgen-inline-002](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--docgen-inline-002.html) | [source](../../../benchmarks/ccb_document/docgen-inline-002) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_docgen-inline-002_5i12ae](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-inline-002_5i12ae.html) | [source](../../../benchmarks/ccb_document/docgen-inline-002) | `mcp-remote-direct` | `passed` | 0.880 | 3 | 0.261 |
| [sgonly_docgen-inline-002](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_docgen-inline-002.html) | [source](../../../benchmarks/ccb_document/docgen-inline-002) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.206 |
| [docgen-onboard-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--docgen-onboard-001.html) | [source](../../../benchmarks/ccb_document/docgen-onboard-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_docgen-onboard-001_hukfPp](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-onboard-001_hukfPp.html) | [source](../../../benchmarks/ccb_document/docgen-onboard-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.958 |
| [sgonly_docgen-onboard-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_docgen-onboard-001.html) | [source](../../../benchmarks/ccb_document/docgen-onboard-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.950 |
| [docgen-runbook-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--docgen-runbook-001.html) | [source](../../../benchmarks/ccb_document/docgen-runbook-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_docgen-runbook-001_jYeNEv](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-runbook-001_jYeNEv.html) | [source](../../../benchmarks/ccb_document/docgen-runbook-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.941 |
| [sgonly_docgen-runbook-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_docgen-runbook-001.html) | [source](../../../benchmarks/ccb_document/docgen-runbook-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.773 |
| [docgen-runbook-002](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--docgen-runbook-002.html) | [source](../../../benchmarks/ccb_document/docgen-runbook-002) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_docgen-runbook-002_DNuQLB](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_docgen-runbook-002_DNuQLB.html) | [source](../../../benchmarks/ccb_document/docgen-runbook-002) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.944 |
| [sgonly_docgen-runbook-002](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_docgen-runbook-002.html) | [source](../../../benchmarks/ccb_document/docgen-runbook-002) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.857 |
| [envoy-arch-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--envoy-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/envoy-arch-doc-gen-001) | `baseline-local-direct` | `passed` | 0.930 | 3 | 0.000 |
| [mcp_envoy-arch-doc-gen-001_uEBdoF](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-arch-doc-gen-001_uEBdoF.html) | [source](../../../benchmarks/ccb_document/envoy-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.955 |
| [sgonly_envoy-arch-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_envoy-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/envoy-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.833 |
| [envoy-migration-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--envoy-migration-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/envoy-migration-doc-gen-001) | `baseline-local-direct` | `passed` | 0.960 | 3 | 0.000 |
| [mcp_envoy-migration-doc-gen-001_RmzLDJ](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_envoy-migration-doc-gen-001_RmzLDJ.html) | [source](../../../benchmarks/ccb_document/envoy-migration-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.630 | 3 | 0.917 |
| [sgonly_envoy-migration-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_envoy-migration-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/envoy-migration-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.790 | 3 | 0.826 |
| [istio-arch-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--istio-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/istio-arch-doc-gen-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_istio-arch-doc-gen-001_TsE9lp](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_istio-arch-doc-gen-001_TsE9lp.html) | [source](../../../benchmarks/ccb_document/istio-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.960 | 3 | 0.947 |
| [sgonly_istio-arch-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_istio-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/istio-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.962 |
| [k8s-apiserver-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--k8s-apiserver-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `baseline-local-direct` | `passed` | 0.520 | 3 | 0.000 |
| [mcp_k8s-apiserver-doc-gen-001_G2WWxT](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-apiserver-doc-gen-001_G2WWxT.html) | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.770 | 3 | 0.971 |
| [mcp_k8s-apiserver-doc-gen-001_e9qHQA](../tasks/ccb_document_haiku_20260224_174311--mcp-remote-direct--mcp_k8s-apiserver-doc-gen-001_e9qHQA.html) | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 3 | 0.875 |
| [sgonly_k8s-apiserver-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_k8s-apiserver-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.520 | 3 | 0.974 |
| [k8s-applyconfig-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--k8s-applyconfig-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `baseline-local-direct` | `passed` | 0.900 | 3 | 0.000 |
| [mcp_k8s-applyconfig-doc-gen-001_KXIqYx](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-applyconfig-doc-gen-001_KXIqYx.html) | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.947 |
| [mcp_k8s-applyconfig-doc-gen-001_JHZsM3](../tasks/ccb_document_haiku_20260224_174311--mcp-remote-direct--mcp_k8s-applyconfig-doc-gen-001_JHZsM3.html) | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.958 |
| [sgonly_k8s-applyconfig-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_k8s-applyconfig-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 3 | 0.955 |
| [k8s-clientgo-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--k8s-clientgo-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_k8s-clientgo-doc-gen-001_rKIpaI](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-clientgo-doc-gen-001_rKIpaI.html) | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.974 |
| [mcp_k8s-clientgo-doc-gen-001_uV7Ssw](../tasks/ccb_document_haiku_20260224_174311--mcp-remote-direct--mcp_k8s-clientgo-doc-gen-001_uV7Ssw.html) | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 3 | 0.868 |
| [sgonly_k8s-clientgo-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_k8s-clientgo-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 3 | 0.872 |
| [k8s-fairqueuing-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--k8s-fairqueuing-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `baseline-local-direct` | `passed` | 0.450 | 3 | 0.000 |
| [mcp_k8s-fairqueuing-doc-gen-001_62urr3](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-fairqueuing-doc-gen-001_62urr3.html) | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.520 | 3 | 0.882 |
| [mcp_k8s-fairqueuing-doc-gen-001_eRPJdR](../tasks/ccb_document_haiku_20260224_174311--mcp-remote-direct--mcp_k8s-fairqueuing-doc-gen-001_eRPJdR.html) | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 3 | 0.957 |
| [sgonly_k8s-fairqueuing-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_k8s-fairqueuing-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.020 | 3 | 0.944 |
| [k8s-kubelet-cm-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--k8s-kubelet-cm-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `baseline-local-direct` | `passed` | 0.650 | 3 | 0.000 |
| [mcp_k8s-kubelet-cm-doc-gen-001_n6VqU9](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_k8s-kubelet-cm-doc-gen-001_n6VqU9.html) | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 3 | 0.952 |
| [mcp_k8s-kubelet-cm-doc-gen-001_mVr2Xz](../tasks/ccb_document_haiku_20260224_174311--mcp-remote-direct--mcp_k8s-kubelet-cm-doc-gen-001_mVr2Xz.html) | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.650 | 3 | 0.968 |
| [sgonly_k8s-kubelet-cm-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_k8s-kubelet-cm-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.300 | 3 | 0.828 |
| [kafka-api-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--kafka-api-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/kafka-api-doc-gen-001) | `baseline-local-direct` | `passed` | 0.990 | 3 | 0.000 |
| [mcp_kafka-api-doc-gen-001_Kv6biZ](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_kafka-api-doc-gen-001_Kv6biZ.html) | [source](../../../benchmarks/ccb_document/kafka-api-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.990 | 3 | 0.938 |
| [sgonly_kafka-api-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_kafka-api-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/kafka-api-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.940 | 3 | 0.794 |
| [terraform-arch-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--terraform-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/terraform-arch-doc-gen-001) | `baseline-local-direct` | `passed` | 0.430 | 3 | 0.000 |
| [mcp_terraform-arch-doc-gen-001_4HxL3B](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_terraform-arch-doc-gen-001_4HxL3B.html) | [source](../../../benchmarks/ccb_document/terraform-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.590 | 3 | 0.920 |
| [sgonly_terraform-arch-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_terraform-arch-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/terraform-arch-doc-gen-001) | `mcp-remote-direct` | `passed` | 0.590 | 3 | 0.962 |
| [terraform-migration-doc-gen-001](../tasks/ccb_document_haiku_20260228_025547--baseline-local-direct--terraform-migration-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/terraform-migration-doc-gen-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [mcp_terraform-migration-doc-gen-001_XjPeYr](../tasks/ccb_document_haiku_20260228_025547--mcp-remote-direct--mcp_terraform-migration-doc-gen-001_XjPeYr.html) | [source](../../../benchmarks/ccb_document/terraform-migration-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.857 |
| [sgonly_terraform-migration-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_terraform-migration-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/terraform-migration-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.933 |
| [vscode-api-doc-gen-001](../tasks/document_haiku_20260223_164240--baseline-local-direct--vscode-api-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/vscode-api-doc-gen-001) | `baseline-local-direct` | `passed` | 0.980 | 2 | 0.000 |
| [sgonly_vscode-api-doc-gen-001](../tasks/document_haiku_20260223_164240--mcp-remote-direct--sgonly_vscode-api-doc-gen-001.html) | [source](../../../benchmarks/ccb_document/vscode-api-doc-gen-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.952 |

## Multi-Run Variance

Tasks with multiple valid runs (38 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| cilium-api-doc-gen-001 | [source](../../../benchmarks/ccb_document/cilium-api-doc-gen-001) | `baseline-local-direct` | 2 | 0.975 | 0.021 | 0.960, 0.990 |
| cilium-api-doc-gen-001 | [source](../../../benchmarks/ccb_document/cilium-api-doc-gen-001) | `mcp-remote-direct` | 2 | 0.975 | 0.007 | 0.980, 0.970 |
| docgen-changelog-001 | [source](../../../benchmarks/ccb_document/docgen-changelog-001) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| docgen-changelog-001 | [source](../../../benchmarks/ccb_document/docgen-changelog-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| docgen-changelog-002 | [source](../../../benchmarks/ccb_document/docgen-changelog-002) | `baseline-local-direct` | 2 | 0.850 | 0.212 | 0.700, 1.000 |
| docgen-changelog-002 | [source](../../../benchmarks/ccb_document/docgen-changelog-002) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| docgen-inline-001 | [source](../../../benchmarks/ccb_document/docgen-inline-001) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| docgen-inline-001 | [source](../../../benchmarks/ccb_document/docgen-inline-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| docgen-inline-002 | [source](../../../benchmarks/ccb_document/docgen-inline-002) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| docgen-inline-002 | [source](../../../benchmarks/ccb_document/docgen-inline-002) | `mcp-remote-direct` | 2 | 0.940 | 0.085 | 1.000, 0.880 |
| docgen-onboard-001 | [source](../../../benchmarks/ccb_document/docgen-onboard-001) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| docgen-onboard-001 | [source](../../../benchmarks/ccb_document/docgen-onboard-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| docgen-runbook-001 | [source](../../../benchmarks/ccb_document/docgen-runbook-001) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| docgen-runbook-001 | [source](../../../benchmarks/ccb_document/docgen-runbook-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| docgen-runbook-002 | [source](../../../benchmarks/ccb_document/docgen-runbook-002) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| docgen-runbook-002 | [source](../../../benchmarks/ccb_document/docgen-runbook-002) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| envoy-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/envoy-arch-doc-gen-001) | `baseline-local-direct` | 2 | 0.965 | 0.050 | 1.000, 0.930 |
| envoy-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/envoy-arch-doc-gen-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| envoy-migration-doc-gen-001 | [source](../../../benchmarks/ccb_document/envoy-migration-doc-gen-001) | `baseline-local-direct` | 2 | 0.805 | 0.219 | 0.650, 0.960 |
| envoy-migration-doc-gen-001 | [source](../../../benchmarks/ccb_document/envoy-migration-doc-gen-001) | `mcp-remote-direct` | 2 | 0.710 | 0.113 | 0.790, 0.630 |
| istio-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/istio-arch-doc-gen-001) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| istio-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/istio-arch-doc-gen-001) | `mcp-remote-direct` | 2 | 0.980 | 0.028 | 1.000, 0.960 |
| k8s-apiserver-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `baseline-local-direct` | 3 | 0.547 | 0.093 | 0.650, 0.470, 0.520 |
| k8s-apiserver-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-apiserver-doc-gen-001) | `mcp-remote-direct` | 3 | 0.647 | 0.125 | 0.520, 0.650, 0.770 |
| k8s-applyconfig-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `baseline-local-direct` | 3 | 0.933 | 0.058 | 0.900, 1.000, 0.900 |
| k8s-applyconfig-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-applyconfig-doc-gen-001) | `mcp-remote-direct` | 3 | 0.883 | 0.202 | 0.650, 1.000, 1.000 |
| k8s-clientgo-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `baseline-local-direct` | 3 | 0.883 | 0.202 | 1.000, 0.650, 1.000 |
| k8s-clientgo-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-clientgo-doc-gen-001) | `mcp-remote-direct` | 3 | 0.767 | 0.202 | 0.650, 0.650, 1.000 |
| k8s-fairqueuing-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `baseline-local-direct` | 3 | 0.413 | 0.158 | 0.240, 0.550, 0.450 |
| k8s-fairqueuing-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-fairqueuing-doc-gen-001) | `mcp-remote-direct` | 3 | 0.397 | 0.333 | 0.020, 0.650, 0.520 |
| k8s-kubelet-cm-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `baseline-local-direct` | 3 | 0.667 | 0.057 | 0.730, 0.620, 0.650 |
| k8s-kubelet-cm-doc-gen-001 | [source](../../../benchmarks/ccb_document/k8s-kubelet-cm-doc-gen-001) | `mcp-remote-direct` | 3 | 0.533 | 0.202 | 0.300, 0.650, 0.650 |
| kafka-api-doc-gen-001 | [source](../../../benchmarks/ccb_document/kafka-api-doc-gen-001) | `baseline-local-direct` | 2 | 0.965 | 0.035 | 0.940, 0.990 |
| kafka-api-doc-gen-001 | [source](../../../benchmarks/ccb_document/kafka-api-doc-gen-001) | `mcp-remote-direct` | 2 | 0.965 | 0.035 | 0.940, 0.990 |
| terraform-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/terraform-arch-doc-gen-001) | `baseline-local-direct` | 2 | 0.425 | 0.007 | 0.420, 0.430 |
| terraform-arch-doc-gen-001 | [source](../../../benchmarks/ccb_document/terraform-arch-doc-gen-001) | `mcp-remote-direct` | 2 | 0.590 | 0.000 | 0.590, 0.590 |
| terraform-migration-doc-gen-001 | [source](../../../benchmarks/ccb_document/terraform-migration-doc-gen-001) | `baseline-local-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| terraform-migration-doc-gen-001 | [source](../../../benchmarks/ccb_document/terraform-migration-doc-gen-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
