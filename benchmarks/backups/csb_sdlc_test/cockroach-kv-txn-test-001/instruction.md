# Task: Write Tests for CockroachDB KV Transaction Conflict Resolution

## Objective
Write unit tests for the transaction conflict resolution logic in CockroachDB's KV layer, covering write-write conflicts, read-write conflicts, and deadlock detection.

## Steps
1. Study the transaction conflict handling in `pkg/kv/kvserver/concurrency/`
2. Understand the `LockTable` and `ConcurrencyManager` interfaces
3. Study the `TxnWaitQueue` or equivalent conflict resolution mechanism
4. Create a test file in `pkg/kv/kvserver/concurrency/` with tests for:
   - Write-write conflict detection between two transactions
   - Read-write conflict with different isolation levels
   - Deadlock detection with two transactions waiting on each other
   - Transaction priority-based conflict resolution
   - Lock acquisition timeout behavior
   - Intent resolution after transaction commit/abort

## Key Reference Files
- `pkg/kv/kvserver/concurrency/concurrency_manager.go`
- `pkg/kv/kvserver/concurrency/lock_table.go`
- `pkg/kv/kvserver/concurrency/` — existing tests as pattern

## Success Criteria
- Test file exists in the concurrency package
- Tests cover write-write conflicts
- Tests cover deadlock scenarios
- Tests reference ConcurrencyManager or LockTable
