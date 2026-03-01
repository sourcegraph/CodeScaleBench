# ccb_mcp_security

## Run/Config Summary

| Run | Config | Valid Tasks | Mean Reward | Pass Rate |
|---|---|---:|---:|---:|
| [ccb_mcp_security_haiku_022126](../runs/ccb_mcp_security_haiku_022126.md) | `baseline-local-artifact` | 2 | 0.500 | 1.000 |
| [ccb_mcp_security_haiku_022126](../runs/ccb_mcp_security_haiku_022126.md) | `mcp-remote-artifact` | 2 | 0.821 | 1.000 |
| [ccb_mcp_security_haiku_20260224_181919](../runs/ccb_mcp_security_haiku_20260224_181919.md) | `mcp-remote-artifact` | 4 | 0.777 | 1.000 |
| [ccb_mcp_security_haiku_20260225_011700](../runs/ccb_mcp_security_haiku_20260225_011700.md) | `baseline-local-artifact` | 4 | 0.000 | 0.000 |
| [ccb_mcp_security_haiku_20260226_035617](../runs/ccb_mcp_security_haiku_20260226_035617.md) | `mcp-remote-direct` | 4 | 0.744 | 1.000 |
| [ccb_mcp_security_haiku_20260226_035622_variance](../runs/ccb_mcp_security_haiku_20260226_035622_variance.md) | `mcp-remote-direct` | 4 | 0.578 | 1.000 |
| [ccb_mcp_security_haiku_20260226_035628_variance](../runs/ccb_mcp_security_haiku_20260226_035628_variance.md) | `mcp-remote-direct` | 4 | 0.767 | 1.000 |
| [ccb_mcp_security_haiku_20260226_035633_variance](../runs/ccb_mcp_security_haiku_20260226_035633_variance.md) | `mcp-remote-direct` | 4 | 0.731 | 1.000 |
| [ccb_mcp_security_haiku_20260228_012337](../runs/ccb_mcp_security_haiku_20260228_012337.md) | `mcp-remote-direct` | 5 | 0.690 | 1.000 |
| [ccb_mcp_security_haiku_20260228_020502](../runs/ccb_mcp_security_haiku_20260228_020502.md) | `baseline-local-direct` | 6 | 0.386 | 0.667 |
| [ccb_mcp_security_haiku_20260228_025547](../runs/ccb_mcp_security_haiku_20260228_025547.md) | `mcp-remote-direct` | 4 | 0.811 | 1.000 |
| [ccb_mcp_security_haiku_20260228_123206](../runs/ccb_mcp_security_haiku_20260228_123206.md) | `baseline-local-direct` | 4 | 0.731 | 1.000 |

## Tasks

| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |
|---|---|---|---|---:|---:|---:|
| [ccx-vuln-remed-011](../tasks/ccb_mcp_security_haiku_022126--baseline--ccx-vuln-remed-011.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-011) | `baseline-local-artifact` | `passed` | 0.750 | 1 | 0.000 |
| [ccx-vuln-remed-011](../tasks/ccb_mcp_security_haiku_20260228_020502--baseline-local-direct--ccx-vuln-remed-011.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-011) | `baseline-local-direct` | `failed` | 0.000 | 2 | 0.000 |
| [ccx-vuln-remed-011](../tasks/ccb_mcp_security_haiku_022126--mcp--ccx-vuln-remed-011.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-011) | `mcp-remote-artifact` | `passed` | 1.000 | 1 | 0.971 |
| [mcp_ccx-vuln-remed-011_pzmpsW](../tasks/ccb_mcp_security_haiku_20260228_012337--mcp-remote-direct--mcp_ccx-vuln-remed-011_pzmpsW.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-011) | `mcp-remote-direct` | `passed` | 1.000 | 1 | 0.933 |
| [ccx-vuln-remed-012](../tasks/ccb_mcp_security_haiku_20260228_020502--baseline-local-direct--ccx-vuln-remed-012.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-012) | `baseline-local-direct` | `passed` | 0.400 | 6 | 0.000 |
| [mcp_CCX-vuln-remed-012_6P8wqO](../tasks/ccb_mcp_security_haiku_20260226_035633_variance--mcp-remote-direct--mcp_CCX-vuln-remed-012_6P8wqO.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-012) | `mcp-remote-direct` | `passed` | 0.563 | 5 | 0.973 |
| [mcp_CCX-vuln-remed-012_6fFmnM](../tasks/ccb_mcp_security_haiku_20260226_035628_variance--mcp-remote-direct--mcp_CCX-vuln-remed-012_6fFmnM.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-012) | `mcp-remote-direct` | `passed` | 0.533 | 5 | 0.909 |
| [mcp_CCX-vuln-remed-012_9JwGrW](../tasks/ccb_mcp_security_haiku_20260226_035622_variance--mcp-remote-direct--mcp_CCX-vuln-remed-012_9JwGrW.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-012) | `mcp-remote-direct` | `passed` | 0.397 | 5 | 0.889 |
| [mcp_CCX-vuln-remed-012_KDiwHr](../tasks/ccb_mcp_security_haiku_20260228_012337--mcp-remote-direct--mcp_CCX-vuln-remed-012_KDiwHr.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-012) | `mcp-remote-direct` | `passed` | 0.500 | 5 | 0.939 |
| [mcp_CCX-vuln-remed-012_lrLTYc](../tasks/ccb_mcp_security_haiku_20260226_035617--mcp-remote-direct--mcp_CCX-vuln-remed-012_lrLTYc.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-012) | `mcp-remote-direct` | `passed` | 0.463 | 5 | 0.923 |
| [ccx-vuln-remed-013](../tasks/ccb_mcp_security_haiku_20260228_020502--baseline-local-direct--ccx-vuln-remed-013.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-013) | `baseline-local-direct` | `passed` | 0.083 | 4 | 0.000 |
| [mcp_CCX-vuln-remed-013_JtNIGY](../tasks/ccb_mcp_security_haiku_20260226_035633_variance--mcp-remote-direct--mcp_CCX-vuln-remed-013_JtNIGY.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-013) | `mcp-remote-direct` | `passed` | 0.624 | 5 | 0.958 |
| [mcp_CCX-vuln-remed-013_LoBHLI](../tasks/ccb_mcp_security_haiku_20260226_035628_variance--mcp-remote-direct--mcp_CCX-vuln-remed-013_LoBHLI.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-013) | `mcp-remote-direct` | `passed` | 0.749 | 5 | 0.963 |
| [mcp_CCX-vuln-remed-013_Kmqlzc](../tasks/ccb_mcp_security_haiku_20260226_035622_variance--mcp-remote-direct--mcp_CCX-vuln-remed-013_Kmqlzc.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-013) | `mcp-remote-direct` | `passed` | 0.105 | 5 | 0.971 |
| [mcp_CCX-vuln-remed-013_exPwzs](../tasks/ccb_mcp_security_haiku_20260228_012337--mcp-remote-direct--mcp_CCX-vuln-remed-013_exPwzs.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-013) | `mcp-remote-direct` | `passed` | 0.742 | 5 | 0.938 |
| [mcp_CCX-vuln-remed-013_WOkHxn](../tasks/ccb_mcp_security_haiku_20260226_035617--mcp-remote-direct--mcp_CCX-vuln-remed-013_WOkHxn.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-013) | `mcp-remote-direct` | `passed` | 0.705 | 5 | 0.926 |
| [ccx-vuln-remed-014](../tasks/ccb_mcp_security_haiku_022126--baseline--ccx-vuln-remed-014.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-014) | `baseline-local-artifact` | `passed` | 0.250 | 1 | 0.000 |
| [ccx-vuln-remed-014](../tasks/ccb_mcp_security_haiku_20260228_020502--baseline-local-direct--ccx-vuln-remed-014.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-014) | `baseline-local-direct` | `failed` | 0.000 | 2 | 0.000 |
| [ccx-vuln-remed-014](../tasks/ccb_mcp_security_haiku_022126--mcp--ccx-vuln-remed-014.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-014) | `mcp-remote-artifact` | `passed` | 0.643 | 1 | 0.976 |
| [mcp_ccx-vuln-remed-014_mOWOl9](../tasks/ccb_mcp_security_haiku_20260228_012337--mcp-remote-direct--mcp_ccx-vuln-remed-014_mOWOl9.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-014) | `mcp-remote-direct` | `passed` | 0.500 | 1 | 0.971 |
| [ccx-vuln-remed-105](../tasks/ccb_mcp_security_haiku_20260228_020502--baseline-local-direct--ccx-vuln-remed-105.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-105) | `baseline-local-direct` | `passed` | 0.833 | 4 | 0.000 |
| [mcp_CCX-vuln-remed-105_JZsxbp](../tasks/ccb_mcp_security_haiku_20260226_035633_variance--mcp-remote-direct--mcp_CCX-vuln-remed-105_JZsxbp.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-105) | `mcp-remote-direct` | `passed` | 0.737 | 5 | 0.909 |
| [mcp_CCX-vuln-remed-105_aQMP88](../tasks/ccb_mcp_security_haiku_20260226_035628_variance--mcp-remote-direct--mcp_CCX-vuln-remed-105_aQMP88.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-105) | `mcp-remote-direct` | `passed` | 0.784 | 5 | 0.971 |
| [mcp_CCX-vuln-remed-105_79Rpkl](../tasks/ccb_mcp_security_haiku_20260226_035622_variance--mcp-remote-direct--mcp_CCX-vuln-remed-105_79Rpkl.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-105) | `mcp-remote-direct` | `passed` | 0.809 | 5 | 0.952 |
| [mcp_CCX-vuln-remed-105_mBXXD3](../tasks/ccb_mcp_security_haiku_20260228_012337--mcp-remote-direct--mcp_CCX-vuln-remed-105_mBXXD3.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-105) | `mcp-remote-direct` | `passed` | 0.709 | 5 | 0.917 |
| [mcp_CCX-vuln-remed-105_1RoC5v](../tasks/ccb_mcp_security_haiku_20260226_035617--mcp-remote-direct--mcp_CCX-vuln-remed-105_1RoC5v.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-105) | `mcp-remote-direct` | `passed` | 0.809 | 5 | 0.958 |
| [ccx-vuln-remed-111](../tasks/ccb_mcp_security_haiku_20260228_020502--baseline-local-direct--ccx-vuln-remed-111.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-111) | `baseline-local-direct` | `passed` | 1.000 | 4 | 0.000 |
| [mcp_CCX-vuln-remed-111_gpcSkd](../tasks/ccb_mcp_security_haiku_20260226_035633_variance--mcp-remote-direct--mcp_CCX-vuln-remed-111_gpcSkd.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-111) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.846 |
| [mcp_CCX-vuln-remed-111_AFyYzp](../tasks/ccb_mcp_security_haiku_20260226_035628_variance--mcp-remote-direct--mcp_CCX-vuln-remed-111_AFyYzp.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-111) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.909 |
| [mcp_CCX-vuln-remed-111_u7rGCx](../tasks/ccb_mcp_security_haiku_20260226_035622_variance--mcp-remote-direct--mcp_CCX-vuln-remed-111_u7rGCx.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-111) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.846 |
| [mcp_CCX-vuln-remed-111_7hdRBX](../tasks/ccb_mcp_security_haiku_20260226_035617--mcp-remote-direct--mcp_CCX-vuln-remed-111_7hdRBX.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-111) | `mcp-remote-direct` | `passed` | 1.000 | 4 | 0.966 |
| [bl_CCX-vuln-remed-126_5Us92F](../tasks/ccb_mcp_security_haiku_20260225_011700--baseline-local-artifact--bl_CCX-vuln-remed-126_5Us92F.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-126) | `baseline-local-artifact` | `failed` | 0.000 | 1 | 0.000 |
| [ccx-vuln-remed-126](../tasks/ccb_mcp_security_haiku_20260228_123206--baseline-local-direct--ccx-vuln-remed-126.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-126) | `baseline-local-direct` | `passed` | 0.771 | 3 | 0.000 |
| [mcp_CCX-vuln-remed-126_HYpbDr](../tasks/ccb_mcp_security_haiku_20260224_181919--mcp-remote-artifact--mcp_CCX-vuln-remed-126_HYpbDr.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-126) | `mcp-remote-artifact` | `passed` | 0.745 | 1 | 0.978 |
| [mcp_CCX-vuln-remed-126_eI5dwX](../tasks/ccb_mcp_security_haiku_20260228_025547--mcp-remote-direct--mcp_CCX-vuln-remed-126_eI5dwX.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-126) | `mcp-remote-direct` | `passed` | 0.734 | 1 | 0.950 |
| [bl_CCX-vuln-remed-130_Zk4x7i](../tasks/ccb_mcp_security_haiku_20260225_011700--baseline-local-artifact--bl_CCX-vuln-remed-130_Zk4x7i.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-130) | `baseline-local-artifact` | `failed` | 0.000 | 1 | 0.000 |
| [ccx-vuln-remed-130](../tasks/ccb_mcp_security_haiku_20260228_123206--baseline-local-direct--ccx-vuln-remed-130.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-130) | `baseline-local-direct` | `passed` | 0.883 | 3 | 0.000 |
| [mcp_CCX-vuln-remed-130_0JULg6](../tasks/ccb_mcp_security_haiku_20260224_181919--mcp-remote-artifact--mcp_CCX-vuln-remed-130_0JULg6.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-130) | `mcp-remote-artifact` | `passed` | 1.000 | 1 | 0.955 |
| [mcp_CCX-vuln-remed-130_qnPGjk](../tasks/ccb_mcp_security_haiku_20260228_025547--mcp-remote-direct--mcp_CCX-vuln-remed-130_qnPGjk.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-130) | `mcp-remote-direct` | `passed` | 0.928 | 1 | 0.944 |
| [bl_CCX-vuln-remed-135_UVjwY5](../tasks/ccb_mcp_security_haiku_20260225_011700--baseline-local-artifact--bl_CCX-vuln-remed-135_UVjwY5.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-135) | `baseline-local-artifact` | `failed` | 0.000 | 1 | 0.000 |
| [ccx-vuln-remed-135](../tasks/ccb_mcp_security_haiku_20260228_123206--baseline-local-direct--ccx-vuln-remed-135.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-135) | `baseline-local-direct` | `passed` | 0.583 | 3 | 0.000 |
| [mcp_CCX-vuln-remed-135_Uueqpt](../tasks/ccb_mcp_security_haiku_20260224_181919--mcp-remote-artifact--mcp_CCX-vuln-remed-135_Uueqpt.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-135) | `mcp-remote-artifact` | `passed` | 0.611 | 1 | 0.929 |
| [mcp_CCX-vuln-remed-135_WZUaS9](../tasks/ccb_mcp_security_haiku_20260228_025547--mcp-remote-direct--mcp_CCX-vuln-remed-135_WZUaS9.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-135) | `mcp-remote-direct` | `passed` | 0.833 | 1 | 0.933 |
| [bl_CCX-vuln-remed-141_Hv3FTI](../tasks/ccb_mcp_security_haiku_20260225_011700--baseline-local-artifact--bl_CCX-vuln-remed-141_Hv3FTI.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-141) | `baseline-local-artifact` | `failed` | 0.000 | 1 | 0.000 |
| [ccx-vuln-remed-141](../tasks/ccb_mcp_security_haiku_20260228_123206--baseline-local-direct--ccx-vuln-remed-141.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-141) | `baseline-local-direct` | `passed` | 0.685 | 3 | 0.000 |
| [mcp_CCX-vuln-remed-141_y0cxyE](../tasks/ccb_mcp_security_haiku_20260224_181919--mcp-remote-artifact--mcp_CCX-vuln-remed-141_y0cxyE.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-141) | `mcp-remote-artifact` | `passed` | 0.750 | 1 | 0.958 |
| [mcp_CCX-vuln-remed-141_I5Vdae](../tasks/ccb_mcp_security_haiku_20260228_025547--mcp-remote-direct--mcp_CCX-vuln-remed-141_I5Vdae.html) | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-141) | `mcp-remote-direct` | `passed` | 0.750 | 1 | 0.958 |

