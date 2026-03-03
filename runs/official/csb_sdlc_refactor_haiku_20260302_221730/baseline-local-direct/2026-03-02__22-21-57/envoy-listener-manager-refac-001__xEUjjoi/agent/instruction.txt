# Task: Rename ListenerManagerImpl to ListenerOrchestrator

## Objective
Rename `ListenerManagerImpl` to `ListenerOrchestrator` in Envoy to better
describe the class's role as an orchestrator of listener lifecycle operations.

## Requirements

1. **Rename the class definition**:
   - `class ListenerManagerImpl` → `class ListenerOrchestrator`
   - Update header file and implementation file

2. **Update all references** (20+ call sites):
   - Constructor calls
   - Type declarations and pointers
   - Test files
   - Factory registrations

3. **Update header guards and includes**

## Key Reference Files
- `source/common/listener_manager/listener_manager_impl.h` — class declaration
- `source/common/listener_manager/listener_manager_impl.cc` — implementation
- `source/server/server.h` — uses ListenerManagerImpl
- `test/common/listener_manager/listener_manager_impl_test.cc` — tests

## Success Criteria
- `class ListenerManagerImpl` no longer exists
- `class ListenerOrchestrator` exists
- 80%+ of references updated
- Tests still reference the class correctly
