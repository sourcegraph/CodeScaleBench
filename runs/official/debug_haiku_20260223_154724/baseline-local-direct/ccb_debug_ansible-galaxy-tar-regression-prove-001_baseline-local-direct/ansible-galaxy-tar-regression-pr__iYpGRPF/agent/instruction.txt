# Bug Investigation: Galaxy Collection Tar Directory Extraction Fails for Certain Archive Layouts

**Repository:** ansible/ansible
**Task Type:** Find and Prove (write a regression test)

## Reported Issue

When installing Ansible Galaxy collections from tarball archives, the extraction process fails or behaves incorrectly for archives where directory entries have trailing path separators in their member names.

Specifically:

1. **Directory lookup uses a custom cache instead of standard tarfile API**: The collection installation code builds a private normalized-name index of tar members and uses that for directory lookups, rather than using the standard library's member lookup. This custom cache strips trailing path separators from names, which creates a fragile mismatch between how directories are looked up versus how they're actually stored in the archive.

2. **Extraction breaks when member names don't match the normalized form**: If a tar archive stores a directory entry with its canonical name (without a trailing separator), but the custom cache was built expecting to strip separators, the lookup can silently retrieve the wrong member or fail entirely.

3. **The workaround is no longer necessary**: The custom cache was originally added as a workaround for a CPython tarfile bug. On current Python versions, the standard `getmember()` API handles directory member lookups correctly, making the workaround unnecessary overhead that adds fragility.

These issues affect `ansible-galaxy collection install` when processing collection tarballs.

## Your Task

1. Investigate the codebase to find the root cause of the tar directory extraction fragility
2. Write a regression test as a single file at `/workspace/regression_test.py`
3. Your test must be self-contained and runnable with `python3 -m pytest --timeout=60 /workspace/regression_test.py`

## Constraints

- Do NOT fix the bug — only write a test that demonstrates it
- Your test must fail on the current (buggy) code for the RIGHT reason
- The test should cover: directory extraction behavior with standard tar member names, demonstrating the fragility of the custom cache approach
- Test timeout: 60 seconds
