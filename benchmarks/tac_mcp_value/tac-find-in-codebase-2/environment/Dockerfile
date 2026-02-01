# TAC Task Wrapper: sde-find-answer-in-codebase-2
FROM ghcr.io/theagentcompany/sde-find-answer-in-codebase-2-image:1.0.0

RUN mkdir -p /logs /workspace/tests

COPY tests/test.sh /workspace/tests/test.sh
RUN chmod +x /workspace/tests/test.sh

WORKDIR /workspace

ENV TAC_SERVER_HOSTNAME=localhost
ENV DECRYPTION_KEY="theagentcompany is all you need"

CMD ["bash"]
