# python-http-class-naming-refac-001 — multi-repo baseline
# Repos cloned into /ccb_crossrepo/src/ to match verifier expectations.
FROM ccb-repo-django-674eda1c AS django-src
FROM ccb-repo-flask-798e006f AS flask-src
FROM ccb-repo-requests-421b8733 AS requests-src

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /ccb_crossrepo/src
COPY --from=django-src /workspace /ccb_crossrepo/src/django
COPY --from=flask-src /workspace /ccb_crossrepo/src/flask
COPY --from=requests-src /workspace /ccb_crossrepo/src/requests

WORKDIR /workspace

RUN git init && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent" && \
    git config --global safe.directory '*'
