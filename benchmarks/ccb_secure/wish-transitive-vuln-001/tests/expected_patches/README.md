# Expected Patches

This is an analysis-only task. No code patches are expected.

The remediation is to update dependencies:
1. Update `golang.org/x/crypto` to v0.31.0 or later
2. This will likely require updating `gliderlabs/ssh` to a version that uses the fixed crypto library
3. Then update `charmbracelet/wish` to use the updated `gliderlabs/ssh`

Or use `go get -u golang.org/x/crypto@v0.31.0` to force upgrade the transitive dependency.
