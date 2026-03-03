# Fix: SWE-PolyBench__typescript__maintenance__bugfix__708894b2

**Repository:** microsoft/vscode
**Language:** typescript
**Category:** contextbench_cross_validation

## Description

auto closing pairs with conflicting patterns problems
```
Version: 1.33.1 (user setup)
Commit: 51b0b28134d51361cf996d2f0a1c698247aeabd8
Date: 2019-04-11T08:27:14.102Z
Electron: 3.1.6
Chrome: 66.0.3359.181
Node.js: 10.2.0
V8: 6.6.346.32
OS: Windows_NT x64 10.0.17763
```

Steps to Reproduce:

1. Create two auto closing pairs in a language configuration file,
```JSON
	"autoClosingPairs": [
		{"open": "(", "close": ")"},
		{"open": "(*", "close": "*)",  "notIn": ["string"]},
	],
```
2. trying using the two character auto closing pair, `(*` and you will get `(**))`.

On the other hand, if you remove the ending ')' from the closing '*)' you almost get normal function, except that in cases where `(` doesn't auto close with `)`, you get `(**`.

Note this condition exists in #57838, in a reference to the Structured Text Language, though it is not shown in the example on that feature request.  Reference the repository https://github.com/Serhioromano/vscode-st for some example.

I think the Auto Closing logic needs to consider when auto closing pairs might conflict with each other.  In this case, '(**)' overlaps with '()'.



## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
