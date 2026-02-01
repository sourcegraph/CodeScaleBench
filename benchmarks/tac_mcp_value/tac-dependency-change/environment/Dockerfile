# TAC Task Wrapper: sde-dependency-change-1
FROM ghcr.io/theagentcompany/sde-dependency-change-1-image:1.0.0

RUN mkdir -p /logs /workspace/tests

COPY tests/test.sh /workspace/tests/test.sh
RUN chmod +x /workspace/tests/test.sh

WORKDIR /workspace

ENV TAC_SERVER_HOSTNAME=localhost
ENV DECRYPTION_KEY="theagentcompany is all you need"

CMD ["bash"]
