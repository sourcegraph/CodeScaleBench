# Bug Investigation: Non-legacy mail content fails to decrypt

**Repository:** tutao/tutanota
**Task Type:** Find and Prove (write a regression test)

## Reported Issue

Users who have accounts with the new (non-legacy) permission model report that opening certain emails results in blank message bodies, missing reply-to addresses, and missing attachment listings. The browser console shows "Missing decryption key" errors when these mails are opened.

The issue specifically affects mails that use owner-encrypted session keys under the new permission model. Legacy mails continue to work correctly. The problem manifests when:

1. Opening a non-legacy mail in the inbox — the body fails to render
2. Opening a draft with reply-to recipients — the reply-to list cannot be loaded
3. The mail indexer/search encounters non-legacy mails — indexing fails silently with decryption errors

The root cause involves how encrypted session keys are propagated when loading related entities. When the application loads supplementary mail data (body content, draft details), the session key needed for decryption is available from the parent mail object but is not being passed through to the entity loading and caching layers. This means the loaded entities cannot be decrypted even though the necessary key exists.

Additionally, batch loading of multiple entities has the same propagation gap — when loading several related items at once, the per-entity session keys are not forwarded to the decryption step.

## Your Task

1. Investigate the codebase to find the root cause of the missing key propagation
2. Write a regression test as a single file at `/workspace/regression_test.test.ts`
3. Your test must be self-contained and runnable with `npx jest --timeout=60000 /workspace/regression_test.test.ts`

## Constraints

- Do NOT fix the bug — only write a test that demonstrates it
- Your test must fail for the RIGHT reason (decryption key not propagated, not some other error)
- Test timeout: 60 seconds
