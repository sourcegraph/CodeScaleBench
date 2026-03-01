# Task: Document Cilium eBPF Map API

## Objective

Generate comprehensive API reference documentation for Cilium's eBPF map API in the `pkg/bpf` package. The documentation should serve as a complete reference for developers working with eBPF maps in Cilium.

## Scope

Focus on the Go wrappers in `pkg/bpf` that provide user-space interaction with kernel eBPF maps. Document:

1. **Core Map Type and Creation**
   - `Map` struct and its primary methods
   - Map creation functions (`NewMap`, `OpenMap`, `OpenOrCreate`)
   - Map lifecycle operations (Open, Create, Close, Recreate)

2. **CRUD Operations**
   - Lookup, Update, Delete operations
   - Batch operations (BatchLookup, DeleteAll)
   - Per-CPU map operations
   - Locked operations (DeleteLocked)

3. **Iteration and Dumping**
   - Dump methods and callbacks
   - BatchIterator type and usage
   - DumpStats for tracking iteration

4. **Pinning and Persistence**
   - Pin/Unpin operations
   - BPF filesystem paths (BPFFSRoot, CiliumPath, MapPath)
   - Map persistence behavior

5. **Key/Value Interfaces**
   - MapKey, MapValue, MapPerCPUValue interfaces
   - EndpointKey as concrete example

6. **Event System**
   - Event types (MapUpdate, MapDelete)
   - DumpAndSubscribe for event streaming
   - Event callbacks and handles

7. **Collection Loading**
   - LoadCollection and LoadAndAssign functions
   - CollectionOptions

## Requirements

Your documentation must include:

1. **API Method Signatures**: Complete signatures with parameter types and return values
2. **Behavioral Semantics**:
   - When maps are pinned vs unpinned
   - Difference between Create() and CreateUnpinned()
   - OpenOrCreate() behavior on existing maps
   - How deletion works within DumpCallback (requires DeleteLocked)
   - Event subscription lifecycle
   - Batch iterator retry behavior on ENOSPC
3. **Usage Examples**: Code snippets showing:
   - Basic map creation and CRUD
   - Iteration with BatchIterator
   - Event subscription and cleanup
   - Pinning and unpinning maps
   - Real-world patterns from Cilium internals
4. **Documentation Structure**: Organize clearly with sections for each category above

## Deliverable

Write your documentation to `/workspace/documentation.md` in Markdown format.

## Constraints

- Do NOT include file paths or specific implementation locations in the documentation
- Focus on API contracts and behavior, not internal implementation details
- Include enough behavioral detail that users can correctly use the API without reading source code
- Provide accurate examples that would compile and work correctly
