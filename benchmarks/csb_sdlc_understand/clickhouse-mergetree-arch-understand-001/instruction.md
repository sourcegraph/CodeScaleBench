# Task: Understand ClickHouse MergeTree Storage Engine Architecture

## Objective
Produce a comprehensive architecture analysis of the MergeTree storage engine, the core table engine in ClickHouse, covering its data organization, merge process, and query execution path.

## Steps
1. Find the MergeTree implementation in `src/Storages/MergeTree/`
2. Trace the write path: how INSERTs create new data parts
3. Trace the merge path: how background merges combine parts
4. Trace the read path: how SELECT queries scan parts with index skipping
5. Create `architecture_analysis.md` in `/workspace/` documenting:
   - High-level MergeTree architecture diagram (text-based)
   - Data part structure (columns, marks, primary index, skip indices)
   - Write path: from INSERT to committed part
   - Merge path: merge selection, merge algorithm, part replacement
   - Read path: part pruning, mark selection, column reading
   - Key source files with their roles
   - At least 10 specific file paths referenced

## Key Reference Files
- `src/Storages/MergeTree/MergeTreeData.h` — base class
- `src/Storages/MergeTree/MergeTreeDataWriter.cpp` — write path
- `src/Storages/MergeTree/MergeTreeDataMergerMutator.cpp` — merge logic
- `src/Storages/MergeTree/MergeTreeDataSelectExecutor.cpp` — read path

## Success Criteria
- architecture_analysis.md exists
- Covers write, merge, and read paths
- References at least 10 specific source files
- Describes data part structure
