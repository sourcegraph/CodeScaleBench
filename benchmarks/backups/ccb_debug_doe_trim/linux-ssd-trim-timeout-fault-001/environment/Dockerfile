FROM gcc:13

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip git curl ca-certificates \
    gawk bc bison flex libssl-dev libelf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Shallow clone Linux kernel at v4.14.114.
# Try stable tree first, fall back to mainline for release candidates.
RUN (git clone --depth 1 --branch v4.14.114 --no-tags \
        https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git . \
    || git clone --depth 1 --branch v4.14.114 --no-tags \
        https://github.com/torvalds/linux.git .) && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
