# syntax=docker/dockerfile:1.4

#####################################################################
# Multi-stage Dockerfile for CommerceSphere Enterprise Suite (CES)  #
# Stage 1  – Compile & Unit-Test the Java Monolith                 #
# Stage 2  – Build a Lean Runtime Image with Non-Root Permissions  #
#####################################################################

########################
# ----- Stage 1 ----- #
########################
FROM maven:3.9.4-eclipse-temurin-21 AS build

# -----------------------------------------------------------------------------
# ARGs allow the CI pipeline to override defaults without touching the file.
# -----------------------------------------------------------------------------
ARG CES_VERSION=SNAPSHOT
ARG CES_ARTIFACT=commerce-sphere-enterprise-suite

LABEL org.opencontainers.image.title="CommerceSphere Enterprise Suite" \
      org.opencontainers.image.version="${CES_VERSION}" \
      org.opencontainers.image.description="Unified, end-to-end B2B ecommerce platform." \
      org.opencontainers.image.vendor="CommerceSphere Inc." \
      org.opencontainers.image.licenses="Apache-2.0"

# -----------------------------------------------------------------------------
# Speed up Maven by caching dependencies before copying the full source tree.
# -----------------------------------------------------------------------------
WORKDIR /usr/src/app
COPY pom.xml ./
COPY .mvn/ .mvn
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B -ntp dependency:go-offline

# -----------------------------------------------------------------------------
# Copy project sources *after* dependency caching layer to keep cache warm.
# -----------------------------------------------------------------------------
COPY src ./src

# -----------------------------------------------------------------------------
# Run Unit Tests & Package the Artifact
# -----------------------------------------------------------------------------
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B -ntp \
        -DskipITs=false \
        -Dmaven.test.failure.ignore=false \
        -Drevision=${CES_VERSION} \
        verify

########################
# ----- Stage 2 ----- #
########################
FROM eclipse-temurin:21-jre-alpine AS runtime

ARG CES_HOME=/opt/commerce-sphere
ARG CES_USER=ces
ARG CES_GROUP=ces
ARG CES_JAVA_OPTS="-XX:+UseContainerSupport -XX:+UseG1GC -XX:MaxRAMPercentage=80.0 -Dfile.encoding=UTF-8"

# -----------------------------------------------------------------------------
# Install lightweight runtime dependencies (e.g., tini for signal handling).
# -----------------------------------------------------------------------------
RUN apk add --no-cache dumb-init tzdata bash

# -----------------------------------------------------------------------------
# Create non-root user & group to follow best-practice container hardening.
# -----------------------------------------------------------------------------
RUN addgroup -S ${CES_GROUP} && adduser -S -G ${CES_GROUP} ${CES_USER}

# -----------------------------------------------------------------------------
# Create application directories with correct ownership.
# -----------------------------------------------------------------------------
RUN mkdir -p ${CES_HOME}/config ${CES_HOME}/logs && \
    chown -R ${CES_USER}:${CES_GROUP} ${CES_HOME}

# -----------------------------------------------------------------------------
# Copy the shaded/uber JAR from the build stage.
# -----------------------------------------------------------------------------
COPY --from=build /usr/src/app/target/${CES_ARTIFACT}.jar ${CES_HOME}/${CES_ARTIFACT}.jar

# -----------------------------------------------------------------------------
# Copy default runtime configuration (can be overridden via volume mounts).
# -----------------------------------------------------------------------------
COPY --chown=${CES_USER}:${CES_GROUP} deployment/docker/config/ ${CES_HOME}/config/

# -----------------------------------------------------------------------------
# Expose HTTP and JMX ports (JMX only bound to localhost by default).
# -----------------------------------------------------------------------------
EXPOSE 8080 9010

# -----------------------------------------------------------------------------
# JVM & Spring Boot runtime flags
# -----------------------------------------------------------------------------
ENV JAVA_OPTS="${CES_JAVA_OPTS} \
    -Dspring.profiles.active=prod \
    -Duser.timezone=UTC \
    -Dcom.sun.management.jmxremote \
    -Dcom.sun.management.jmxremote.port=9010 \
    -Dcom.sun.management.jmxremote.local.only=true \
    -Dcom.sun.management.jmxremote.authenticate=false \
    -Dcom.sun.management.jmxremote.ssl=false"

# -----------------------------------------------------------------------------
# Define healthcheck to aid orchestration frameworks (K8s / Docker Swarm).
# -----------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:8080/actuator/health || exit 1

# -----------------------------------------------------------------------------
# Use dumb-init as PID 1 for proper signal forwarding (e.g., SIGTERM).
# -----------------------------------------------------------------------------
USER ${CES_USER}

WORKDIR ${CES_HOME}

ENTRYPOINT ["/usr/bin/dumb-init", "--"]

CMD ["sh", "-c", "java ${JAVA_OPTS} -jar ${CES_ARTIFACT}.jar --spring.config.location=file:${CES_HOME}/config/"]