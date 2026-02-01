# syntax=docker/dockerfile:1.5

################################################################################
# PaletteStream.Loader — Container Image
#
# This Dockerfile produces a minimal, production-ready container image for the
# “PaletteStream.Loader” micro-service.  The build leverages a multi-stage
# pipeline to:
#   1. Restore NuGet packages & resolve dependencies
#   2. Build the service with Release optimizations
#   3. Execute the full test suite (fail fast on test errors)
#   4. Publish self-contained output trimmed for Alpine Linux
#
# A lean, non-root runtime image is emitted that includes health-checks and
# sensible metadata for observability platforms (OpenTelemetry, Prometheus).
################################################################################

########################
# Build/Test Stage
########################
ARG DOTNET_VERSION=8.0
ARG BUILD_CONFIGURATION=Release

FROM mcr.microsoft.com/dotnet/sdk:${DOTNET_VERSION} AS build

# ==== Metadata ================================================================
LABEL org.opencontainers.image.title="PaletteStream.Loader"
LABEL org.opencontainers.image.description="ETL Loader service for PaletteStream Canvas."
LABEL org.opencontainers.image.source="https://github.com/PaletteStream/PaletteStream-ETL-Canvas"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.revision="${VCS_REF}"

# ==== Environment =============================================================
ENV DOTNET_EnableDiagnostics=0 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    ASPNETCORE_URLS=http://+:8080

WORKDIR /src

# ==== Copy csproj and restore early (leveraging Docker cache) ================
COPY ["src/Services/PaletteStream.Loader/PaletteStream.Loader.csproj", "src/Services/PaletteStream.Loader/"]
# If the solution references shared libraries, copy their csproj files too:
COPY ["src/BuildingBlocks/*.csproj", "src/BuildingBlocks/"]

RUN dotnet restore "src/Services/PaletteStream.Loader/PaletteStream.Loader.csproj" --verbosity minimal

# ==== Copy the remaining source, then build ===================================
COPY . .

RUN dotnet build "src/Services/PaletteStream.Loader/PaletteStream.Loader.csproj" \
    -c ${BUILD_CONFIGURATION} -o /artifacts --no-restore

# ==== Execute the complete test suite =========================================
# If any test fails, the build is aborted.
RUN dotnet test "tests" \
    --configuration ${BUILD_CONFIGURATION} \
    --logger "trx;LogFileName=test_results.trx" \
    --results-directory /artifacts/test-results \
    --no-restore --no-build

# ==== Publish trimmed, self-contained binaries ================================
RUN dotnet publish "src/Services/PaletteStream.Loader/PaletteStream.Loader.csproj" \
    -c ${BUILD_CONFIGURATION} \
    -o /app \
    --no-restore \
    -p:PublishReadyToRun=true \
    -p:PublishTrimmed=true \
    -p:TrimMode=Link \
    -p:SelfContained=false

########################
# Runtime Stage
########################
FROM mcr.microsoft.com/dotnet/runtime-deps:${DOTNET_VERSION}-alpine AS runtime

# ==== Security: create non-root user ==========================================
RUN addgroup --system --gid 1001 palette && \
    adduser  --system --uid 1001 --ingroup palette --home /app palette

WORKDIR /app

# ==== Copy published output from build stage ==================================
COPY --from=build /app .

# ==== Healthcheck =============================================================
HEALTHCHECK --interval=30s --timeout=5s \
    CMD wget --quiet --tries=1 --spider http://localhost:8080/health || exit 1

# ==== Expose service port =====================================================
EXPOSE 8080

USER palette

# ==== Entry point =============================================================
ENTRYPOINT ["dotnet", "PaletteStream.Loader.dll"]