# Fix: Multi-SWE-Bench__go__maintenance__bugfix__52c152ba

**Repository:** cli/cli
**Language:** go
**Category:** contextbench_cross_validation

## Description

Get config for default host when -h is not given

<!--
  Thank you for contributing to GitHub CLI!
  To reference an open issue, please write this in your description: `Fixes #NUMBER`
-->

# What

This aligns `config get`'s behaviour with `config list` [1].

[1] https://github.com/cli/cli/blob/1f488f4d5496e176300614b7bd9ded02c8572ec3/pkg/cmd/config/list/list.go#L50-L55

# Why

I have the following configs currently:

`~/.config/gh/config.yml`:

```yaml
git_protocol: https
```

`~/.config/gh/hosts.yml`:

```yaml
github.com:
    git_protocol: ssh
```

Now in a github.com repo,

```
$ gh config list
git_protocol=ssh
editor=
prompt=enabled
pager=
http_unix_socket=
browser=

$ gh config get git_protocol
https
```

I think the output should be consistent.

Fixes #6123

## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
