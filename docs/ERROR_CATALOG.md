# Error Catalog

A living catalog of known error patterns encountered in CodeContextBench benchmark runs. Each entry documents the pattern signature, root cause, affected benchmarks, and recommended fix. Use this to quickly diagnose and resolve failures.

---

## deep_search_polling_timeout

**Pattern:** `sg_deepsearch_read` returns a polling link (`{"link":"...","note":"Poll for results using sg_deepsearch_read..."}`) instead of actual semantic analysis results. The agent polls 1-2 times then gives up.

**Root Cause:** Deep Search is asynchronous, typically taking 50-300+ seconds to complete on the Sourcegraph backend. The agent polls at ~53-second intervals but only attempts 1-2 reads before moving on. 70.1% of all Deep Search calls (96/137) returned polling-only responses. At the task level, 38% of tasks (23/60) that invoked Deep Search never received useful results during the entire execution.

**Affected Benchmarks:**

| Benchmark | Tasks with DS | Got Results | Never Got Results | Success Rate |
|-----------|:------------:|:-----------:|:-----------------:|:------------:|
| K8s Docs | 5 | 2 | 3 | 40% |
| PyTorch | 12 | 6 | 6 | 50% |
| SWE-bench Pro | 43 | 29 | 14 | 67% |
| **Total** | **60** | **37** | **23** | **62%** |

**Fix:** SG_full preamble updated in `claude_baseline_agent.py` to instruct the agent: "After calling sg_deepsearch, call sg_deepsearch_read at least 3-5 times with 10-15 second waits between attempts. Deep Search is asynchronous and typically takes 50-300 seconds." Reruns with the updated preamble should resolve the issue.

**Auto-retry:** true
