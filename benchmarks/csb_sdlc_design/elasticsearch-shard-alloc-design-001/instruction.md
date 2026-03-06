# Task: Design a Priority-Based Shard Allocation Strategy

## Background
Elasticsearch's shard allocation balances shards across nodes, but doesn't support priority-based allocation where critical indices get preferred placement on faster nodes.

## Objective
Design a new `PriorityShardsAllocator` that extends the existing allocation framework to support index-priority-aware shard placement.

## Steps
1. Study the existing shard allocation in `server/src/main/java/org/elasticsearch/cluster/routing/allocation/`
2. Understand the `ShardsAllocator` interface and `BalancedShardsAllocator`
3. Study `AllocationDeciders` and how decisions compose
4. Create a design document `design_doc.md` in `/workspace/` with:
   - Architecture overview of current allocation
   - Proposed PriorityShardsAllocator class design
   - New `AllocationDecider` for priority constraints
   - Index setting for priority level (`index.routing.allocation.priority`)
   - Interaction with existing deciders (DiskThresholdDecider, AwarenessAllocationDecider)
   - API changes needed
5. Create a skeleton Java file `PriorityShardsAllocator.java` showing the class structure

## Key Reference Files
- `server/src/main/java/org/elasticsearch/cluster/routing/allocation/allocator/BalancedShardsAllocator.java`
- `server/src/main/java/org/elasticsearch/cluster/routing/allocation/allocator/ShardsAllocator.java`
- `server/src/main/java/org/elasticsearch/cluster/routing/allocation/decider/AllocationDeciders.java`

## Success Criteria
- Design doc exists with architecture overview
- Skeleton Java file exists
- Design references existing allocation classes
- Includes interaction with existing deciders
