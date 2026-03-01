# ccb_debug

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_debug_haiku_20260228_025547](../runs/ccb_debug_haiku_20260228_025547.md) | `baseline-local-direct` | 5 | 0.500 | 1.000 |
| [ccb_debug_haiku_20260228_025547](../runs/ccb_debug_haiku_20260228_025547.md) | `mcp-remote-direct` | 5 | 0.000 | 0.000 |
| [debug_haiku_20260301_021540](../runs/debug_haiku_20260301_021540.md) | `baseline-local-direct` | 11 | 0.847 | 1.000 |
| [debug_haiku_20260301_021540](../runs/debug_haiku_20260301_021540.md) | `mcp-remote-direct` | 11 | 0.813 | 1.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [ansible-galaxy-tar-regression-prove-001](../tasks/ccb_debug_haiku_20260228_025547--baseline-local-direct--ansible-galaxy-tar-regression-prove-001.html) | [source](../../../benchmarks/ccb_debug/ansible-galaxy-tar-regression-prove-001) | `baseline-local-direct` | `passed` | 0.500 | 1 | 0.000 |
| [mcp_ansible-galaxy-tar-regression-prove-001_eJLVHH](../tasks/ccb_debug_haiku_20260228_025547--mcp-remote-direct--mcp_ansible-galaxy-tar-regression-prove-001_eJLVHH.html) | [source](../../../benchmarks/ccb_debug/ansible-galaxy-tar-regression-prove-001) | `mcp-remote-direct` | `failed` | 0.000 | 1 | 0.289 |
| [django-admins-migration-audit-001](../tasks/debug_haiku_20260301_021540--baseline-local-direct--django-admins-migration-audit-001.html) | [source](../../../benchmarks/ccb_debug/django-admins-migration-audit-001) | `baseline-local-direct` | `passed` | 1.000 | 3 | 0.000 |
| [sgonly_django-admins-migration-audit-001](../tasks/debug_haiku_20260301_021540--mcp-remote-direct--sgonly_django-admins-migration-audit-001.html) | [source](../../../benchmarks/ccb_debug/django-admins-migration-audit-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.962 |
| [envoy-duplicate-headers-debug-001](../tasks/debug_haiku_20260301_021540--baseline-local-direct--envoy-duplicate-headers-debug-001.html) | [source](../../../benchmarks/ccb_debug/envoy-duplicate-headers-debug-001) | `baseline-local-direct` | `passed` | 0.940 | 4 | 0.000 |
| [sgonly_envoy-duplicate-headers-debug-001](../tasks/debug_haiku_20260301_021540--mcp-remote-direct--sgonly_envoy-duplicate-headers-debug-001.html) | [source](../../../benchmarks/ccb_debug/envoy-duplicate-headers-debug-001) | `mcp-remote-direct` | `passed` | 0.770 | 3 | 0.971 |
| [flipt-auth-cookie-regression-prove-001](../tasks/ccb_debug_haiku_20260228_025547--baseline-local-direct--flipt-auth-cookie-regression-prove-001.html) | [source](../../../benchmarks/ccb_debug/flipt-auth-cookie-regression-prove-001) | `baseline-local-direct` | `passed` | 0.500 | 1 | 0.000 |
| [mcp_flipt-auth-cookie-regression-prove-001_CCv72S](../tasks/ccb_debug_haiku_20260228_025547--mcp-remote-direct--mcp_flipt-auth-cookie-regression-prove-001_CCv72S.html) | [source](../../../benchmarks/ccb_debug/flipt-auth-cookie-regression-prove-001) | `mcp-remote-direct` | `failed` | 0.000 | 1 | 0.413 |
| [grafana-table-panel-regression-001](../tasks/debug_haiku_20260301_021540--baseline-local-direct--grafana-table-panel-regression-001.html) | [source](../../../benchmarks/ccb_debug/grafana-table-panel-regression-001) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [sgonly_grafana-table-panel-regression-001](../tasks/debug_haiku_20260301_021540--mcp-remote-direct--sgonly_grafana-table-panel-regression-001.html) | [source](../../../benchmarks/ccb_debug/grafana-table-panel-regression-001) | `mcp-remote-direct` | `passed` | 0.800 | 3 | 0.842 |
| [istio-xds-destrul-debug-001](../tasks/debug_haiku_20260301_021540--baseline-local-direct--istio-xds-destrul-debug-001.html) | [source](../../../benchmarks/ccb_debug/istio-xds-destrul-debug-001) | `baseline-local-direct` | `passed` | 0.950 | 4 | 0.000 |
| [sgonly_istio-xds-destrul-debug-001](../tasks/debug_haiku_20260301_021540--mcp-remote-direct--sgonly_istio-xds-destrul-debug-001.html) | [source](../../../benchmarks/ccb_debug/istio-xds-destrul-debug-001) | `mcp-remote-direct` | `passed` | 0.940 | 3 | 0.864 |
| [linux-acpi-backlight-fault-001](../tasks/debug_haiku_20260301_021540--baseline-local-direct--linux-acpi-backlight-fault-001.html) | [source](../../../benchmarks/ccb_debug/linux-acpi-backlight-fault-001) | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [sgonly_linux-acpi-backlight-fault-001](../tasks/debug_haiku_20260301_021540--mcp-remote-direct--sgonly_linux-acpi-backlight-fault-001.html) | [source](../../../benchmarks/ccb_debug/linux-acpi-backlight-fault-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.889 |
| [linux-hda-intel-suspend-fault-001](../tasks/debug_haiku_20260301_021540--baseline-local-direct--linux-hda-intel-suspend-fault-001.html) | [source](../../../benchmarks/ccb_debug/linux-hda-intel-suspend-fault-001) | `baseline-local-direct` | `passed` | 0.700 | 5 | 0.000 |
| [sgonly_linux-hda-intel-suspend-fault-001](../tasks/debug_haiku_20260301_021540--mcp-remote-direct--sgonly_linux-hda-intel-suspend-fault-001.html) | [source](../../../benchmarks/ccb_debug/linux-hda-intel-suspend-fault-001) | `mcp-remote-direct` | `passed` | 0.700 | 3 | 0.789 |
| [linux-iwlwifi-subdevice-fault-001](../tasks/debug_haiku_20260301_021540--baseline-local-direct--linux-iwlwifi-subdevice-fault-001.html) | [source](../../../benchmarks/ccb_debug/linux-iwlwifi-subdevice-fault-001) | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [sgonly_linux-iwlwifi-subdevice-fault-001](../tasks/debug_haiku_20260301_021540--mcp-remote-direct--sgonly_linux-iwlwifi-subdevice-fault-001.html) | [source](../../../benchmarks/ccb_debug/linux-iwlwifi-subdevice-fault-001) | `mcp-remote-direct` | `passed` | 1.000 | 3 | 0.769 |
| [linux-nfs-inode-revalidate-fault-001](../tasks/debug_haiku_20260301_021540--baseline-local-direct--linux-nfs-inode-revalidate-fault-001.html) | [source](../../../benchmarks/ccb_debug/linux-nfs-inode-revalidate-fault-001) | `baseline-local-direct` | `passed` | 0.300 | 5 | 0.000 |
| [sgonly_linux-nfs-inode-revalidate-fault-001](../tasks/debug_haiku_20260301_021540--mcp-remote-direct--sgonly_linux-nfs-inode-revalidate-fault-001.html) | [source](../../../benchmarks/ccb_debug/linux-nfs-inode-revalidate-fault-001) | `mcp-remote-direct` | `passed` | 0.300 | 3 | 0.808 |
| [linux-ssd-trim-timeout-fault-001](../tasks/debug_haiku_20260301_021540--baseline-local-direct--linux-ssd-trim-timeout-fault-001.html) | [source](../../../benchmarks/ccb_debug/linux-ssd-trim-timeout-fault-001) | `baseline-local-direct` | `passed` | 1.000 | 5 | 0.000 |
| [sgonly_linux-ssd-trim-timeout-fault-001](../tasks/debug_haiku_20260301_021540--mcp-remote-direct--sgonly_linux-ssd-trim-timeout-fault-001.html) | [source](../../../benchmarks/ccb_debug/linux-ssd-trim-timeout-fault-001) | `mcp-remote-direct` | `passed` | 1.000 | 2 | 0.800 |
| [prometheus-queue-reshard-debug-001](../tasks/debug_haiku_20260301_021540--baseline-local-direct--prometheus-queue-reshard-debug-001.html) | [source](../../../benchmarks/ccb_debug/prometheus-queue-reshard-debug-001) | `baseline-local-direct` | `passed` | 0.480 | 4 | 0.000 |
| [sgonly_prometheus-queue-reshard-debug-001](../tasks/debug_haiku_20260301_021540--mcp-remote-direct--sgonly_prometheus-queue-reshard-debug-001.html) | [source](../../../benchmarks/ccb_debug/prometheus-queue-reshard-debug-001) | `mcp-remote-direct` | `passed` | 0.480 | 3 | 0.846 |
| [qutebrowser-adblock-cache-regression-prove-001](../tasks/ccb_debug_haiku_20260228_025547--baseline-local-direct--qutebrowser-adblock-cache-regression-prove-001.html) | [source](../../../benchmarks/ccb_debug/qutebrowser-adblock-cache-regression-prove-001) | `baseline-local-direct` | `passed` | 0.500 | 1 | 0.000 |
| [mcp_qutebrowser-adblock-cache-regression-prove-001_VQx0Mu](../tasks/ccb_debug_haiku_20260228_025547--mcp-remote-direct--mcp_qutebrowser-adblock-cache-regression-prove-001_VQx0Mu.html) | [source](../../../benchmarks/ccb_debug/qutebrowser-adblock-cache-regression-prove-001) | `mcp-remote-direct` | `failed` | 0.000 | 1 | 0.170 |
| [qutebrowser-darkmode-threshold-regression-prove-001](../tasks/ccb_debug_haiku_20260228_025547--baseline-local-direct--qutebrowser-darkmode-threshold-regression-prove-001.html) | [source](../../../benchmarks/ccb_debug/qutebrowser-darkmode-threshold-regression-prove-001) | `baseline-local-direct` | `passed` | 0.500 | 1 | 0.000 |
| [mcp_qutebrowser-darkmode-threshold-regression-prove-001_dIF4Tz](../tasks/ccb_debug_haiku_20260228_025547--mcp-remote-direct--mcp_qutebrowser-darkmode-threshold-regression-prove-001_dIF4Tz.html) | [source](../../../benchmarks/ccb_debug/qutebrowser-darkmode-threshold-regression-prove-001) | `mcp-remote-direct` | `failed` | 0.000 | 1 | 0.305 |
| [qutebrowser-hsv-color-regression-prove-001](../tasks/ccb_debug_haiku_20260228_025547--baseline-local-direct--qutebrowser-hsv-color-regression-prove-001.html) | [source](../../../benchmarks/ccb_debug/qutebrowser-hsv-color-regression-prove-001) | `baseline-local-direct` | `passed` | 0.500 | 1 | 0.000 |
| [mcp_qutebrowser-hsv-color-regression-prove-001_CHxVCm](../tasks/ccb_debug_haiku_20260228_025547--mcp-remote-direct--mcp_qutebrowser-hsv-color-regression-prove-001_CHxVCm.html) | [source](../../../benchmarks/ccb_debug/qutebrowser-hsv-color-regression-prove-001) | `mcp-remote-direct` | `failed` | 0.000 | 1 | 0.224 |
| [terraform-phantom-update-debug-001](../tasks/debug_haiku_20260301_021540--baseline-local-direct--terraform-phantom-update-debug-001.html) | [source](../../../benchmarks/ccb_debug/terraform-phantom-update-debug-001) | `baseline-local-direct` | `passed` | 0.950 | 4 | 0.000 |
| [sgonly_terraform-phantom-update-debug-001](../tasks/debug_haiku_20260301_021540--mcp-remote-direct--sgonly_terraform-phantom-update-debug-001.html) | [source](../../../benchmarks/ccb_debug/terraform-phantom-update-debug-001) | `mcp-remote-direct` | `passed` | 0.950 | 3 | 0.926 |

## Multi-Run Variance

Tasks with multiple valid runs (22 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| django-admins-migration-audit-001 | [source](../../../benchmarks/ccb_debug/django-admins-migration-audit-001) | `baseline-local-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| django-admins-migration-audit-001 | [source](../../../benchmarks/ccb_debug/django-admins-migration-audit-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| envoy-duplicate-headers-debug-001 | [source](../../../benchmarks/ccb_debug/envoy-duplicate-headers-debug-001) | `baseline-local-direct` | 4 | 0.917 | 0.040 | 0.860, 0.950, 0.920, 0.940 |
| envoy-duplicate-headers-debug-001 | [source](../../../benchmarks/ccb_debug/envoy-duplicate-headers-debug-001) | `mcp-remote-direct` | 3 | 0.857 | 0.076 | 0.890, 0.910, 0.770 |
| grafana-table-panel-regression-001 | [source](../../../benchmarks/ccb_debug/grafana-table-panel-regression-001) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| grafana-table-panel-regression-001 | [source](../../../benchmarks/ccb_debug/grafana-table-panel-regression-001) | `mcp-remote-direct` | 3 | 0.800 | 0.100 | 0.900, 0.700, 0.800 |
| istio-xds-destrul-debug-001 | [source](../../../benchmarks/ccb_debug/istio-xds-destrul-debug-001) | `baseline-local-direct` | 4 | 0.948 | 0.021 | 0.950, 0.970, 0.920, 0.950 |
| istio-xds-destrul-debug-001 | [source](../../../benchmarks/ccb_debug/istio-xds-destrul-debug-001) | `mcp-remote-direct` | 3 | 0.910 | 0.036 | 0.920, 0.870, 0.940 |
| linux-acpi-backlight-fault-001 | [source](../../../benchmarks/ccb_debug/linux-acpi-backlight-fault-001) | `baseline-local-direct` | 5 | 0.860 | 0.313 | 0.300, 1.000, 1.000, 1.000, 1.000 |
| linux-acpi-backlight-fault-001 | [source](../../../benchmarks/ccb_debug/linux-acpi-backlight-fault-001) | `mcp-remote-direct` | 3 | 1.000 | 0.000 | 1.000, 1.000, 1.000 |
| linux-hda-intel-suspend-fault-001 | [source](../../../benchmarks/ccb_debug/linux-hda-intel-suspend-fault-001) | `baseline-local-direct` | 5 | 0.700 | 0.000 | 0.700, 0.700, 0.700, 0.700, 0.700 |
| linux-hda-intel-suspend-fault-001 | [source](../../../benchmarks/ccb_debug/linux-hda-intel-suspend-fault-001) | `mcp-remote-direct` | 3 | 0.700 | 0.000 | 0.700, 0.700, 0.700 |
| linux-iwlwifi-subdevice-fault-001 | [source](../../../benchmarks/ccb_debug/linux-iwlwifi-subdevice-fault-001) | `baseline-local-direct` | 5 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000, 1.000 |
| linux-iwlwifi-subdevice-fault-001 | [source](../../../benchmarks/ccb_debug/linux-iwlwifi-subdevice-fault-001) | `mcp-remote-direct` | 3 | 0.900 | 0.173 | 0.700, 1.000, 1.000 |
| linux-nfs-inode-revalidate-fault-001 | [source](../../../benchmarks/ccb_debug/linux-nfs-inode-revalidate-fault-001) | `baseline-local-direct` | 5 | 0.300 | 0.000 | 0.300, 0.300, 0.300, 0.300, 0.300 |
| linux-nfs-inode-revalidate-fault-001 | [source](../../../benchmarks/ccb_debug/linux-nfs-inode-revalidate-fault-001) | `mcp-remote-direct` | 3 | 0.300 | 0.000 | 0.300, 0.300, 0.300 |
| linux-ssd-trim-timeout-fault-001 | [source](../../../benchmarks/ccb_debug/linux-ssd-trim-timeout-fault-001) | `baseline-local-direct` | 5 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000, 1.000 |
| linux-ssd-trim-timeout-fault-001 | [source](../../../benchmarks/ccb_debug/linux-ssd-trim-timeout-fault-001) | `mcp-remote-direct` | 2 | 1.000 | 0.000 | 1.000, 1.000 |
| prometheus-queue-reshard-debug-001 | [source](../../../benchmarks/ccb_debug/prometheus-queue-reshard-debug-001) | `baseline-local-direct` | 4 | 0.565 | 0.077 | 0.520, 0.620, 0.640, 0.480 |
| prometheus-queue-reshard-debug-001 | [source](../../../benchmarks/ccb_debug/prometheus-queue-reshard-debug-001) | `mcp-remote-direct` | 3 | 0.507 | 0.046 | 0.480, 0.560, 0.480 |
| terraform-phantom-update-debug-001 | [source](../../../benchmarks/ccb_debug/terraform-phantom-update-debug-001) | `baseline-local-direct` | 4 | 0.965 | 0.024 | 1.000, 0.960, 0.950, 0.950 |
| terraform-phantom-update-debug-001 | [source](../../../benchmarks/ccb_debug/terraform-phantom-update-debug-001) | `mcp-remote-direct` | 3 | 0.967 | 0.029 | 0.950, 1.000, 0.950 |
