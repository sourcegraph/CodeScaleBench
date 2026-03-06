# Task: Refactor Roslyn Symbol Lookup to Unified Resolution Strategy

## Background
Roslyn's symbol lookup has separate code paths for different contexts (expression binding, type resolution, member access). This task extracts common patterns into a shared strategy.

## Objective
Create a `UnifiedSymbolResolver` that consolidates the common symbol lookup patterns used across different binding contexts.

## Steps
1. Study symbol resolution in `src/Compilers/CSharp/Portable/Binder/`
2. Identify common patterns in `Binder.LookupSymbolsInSingleBinder`, `Binder_Lookup.cs`, and type resolution
3. Create `src/Compilers/CSharp/Portable/Binder/UnifiedSymbolResolver.cs` with:
   - A strategy interface `ISymbolResolutionStrategy`
   - Concrete strategies for: TypeResolution, MemberAccess, NamespaceResolution
   - A `Resolve()` method that walks scope chains using the strategy
   - Results type that captures both found symbols and diagnostics
4. Create a test file in the test directory

## Key Reference Files
- `src/Compilers/CSharp/Portable/Binder/Binder_Lookup.cs`
- `src/Compilers/CSharp/Portable/Binder/Binder.cs`
- `src/Compilers/CSharp/Portable/Symbols/` — symbol types

## Success Criteria
- UnifiedSymbolResolver.cs exists
- Defines ISymbolResolutionStrategy interface
- Has concrete strategy implementations
- Test file exists
