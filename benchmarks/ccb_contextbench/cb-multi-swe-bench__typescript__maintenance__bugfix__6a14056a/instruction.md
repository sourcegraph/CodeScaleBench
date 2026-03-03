# Fix: Multi-SWE-Bench__typescript__maintenance__bugfix__6a14056a

**Repository:** vuejs/core
**Language:** typescript
**Category:** contextbench_cross_validation

## Description

feat(custom-element): inject child components styles to custom element shadow root

close #4662
close #6610
close #7941

This references both #6610 and #7942 but implements it in a way that minimizes changes to `runtime-core` and also handles HMR for child-injected styles, without relying on changes to `@vitejs/plugin-vue`.

With this change, a `*.ce.vue` component can import other `*.ce.vue` components and use them directly as Vue child components instead of custom elements. Child component's styles will be injected as native `<style>` tags into the root custom element's shadow root:

```js
import { defineCustomElement } from 'vue'
import Root from './Root.ce.vue'

customElements.define('my-el', defineCustomElement(Root))
```

```vue
<!-- Root.ce.vue -->
<script setup>
import Child from './Child.ce.vue'
</script>
```

```vue
<!-- Child.ce.vue -->
<style>
div { color: red }; /* will be injected to Root.ce.vue's shadow root */
</style>
```

## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
