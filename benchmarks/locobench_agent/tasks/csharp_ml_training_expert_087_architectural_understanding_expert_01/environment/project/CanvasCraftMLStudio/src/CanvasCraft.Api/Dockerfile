# syntax=docker/dockerfile:1

#######################################################################
# CanvasCraft ML Studio – API Container                               #
#                                                                     #
# This Dockerfile builds and packages the CanvasCraft.Api ASP.NET Core#
# service using a multi-stage approach. It is optimised for small     #
# image size, build-time caching, security (non-root execution), and  #
# operational robustness (health checks & diagnostics).               #
#######################################################################

############################
# 1️⃣  Base Runtime Image  #
############################
FROM mcr.microsoft.com/dotnet/aspnet:8.0-jammy AS runtime
LABEL maintainer="CanvasCraft ML Studio <opensource@canvascraft.ai>"
WORKDIR /app

# Configure Kestrel to listen on the container-friendly port 8080
ENV ASPNETCORE_URLS=http://+:8080 \
    DOTNET_EnableDiagnostics=0              \
    DOTNET_GCHeapHardLimitPercent=60        \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false

# Expose HTTP & optional gRPC ports
EXPOSE 8080 9090

############################
# 2️⃣  Build Image         #
############################
FROM mcr.microsoft.com/dotnet/sdk:8.0-jammy AS build
ARG BUILD_CONFIGURATION=Release
ARG COMMIT_SHA=unknown
ARG BUILD_NUMBER=0
ARG VERSION=0.0.0

WORKDIR /src

# Copy solution & project files first for better layer caching
COPY ["CanvasCraft.Api/CanvasCraft.Api.csproj", "CanvasCraft.Api/"]
# If you have additional projects that the API depends on, list them here
COPY ["CanvasCraft.Application/CanvasCraft.Application.csproj", "CanvasCraft.Application/"]
COPY ["CanvasCraft.Domain/CanvasCraft.Domain.csproj", "CanvasCraft.Domain/"]
COPY ["CanvasCraft.Infrastructure/CanvasCraft.Infrastructure.csproj", "CanvasCraft.Infrastructure/"]

# Restore dependencies - separate layer for caching
RUN dotnet restore "CanvasCraft.Api/CanvasCraft.Api.csproj"

# Copy remaining source
COPY . .

# Build & publish
RUN dotnet publish "CanvasCraft.Api/CanvasCraft.Api.csproj" \
        -c $BUILD_CONFIGURATION \
        -o /app/publish          \
        /p:Version=$VERSION      \
        /p:SourceRevisionId=$COMMIT_SHA \
        /p:ContinuousIntegrationBuild=true \
        /p:PublishReadyToRun=true \
        /p:PublishTrimmed=false   \
        /p:UseAppHost=false

############################
# 3️⃣  Production Image   #
############################
FROM runtime AS final

# Add non-root user for security
RUN addgroup --gid 10001 canvas && \
    adduser  --disabled-password --gecos "" --uid 10001 --gid 10001 canvas
USER canvas

# Copy published output
COPY --from=build /app/publish/ ./

# Health check: assumes a minimal /health endpoint in the API project
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# Run the application
ENTRYPOINT ["dotnet", "CanvasCraft.Api.dll"]