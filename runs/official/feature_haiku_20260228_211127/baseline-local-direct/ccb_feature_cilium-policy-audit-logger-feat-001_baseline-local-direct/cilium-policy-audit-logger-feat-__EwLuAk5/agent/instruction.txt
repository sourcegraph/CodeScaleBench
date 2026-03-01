# Task: Implement PolicyAuditLogger for Cilium

## Objective
Create a `PolicyAuditLogger` in `pkg/policy/` that provides structured logging of policy
evaluation decisions for audit and debugging purposes.

## Requirements

1. **Create `pkg/policy/audit_logger.go`** with:
   - `PolicyAuditLogger` struct with configurable log level and output
   - `LogDecision(identity, policy, verdict, reason)` method
   - `LogEvaluation(ctx, policyKey, selectorCache, result)` method
   - Integration with Cilium's existing logging framework (logrus/scopedLog)
   - Support for JSON-structured audit log output

2. **Create `pkg/policy/audit_logger_test.go`** with tests

3. **Follow Cilium patterns**:
   - Use `logfields` package for structured log fields
   - Follow the `SelectorCache` interaction pattern
   - Use `lock.Mutex` from `pkg/lock/` for thread safety

## Key Reference Files
- `pkg/policy/distillery.go` — policy decision evaluation
- `pkg/policy/selectorcache.go` — SelectorCache for identity matching
- `pkg/policy/types.go` — policy types and interfaces
- `pkg/logging/logfields/logfields.go` — structured log field constants
- `pkg/lock/lock.go` — Cilium's lock primitives

## Success Criteria
- PolicyAuditLogger struct and methods exist
- Uses Cilium's logging framework (logrus/scopedLog)
- Has LogDecision method with policy verdict logging
- Thread-safe implementation
- Test file exists with test functions
