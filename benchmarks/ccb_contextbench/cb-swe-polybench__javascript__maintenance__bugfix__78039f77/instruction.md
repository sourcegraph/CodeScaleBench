# Fix: SWE-PolyBench__javascript__maintenance__bugfix__78039f77

**Repository:** sveltejs/svelte
**Language:** javascript
**Category:** contextbench_cross_validation

## Description

Spread properties cause CSS to be DCE'd incorrectly
[REPL](https://svelte.technology/repl?version=1.60.0&gist=678853cb781d28931abbc159c22d2d7f)

```html
<div {{...props}} >
	Big red Comic Sans
</div>

<style>
	.foo {
		color: red;
		font-size: 2em;
		font-family: 'Comic Sans MS';
	}
</style>
```

`.foo` should be preserved; it isn't.


## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
