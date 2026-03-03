# Fix: SWE-PolyBench__typescript__maintenance__bugfix__42165c4e

**Repository:** coder/code-server
**Language:** typescript
**Category:** contextbench_cross_validation

## Description

[Bug]: Can't start 2 instances of code-server `4.14.0` for separate users
### Is there an existing issue for this?

- [X] I have searched the existing issues

### OS/Web Information

- Web Browser: Chrome
- Local OS: Ubuntu
- Remote OS: Windows
- Remote Architecture: amd64
- `code-server --version`: 4.14.0


### Steps to Reproduce

1. Run `/usr/bin/code-server` for user 1 - ok
2. Run `/usr/bin/code-server` for user 2 - fails with the following


### Expected

Both instances should start

### Actual

2nd instance fails to start

### Logs

2nd instance tries to open the same file

[2023-06-19T16:15:12.625Z] info  code-server 4.14.0 9955cd91a4ca17e47d205e5acaf4c342a917a5e9
[2023-06-19T16:15:12.626Z] info  Using user-data-dir ~/code-server/user
[2023-06-19T16:15:12.629Z] error EPERM: operation not permitted, unlink '/tmp/code-server-ipc.sock'


### Screenshot/Video

_No response_

### Does this issue happen in VS Code or GitHub Codespaces?

- [X] I cannot reproduce this in VS Code.
- [X] I cannot reproduce this in GitHub Codespaces.

### Are you accessing code-server over HTTPS?

- [X] I am using HTTPS.

### Notes

It seems that every instance is trying to write to `/tmp/code-server-ipc.sock`, this was not the case in `4.13.0`. Is there a way to specify an alternate socket file for each instance?


## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
