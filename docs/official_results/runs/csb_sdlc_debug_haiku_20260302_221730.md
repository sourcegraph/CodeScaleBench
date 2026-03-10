# csb_sdlc_debug_haiku_20260302_221730

## baseline-local-direct

- Valid tasks: `9`
- Mean reward: `0.496`
- Pass rate: `0.667`
- Scorer families: `unknown (5), checklist (4)`
- Output contracts: `unknown (5), answer_json_bridge (4)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [istio-xds-destrul-debug-001](../tasks/csb_sdlc_debug_haiku_20260302_221730--baseline-local-direct--istio-xds-destrul-debug-001--6fec1826ab.html) | `failed` | 0.000 | `None` | `-` | `-` | - | - | traj, tx |
| [linux-iwlwifi-subdevice-fault-001](../tasks/csb_sdlc_debug_haiku_20260302_221730--baseline-local-direct--linux-iwlwifi-subdevice-fault-001--17083b838e.html) | `failed` | 0.000 | `None` | `checklist` | `answer_json_bridge` | - | - | traj, tx |
| [terraform-phantom-update-debug-001](../tasks/csb_sdlc_debug_haiku_20260302_221730--baseline-local-direct--terraform-phantom-update-debug-001--9431f9c953.html) | `failed` | 0.000 | `None` | `-` | `-` | - | - | traj, tx |
| [envoy-duplicate-headers-debug-001](../tasks/csb_sdlc_debug_haiku_20260302_221730--baseline-local-direct--envoy-duplicate-headers-debug-001--11d47a1c24.html) | `passed` | 0.940 | `None` | `-` | `-` | 0.000 | 44 | traj, tx |
| [grafana-table-panel-regression-001](../tasks/csb_sdlc_debug_haiku_20260302_221730--baseline-local-direct--grafana-table-panel-regression-001--715ef5cecb.html) | `passed` | 1.000 | `None` | `-` | `-` | 0.000 | 73 | traj, tx |
| [linux-acpi-backlight-fault-001](../tasks/csb_sdlc_debug_haiku_20260302_221730--baseline-local-direct--linux-acpi-backlight-fault-001--cb5df9fcc7.html) | `passed` | 1.000 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 26 | traj, tx |
| [linux-hda-intel-suspend-fault-001](../tasks/csb_sdlc_debug_haiku_20260302_221730--baseline-local-direct--linux-hda-intel-suspend-fault-001--8efd37a3cb.html) | `passed` | 0.700 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 32 | traj, tx |
| [linux-nfs-inode-revalidate-fault-001](../tasks/csb_sdlc_debug_haiku_20260302_221730--baseline-local-direct--linux-nfs-inode-revalidate-fault-001--d5bc295315.html) | `passed` | 0.300 | `None` | `checklist` | `answer_json_bridge` | 0.000 | 104 | traj, tx |
| [prometheus-queue-reshard-debug-001](../tasks/csb_sdlc_debug_haiku_20260302_221730--baseline-local-direct--prometheus-queue-reshard-debug-001--e5fea65501.html) | `passed` | 0.520 | `None` | `-` | `-` | 0.000 | 27 | traj, tx |

## mcp-remote-direct

- Valid tasks: `6`
- Mean reward: `0.825`
- Pass rate: `1.000`
- Scorer families: `unknown (4), checklist (2)`
- Output contracts: `unknown (4), answer_json_bridge (2)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_grafana-table-panel-regression-001_alyqvi](../tasks/csb_sdlc_debug_haiku_20260302_221730--mcp-remote-direct--mcp_grafana-table-panel-regression-001_alyqvi--bb7cb92720.html) | `passed` | 0.900 | `None` | `-` | `-` | 0.968 | 31 | traj, tx |
| [mcp_istio-xds-destrul-debug-001_jqj09p](../tasks/csb_sdlc_debug_haiku_20260302_221730--mcp-remote-direct--mcp_istio-xds-destrul-debug-001_jqj09p--d46fe0347b.html) | `passed` | 0.950 | `None` | `-` | `-` | 0.909 | 22 | traj, tx |
| [mcp_linux-hda-intel-suspend-fault-001_3hex7j](../tasks/csb_sdlc_debug_haiku_20260302_221730--mcp-remote-direct--mcp_linux-hda-intel-suspend-fault-001_3hex7j--4ab8ab6e7d.html) | `passed` | 0.700 | `None` | `checklist` | `answer_json_bridge` | 0.789 | 38 | traj, tx |
| [mcp_linux-iwlwifi-subdevice-fault-001_nkjwuw](../tasks/csb_sdlc_debug_haiku_20260302_221730--mcp-remote-direct--mcp_linux-iwlwifi-subdevice-fault-001_nkjwuw--f423ee5b21.html) | `passed` | 1.000 | `None` | `checklist` | `answer_json_bridge` | 0.560 | 25 | traj, tx |
| [mcp_prometheus-queue-reshard-debug-001_gdo5vy](../tasks/csb_sdlc_debug_haiku_20260302_221730--mcp-remote-direct--mcp_prometheus-queue-reshard-debug-001_gdo5vy--b4f75acd84.html) | `passed` | 0.420 | `None` | `-` | `-` | 0.846 | 26 | traj, tx |
| [mcp_terraform-phantom-update-debug-001_bsmkd1](../tasks/csb_sdlc_debug_haiku_20260302_221730--mcp-remote-direct--mcp_terraform-phantom-update-debug-001_bsmkd1--1923b7c7c1.html) | `passed` | 0.980 | `None` | `-` | `-` | 0.902 | 41 | traj, tx |
