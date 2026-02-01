# syntax=docker/dockerfile:1.4

############################
# 1️⃣  BUILD STAGE
############################
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build

ARG BUILD_CONFIGURATION=Release
ARG VERSION=1.0.0
ARG COMMIT_SHA=dev

WORKDIR /src

# Copy solution file and restore as distinct layers for better build-cache utilisation
COPY PaletteStream-ETL-Canvas.sln ./

# Copy only the ingestion project file first, allowing Docker to cache `dotnet restore`
COPY src/Services/PaletteStream.Ingestion/PaletteStream.Ingestion.csproj src/Services/PaletteStream.Ingestion/
RUN dotnet restore src/Services/PaletteStream.Ingestion/PaletteStream.Ingestion.csproj

# Copy the rest of the repository
COPY . .

# Publish the ingestion service
RUN dotnet publish src/Services/PaletteStream.Ingestion/PaletteStream.Ingestion.csproj \
    --configuration $BUILD_CONFIGURATION \
    --output /app/publish \
    /p:ContinuousIntegrationBuild=true \
    /p:Version=$VERSION \
    /p:SourceRevisionId=$COMMIT_SHA

############################
# 2️⃣  RUNTIME STAGE
############################
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime

# Runtime environment variables
ENV ASPNETCORE_URLS=http://+:8080 \
    ASPNETCORE_ENVIRONMENT=Production \
    DOTNET_EnableDiagnostics=0 \
    DOTNET_gcServer=1 \
    TZ=UTC

# OCI-compliant labels
LABEL org.opencontainers.image.title="PaletteStream.Ingestion" \
      org.opencontainers.image.description="Ingestion microservice for PaletteStream ETL Canvas" \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$COMMIT_SHA \
      org.opencontainers.image.authors="PaletteStream Engineering <engineering@palettestream.io>" \
      org.opencontainers.image.licenses="Apache-2.0"

# Create a non-root user for enhanced security
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app
COPY --from=build /app/publish .

# Expose HTTP port
EXPOSE 8080

# Health-check hits the built-in health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget --quiet --spider http://localhost:8080/health || exit 1

# Run as non-root
USER app

# Launch the service
ENTRYPOINT ["dotnet", "PaletteStream.Ingestion.dll"]