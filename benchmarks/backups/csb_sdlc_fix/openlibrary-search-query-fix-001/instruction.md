# Fix Work Search Query Processing for Edge-Case Inputs

**Repository:** internetarchive/openlibrary
**Language:** Python
**Difficulty:** hard

## Problem

Following the introduction of the `SearchScheme`-based work search, raw user queries are not consistently normalized and escaped before reaching Solr. Inputs with trailing dashes, reserved operators, or quoted strings can be misinterpreted by the parser under the current work search scheme, leading to parse errors or unintended queries.

## Reproduction

1. Open the work search page, enter a query ending with a hyphen (e.g., `Horror-`), and submit
2. Observe that the request fails or does not yield results due to query parsing issues
3. Similar issues occur with inputs containing operator-like tokens or quoted phrases

## Key Components

- `WorkSearchScheme.process_user_query` — the entry point where raw user input is processed for Solr
- Solr query construction and escaping logic in the worksearch plugin

## Task

1. Locate `WorkSearchScheme.process_user_query` and trace how raw user input flows to Solr
2. Fix normalization and escaping to handle: trailing dashes, operator-like tokens, quoted phrases, and ISBN-like strings
3. Ensure the fix produces safely escaped, semantically correct Solr queries for all edge cases
4. Verify that standard (non-edge-case) searches are unaffected
5. Run existing tests to ensure no regressions

## Success Criteria

- Queries with trailing hyphens (e.g., `Horror-`) execute without Solr errors
- Operator-like tokens and quoted phrases are properly escaped
- ISBN-like strings are handled correctly
- Standard search queries continue to work as expected
- All existing tests pass

