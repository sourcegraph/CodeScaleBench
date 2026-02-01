# --------------------------------------------------------------------------------------------------
# Dockerfile for PaletteStream.ApiGateway
# --------------------------------------------------------------------------------------------------
# This multi-stage build produces a small, production-ready container image for the
# PaletteStream.ApiGateway ASP.NET Core micro-service (YARP reverse proxy).
#
# Stages:
#   1. build-base  : Restores dependencies
#   2. build       : Compiles, tests, and publishes the application
#   3. runtime     : Final minimal image with non-root user, health-check, and metadata
# --------------------------------------------------------------------------------------------------

# --------------------------------------------------------------------------------------------------
# Stage 1 – Build base (restore NuGet packages)
# --------------------------------------------------------------------------------------------------
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build-base

ARG BUILD_CONFIGURATION=Release
ARG NUGET_LOG=https://api.nuget.org/v3/index.json

ENV DOTNET_NOLOGO=1 \
    DOTNET_SDK_VERSION=8.0 \
    NUGET_PACKAGES=/root/.nuget/packages \
    aspnetcore_environment=Production

WORKDIR /src

# Copy solution and project files first to leverage Docker layer caching for restores.
COPY ["./PaletteStream.ApiGateway/PaletteStream.ApiGateway.csproj", "PaletteStream.ApiGateway/"]

# Optional: copy referenced projects to satisfy transitive restore (improves cache hits)
COPY ["./PaletteStream.Common/PaletteStream.Common.csproj", "PaletteStream.Common/"]

RUN dotnet restore "PaletteStream.ApiGateway/PaletteStream.ApiGateway.csproj" \
    --configfile $HOME/.nuget/NuGet.Config \
    --source ${NUGET_LOG} \
    --verbosity minimal

# --------------------------------------------------------------------------------------------------
# Stage 2 – Build, test, and publish
# --------------------------------------------------------------------------------------------------
FROM build-base AS build

# Copy the full source tree and compile
COPY . .

# Optionally, run unit tests
# RUN dotnet test ./tests/PaletteStream.ApiGateway.Tests/PaletteStream.ApiGateway.Tests.csproj --configuration ${BUILD_CONFIGURATION} --no-build --verbosity normal

# Publish trimmed, self-contained build (no apphost to reduce size)
RUN dotnet publish "PaletteStream.ApiGateway/PaletteStream.ApiGateway.csproj" \
    -c ${BUILD_CONFIGURATION} \
    -o /app/publish \
    -p:PublishTrimmed=true \
    -p:PublishSingleFile=false \
    -p:UseAppHost=false

# --------------------------------------------------------------------------------------------------
# Stage 3 – Runtime (slim ASP.NET Core runtime image)
# --------------------------------------------------------------------------------------------------
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime

ARG GIT_COMMIT=unknown
ARG BUILD_NUMBER=0
ARG SERVICE_NAME=PaletteStream.ApiGateway

# ---------------------------
# Labels for traceability
# ---------------------------
LABEL maintainer="PaletteStream Engineering <eng@palettestream.io>" \
      org.opencontainers.image.title="${SERVICE_NAME}" \
      org.opencontainers.image.description="PaletteStream ETL Canvas – API Gateway Service" \
      org.opencontainers.image.version="${BUILD_NUMBER}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.source="https://github.com/PaletteStream/etl-canvas" \
      org.opencontainers.image.documentation="https://docs.palettestream.io"

# ---------------------------
# Environment
# ---------------------------
ENV ASPNETCORE_URLS=http://0.0.0.0:8080 \
    DOTNET_EnableDiagnostics=0 \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    TZ=UTC

WORKDIR /app

# ---------------------------
# Copy build artifacts
# ---------------------------
COPY --from=build /app/publish .

# --------------------------------------------------------------------
# Security hardening: create a non-root user with minimal privileges
# --------------------------------------------------------------------
RUN addgroup --system dotnet && adduser --system --ingroup dotnet dotnetuser \
    && chown -R dotnetuser:dotnet /app

USER dotnetuser

# ---------------------------
# Networking
# ---------------------------
EXPOSE 8080

# ---------------------------
# Health check: expects minimal /healthz endpoint within service
# ---------------------------
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/healthz || exit 1

# ---------------------------
# Entrypoint
# ---------------------------
ENTRYPOINT ["dotnet", "PaletteStream.ApiGateway.dll"]