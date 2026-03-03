# Fix: SWE-PolyBench__typescript__maintenance__bugfix__7d106697

**Repository:** microsoft/vscode
**Language:** typescript
**Category:** contextbench_cross_validation

## Description

configurationDefaults contribution changes JSON auto-complete behavior
Reported originally by @JacksonKearl where GitLens seemed to be breaking JSON auto-complete behavior -- causing an extra `"` being added at the end.

![recording (16)](https://user-images.githubusercontent.com/641685/97644218-2495ba00-1a20-11eb-9442-b1e44789c4d4.gif)

I tracked it down to this contribution causing the issue

```json
"configurationDefaults": {
	"[json]": {
		"gitlens.codeLens.scopes": [
			"document"
		]
	}
}
```

I was able to reproduce this with a clean vscode user-dir/extensions-dir and a simple extension with that contribution


## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
