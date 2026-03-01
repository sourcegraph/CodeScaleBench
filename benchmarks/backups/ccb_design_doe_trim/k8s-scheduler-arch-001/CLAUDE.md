# big-code-k8s-arch-001: Kubernetes Scheduler Architecture

This repository is large (~2.5M LOC). Use comprehensive search strategies for broad architectural queries rather than narrow, single-directory scopes.

## Task Type: Architectural Understanding

Your goal is to analyze and explain the architecture of the Kubernetes scheduler. Focus on:

1. **Component identification**: Find all major components in pkg/scheduler/ (scheduler core, framework, queue, cache, plugins)
2. **Dependency mapping**: Trace how ScheduleOne triggers the scheduling cycle and binding cycle
3. **Design pattern recognition**: Plugin framework with extension points, two-phase async design, optimistic assume-based cache
4. **Interface boundaries**: Framework interface, Plugin interfaces, SchedulingQueue interface, Cache interface

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — role in the architecture

## Dependency Chain
1. path/to/core.ext (foundational types/interfaces)
2. path/to/impl.ext (implementation layer)
3. path/to/integration.ext (integration/wiring layer)

## Analysis
[Your architectural analysis]
```

## Search Strategy

- Start with `pkg/scheduler/scheduler.go` (main entry) and `pkg/scheduler/schedule_one.go` (core loop)
- Explore `pkg/scheduler/framework/` for the plugin framework interfaces and runtime
- Check `pkg/scheduler/backend/queue/` and `pkg/scheduler/backend/cache/` for infrastructure
- Use `find_references` to trace how components connect
- Use `go_to_definition` to understand interface implementations
