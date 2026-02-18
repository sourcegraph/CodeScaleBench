# Navprove Task Environment
# Source: flipt-io/flipt (6fe76d02)

FROM jefzda/sweap-images:flipt-io.flipt-flipt-io__flipt-6fe76d024ee0c50ddb09c86f4ae0bd4c208fd65f

# Create required directories for Harbor
RUN mkdir -p /logs

# SWE-bench Pro images have the repository at /app
# Symlink /workspace -> /app so verifier PATCH_APPLY_DIR works
RUN ln -sf /app /workspace || true

WORKDIR /app

ENTRYPOINT []
