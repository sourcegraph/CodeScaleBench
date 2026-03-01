# Task: Rename MemoryStorage to InMemoryRaftLog

## Objective
Rename `MemoryStorage` to `InMemoryRaftLog` in etcd's raft package to better
describe the struct's role as an in-memory Raft log implementation.

## Requirements

1. **Rename struct** in raft storage file:
   - `type MemoryStorage struct` → `type InMemoryRaftLog struct`
   - Rename constructor: `NewMemoryStorage` → `NewInMemoryRaftLog`

2. **Update all references** (20+ call sites):
   - `raft/` package — internal usage
   - `server/` — server initialization
   - Test files
   - Interface implementations

3. **Update receiver methods**

## Key Reference Files
- `raft/storage.go` — MemoryStorage definition
- `raft/raft.go` — uses storage
- `raft/raft_test.go` — test usage
- `server/etcdserver/raft.go` — server integration

## Success Criteria
- `type MemoryStorage struct` no longer exists
- `type InMemoryRaftLog struct` exists
- Constructor renamed
- 80%+ of references updated
