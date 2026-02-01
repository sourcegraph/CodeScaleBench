#!/bin/bash
# Oracle solution for {instance_id}
# This applies the gold patch that fixes the issue

set -e
cd /app 2>/dev/null || cd /testbed 2>/dev/null || cd /workspace

# Apply the gold patch
cat << 'PATCH_EOF' | git apply -v -
{patch}
PATCH_EOF

echo "✓ Gold patch applied successfully"
