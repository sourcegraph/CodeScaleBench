# Task: Implement CSS Container Queries Size Evaluation in Servo

## Objective
Add CSS Container Queries support to Servo's style system, implementing the `@container` at-rule with size-based queries (`min-width`, `max-width`, `min-height`, `max-height`, `width`, `height`).

CSS Container Queries (CSS Containment Level 3) allow elements to be styled based on their container's size rather than the viewport. A container is designated via `container-type: size | inline-size` and queried with `@container (min-width: 400px) { ... }`.

## Requirements

1. **Define container type properties** in Servo's style properties:
   - Add `container-type` CSS property (values: `normal`, `size`, `inline-size`)
   - Add `container-name` CSS property (values: `none` or custom ident)
   - These should be defined in `components/style/properties/` following Servo's property definition pattern

2. **Parse @container rules** in the CSS parser:
   - Extend `components/style/stylesheets/` to handle `@container` at-rules
   - Parse container size conditions: `(min-width: Npx)`, `(max-width: Npx)`, `(width > Npx)`, etc.
   - Store parsed container queries in the stylesheet data structures

3. **Implement container query evaluation**:
   - In the style resolution path, evaluate container size queries against the actual container dimensions
   - Walk up the DOM tree to find the nearest container ancestor with matching `container-name`
   - Compare container dimensions against the query conditions

4. **Integrate with style matching**:
   - During rule matching, check if `@container` rules apply given the current container sizes
   - Rules inside a matching `@container` block should be included in the cascade

## Key Reference Files
- `components/style/properties/longhands/` — longhand property definitions (add container-type, container-name here)
- `components/style/stylesheets/rule_parser.rs` — at-rule parsing
- `components/style/stylesheets/container_rule.rs` — may already exist as a stub
- `components/style/matching.rs` — style matching/cascade logic
- `components/style/values/specified/length.rs` — length value parsing
- `components/style/media_queries/` — reference pattern for conditional rules (similar to @media)

## Success Criteria
- `container-type` property definition exists in properties
- `container-name` property definition exists in properties
- Container query parsing structures defined (ContainerCondition or similar)
- @container at-rule parsing integrated into stylesheet parser
- Size query evaluation logic exists (comparing dimensions against conditions)
- Integration point in style matching that checks container queries
