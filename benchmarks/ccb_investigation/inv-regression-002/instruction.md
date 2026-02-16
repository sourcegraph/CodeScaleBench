# Investigation Task: Prometheus Alert Rule State Loss on Config Reload

## Background

You are investigating a regression in Prometheus where alert rules lose their accumulated state (specifically the "for" clause state) when the configuration is reloaded. This bug was introduced by a code change that affected how rule groups are tracked during configuration updates.

The regression manifests as follows:
- When a user reloads Prometheus configuration (via SIGHUP or HTTP POST to /-/reload)
- Alert rules that were in "pending" state (counting time toward their "for" duration) are reset
- Active alerts that should remain firing are lost
- The alert evaluation essentially restarts from scratch, even though the rules themselves didn't change

This is particularly problematic for:
- Alerts with long "for" durations (e.g., "for: 5m" or "for: 10m")
- Production systems that reload configs frequently for updates
- Alerts that were close to firing but get reset before reaching their threshold

The codebase you're analyzing is at a commit AFTER the regression was introduced but BEFORE it was fixed.

## Symptom

**Alert rule state loss on configuration reload:**
- Alert rules lose their "for" state when Prometheus config is reloaded
- Rules that were pending (counting toward their "for" duration) reset to 0
- Active alerts disappear and must re-trigger from scratch
- The issue affects all alert rules, regardless of their content
- The problem occurs specifically during the `ApplyConfig` operation
- Recording rules are not affected - only alerting rules lose state

The symptom is reproducible 100% of the time when:
1. An alert rule exists with a "for" clause (e.g., "for: 1m")
2. The alert condition becomes true, starting the "for" countdown
3. Before the alert fires, the Prometheus configuration is reloaded
4. The alert's accumulated state is lost and countdown resets to 0

## Your Task

Investigate the Prometheus codebase to find:

1. **The regressing commit**: Identify the specific commit SHA that introduced this state loss bug
2. **The changed component**: Determine which file(s) and function(s) were modified
3. **The regression mechanism**: Explain HOW the change caused alert state to be lost
4. **The causal chain**: Trace the complete path from the code change to the observed symptom
5. **The fix**: Identify how this regression was eventually fixed

## Investigation Approach

Since this is a regression hunt, you should:
- Use git log and commit history analysis to identify candidate commits
- Focus on commits that modified rule group management or config reload logic
- Look for changes to how rule groups are indexed/keyed in maps
- Examine the `ApplyConfig` method in `rules/manager.go`
- Search for commits that changed how groups are stored during `loadGroups`
- Use git diff to understand what changed between working and broken states

## Key Areas to Investigate

The regression likely involves one or more of these components:
- Rule group management (`rules/manager.go`)
- Configuration loading and application (`ApplyConfig` method)
- State copying between old and new rule groups
- Map key generation for tracking rule groups
- The relationship between `loadGroups` and `ApplyConfig`

Focus your investigation on commits made to `rules/manager.go` between mid-2017 and late-2017 that touched group tracking or state management.

## Root Cause Hint

The bug involves an **inconsistency in map key formatting** between two parts of the code:
- One part uses a certain format to store rule groups in a map
- Another part uses a different format to retrieve those same groups
- This mismatch causes the "copy state from old group to new group" logic to fail

## Output Format

Write your findings to `/logs/agent/investigation.md` with the following structure:

```markdown
# Investigation Report: Prometheus Alert Rule State Loss on Config Reload

## Summary
[Brief description of the regression and root cause]

## Regressing Commit
- **Commit SHA**: [full 40-character SHA]
- **Commit Message**: [the commit message]
- **Date**: [when it was committed]
- **Files Changed**: [list of files modified]

## Root Cause Analysis

### Changed Function/Component
[Describe what function(s) or component(s) were modified]

### Mechanism of Regression
[Explain HOW the change caused alert state loss]

### Why It Causes the Symptom
[Connect the code change to the observed state loss during config reload]

## Causal Chain

1. [First step: the code change itself - what was modified]
2. [Second step: how the map key format changed in one place but not another]
3. [Third step: what happens during ApplyConfig when keys don't match]
4. [Fourth step: why this causes state to be lost instead of copied]

## Supporting Evidence

### Code Snippets
[Include relevant code snippets from the regressing commit]

### The Fix
[Describe the commit that fixed this regression and what it changed]

### Related Files
[List files involved in the regression path]

## Negative Findings

### What It's NOT
[List plausible-but-incorrect explanations you ruled out]

## Conclusion
[Final assessment of the regression cause]
```

## Verification

Your investigation will be evaluated on:
- Correctly identifying the regressing commit SHA (exact match required)
- Accurately describing the changed function/component
- Explaining the map key inconsistency mechanism
- Tracing the complete causal chain from code change to symptom
- Identifying the fix commit that resolved the regression
- Ruling out plausible alternative explanations
