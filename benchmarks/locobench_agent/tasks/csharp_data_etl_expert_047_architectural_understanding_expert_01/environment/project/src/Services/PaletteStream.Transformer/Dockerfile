# -------------------------------------------------------------------------
#  PaletteStream Transformer Service · Dockerfile
#  ------------------------------------------------
#  This Dockerfile builds and packages the PaletteStream Transformer
#  micro-service as a lean, production-ready OCI image.
#
#  Key features:
#    • Multi-stage build (restore → build → publish → runtime)
#    • Deterministic versioning through build-args
#    • Optimised single-file publish with trimming & Ready-To-Run
#    • Health-check for active container monitoring
#    • Runs as non-root user for improved security
# -------------------------------------------------------------------------

#############################
#        Build Stage        #
#############################
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build

# ---- Build-time metadata ---------------------------
ARG BUILD_CONFIGURATION=Release
ARG VERSION=0.0.1
ARG VCS_REF=unknown
ARG BUILD_DATE
LABEL org.opencontainers.image.created=$BUILD_DATE \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$VCS_REF \
      org.opencontainers.image.title="PaletteStream Transformer" \
      org.opencontainers.image.description="PaletteStream ETL Canvas ‑ Transformer microservice"

# ---- Restore dependencies --------------------------
WORKDIR /src

# Copy project files first to leverage Docker cache layers
COPY Directory.Build.* ./
COPY src/Services/PaletteStream.Transformer/PaletteStream.Transformer.csproj ./src/Services/PaletteStream.Transformer/

# Restore without caching artifacts between builds
RUN dotnet restore \
      ./src/Services/PaletteStream.Transformer/PaletteStream.Transformer.csproj \
      --disable-parallel --nologo

# ---- Build the application -------------------------
# Copy the remainder of the source code
COPY . .

# Build & publish as a trimmed, self-contained single file
RUN dotnet publish \
      ./src/Services/PaletteStream.Transformer/PaletteStream.Transformer.csproj \
      -c $BUILD_CONFIGURATION -p:Version=$VERSION \
      -p:PublishTrimmed=true -p:PublishSingleFile=true \
      -p:IncludeNativeLibrariesForSelfExtract=true \
      -p:ReadyToRun=true \
      -o /app/publish

#############################
#     Runtime Base Image    #
#############################
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime

# ---- Environment tuning ----------------------------
ENV DOTNET_EnableGCCleanup=1 \
    DOTNET_EnableWriteXorExecute=0 \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false \
    ASPNETCORE_URLS=http://+:8080 \
    ASPNETCORE_ENVIRONMENT=Production

# ---- Create non-root user --------------------------
RUN useradd --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY --from=build /app/publish ./
RUN chown -R appuser:appuser /app
USER appuser

# ---- Health check ----------------------------------
# The transformer service exposes a lightweight health endpoint at /health
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/health || exit 1

EXPOSE 8080
ENTRYPOINT ["./PaletteStream.Transformer"]