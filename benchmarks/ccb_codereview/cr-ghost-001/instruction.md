# Cr Ghost 001

- **Repository**: agentic-review-benchmarks/benchmark-pr-mapping
- **Difficulty**: hard
- **Category**: code-review
- **Task Type**: repo-clone

## Description

Review a Ghost PR for injected functional bugs and compliance violations, identifying defects with file and line-level localization. This task is based on the Qodo AI Code Review benchmark methodology, which injects realistic defects (compliance violations and functional bugs) into merged production PRs and evaluates detection precision and recall.

## Task

YOU MUST IMPLEMENT CODE CHANGES to complete this task.

TODO: Add detailed task instructions here. Specify:
- Which PR diff to review (reference the benchmark-pr-mapping table)
- The injected defect types to look for (functional bugs, compliance violations)
- Expected output format (file path, line number, defect description)
- Whether the agent should produce a review report or fix the defects

## Success Criteria

- [ ] TODO: Define measurable success criteria (e.g., precision/recall thresholds)
- [ ] Defects identified with correct file and line-level localization
- [ ] Review output written to expected location

## Testing

- **Time limit**: 1200 seconds
- Run `bash /workspace/tests/test.sh` to verify your changes
