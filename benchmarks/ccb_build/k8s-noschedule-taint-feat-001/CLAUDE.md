# big-code-k8s-001: NoScheduleNoTraffic Taint Effect

This repository is large. Use comprehensive search strategies for broad architectural queries rather than narrow, single-directory scopes.

## Kubernetes Architecture Notes

The NoScheduleNoTraffic taint effect implementation requires understanding:

1. **Taint Effect Constants**: Where effects like NoSchedule, NoExecute are defined
2. **Scheduler Logic**: How pod admission checks taint effects during scheduling
3. **Endpoint Slice Controller**: How service endpoints are updated based on taint effects
4. **Node Controller**: How taint effects affect pod eviction and node lifecycle
5. **Toleration Matching**: How pod tolerations are matched against taint effects
6. **Tests**: How taint effect behavior is validated

Find all references to existing taint effects (`NoSchedule`, `NoExecute`) across the codebase—this tells you all locations where you need to add `NoScheduleNoTraffic` support. The Kubernetes codebase is distributed across many packages (scheduler, admission, endpoint, node).
