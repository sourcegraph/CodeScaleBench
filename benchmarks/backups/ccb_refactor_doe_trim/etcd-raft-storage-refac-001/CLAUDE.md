# etcd-raft-storage-refac-001: Rename MemoryStorage

## Task Type: Cross-File Refactoring (Rename)

Rename MemoryStorage → InMemoryRaftLog in etcd raft package.

## Key Reference Files
- `raft/storage.go` — definition
- `raft/raft.go` — usage
- `server/etcdserver/raft.go` — server integration

## Search Strategy
- Search for `MemoryStorage` across raft/ and server/
- Search for `NewMemoryStorage` for constructor calls