## Multi-Run Variance

Tasks with multiple valid runs (14 task/config pairs).

| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |
|---|---|---|---:|---:|---:|---|
| CCX-vuln-remed-011 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-011) | `baseline-local-direct` | 2 | 0.000 | 0.000 | 0.000, 0.000 |
| CCX-vuln-remed-012 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-012) | `baseline-local-direct` | 6 | 0.466 | 0.081 | 0.433, 0.586, 0.514, 0.367, 0.494, 0.400 |
| CCX-vuln-remed-012 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-012) | `mcp-remote-direct` | 5 | 0.491 | 0.065 | 0.463, 0.563, 0.397, 0.533, 0.500 |
| CCX-vuln-remed-013 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-013) | `baseline-local-direct` | 4 | 0.207 | 0.160 | 0.355, 0.336, 0.056, 0.083 |
| CCX-vuln-remed-013 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-013) | `mcp-remote-direct` | 5 | 0.585 | 0.273 | 0.705, 0.624, 0.105, 0.749, 0.742 |
| CCX-vuln-remed-014 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-014) | `baseline-local-direct` | 2 | 0.000 | 0.000 | 0.000, 0.000 |
| CCX-vuln-remed-105 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-105) | `baseline-local-direct` | 4 | 0.675 | 0.123 | 0.569, 0.709, 0.587, 0.833 |
| CCX-vuln-remed-105 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-105) | `mcp-remote-direct` | 5 | 0.770 | 0.045 | 0.809, 0.737, 0.809, 0.784, 0.709 |
| CCX-vuln-remed-111 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-111) | `baseline-local-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| CCX-vuln-remed-111 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-111) | `mcp-remote-direct` | 4 | 1.000 | 0.000 | 1.000, 1.000, 1.000, 1.000 |
| CCX-vuln-remed-126 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-126) | `baseline-local-direct` | 3 | 0.763 | 0.047 | 0.806, 0.713, 0.771 |
| CCX-vuln-remed-130 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-130) | `baseline-local-direct` | 3 | 0.913 | 0.026 | 0.928, 0.928, 0.883 |
| CCX-vuln-remed-135 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-135) | `baseline-local-direct` | 3 | 0.451 | 0.126 | 0.438, 0.333, 0.583 |
| CCX-vuln-remed-141 | [source](../../../benchmarks/ccb_mcp_security/ccx-vuln-remed-141) | `baseline-local-direct` | 3 | 0.714 | 0.062 | 0.786, 0.672, 0.685 |
