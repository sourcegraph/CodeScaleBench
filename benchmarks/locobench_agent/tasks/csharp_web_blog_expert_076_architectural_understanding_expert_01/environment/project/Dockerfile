# syntax=docker/dockerfile:1.4

#########################################################
# TempoScribe Pro – Web Blog                            #
# Production-grade, multi-stage Dockerfile              #
#                                                       #
# Builds the Hexagonal C#/.NET + Blazor WebAssembly API #
# with front-end assets, runs unit/integration tests,   #
# and produces a hardened runtime image.                #
#########################################################

########################
# 1. Build & Publish   #
########################
FROM mcr.microsoft.com/dotnet/sdk:7.0 AS build

ARG BUILD_CONFIGURATION=Release
ARG COMMIT_SHA=local
ARG NUGET_SOURCE=https://api.nuget.org/v3/index.json
ARG NUGET_CONFIG=NuGet.config

# Basic environment hardening & telemetry opt-out
ENV DOTNET_ROLL_FORWARD=Major \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    COMMIT_SHA=${COMMIT_SHA}

LABEL org.opencontainers.image.source="https://github.com/temposcribe/temposcribe-pro" \
      org.opencontainers.image.revision="${COMMIT_SHA}" \
      org.opencontainers.image.title="TempoScribe Pro – Web Blog (builder)" \
      org.opencontainers.image.version="1.0.0"

# Install Node LTS + Yarn for front-end (Tailwind, Blazor WASM assets, etc.)
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get update && apt-get install -y nodejs --no-install-recommends \
    && npm install -g yarn \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Copy solution & NuGet config first to leverage Docker cache
COPY ["TempoScribePro.sln", "./"]
COPY ["${NUGET_CONFIG}", "./"]

# Copy individual project files for deterministic layer caching
COPY ["src/TempoScribePro.Domain/TempoScribePro.Domain.csproj", "src/TempoScribePro.Domain/"]
COPY ["src/TempoScribePro.Infrastructure/TempoScribePro.Infrastructure.csproj", "src/TempoScribePro.Infrastructure/"]
COPY ["src/TempoScribePro.Application/TempoScribePro.Application.csproj", "src/TempoScribePro.Application/"]
COPY ["src/TempoScribePro.Adapters.Persistence.Sql/TempoScribePro.Adapters.Persistence.Sql.csproj", "src/TempoScribePro.Adapters.Persistence.Sql/"]
COPY ["src/TempoScribePro.Adapters.Payments.Stripe/TempoScribePro.Adapters.Payments.Stripe.csproj", "src/TempoScribePro.Adapters.Payments.Stripe/"]
COPY ["src/TempoScribePro.Adapters.Caching.Redis/TempoScribePro.Adapters.Caching.Redis.csproj", "src/TempoScribePro.Adapters.Caching.Redis/"]
COPY ["src/TempoScribePro.Web.Blog/TempoScribePro.Web.Blog.csproj", "src/TempoScribePro.Web.Blog/"]

# Restore packages (using explicit source helps in air-gapped environments)
RUN dotnet restore "TempoScribePro.sln" --source ${NUGET_SOURCE}

# Copy rest of the source code
COPY . .

# Build, test, and publish to /app/publish
RUN dotnet build "TempoScribePro.sln" -c ${BUILD_CONFIGURATION} --no-restore \
    && dotnet test  "tests/TempoScribePro.Tests.Unit/TempoScribePro.Tests.Unit.csproj"         -c ${BUILD_CONFIGURATION} --no-build --verbosity normal \
    && dotnet test  "tests/TempoScribePro.Tests.Integration/TempoScribePro.Tests.Integration.csproj" -c ${BUILD_CONFIGURATION} --no-build --verbosity normal \
    && dotnet publish "src/TempoScribePro.Web.Blog/TempoScribePro.Web.Blog.csproj" \
         -c ${BUILD_CONFIGURATION} \
         -o /app/publish \
         /p:PublishTrimmed=true \
         /p:PublishReadyToRun=true \
         /p:UseAppHost=false

########################
# 2. Runtime Image     #
########################
FROM mcr.microsoft.com/dotnet/aspnet:7.0-alpine AS runtime

# Add non-root user for least-privilege execution
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

ENV ASPNETCORE_ENVIRONMENT=Production \
    ASPNETCORE_URLS=http://+:8080 \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false

LABEL org.opencontainers.image.title="TempoScribe Pro – Web Blog" \
      org.opencontainers.image.description="High-performance Hexagonal CMS geared toward productivity engineering." \
      org.opencontainers.image.authors="TempoScribe DevOps <devops@temposcribe.io>"

WORKDIR /app

# Copy published output from build stage
COPY --from=build /app/publish ./

# Health endpoint check
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD wget -qO- http://localhost:8080/health || exit 1

EXPOSE 8080

# Ensure correct permissions & switch to non-root user
RUN chown -R appuser:appgroup /app
USER appuser

# Launch the application
ENTRYPOINT ["dotnet", "TempoScribePro.Web.Blog.dll"]