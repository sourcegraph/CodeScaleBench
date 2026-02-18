# big-code-strata-refac-001: Rename FxVanillaOption to FxEuropeanOption

This repository is large (~500K LOC). Use comprehensive search to find ALL references before making changes.

## Task Type: Cross-File Refactoring

Your goal is to rename the `FxVanillaOption` type family to `FxEuropeanOption` across 4 Maven modules in OpenGamma Strata. Focus on:

1. **Complete identification**: Find ALL files that reference `FxVanillaOption` — the 4 core Joda-Beans classes, 4 pricers, 4 measure classes, 1 loader plugin, the `ProductType` constant, and all dependent files (barrier option classes, CSV utilities, trade resolvers)
2. **Dependency ordering**: Change the core product classes first, then pricers, then measure, then loader. Update dependent files (FxSingleBarrierOption, barrier pricers) after the core types
3. **Joda-Beans awareness**: Each core class has 70-83% auto-generated code (Meta/Builder inner classes). The `@BeanDefinition` annotation triggers code generation — renaming the class means the auto-generated sections also change
4. **Consistency**: Ensure no stale references to `FxVanillaOption` remain after the refactoring
5. **Compilation**: Verify with `mvn compile -pl modules/product,modules/pricer,modules/measure,modules/loader -q`

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — why this file needs changes

## Dependency Chain
1. path/to/definition.ext (original definition)
2. path/to/user1.ext (direct reference)
3. path/to/user2.ext (transitive dependency)

## Code Changes
### path/to/file1.ext
\`\`\`diff
- old code
+ new code
\`\`\`

## Analysis
[Refactoring strategy and verification approach]
```

## Search Strategy

- Start with `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOption.java` — the primary definition
- Use `find_references` on `FxVanillaOption` to find ALL usages across the codebase
- Check `modules/product/src/main/java/com/opengamma/strata/product/fxopt/` for all 4 core types and sibling barrier option classes
- Check `modules/product/src/main/java/com/opengamma/strata/product/ProductType.java` for the string constant
- Search `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/` for all pricer classes
- Search `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/` for measure classes including `FxVanillaOptionMethod.java`
- Search `modules/loader/src/main/java/com/opengamma/strata/loader/csv/` for CSV plugin and utilities
- Check `TradeCsvInfoResolver.java` for method signatures with `FxVanillaOptionTrade`
- After changes, grep for `FxVanillaOption` to verify no stale references remain
