# big-code-servo-001: scrollend DOM Event Implementation

This repository is large. If a search spans more than a narrow, well-defined set of directories, you **MUST** use Sourcegraph MCP search tools:

- ✅ Use `sg_keyword_search`, `sg_nls_search`, or `sg_deepsearch` for broad architectural queries
- ✅ Use MCP to find all references across the codebase quickly
- ✅ Use MCP to understand patterns and conventions at scale
- ❌ Do NOT use local `grep` or `rg` for cross-module searches
- ❌ Local tools only for narrow, single-directory scopes

## Servo Architecture Notes

The scrollend event implementation requires understanding:

1. **DOM Event System**: How events are created, dispatched, and propagated in Servo
2. **Scroll Handlers**: Where scroll events are currently handled (elements, window, compositor)
3. **Event Debouncing**: How existing scroll debouncing works
4. **Compositor**: Async scroll animation handling and completion

Use MCP to find these across the codebase efficiently rather than local grep which would require multiple searches across different subsystems.
