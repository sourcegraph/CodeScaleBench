# ccb_debug_haiku_20260221_203204__pre_sgenv_fix

## baseline-local-artifact

- Valid tasks: `5`
- Mean reward: `0.500`
- Pass rate: `1.000`
- Scorer families: `unknown (5)`
- Output contracts: `unknown (5)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [ansible-vault-regression-prove-001](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--baseline-local-artifact--ansible-vault-regression-prove-001--bd354c5824.html) | `passed` | 0.500 | `True` | `-` | `-` | 0.000 | 21 | traj, tx |
| [flipt-cache-regression-prove-001](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--baseline-local-artifact--flipt-cache-regression-prove-001--14a77200eb.html) | `passed` | 0.500 | `True` | `-` | `-` | 0.000 | 26 | traj, tx |
| [qutebrowser-bookmark-regression-prove-001](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--baseline-local-artifact--qutebrowser-bookmark-regression-prove-001--0225a478e5.html) | `passed` | 0.500 | `True` | `-` | `-` | 0.000 | 23 | traj, tx |
| [qutebrowser-download-regression-prove-001](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--baseline-local-artifact--qutebrowser-download-regression-prove-001--978a5a4ef5.html) | `passed` | 0.500 | `True` | `-` | `-` | 0.000 | 31 | traj, tx |
| [qutebrowser-tab-regression-prove-001](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--baseline-local-artifact--qutebrowser-tab-regression-prove-001--a05d99e59c.html) | `passed` | 0.500 | `True` | `-` | `-` | 0.000 | 30 | traj, tx |

## mcp-remote-artifact

- Valid tasks: `19`
- Mean reward: `0.563`
- Pass rate: `0.842`
- Scorer families: `unknown (12), checklist (4), find_and_prove (3)`
- Output contracts: `unknown (12), answer_json_bridge (7)`

| Task | Status | Reward | Passed | Scorer Family | Output Contract | MCP Ratio | Tool Calls | Trace |
|---|---|---:|---|---|---|---:|---:|---|
| [mcp_envoy-duplicate-headers-debug-001_69IMsJ](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_envoy-duplicate-headers-debug-001_69IMsJ--813bd5ee9a.html) | `failed` | 0.000 | `False` | `-` | `-` | - | - | tx |
| [mcp_istio-xds-destrul-debug-001_8WtggJ](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_istio-xds-destrul-debug-001_8WtggJ--e997cea237.html) | `failed` | 0.000 | `False` | `-` | `-` | - | - | tx |
| [mcp_terraform-phantom-update-debug-001_77ZQaN](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_terraform-phantom-update-debug-001_77ZQaN--5b8e0af22d.html) | `failed` | 0.000 | `False` | `-` | `-` | - | - | tx |
| [mcp_ansible-vault-regression-prove-001_QEcoty](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_ansible-vault-regression-prove-001_QEcoty--e62a02a947.html) | `passed` | 0.500 | `True` | `-` | `-` | 0.188 | 101 | traj, tx |
| [mcp_django-admins-migration-audit-001_yrorHk](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_django-admins-migration-audit-001_yrorHk--e298ec1dd4.html) | `passed` | 0.950 | `True` | `-` | `-` | 0.960 | 25 | traj, tx |
| [mcp_flipt-cache-regression-prove-001_qKZ9ep](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_flipt-cache-regression-prove-001_qKZ9ep--1e81541162.html) | `passed` | 1.000 | `True` | `-` | `-` | 0.460 | 50 | traj, tx |
| [mcp_grafana-table-panel-regression-001_54kJkG](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_grafana-table-panel-regression-001_54kJkG--c338f2d920.html) | `passed` | 0.900 | `True` | `-` | `-` | 0.867 | 15 | traj, tx |
| [mcp_linux-acpi-backlight-fault-001_V6jsOp](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_linux-acpi-backlight-fault-001_V6jsOp--b746a3a082.html) | `passed` | 1.000 | `True` | `checklist` | `answer_json_bridge` | 0.583 | 12 | traj, tx |
| [mcp_linux-hda-intel-suspend-fault-001_HnkE0w](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_linux-hda-intel-suspend-fault-001_HnkE0w--eb5da1276f.html) | `passed` | 0.700 | `True` | `checklist` | `answer_json_bridge` | 0.867 | 30 | traj, tx |
| [mcp_linux-iwlwifi-subdevice-fault-001_xuzTAt](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_linux-iwlwifi-subdevice-fault-001_xuzTAt--026bdb933e.html) | `passed` | 0.700 | `True` | `checklist` | `answer_json_bridge` | 0.852 | 27 | traj, tx |
| [mcp_linux-nfs-inode-revalidate-fault-001_1bBfke](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_linux-nfs-inode-revalidate-fault-001_1bBfke--8b0c0d6426.html) | `passed` | 0.300 | `True` | `checklist` | `answer_json_bridge` | 0.852 | 27 | traj, tx |
| [mcp_linux-ssd-trim-timeout-fault-001_sgIFrN](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_linux-ssd-trim-timeout-fault-001_sgIFrN--db7d1b8148.html) | `passed` | 0.700 | `True` | `-` | `-` | 0.822 | 45 | traj, tx |
| [mcp_prometheus-queue-reshard-debug-001_WNWvRu](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_prometheus-queue-reshard-debug-001_WNWvRu--e9fb39ae66.html) | `passed` | 0.940 | `True` | `-` | `-` | 0.895 | 19 | traj, tx |
| [mcp_qutebrowser-bookmark-regression-prove-001_FgqLe3](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_qutebrowser-bookmark-regression-prove-001_FgqLe3--08874d27f5.html) | `passed` | 0.500 | `True` | `-` | `-` | 0.333 | 42 | traj, tx |
| [mcp_qutebrowser-tab-regression-prove-001_1HzfGj](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_qutebrowser-tab-regression-prove-001_1HzfGj--be3ae4d47d.html) | `passed` | 0.500 | `True` | `-` | `-` | 0.265 | 34 | traj, tx |
| [mcp_qutebrowser-url-regression-prove-001_9uoJfC](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_qutebrowser-url-regression-prove-001_9uoJfC--fb6d1561a3.html) | `passed` | 0.500 | `True` | `find_and_prove` | `answer_json_bridge` | 0.455 | 22 | traj, tx |
| [mcp_teleport-ssh-regression-prove-001_ZvMNzX](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_teleport-ssh-regression-prove-001_ZvMNzX--20190d61c0.html) | `passed` | 0.500 | `True` | `find_and_prove` | `answer_json_bridge` | 0.568 | 37 | traj, tx |
| [mcp_tutanota-search-regression-prove-001_QHVlFf](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_tutanota-search-regression-prove-001_QHVlFf--114fd3f0ef.html) | `passed` | 0.500 | `True` | `-` | `-` | 0.525 | 40 | traj, tx |
| [mcp_vuls-oval-regression-prove-001_rzeK6V](../tasks/ccb_debug_haiku_20260221_203204__pre_sgenv_fix--mcp-remote-artifact--mcp_vuls-oval-regression-prove-001_rzeK6V--0296b0e28a.html) | `passed` | 0.500 | `True` | `find_and_prove` | `answer_json_bridge` | 0.469 | 32 | traj, tx |
