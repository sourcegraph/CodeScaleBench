# Error Catalog

A living catalog of known error patterns encountered in CodeContextBench benchmark runs. Each entry documents the pattern signature, root cause, affected benchmarks, and recommended fix. Use this to quickly diagnose and resolve failures.

Fingerprints are defined in `scripts/status_fingerprints.py` and matched in order (first match wins).

## Summary

| ID | Label | Severity | Auto-retry |
|----|-------|----------|:----------:|
| token_refresh_403 | OAuth token refresh failure | infra | Yes |
| verifier_parse_error | Verifier output parse error | verifier | No |
| api_500 | API 500 server error | api | Yes |
| api_rate_limit | API rate limit / overloaded | api | Yes |
| context_window_exceeded | Context window exceeded | infra | No |
| timeout | Task timeout | task | No |
| mcp_connection | MCP server connection failure | mcp | Yes |
| import_error | Python import error | setup | No |
| docker_compose_fail | Docker/container failure | setup | No |
| permission_denied | Permission denied | infra | No |
| git_error | Git operation failure | setup | No |
| deep_search_polling_only | Deep Search returned polling-only | warning | Yes |
| deep_search_polling_timeout | Deep Search polling timeout (aggregate) | warning | Yes |

---

## token_refresh_403

**Pattern:** Matches `403`, `Forbidden`, `token.*refresh`, `refresh.*token`, or `credentials.*expired` in exception info.

**Root Cause:** OAuth token expired or credentials file is stale. The Claude API rejects requests with a 403 when the token needs refreshing.

**Fix:** Re-authenticate with `claude auth` or check `~/.claude/.credentials.json`. The `ensure_fresh_token` function in `_common.sh` handles automatic refresh with a 30-minute margin.

**Auto-retry:** true

---

## verifier_parse_error

**Pattern:** Matches `verifier.*parse`, `verifier.*json`, `verifier.*decode`, `JSONDecodeError.*verifier`, or `reward.*parse` in exception info.

**Root Cause:** The verifier script produced output that couldn't be parsed as valid JSON. The reward.txt or reward.json file is malformed or missing.

**Fix:** Check verifier script output format; ensure reward.txt/reward.json contains valid JSON with the expected schema.

**Auto-retry:** false

---

## api_500

**Pattern:** Matches `500 Internal Server Error`, `api.*500`, or `server.*error.*5xx` in exception info.

**Root Cause:** Transient server-side error from the Claude API or Sourcegraph API.

**Fix:** Retry the task. If persistent, check the API status page for outages.

**Auto-retry:** true

---

## api_rate_limit

**Pattern:** Matches `rate limit`, `429`, `too many requests`, `throttl`, or `overloaded` in exception info.

**Root Cause:** Too many concurrent API requests exceeded account rate limits or the API is overloaded.

**Fix:** Reduce parallelism (lower PARALLEL_JOBS) or wait before retrying. Check account quotas.

**Auto-retry:** true

---

## context_window_exceeded

**Pattern:** Matches `conversation is too long`, `context_window`, `context window`, `max_tokens exceeded`, `maximum context length`, or `prompt is too long` in exception info.

**Root Cause:** The task required more context than the model's maximum window. Common in large-codebase tasks like TAC find-in-codebase (5-12M tokens) and CrossRepo API upgrades.

**Fix:** Not a task failure — classify as infrastructure limitation. Consider tasks that require less context, or use MCP tools to reduce context usage.

**Auto-retry:** false

---

## timeout

**Pattern:** Matches `timeout`, `timed out`, `deadline exceeded`, `SIGTERM`, or `killed.*signal` in exception info.

**Root Cause:** The task exceeded its configured time limit (`time_limit_sec` in task.toml or `timeout_hours` in the run config).

**Fix:** Consider increasing timeout_hours or simplifying the task. Check if the agent is stuck in a loop.

**Auto-retry:** false

---

## mcp_connection

**Pattern:** Matches `mcp.*connect`, `mcp.*refused`, `mcp.*unavailable`, `mcp.*error`, or `sourcegraph.*connect/error/fail` in exception info.

**Root Cause:** The MCP server (Sourcegraph) is unreachable or returned a connection error. Can be caused by network issues, server downtime, or misconfigured MCP settings.

**Fix:** Check that the MCP server is running and accessible. Verify MCP config in the task setup.

**Auto-retry:** true

---

## import_error

**Pattern:** Matches `ImportError`, `ModuleNotFoundError`, `No module named`, or `cannot import` in exception info.

**Root Cause:** A Python dependency is missing from the Docker image. The Dockerfile or requirements.txt is incomplete.

**Fix:** Update the Dockerfile or requirements.txt to include the missing dependency, then rebuild the image.

**Auto-retry:** false

---

## docker_compose_fail

**Pattern:** Matches `docker.*compose/build/pull.*fail`, `container.*exit/crash/fail`, or `OOMKill` in exception info.

**Root Cause:** Docker image build failure, container crash, or out-of-memory kill. Can be caused by missing base images, insufficient disk space, or memory limits.

**Fix:** Check Docker image availability, disk space, and memory limits. For OOMKill, increase container memory allocation.

**Auto-retry:** false

---

## permission_denied

**Pattern:** Matches `permission denied`, `EACCES`, or `Operation not permitted` in exception info.

**Root Cause:** File or directory permission issues in the task workspace. Common when files are owned by a different user (e.g., ubuntu:ubuntu in Docker).

**Fix:** Check file/directory permissions in the task workspace. May need `chmod`/`chown` in the Dockerfile.

**Auto-retry:** false

---

## git_error

**Pattern:** Matches `fatal:.*git`, `git.*clone/checkout/pull.*fail`, or `repository not found` in exception info.

**Root Cause:** A git operation failed — usually a clone, checkout, or pull. Can be caused by network issues, invalid repo URLs, or missing credentials for private repos.

**Fix:** Check repository URL and network access. Verify git credentials if the repo is private.

**Auto-retry:** false

---

## deep_search_polling_only

**Pattern:** Matches `Poll for results using sg_deepsearch_read` in session/trajectory content (not exception_info).

**Root Cause:** The agent called `sg_deepsearch` and received an async polling link, but `sg_deepsearch_read` only returned the polling message instead of actual results. The agent didn't retry enough times for Deep Search to complete.

**Fix:** Deep Search did not return results within the polling window. The run may have degraded quality. Rerun after the preamble retry fix is applied.

**Auto-retry:** true

> **Note:** This fingerprint matches trajectory/session content, not exception_info. The current `fingerprint_error()` function won't detect it. It is included in `status_fingerprints.py` for use by future trajectory-scanning tools.

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
