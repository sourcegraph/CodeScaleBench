# Fix: SWE-PolyBench__javascript__maintenance__bugfix__e647c8ce

**Repository:** sveltejs/svelte
**Language:** javascript
**Category:** contextbench_cross_validation

## Description

Hydrating element removes every other attribute
I'm new to Svelte so it's entirely possible i'm missing something basic.  I'm seeing some weird behavior around the hydration feature. Attributes on the element being hydrated are removed and I'm not sure why. 

For example, given this markup:
```html
<span id="rehydrateContainer">
  <button data-track-id="123" class="button button--small" id="button" role="button" disabled>content</button>
</span>
```
and this component:
```html
<button on:click="set({ count: count + 1 })">
  {text} {count}
</button>

<script>
  export default {
    oncreate() {
      this.set({ count: 0 });
    }
  };
</script>
```
the hydrated dom ends up being this:
```html
<span id="rehydrateContainer">
  <button class="button button--small" role="button">rehydrated 0</button>
</span>
```

At first glance it seems that it maybe only works with certain attributes like `class` or `role` but that's not the case. When I change the order it seems like the odd numbered attributes are being removed.

given this:
```html
<button class="button button--small" data-track-id="123" role="button" id="button" disabled>content</button>
```

we end up with this:
```html
<button data-track-id="123" id="button">rehydrated 0</button>
```

here's a small reproduction to play around with: https://github.com/sammynave/rehydrate-attrs


## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
