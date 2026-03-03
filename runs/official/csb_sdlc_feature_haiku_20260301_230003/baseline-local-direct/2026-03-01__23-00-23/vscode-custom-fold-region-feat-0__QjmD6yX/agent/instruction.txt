# Task: Implement Custom Named Folding Regions with Navigation in VS Code

## Objective
Add support for custom named folding regions in VS Code that can be navigated via a quick-pick menu. Users mark regions with special comments (e.g., `// #region MySection` / `// #endregion`), and this feature extends the existing folding to allow naming and jumping to regions by name.

## Requirements

1. **Create a Named Region Provider** in the folding subsystem:
   - Create or extend a folding range provider in `src/vs/editor/contrib/folding/browser/`
   - Detect `#region <name>` and `#endregion` comment markers
   - Extract the region name from the marker
   - Register named regions in a data structure that maps name -> line range

2. **Add region decoration** in the editor:
   - Display the region name as a decorative label in the gutter or inline
   - Use VS Code's decoration API (`IModelDecorationOptions`)
   - Collapsed regions should show the name in the fold placeholder text

3. **Register a "Go to Region" command**:
   - Add command `editor.action.goToNamedRegion` in `src/vs/editor/contrib/folding/browser/`
   - Wire it to a keybinding (suggest `Ctrl+Shift+R` / `Cmd+Shift+R`)
   - Register the command via `registerEditorAction` or `registerEditorCommand` pattern

4. **Implement quick-pick navigation**:
   - When the command is invoked, show a quick-pick (`IQuickInputService`) listing all named regions in the current file
   - Each item shows the region name and line number
   - Selecting an item navigates the editor cursor to that region and unfolds it

5. **Add a test file** for the named region provider:
   - Test region detection and name extraction
   - Test navigation to a named region

## Key Reference Files
- `src/vs/editor/contrib/folding/browser/folding.ts` — main folding contribution
- `src/vs/editor/contrib/folding/browser/foldingRanges.ts` — FoldingRanges data structure
- `src/vs/editor/contrib/folding/browser/indentRangeProvider.ts` — reference range provider
- `src/vs/editor/contrib/folding/browser/syntaxRangeProvider.ts` — another range provider pattern
- `src/vs/editor/common/model/textModel.ts` — text model API for line access
- `src/vs/editor/contrib/gotoSymbol/browser/goToCommands.ts` — reference for navigation commands
- `src/vs/platform/quickinput/common/quickInput.ts` — QuickInput service interface

## Success Criteria
- Named region detection code exists in folding contrib
- Region name extraction from `#region` markers implemented
- Command registered for navigating to named regions
- Quick-pick integration with region listing
- Decoration or placeholder text shows region names
- Test file exists for the region provider
