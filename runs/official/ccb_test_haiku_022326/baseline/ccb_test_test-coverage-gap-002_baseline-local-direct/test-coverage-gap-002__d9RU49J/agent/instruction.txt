# Task: Map Test Coverage Gaps in Kafka Consumer Group Coordinator

**Repository:** apache/kafka
**Output:** Write your analysis to `/workspace/coverage_analysis.md`

## Objective

Identify test coverage gaps in Kafka's consumer group coordinator. The group coordinator manages consumer group membership, partition assignment, and offset commits for Kafka consumers.

## Scope

Focus on:
- `core/src/main/scala/kafka/coordinator/group/GroupCoordinator.scala` — main coordinator logic
- `core/src/test/scala/unit/kafka/coordinator/group/GroupCoordinatorTest.scala` — existing tests
- `core/src/main/scala/kafka/coordinator/group/GroupMetadata.scala` — group state machine

## Content Expectations

Your analysis must:
1. **Identify at least 5 specific failure modes** that are not tested in `GroupCoordinatorTest.scala`
2. **Propose a regression test** for each failure mode (class name, test method signature, key assertions)
3. **Estimate the coverage delta** each proposed test would add (which code paths would it hit)
4. **Label risk level**: HIGH / MEDIUM / LOW

## Output Format

Write to `/workspace/coverage_analysis.md`:

```markdown
# Test Coverage Gap Analysis: Kafka Consumer Group Coordinator

## Summary

## Failure Modes and Proposed Tests

### Failure Mode 1: [Name]
- **Risk**: HIGH/MEDIUM/LOW
- **Code Location**: GroupCoordinator.scala ~line NNN
- **Description**: [What failure scenario is untested]
- **Proposed Test**:
  ```java
  @Test
  public void testXxx() { ... }
  ```
- **Coverage Delta**: [Which code paths this test would exercise]

[Repeat for 5+ failure modes]

## File References
```

## Anti-Requirements
- Do not fabricate class or method names — read the actual source first
- Each gap must reference a specific file and approximate location
- Do NOT run the tests yourself — write the test file and the evaluation system validates independently
