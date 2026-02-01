# Hello World Test Benchmark

Simple benchmark for testing the CodeContextBench evaluation pipeline.

## Purpose

This benchmark provides a minimal task for:
- **Testing agent configurations** - Verify agents can execute basic tasks
- **Testing oracle validation** - Confirm Harbor can run reference solutions
- **Pipeline debugging** - Quick feedback loop for testing changes

## Tasks

### hello-world-001

**Task:** Create a Python script that prints "Hello, World!"

**Difficulty:** Easy
**Time Limit:** 60 seconds

**Success Criteria:**
- Create `hello_world.py` in workspace root
- Script outputs exactly `Hello, World!\n` when run

## Usage

### Oracle Validation (Benchmark Manager)

1. Go to **Benchmark Manager** in dashboard
2. Select "hello_world_test"
3. Select tasks to validate
4. Click **"Run Oracle Validation"**

This tests that the task and verifier work correctly.

### Agent Testing (Evaluation Runner)

1. Go to **Evaluation Runner** in dashboard
2. Select "hello_world_test" benchmark
3. Select "hello-world-001" task
4. Choose agent configuration (baseline, with/without MCP)
5. Click **"Start Evaluation"**

### Command Line Testing

```bash
# Oracle validation
harbor run --path benchmarks/hello_world_test --agent oracle -n 1

# With baseline agent
source .env.local
export ANTHROPIC_API_KEY SOURCEGRAPH_ACCESS_TOKEN SOURCEGRAPH_URL
harbor run \
  --path benchmarks/hello_world_test \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

## Expected Results

**Oracle validation:**
- Should complete in < 30 seconds
- Exit code: 0
- Reward: 1.0
- Test output: "PASS: hello_world.py outputs correctly"

**Agent evaluation:**
- Should complete in < 60 seconds
- Reward: 1.0 (if agent creates the file correctly)
- Low token usage (< 5,000 tokens expected)

## Files

```
hello-world-001/
├── task.toml              # Task configuration
├── instruction.md         # Task description for agent
├── environment/
│   └── Dockerfile        # Docker environment setup
├── solution/
│   └── hello_world.py    # Reference solution (oracle)
└── tests/
    └── test_hello.py     # Verification test
```

## Troubleshooting

**If oracle validation fails:**
- Check Docker is running
- Verify `solution/hello_world.py` exists
- Check `tests/test_hello.py` is executable

**If agent fails:**
- Check ANTHROPIC_API_KEY is set
- Review agent trace in Run Results view
- Verify agent can write to `/workspace`
