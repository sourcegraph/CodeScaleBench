FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && apt-get install -y -qq \
    python3 python3-pip git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install .NET SDK
RUN apt-get update -qq && apt-get install -y -qq wget && \
    wget -q https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb && \
    dpkg -i packages-microsoft-prod.deb && rm packages-microsoft-prod.deb && \
    apt-get update -qq && apt-get install -y -qq dotnet-sdk-8.0
# Copy repo
COPY repo /app/repo

WORKDIR /app/repo
