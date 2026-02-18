# Navprove Task Environment
# Source: qutebrowser/qutebrowser (deeb15d6)

FROM jefzda/sweap-images:qutebrowser.qutebrowser-qutebrowser__qutebrowser-deeb15d6f009b3ca0c3bd503a7cef07462bd16b4-v363c8a7e5ccdf6968fc7ab84a2053ac780366

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Install test dependencies
RUN pip install pytest pytest-timeout || true

# Create required directories for Harbor
RUN mkdir -p /logs

# SWE-bench Pro images have the repository at /app
# Symlink /workspace -> /app so verifier PATCH_APPLY_DIR works
RUN ln -sf /app /workspace || true

WORKDIR /app

ENTRYPOINT []
