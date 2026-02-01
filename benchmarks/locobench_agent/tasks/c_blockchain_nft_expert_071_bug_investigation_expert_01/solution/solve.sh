#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
{
  "vulnerable_file": "HoloCanvas//services//ledger_core//src//block_builder.c",
  "bug_description": "In `block_builder.c`, within the function that adds transactions to a new block, there is a conditional block to handle `TX_GOVERNANCE_UPDATE_RECIPE` transactions. The line that updates the block's size for this transaction's payload is incorrect. It uses `current_block_size += sizeof(transaction->payload);`. This should be `current_block_size += transaction->payload_size;`, which correctly references the size of the dynamically allocated payload from the transaction structure (defined in `transaction.h`). The `sizeof()` operator on the pointer results in adding only 4 or 8 bytes, causing the block builder to believe the block is much smaller than it is, leading it to add more transactions and exceed the protocol's maximum block size limit.",
  "secondary_issue_file": "HoloCanvas//services//ledger_core//src//strategies//pos_strategy.c",
  "secondary_issue_description": "The consensus validation function within `pos_strategy.c` is incomplete. It lacks the rigorous block size check that is correctly implemented in `da_strategy.c`. This discrepancy in validation logic is why the bug in `block_builder.c` is only exposed when the `da_strategy` is active, making the bug appear intermittent and strategy-dependent.",
  "key_files_for_analysis": [
    "HoloCanvas//services//ledger_core//src//block_builder.c",
    "HoloCanvas//services//ledger_core//src//strategies//da_strategy.c",
    "HoloCanvas//services//ledger_core//src//strategies//pos_strategy.c",
    "HoloCanvas//services//ledger_core//include//transaction.h"
  ]
}
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
