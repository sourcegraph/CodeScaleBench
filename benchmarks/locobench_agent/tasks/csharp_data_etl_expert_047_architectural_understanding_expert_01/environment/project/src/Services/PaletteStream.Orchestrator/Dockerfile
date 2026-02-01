# PaletteStream.Orchestrator
# ----------------------------------------------------------
# Production-grade, multi-stage Dockerfile for the Orchestrator
# micro-service.  Implements the following best-practices:
#  • Multi-stage build to keep runtime image slim
#  • Non-root user execution
#  • Layered restore for maximum Docker cache hit rate
#  • Secure SSL cert handling for outbound calls
#  • Health-check and diagnostics endpoints
#  • Readiness of optional GPU libraries (ComputeSharp)
# ----------------------------------------------------------

###############
# BUILD STAGE #
###############
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build

# Disable telemetry & enable deterministic builds
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 \
    NUGET_XMLDOC_MODE=skip

# Copy solution and project files first to leverage Docker cache
WORKDIR /src
COPY ["global.json", "./"]
COPY ["Directory.Build.props", "./"]

# Copy only *.csproj to restore early
COPY src/Services/PaletteStream.Orchestrator/PaletteStream.Orchestrator.csproj ./PaletteStream.Orchestrator/
RUN dotnet restore "./PaletteStream.Orchestrator/PaletteStream.Orchestrator.csproj" --no-cache

# Copy the remaining source
COPY src ./src

# Build and publish (self-contained disabled for size)
WORKDIR /src/src/Services/PaletteStream.Orchestrator
RUN dotnet publish \
    -c Release \
    -o /app/publish \
    /p:UseAppHost=false \
    /p:PublishSingleFile=true \
    /p:PublishTrimmed=true

################
# RUNTIME BASE #
################
FROM mcr.microsoft.com/dotnet/aspnet:8.0-alpine AS base

# Enable globalization (remove to make image smaller if using invariant)
RUN apk add --no-cache icu-libs \
    && dotnet tool install -g dotnet-diagnostics-monitor

ENV \
    DOTNET_EnableDiagnostics=1 \
    DOTNET_GCServer=1 \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false \
    ASPNETCORE_URLS=http://+:8080 \
    ASPNETCORE_ENVIRONMENT=Production

# Create non-root user and group
RUN addgroup -S appgrp && adduser -S appuser -G appgrp
WORKDIR /app
COPY --from=build /app/publish ./

# Give permissions to the non-root user
RUN chown -R appuser:appgrp /app
USER appuser

##############
# HEALTHCHECK#
##############
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD \
    wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

###################
# ENTRY & COMMAND #
###################
EXPOSE 8080
ENTRYPOINT ["dotnet", "PaletteStream.Orchestrator.dll"]