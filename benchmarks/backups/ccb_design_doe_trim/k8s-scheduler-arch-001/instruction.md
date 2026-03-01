# big-code-k8s-arch-001: Kubernetes Scheduler Architecture

## Task

Explain the Kubernetes scheduler architecture and how a Pod gets assigned to a Node. Trace the complete scheduling pipeline from when a Pod enters the scheduling queue to when it is bound to a Node, including the plugin framework, extension points, and the two-phase (scheduling cycle + binding cycle) design.

## Context

- **Repository**: kubernetes/kubernetes (Go, ~2.5M LOC)
- **Category**: Architectural Understanding
- **Difficulty**: hard
- **Subsystem Focus**: pkg/scheduler/ — the kube-scheduler component

## Requirements

1. Identify all files involved in the scheduler subsystem (scheduler core, framework, queue, cache, plugins)
2. Trace the dependency chain from the main scheduling loop through the scheduling cycle and binding cycle
3. Document the plugin framework architecture (extension points: PreFilter, Filter, Score, Reserve, Permit, Bind)
4. Explain how the SchedulingQueue, Cache, and CycleState interact during a scheduling cycle

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```
## Files Examined
- path/to/file1.ext — role in architecture
- path/to/file2.ext — role in architecture
...

## Dependency Chain
1. Entry point: path/to/entry.ext
2. Calls: path/to/next.ext (via function/method name)
3. Delegates to: path/to/impl.ext
...

## Analysis
[Detailed architectural analysis including:
- Design patterns identified
- Component responsibilities
- Data flow description
- Interface contracts between components]

## Summary
[Concise 2-3 sentence summary answering the task question]
```

## Evaluation Criteria

- File recall: Did you find the correct set of architecturally relevant files?
- Dependency accuracy: Did you trace the correct dependency/call chain?
- Architectural coherence: Did you correctly identify the design patterns and component relationships?
