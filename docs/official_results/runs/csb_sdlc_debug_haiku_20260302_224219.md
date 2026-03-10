# csb_sdlc_debug_haiku_20260302_224219

## baseline-local-direct

- Valid tasks: `5`
- Mean reward: `0.836`
- Pass rate: `1.000`
- Scorer families: `unknown (5)`
- Output contracts: `unknown (5)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [envoy-duplicate-headers-debug-001](../tasks/csb_sdlc_debug_haiku_20260302_224219--baseline-local-direct--envoy-duplicate-headers-debug-001--b435280e79.html) | `passed` | 0.940 | `True` | `-` | `-` | 0.000 | 41 | traj, tx |
| [grafana-table-panel-regression-001](../tasks/csb_sdlc_debug_haiku_20260302_224219--baseline-local-direct--grafana-table-panel-regression-001--cd616e86e4.html) | `passed` | 0.900 | `True` | `-` | `-` | 0.000 | 18 | traj, tx |
| [istio-xds-destrul-debug-001](../tasks/csb_sdlc_debug_haiku_20260302_224219--baseline-local-direct--istio-xds-destrul-debug-001--65e34f58d9.html) | `passed` | 0.970 | `True` | `-` | `-` | 0.000 | 31 | traj, tx |
| [prometheus-queue-reshard-debug-001](../tasks/csb_sdlc_debug_haiku_20260302_224219--baseline-local-direct--prometheus-queue-reshard-debug-001--2576a18125.html) | `passed` | 0.420 | `True` | `-` | `-` | 0.000 | 23 | traj, tx |
| [terraform-phantom-update-debug-001](../tasks/csb_sdlc_debug_haiku_20260302_224219--baseline-local-direct--terraform-phantom-update-debug-001--d2fa620ae4.html) | `passed` | 0.950 | `True` | `-` | `-` | 0.000 | 34 | traj, tx |

## mcp-remote-direct

- Valid tasks: `7`
- Mean reward: `0.759`
- Pass rate: `1.000`
- Scorer families: `unknown (4), checklist (3)`
- Output contracts: `unknown (4), answer_json_bridge (3)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_envoy-duplicate-headers-debug-001_jafclc](../tasks/csb_sdlc_debug_haiku_20260302_224219--mcp-remote-direct--mcp_envoy-duplicate-headers-debug-001_jafclc--c4b163c80c.html) | `passed` | 0.940 | `True` | `-` | `-` | 0.975 | 40 | traj, tx |
| [mcp_istio-xds-destrul-debug-001_md9xry](../tasks/csb_sdlc_debug_haiku_20260302_224219--mcp-remote-direct--mcp_istio-xds-destrul-debug-001_md9xry--5745f09953.html) | `passed` | 0.950 | `True` | `-` | `-` | 0.857 | 28 | traj, tx |
| [mcp_linux-acpi-backlight-fault-001_zgbt7k](../tasks/csb_sdlc_debug_haiku_20260302_224219--mcp-remote-direct--mcp_linux-acpi-backlight-fault-001_zgbt7k--9022b9da3f.html) | `passed` | 0.700 | `True` | `checklist` | `answer_json_bridge` | 0.742 | 31 | traj, tx |
| [mcp_linux-iwlwifi-subdevice-fault-001_zn5mm8](../tasks/csb_sdlc_debug_haiku_20260302_224219--mcp-remote-direct--mcp_linux-iwlwifi-subdevice-fault-001_zn5mm8--ab1440b822.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.722 | 18 | traj, tx |
| [mcp_linux-nfs-inode-revalidate-fault-001_choefq](../tasks/csb_sdlc_debug_haiku_20260302_224219--mcp-remote-direct--mcp_linux-nfs-inode-revalidate-fault-001_choefq--01e1425f89.html) | `passed` | 0.300 | `True` | `checklist` | `answer_json_bridge` | 0.815 | 27 | traj, tx |
| [mcp_prometheus-queue-reshard-debug-001_deif1d](../tasks/csb_sdlc_debug_haiku_20260302_224219--mcp-remote-direct--mcp_prometheus-queue-reshard-debug-001_deif1d--d656b41a8f.html) | `passed` | 0.420 | `True` | `-` | `-` | 0.810 | 21 | traj, tx |
| [mcp_terraform-phantom-update-debug-001_76d9jd](../tasks/csb_sdlc_debug_haiku_20260302_224219--mcp-remote-direct--mcp_terraform-phantom-update-debug-001_76d9jd--93976bd015.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.853 | 34 | traj, tx |
