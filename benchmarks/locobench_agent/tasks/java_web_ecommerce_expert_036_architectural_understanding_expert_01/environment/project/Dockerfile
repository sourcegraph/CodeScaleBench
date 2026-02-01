# ──────────────────────────────────────────────────────────────────────────────
#  SprintCart Pro – Hyper-Productive E-Commerce Workbench
#  Production-grade Dockerfile
#
#  This container builds a full SprintCart Pro deployment consisting of:
#    1. Java / Spring Boot back-end (Hexagonal Architecture)
#    2. Vue 3 SPA front-end
#
#  Multi-stage build for optimal size:
#    • Stage 1 – Node builder:       Compiles and minifies the SPA
#    • Stage 2 – Maven builder:      Packages the Spring Boot application
#    • Stage 3 – Runtime container:  Runs the fat-jar with a slim JRE
#
#  Usage:
#     docker build -t sprintcart-pro:latest .
#     docker run -p 8080:8080 sprintcart-pro:latest
#
#  Expected project layout:
#     /frontend        → Vue 3 SPA (package.json, vite.config.*)
#     /backend         → Spring Boot application (pom.xml or mvnw)
# ──────────────────────────────────────────────────────────────────────────────

# ------------------------------------------------------------------------------
#   Stage 1 — Build Vue 3 SPA
# ------------------------------------------------------------------------------
FROM node:18-alpine AS spa-builder

WORKDIR /usr/src/app/frontend

# Install dependencies first to leverage Docker cache
COPY frontend/package*.json ./
RUN npm ci --silent

# Copy SPA source and build
COPY frontend/ .
RUN npm run build

# ------------------------------------------------------------------------------
#   Stage 2 — Build Spring Boot application
# ------------------------------------------------------------------------------
FROM maven:3.9.6-eclipse-temurin-17-alpine AS backend-builder

# Faster, reproducible Maven builds
ARG MAVEN_OPTS="-Xmx1G"
ENV MAVEN_CONFIG=/root/.m2

WORKDIR /usr/src/app/backend

# Copy only pom files first for better caching
COPY backend/pom.xml backend/.mvn/ backend/mvnw ./
RUN ./mvnw -B -ntp dependency:go-offline

# Copy rest of the source
COPY backend/ .

# Inject the built SPA assets into backend resources before packaging
# Assumes Spring Web MVC will serve static files from classpath:/static
COPY --from=spa-builder /usr/src/app/frontend/dist/ src/main/resources/static/

# Build fat JAR
RUN ./mvnw -B -Pprod clean package -DskipTests

# ------------------------------------------------------------------------------
#   Stage 3 — Minimal runtime image
# ------------------------------------------------------------------------------
FROM eclipse-temurin:17-jre-alpine

# Metadata
LABEL org.opencontainers.image.title="SprintCart Pro"
LABEL org.opencontainers.image.description="Hyper-Productive E-Commerce Workbench"
LABEL org.opencontainers.image.source="https://github.com/sprintcart/sprintcart-pro"
LABEL org.opencontainers.image.version="1.0.0"

# Non-root runtime user
RUN addgroup --system --gid 1001 sprintcart \
 && adduser  --system --uid 1001 --ingroup sprintcart --home /home/sprintcart sprintcart

WORKDIR /app

# Copy JAR
COPY --from=backend-builder /usr/src/app/backend/target/sprintcart-pro-*.jar sprintcart-pro.jar

# Environment defaults (override at runtime as needed)
ENV JAVA_OPTS="-XX:+UseContainerSupport -XX:MaxRAMPercentage=75.0"
ENV SPRING_PROFILES_ACTIVE=prod
ENV TZ=UTC

# Healthcheck hits Spring Actuator
HEALTHCHECK --interval=1m --timeout=5s --start-period=30s --retries=3 \
 CMD wget --no-verbose --tries=1 --spider http://localhost:8080/actuator/health || exit 1

USER sprintcart

EXPOSE 8080

# jcmd/JFR are rarely needed; disable modules for smaller footprint (optional)
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar sprintcart-pro.jar"]