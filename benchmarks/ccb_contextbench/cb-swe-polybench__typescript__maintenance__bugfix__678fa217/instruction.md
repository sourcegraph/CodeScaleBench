# Fix: SWE-PolyBench__typescript__maintenance__bugfix__678fa217

**Repository:** mui/material-ui
**Language:** typescript
**Category:** contextbench_cross_validation

## Description

[ButtonBase] Unfocus does not clear ripple
<!-- Provide a general summary of the issue in the Title above -->

keyboard tab between ButtonBase component does not clear the focus ripple. I can confirm that revert the code on this commit does not have this issue (in `ButtonBase.js`). https://github.com/mui-org/material-ui/commit/5f30983bfa16195237fde55a78d5e43b151a29fa

cc @michaldudak can you help take a look?

<!--
  Thank you very much for contributing to Material-UI by creating an issue! ❤️
  To avoid duplicate issues we ask you to check off the following list.
-->

<!-- Checked checkbox should look like this: [x] -->

- [x] The issue is present in the latest release.
- [x] I have searched the [issues](https://github.com/mui-org/material-ui/issues) of this repository and believe that this is not a duplicate.

## Current Behavior 😯

<!-- Describe what happens instead of the expected behavior. -->

<img width="1440" alt="Screen Shot 2564-09-06 at 14 58 24" src="https://user-images.githubusercontent.com/18292247/132181388-0bdc536c-db56-4330-97a8-8e6b2542e371.png">

## Expected Behavior 🤔

it should clear the ripple element
<!-- Describe what should happen. -->

## Steps to Reproduce 🕹

<!--
  Provide a link to a live example (you can use codesandbox.io) and an unambiguous set of steps to reproduce this bug.
  Include code to reproduce, if relevant (which it most likely is).

  You should use the official codesandbox template as a starting point: https://material-ui.com/r/issue-template-next

  If you have an issue concerning TypeScript please start from this TypeScript playground: https://material-ui.com/r/ts-issue-template

  Issues without some form of live example have a longer response time.
-->

Steps:

1. open https://next.material-ui.com/components/buttons/#main-content
2. tab through the docs
3.
4.

## Context 🔦

<!--
  What are you trying to accomplish? How has this issue affected you?
  Providing context helps us come up with a solution that is most useful in the real world.
-->

## Your Environment 🌎

<!--
  Run `npx @mui/envinfo` and post the results.
  If you encounter issues with TypeScript please include the used tsconfig.
-->
<details>
  <summary>`npx @mui/envinfo`</summary>
  
```
  Don't forget to mention which browser you used.
  Output from `npx @mui/envinfo` goes here.
```
</details>



## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
