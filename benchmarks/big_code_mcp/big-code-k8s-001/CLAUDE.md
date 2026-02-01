# big-code-k8s-001: NoScheduleNoTraffic Taint Effect

This repository is large. If a search spans more than a narrow, well-defined set of directories, you **MUST** use Sourcegraph MCP search tools:

- ✅ Use `sg_keyword_search`, `sg_nls_search`, or `sg_deepsearch` for broad architectural queries
- ✅ Use MCP to find all references across the codebase quickly
- ✅ Use MCP to understand patterns and conventions at scale
- ❌ Do NOT use local `grep` or `rg` for cross-module searches
- ❌ Local tools only for narrow, single-directory scopes

## Kubernetes Architecture Notes

The NoScheduleNoTraffic taint effect implementation requires understanding:

1. **Taint Effect Constants**: Where effects like NoSchedule, NoExecute are defined
2. **Scheduler Logic**: How pod admission checks taint effects during scheduling
3. **Endpoint Slice Controller**: How service endpoints are updated based on taint effects
4. **Node Controller**: How taint effects affect pod eviction and node lifecycle
5. **Toleration Matching**: How pod tolerations are matched against taint effects
6. **Tests**: How taint effect behavior is validated

Use MCP to find all references to existing taint effects (`NoSchedule`, `NoExecute`) across the codebase—this tells you all locations where you need to add `NoScheduleNoTraffic` support. The Kubernetes codebase is distributed across many packages (scheduler, admission, endpoint, node). Local tools would require multiple searches and might miss critical locations.
