# Fix: Multi-SWE-Bench__typescript__maintenance__bugfix__05c53458

**Repository:** mui/material
**Language:** typescript
**Category:** contextbench_cross_validation

## Description

[AvatarGroup] Allow specifying total number of avatars

<!-- Thanks so much for your PR, your contribution is appreciated! ❤️ -->

- [x] I have followed (at least) the [PR section of the contributing guide](https://github.com/mui-org/material-ui/blob/HEAD/CONTRIBUTING.md#sending-a-pull-request).

Closes #29649 

Allow the developer to specify a `total` number of avatars. If a `total` is provided, all `AvatarGroup` calculations will be based on this number, rather than relying solely on `children.length`.

This is useful in use cases where the avatars are based on paginated lists and the server exposes the total count. There shouldn't be a need to request the whole list from the server (or to generate a list with that length) just to fulfil the requirement of the `AvatarGroup`.

## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
