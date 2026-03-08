FROM golang:1.23-alpine AS base

# Install git, bash, and python3 (needed by verifier test.sh scoring)
RUN apk add --no-cache git bash python3

# Clone repos at pinned commits
WORKDIR /workspace

# Clone kubernetes/kubernetes
RUN git clone --depth 1 https://github.com/sg-evals/kubernetes--31bf3ed4.git kubernetes

# Clone kubernetes/api (synced from k/k staging)
RUN git clone --depth 1 https://github.com/sg-evals/api--f32ed1d6.git api

# Clone kubernetes/apimachinery
RUN git clone --depth 1 https://github.com/sg-evals/apimachinery--b2e9f88f.git apimachinery

# Verify repos exist
RUN ls -la /workspace/ && \
    test -d /workspace/kubernetes && \
    test -d /workspace/api && \
    test -d /workspace/apimachinery

FROM base AS final
WORKDIR /workspace
CMD ["/bin/bash"]
