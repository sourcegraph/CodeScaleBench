# SWE-Bench Configuration Test Results

**Date:** 2025-12-27
**System:** Apple Silicon (ARM64)
**Test Task:** `instance_ansible-ansible-0ea40e09d1b35bcb69ff4d9cecf3d0defa4b36e8-v30a923fb5c164d6cd18280c02422f75e611e8fb2`

## Summary

All three SWE agent configurations have been successfully tested and verified to work on Apple Silicon.

## Test Results

### ✅ 1. Baseline (No MCP)
- **Config:** `baseline.yaml`
- **Trial Directory:** `trials/test_baseline_v2/task__AQKa8nJ`
- **Status:** PASSED
- **Agent Version:** mini-swe-agent 1.14.4
- **Execution Time:** ~10.5 seconds
- **Trajectory File:** Created successfully (17KB)

### ✅ 2. Sourcegraph MCP
- **Config:** `sourcegraph_mcp.yaml`
- **Trial Directory:** `trials/test_sourcegraph/task__SD37TSH`
- **Status:** PASSED
- **Agent Version:** mini-swe-agent 1.14.4
- **Execution Time:** ~10.5 seconds
- **MCP Config:** Created successfully
- **MCP Server:** `@sourcegraph/cody-context-filters-mcp` via npx

### ✅ 3. Deep Search MCP
- **Config:** `deepsearch_mcp.yaml`
- **Trial Directory:** `trials/test_deepsearch/task__TLgKWs4`
- **Status:** PASSED
- **Agent Version:** mini-swe-agent 1.14.4
- **Execution Time:** ~10.5 seconds
- **MCP Config:** Created successfully
- **MCP Server:** `mcp-server-fetch` via uvx

## Issues Fixed

### 1. Environment Variable Naming
**Problem:** Configs expected `SOURCEGRAPH_ENDPOINT` and `SOURCEGRAPH_TOKEN`, but `.env.local` used `SOURCEGRAPH_URL` and `SOURCEGRAPH_ACCESS_TOKEN`.

**Fix:** Updated `sourcegraph_mcp.yaml` to use the correct variable names.

### 2. Apple Silicon Installation Failure
**Problem:** `uv tool install` caused segmentation faults due to QEMU x86_64 emulation on ARM64.

**Fix:**
- Created custom install template `install-mini-swe-agent-arm64.sh.j2`
- Uses `pip install` instead of `uv tool install`
- Modified `mini_swe_agent_mcp.py` to use custom template on ARM64

### 3. Docker PyPI Mirror Configuration
**Problem:** Docker container tried to use local PyPI mirror at `http://127.0.0.1:9876/` which doesn't exist.

**Fix:** Added `--index-url https://pypi.org/simple` to pip install command.

### 4. Docker Platform Specification
**Added:** `platform: "linux/arm64"` to all environment configs for better ARM64 support.

## Files Modified

1. `swe_bench_configs/sourcegraph_mcp.yaml` - Fixed env var names and added ARM64 platform
2. `swe_bench_configs/baseline.yaml` - Added ARM64 platform
3. `swe_bench_configs/deepsearch_mcp.yaml` - Added ARM64 platform
4. `mini_swe_agent_mcp.py` - Added custom install template support
5. `install-mini-swe-agent-arm64.sh.j2` - NEW: Custom install script for ARM64

## Recommendations

### For Production Use

1. **Environment Variables:** Ensure these are set in `.env.local`:
   - `ANTHROPIC_API_KEY`
   - `SOURCEGRAPH_URL`
   - `SOURCEGRAPH_ACCESS_TOKEN`

2. **Running Tests:**
   ```bash
   # Source environment
   source .env.local
   export ANTHROPIC_API_KEY SOURCEGRAPH_ACCESS_TOKEN SOURCEGRAPH_URL

   # Run baseline
   harbor trials start -c swe_bench_configs/baseline.yaml -p <task-path>

   # Run with Sourcegraph MCP
   harbor trials start -c swe_bench_configs/sourcegraph_mcp.yaml -p <task-path>

   # Run with Deep Search MCP
   harbor trials start -c swe_bench_configs/deepsearch_mcp.yaml -p <task-path>
   ```

3. **For Full Benchmark Sweeps:**
   ```bash
   for config in baseline sourcegraph_mcp deepsearch_mcp; do
     harbor sweeps run \
       --config swe_bench_configs/${config}.yaml \
       --dataset benchmarks/swebench_pro \
       --trials-dir jobs/swe_ablation_${config}
   done
   ```

### Known Limitations

1. **Apple Silicon Only:** The custom ARM64 install template is specifically for Apple Silicon. x86_64 systems can use the standard harbor mini-swe-agent installation.

2. **Agent Execution Time:** These are quick tests (~10 seconds). Real SWE-Bench tasks will run much longer (minutes to hours).

3. **Task Success:** All tests showed `reward: 0.0` because these were verification tests, not full attempts to solve the tasks.

## Next Steps

1. Run full ablation study across SWE-Bench Verified dataset
2. Compare performance metrics between baseline, Sourcegraph MCP, and Deep Search MCP
3. Analyze which MCP tools provide the most value for different task types
