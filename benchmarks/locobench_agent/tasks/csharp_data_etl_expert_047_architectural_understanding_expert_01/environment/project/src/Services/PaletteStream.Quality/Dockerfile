# syntax=docker/dockerfile:1.4
################################################################################
# PaletteStream.Quality – Data-Quality Microservice
#
# Multi-stage Dockerfile that:
#   1. Restores NuGet packages with caching
#   2. Builds and unit-tests the service (fail-fast if tests break)
#   3. Publishes a self-contained, trimmed build
#   4. Runs the service as a non-root user with a healthcheck
#
# NOTE:
#   • Assumes the solution root is two directories up from this Dockerfile
#   • Expects a solution file   : PaletteStream.ETL.Canvas.sln
#   • Expects project file path : /src/Services/PaletteStream.Quality/PaletteStream.Quality.csproj
################################################################################

########################
# 1️⃣ Restore & Build
########################
FROM mcr.microsoft.com/dotnet/sdk:8.0-alpine AS build
ARG BUILD_CONFIGURATION=Release
WORKDIR /src

# Copy solution and project files first to leverage Docker layer caching
COPY ../../PaletteStream.ETL.Canvas.sln ./
COPY ../../Directory.Build.* ./
COPY ../../src/Services/PaletteStream.Quality/PaletteStream.Quality.csproj \
     ./src/Services/PaletteStream.Quality/
RUN dotnet restore PaletteStream.ETL.Canvas.sln --configfile /root/.nuget/NuGet.Config

# Copy the remaining source code
COPY ../../ ./

# Build (no publish) to ensure compile errors surface early
RUN dotnet build PaletteStream.ETL.Canvas.sln --configuration ${BUILD_CONFIGURATION} --no-restore

########################
# 2️⃣ Run Unit / Integration Tests
########################
FROM build AS test
# Run tests with code coverage enabled; fail the build if any test fails
RUN dotnet test PaletteStream.ETL.Canvas.sln \
        --configuration ${BUILD_CONFIGURATION} \
        --no-build --verbosity normal \
        --collect:"XPlat Code Coverage"

########################
# 3️⃣ Publish
########################
FROM build AS publish
# Publish a self-contained, trimmed binary for Linux-musl (Alpine)
RUN dotnet publish src/Services/PaletteStream.Quality/PaletteStream.Quality.csproj \
        --configuration ${BUILD_CONFIGURATION} \
        --runtime linux-musl-x64 \
        --self-contained true \
        /p:PublishTrimmed=true /p:PublishSingleFile=true \
        --no-build \
        --output /app/publish

########################
# 4️⃣ Final Runtime Image
########################
FROM mcr.microsoft.com/dotnet/runtime-deps:8.0-alpine AS runtime

# Security: add a non-root user to run the service
RUN addgroup --system --gid 1001 appgroup && \
    adduser  --system --uid 1001 --ingroup appgroup --shell /sbin/nologin appuser

# Copy published output
WORKDIR /app
COPY --from=publish /app/publish .

# Configure ASP.NET Core for optimal container behavior
ENV ASPNETCORE_URLS=http://+:8080 \
    DOTNET_EnableDiagnostics=0 \
    DOTNET_GCServer=1 \
    DOTNET_TieredPGO=1

# Expose the HTTP port
EXPOSE 8080

# Add a basic healthcheck that verifies the liveness endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
           CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health/live || exit 1

# Drop privs and launch the application
USER appuser

ENTRYPOINT ["./PaletteStream.Quality"]