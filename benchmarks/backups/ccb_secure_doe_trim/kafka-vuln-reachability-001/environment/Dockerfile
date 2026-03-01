FROM eclipse-temurin:17-jdk-jammy

# Install required tools for verification
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    jq \
    bc \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Clone Apache Kafka at pre-fix commit (vulnerable version)
# Pre-fix commit: 0cd95bc2d82106ea9fb36061d8419f7fc9051d69
# This is the parent of the fix commit b385b38e56990a9d3e22f752422e8be812cf0d5d
WORKDIR /workspace
RUN git clone --depth 1 https://github.com/sg-evals/kafka--0cd95bc2.git kafka && \
    echo "Kafka repository at pre-fix commit (vulnerable SCRAM nonce validation)"

# Create output directory
RUN mkdir -p /logs/agent

WORKDIR /workspace/kafka
