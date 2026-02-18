FROM golang:1.23-alpine AS base

# Install git for cloning
RUN apk add --no-cache git bash

# Clone repos at pinned commits
WORKDIR /workspace

# Clone kubernetes/kubernetes
RUN git clone https://github.com/kubernetes/kubernetes.git kubernetes && \
    cd kubernetes && \
    git checkout 31bf3ed48b91b67e5003d8df1b3bd0b918d1fb94

# Clone kubernetes/api (synced from k/k staging)
RUN git clone https://github.com/kubernetes/api.git api && \
    cd api && \
    git checkout f32ed1d60cf0787a512bebd6c06a4b84ae0b7cc7

# Clone kubernetes/apimachinery
RUN git clone https://github.com/kubernetes/apimachinery.git apimachinery && \
    cd apimachinery && \
    git checkout b2e9f88ff6d4c50c13061a53b1239c7707354eda

# Verify repos exist
RUN ls -la /workspace/ && \
    test -d /workspace/kubernetes && \
    test -d /workspace/api && \
    test -d /workspace/apimachinery

FROM base AS final
WORKDIR /workspace
CMD ["/bin/bash"]
