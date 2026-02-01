# TAC Task Wrapper: sde-implement-hyperloglog
FROM ghcr.io/theagentcompany/sde-implement-hyperloglog-image:1.0.0

# Create logs directory for Harbor compatibility
RUN mkdir -p /logs /workspace/tests

# Copy our test wrapper script
COPY tests/test.sh /workspace/tests/test.sh
RUN chmod +x /workspace/tests/test.sh

# Set working directory
WORKDIR /workspace

# Environment variables
ENV TAC_SERVER_HOSTNAME=localhost
ENV DECRYPTION_KEY="theagentcompany is all you need"

CMD ["bash"]
