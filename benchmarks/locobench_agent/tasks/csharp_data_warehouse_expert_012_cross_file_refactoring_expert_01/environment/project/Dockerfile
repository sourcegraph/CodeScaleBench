# syntax=docker/dockerfile:1

#######################################################################
#  PulseOps Warehouse – Serverless Productivity Intelligence Fabric   #
#  Multi-stage Dockerfile                                             #
#                                                                     #
#  Stage 1  : build-env  -> Restores, builds, tests, and packages all  #
#                            .NET 7 Lambda functions & CDK constructs #
#  Stage 2  : runtime    -> Lightweight image containing ready-to-use #
#                            Lambda artifacts for local invocation    #
#######################################################################

############################
# Stage 1 – Build & Test   #
############################
FROM mcr.microsoft.com/dotnet/sdk:7.0-alpine AS build-env

LABEL maintainer="PulseOps Engineering <eng@pulseops.io>" \
      org.opencontainers.image.source="https://github.com/pulseops/warehouse" \
      org.opencontainers.image.description="Build image for PulseOps Warehouse (serverless data-warehouse written in C#)"

ARG CDK_VERSION=2.138.0
ARG LAMBDA_TOOLS_VERSION=5.10.0

# -----------------------------------------------------------------------------
# Install OS build dependencies
# -----------------------------------------------------------------------------
RUN apk add --no-cache \
        bash \
        git \
        curl \
        openssh-client \
        python3 \
        py3-pip \
        nodejs \
        npm

# -----------------------------------------------------------------------------
# Install global .NET & Node tooling
#   • Amazon.Lambda.Tools  – CLI helper for packaging/deploying .NET Lambdas
#   • AWS CDK              – Synthesis & diff of IaC (required for CI jobs)
# -----------------------------------------------------------------------------
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    PATH="$PATH:/root/.dotnet/tools"

RUN dotnet tool install -g Amazon.Lambda.Tools --version ${LAMBDA_TOOLS_VERSION} && \
    npm -g config set user 0 && \
    npm -g config set unsafe-perm true && \
    npm install -g aws-cdk@${CDK_VERSION}

# -----------------------------------------------------------------------------
# Copy solution & restore dependencies
#   • Using separate COPY commands keeps Docker cache efficient
#   • Cache NuGet packages for faster iterative builds
# -----------------------------------------------------------------------------
WORKDIR /src

COPY PulseOpsWarehouse.sln ./
COPY src/**/*.csproj      ./src/
COPY tests/**/*.csproj    ./tests/

# Restore with NuGet cache mounted as a distinct layer
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet restore -p:ContinuousIntegrationBuild=true

# -----------------------------------------------------------------------------
# Copy the full source-tree and perform build, test, and publish
# -----------------------------------------------------------------------------
COPY src ./src
COPY tests ./tests

# Build (compile only; no publish yet)
RUN dotnet build -c Release -p:ContinuousIntegrationBuild=true --no-restore

# Run unit tests, outputting TRX for Azure DevOps / GitHub Actions publishing
RUN dotnet test -c Release --no-build --logger "trx;LogFileName=test_results.trx"

# -----------------------------------------------------------------------------
# Package every Lambda project (*.Lambda.csproj) into zip bundles
# Artifacts are dropped into /artifacts for use in subsequent stages.
# -----------------------------------------------------------------------------
RUN mkdir /artifacts && \
    for project in $(find ./src -name "*.Lambda.csproj"); do \
        echo "📦 Packaging Lambda: ${project}" ; \
        dotnet lambda package \
            --project-location "$project" \
            --configuration Release \
            --framework net7.0 \
            --output-package "/artifacts/$(basename ${project%.*}).zip" ; \
    done

# -----------------------------------------------------------------------------
# CDK synth – generate CloudFormation template to validate IaC
# -----------------------------------------------------------------------------
RUN if [ -d "./src/Infrastructure" ]; then \
        cd ./src/Infrastructure && \
        echo "🛠  Synthesizing CDK stack…" && \
        cdk synth --output /artifacts; \
    fi

############################
# Stage 2 – Runtime Image  #
############################
FROM public.ecr.aws/lambda/dotnet:7 AS runtime

LABEL maintainer="PulseOps Engineering <eng@pulseops.io>" \
      org.opencontainers.image.description="Runtime image containing packaged PulseOps Warehouse Lambda functions"

# Non-root best practice (UID 1001 is arbitrary but > 1000)
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser:appuser /var/task
USER appuser

WORKDIR /var/task

# Bring in published artifacts from build stage
COPY --from=build-env --chown=appuser:appuser /artifacts ./artifacts

# Default entrypoint simply lists built artifacts.
# Override in `docker run` for local Lambda invocations (e.g., using AWS SAM CLI).
CMD [ "/bin/bash", "-c", "echo '📦 Lambda artifact listing:' && ls -al ./artifacts" ]

#######################################################################
# Usage                                                              #
#   Build:   docker build -t pulseops/warehouse:latest .             #
#   Run:     docker run --rm pulseops/warehouse:latest               #
#   Inspect: docker run -it --entrypoint /bin/bash pulseops/warehouse#
#######################################################################
