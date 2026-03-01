# Task: Rename SchedulerProfile to SchedulingProfile

## Objective
Rename `SchedulerProfile` to `SchedulingProfile` in the Kubernetes scheduler
to follow the API naming convention (action-noun pattern).

## Requirements

1. **Rename the type** (likely in scheduler config or profile package):
   - `type SchedulerProfile struct` → `type SchedulingProfile struct`

2. **Update all references** (15+ call sites):
   - `pkg/scheduler/` — scheduler internals
   - `staging/src/k8s.io/kube-scheduler/` — API types
   - Config and profile loading code
   - Test files

3. **Update constructor functions** and factory methods

## Key Reference Files
- `pkg/scheduler/profile/profile.go` — profile definition
- `pkg/scheduler/scheduler.go` — uses profiles
- `staging/src/k8s.io/kube-scheduler/config/` — API config types

## Success Criteria
- `SchedulerProfile` no longer used as type name
- `SchedulingProfile` used instead
- 80%+ of references updated
