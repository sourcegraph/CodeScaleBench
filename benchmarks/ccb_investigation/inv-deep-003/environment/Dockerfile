FROM ubuntu:22.04

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Clone Terraform at the pre-fix commit for the sensitive marks bug.
# PR #34567 (merge commit c4a2f74054a9) fixes the bug where provider-schema-
# defined sensitive attributes are not applied to values returned by
# ReadResource / PlanResourceChange, causing phantom diffs and incomplete
# sensitive_attributes in state.
# We check out the parent commit (9658f9df) to get the broken state.
RUN git clone --filter=blob:none --no-checkout https://github.com/hashicorp/terraform.git . && \
    git checkout 9658f9df6b24bd6d2c267c07cffd4c97cf8b9b40 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
