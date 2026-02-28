# numpy-dtype-localize-001 — multi-repo baseline
# Repos cloned into /ccb_crossrepo/src/ to match verifier expectations.
FROM ccb-repo-numpy-a639fbf5 AS numpy-src
FROM ccb-repo-scikit-learn-cb7e82dd AS sklearn-src
FROM ccb-repo-pandas-41968da5 AS pandas-src

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /ccb_crossrepo/src
COPY --from=numpy-src /workspace /ccb_crossrepo/src/numpy
COPY --from=sklearn-src /workspace /ccb_crossrepo/src/scikit-learn
COPY --from=pandas-src /workspace /ccb_crossrepo/src/pandas

WORKDIR /workspace

RUN git init && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent" && \
    git config --global safe.directory '*'
