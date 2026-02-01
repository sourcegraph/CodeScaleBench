# RepoQA: Negative/Disambiguation QA (NR-QA)

## Task: Pick the Right Function

The codebase contains multiple similar functions. Your job is to identify which one matches the description using semantic understanding.

**Repository**: {repository}  
**Language**: {language}  
**Commit**: {commit}

## Function Description

```
{function_description}
```

## Important Constraint

Only **ONE** function fully matches this description. The others are similar in name or behavior but have a critical difference:

```
{semantic_constraint}
```

This constraint is **the key differentiator**. Functions that don't satisfy it are wrong, even if they seem plausible.

## What Makes This Difficult

- Multiple functions may have similar names
- Multiple functions may do related work
- You must use semantic understanding to identify the exact one
- Generic keyword matching will lead to false positives

## Search Strategy

1. **Search for functions** matching the behavior description
2. **Understand the semantic constraint** (see above)
3. **Verify each candidate** has or doesn't have the constraint property
4. **Select the one function** that satisfies the constraint

### Sourcegraph MCP Tools

- **`search_codebase`**: Find candidate functions
- **`get_definition`**: Examine each function's implementation
- **`get_references`**: See how functions are used (clues about behavior)
- **`get_call_graph`**: Understand function relationships

## Output Format

```json
{
  "function_path": "path/to/file.py",
  "function_name": "correct_function",
  "justification": "Why this is the correct one: explain how it satisfies the constraint and why the others don't"
}
```

## Scoring

- ✅ **Correct** (1.0): You picked the right function
- ❌ **Wrong** (0.0): You picked a different function, even if plausible

This is **binary**: either you get it right or wrong. There's no partial credit.

However, if you pick the right path but wrong name (or vice versa), you get +0.3.

## Example

**Description**: "Function that handles password validation in authentication"  
**Constraint**: "Must throw an exception on validation failure"

**Candidates**:
1. `auth.validate_password()` - validates password, throws exception ✅ **CORRECT**
2. `auth.check_password()` - validates password, returns boolean ❌ (doesn't throw)
3. `auth.password_matches()` - validates password, returns boolean ❌ (doesn't throw)

The constraint is critical: even though all three validate passwords, only the first one throws exceptions.

## Tips

- Read the constraint carefully
- Examine the implementation (not just the name)
- Look at error handling patterns
- Understand what the function does, not just what it's called

Your semantic understanding is being tested here. Generic search won't work.
