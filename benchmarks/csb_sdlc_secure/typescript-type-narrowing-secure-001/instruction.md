# Task: Security Review of TypeScript Type Narrowing

## Objective
Review the TypeScript compiler's type narrowing implementation for patterns that could lead to unsound type assertions, enabling developers to bypass type safety unknowingly.

## Steps
1. Find the type narrowing implementation in `src/compiler/checker.ts`
2. Identify the narrowing functions (narrowType, narrowTypeByGuard, narrowTypeByTypeof, etc.)
3. Analyze potential unsoundness in:
   - typeof narrowing with user-defined type guards
   - Discriminated union narrowing edge cases
   - Control flow analysis across function boundaries
   - Type assertion vs type narrowing interaction
4. Create `security_review.md` in `/workspace/` documenting:
   - Overview of the narrowing architecture (file paths and functions)
   - At least 3 patterns where narrowing could produce unsound types
   - TypeScript code examples demonstrating each pattern
   - Severity assessment for each finding
   - Recommendations for stricter narrowing

## Key Reference Files
- `src/compiler/checker.ts` — main type checker with narrowing
- `src/compiler/types.ts` — type system definitions
- `src/compiler/utilities.ts` — helper functions

## Success Criteria
- security_review.md exists
- Identifies specific narrowing functions
- Documents at least 3 unsound patterns
- Includes TypeScript code examples
