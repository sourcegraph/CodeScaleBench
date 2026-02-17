Show divergent tasks across baseline/SG_full configs. Identifies "MCP helps" vs "MCP hurts" patterns.

## Steps

1. Run cross-config comparison:
```bash
python3 scripts/compare_configs.py
```

2. For MCP-conditioned analysis:
```bash
python3 scripts/compare_configs.py --mcp-analysis
```

3. Summarize: which tasks benefit from MCP, which are hurt, overall delta

## Arguments

$ARGUMENTS — optional: --suite <name>, --mcp-analysis
