FROM ccb-repo-k8s-8c9c67c0

# SURGICAL: Remove ONLY the target doc.go (not recursive!)
RUN rm -f staging/src/k8s.io/client-go/doc.go
# Strip "// Package ..." line from files in the immediate directory only
RUN find staging/src/k8s.io/client-go -maxdepth 1 -name "*.go" -exec sed -i '/^\/\/ Package/d' {} +

# Create test directory for verifier
RUN mkdir -p /workspace/tests

# Create /app directory for MCP config upload compatibility
RUN mkdir -p /app
