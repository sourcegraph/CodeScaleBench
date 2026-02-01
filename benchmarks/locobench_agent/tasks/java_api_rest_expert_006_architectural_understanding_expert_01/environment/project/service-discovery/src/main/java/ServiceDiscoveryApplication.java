```java
/*
 * OpsForge Utility Nexus
 * Module : service-discovery
 * File   : ServiceDiscoveryApplication.java
 *
 * Copyright 2024 OpsForge
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 *
 * This is the entry-point and single-file, self-contained reference
 * implementation of the Service-Discovery micro-service. It exposes:
 *
 *  • REST endpoints for instance registration / deregistration / lookup
 *  • An in-memory, TTL-aware service registry with scheduled eviction
 *  • Caching for high-traffic “lookup” queries
 *  • Graceful error-handling with RFC-7807 compliant Problem Details
 *
 * The code purposefully follows Hexagonal Architecture: controllers are
 * incoming adapters, while the registry is an application service that
 * works solely with domain constructs (RegisteredService).
 *
 * NOTE: For brevity, multiple classes are declared in a single *.java file.
 * In production, each top-level class should live in its own file.
 */
package com.opsforge.utilitynexus.servicediscovery;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;

import java.net.InetAddress;
import java.net.URI;
import java.net.UnknownHostException;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

import static org.springframework.http.HttpStatus.*;

/**
 * Main bootstrap class for the Service Discovery micro-service.
 */
@SpringBootApplication
@EnableScheduling
@EnableCaching
public class ServiceDiscoveryApplication {

    /* ******************************************************
     *  Bootstrapping
     * ******************************************************/
    public static void main(String[] args) {
        SpringApplication.run(ServiceDiscoveryApplication.class, args);
    }

    /* ******************************************************
     *  Infrastructure Beans
     * ******************************************************/
    /**
     * Simple in-process cache manager backed by Caffeine. Using Caffeine avoids
     * external dependencies while providing high-performance, bounded caches.
     */
    @Bean
    @Primary
    CacheManager cacheManager() {
        CaffeineCacheManager manager = new CaffeineCacheManager("registryList");
        manager.setCaffeine(com.github.benmanes.caffeine.cache.Caffeine.newBuilder()
                .maximumSize(1_000)
                .expireAfterWrite(Duration.ofSeconds(15)));
        return manager;
    }

    /* ======================================================
     *  Domain Model
     * ======================================================*/

    /**
     * RegisteredService is the pure domain entity representing one
     * micro-service instance made available to the platform.
     */
    public record RegisteredService(
            UUID   id,
            String name,
            String host,
            int    port,
            String basePath,
            Instant registeredAt,
            Duration ttl
    ) {
        public URI endpoint() {
            String normalizedBase = (basePath == null || basePath.isBlank())
                    ? ""
                    : (basePath.startsWith("/") ? basePath : "/" + basePath);
            return URI.create("http://" + host + ":" + port + normalizedBase);
        }

        public boolean isExpired() {
            return Instant.now().isAfter(registeredAt.plus(ttl));
        }
    }

    /* ======================================================
     *  Incoming Adapter : REST Controller
     * ======================================================*/

    /**
     * REST facade for the registry. All routes are versioned (v1) to allow
     * graceful evolution of the contract.
     */
    @RestController
    @RequestMapping(path = "/api/v1/registry")
    @Validated
    static class ServiceRegistryController {

        private final ServiceRegistry registry;

        ServiceRegistryController(ServiceRegistry registry) {
            this.registry = registry;
        }

        /* ---------- Registration Endpoints ---------- */

        @PostMapping("/register")
        @ResponseStatus(CREATED)
        public RegisteredService register(@RequestBody @Valid RegistrationRequest request) {
            return registry.register(request);
        }

        @DeleteMapping("/{id}")
        @ResponseStatus(NO_CONTENT)
        public void deregister(@PathVariable UUID id) {
            registry.deregister(id);
        }

        /* ---------- Query Endpoints ---------- */

        @GetMapping
        @Cacheable("registryList")
        public List<RegisteredService> list(@RequestParam(name = "serviceName", required = false) String name) {
            return registry.list(Optional.ofNullable(name));
        }

        @GetMapping("/{id}")
        public RegisteredService byId(@PathVariable UUID id) {
            return registry.findById(id);
        }
    }

    /* ======================================================
     *  Application Service : Registry
     * ======================================================*/

    /**
     * Thread-safe, TTL-aware in-memory registry. Could easily be swapped for
     * Redis, DynamoDB, or Consul by implementing the same API.
     */
    @Component
    static class ServiceRegistry {

        /** Keyed by service instance ID */
        private final Map<UUID, RegisteredService> store = new ConcurrentHashMap<>();

        /* ---------------- Registration ---------------- */

        public RegisteredService register(RegistrationRequest dto) {
            UUID id  = UUID.randomUUID();
            String host = resolveHost(dto.host());
            RegisteredService service = new RegisteredService(
                    id,
                    dto.name(),
                    host,
                    dto.port(),
                    dto.basePath(),
                    Instant.now(),
                    Duration.ofSeconds(dto.ttlSeconds())
            );
            store.put(id, service);
            return service;
        }

        /* ---------------- Deregistration -------------- */

        @CacheEvict(value = "registryList", allEntries = true)
        public void deregister(UUID id) {
            RegisteredService removed = store.remove(id);
            if (removed == null) {
                throw new ServiceNotFoundException("No service registered with id " + id);
            }
        }

        /* ---------------- Queries --------------------- */

        @Cacheable("registryList")
        public List<RegisteredService> list(Optional<String> serviceName) {
            Stream<RegisteredService> stream = store.values().stream().filter(s -> !s.isExpired());
            if (serviceName.isPresent()) {
                stream = stream.filter(s -> s.name().equalsIgnoreCase(serviceName.get()));
            }
            return stream.sorted(Comparator.comparing(RegisteredService::registeredAt).reversed())
                         .collect(Collectors.toList());
        }

        public RegisteredService findById(UUID id) {
            RegisteredService service = store.get(id);
            if (service == null || service.isExpired()) {
                throw new ServiceNotFoundException("No active service registered with id " + id);
            }
            return service;
        }

        /* ---------------- House-Keeping --------------- */

        @Scheduled(fixedDelayString = "${registry.eviction.interval-ms:5000}")
        @CacheEvict(value = "registryList", allEntries = true)
        void evictExpired() {
            Instant now = Instant.now();
            store.entrySet().removeIf(entry -> now.isAfter(entry.getValue().registeredAt().plus(entry.getValue().ttl())));
        }

        /* ---------------- Utilities ------------------- */

        private String resolveHost(String host) {
            try {
                return InetAddress.getByName(host).getHostAddress();
            } catch (UnknownHostException e) {
                throw new IllegalArgumentException("Unable to resolve host: " + host);
            }
        }
    }

    /* ======================================================
     *  DTOs
     * ======================================================*/

    /**
     * Validated DTO used for incoming registration requests.
     */
    record RegistrationRequest(
            @NotBlank @Size(max = 100) String name,
            @NotBlank @Size(max = 255) String host,
            @Positive                      int port,
            @Size(max = 255)              String basePath,
            @Positive                     long ttlSeconds
    ) {}

    /* ======================================================
     *  Exception Handling
     * ======================================================*/

    /**
     * Domain specific exception signalling that a service does not exist.
     */
    static class ServiceNotFoundException extends RuntimeException {
        ServiceNotFoundException(String message) { super(message); }
    }

    /**
     * Global exception translator to RFC-7807 Problem Details.
     */
    @RestControllerAdvice
    static class GlobalErrorHandler {

        @ExceptionHandler(ServiceNotFoundException.class)
        public ResponseEntity<ProblemDetail> handleNotFound(ServiceNotFoundException ex) {
            ProblemDetail problem = ProblemDetail.forStatusAndDetail(NOT_FOUND, ex.getMessage());
            problem.setTitle("Service Not Found");
            return ResponseEntity.status(NOT_FOUND).body(problem);
        }

        @ExceptionHandler(MethodArgumentNotValidException.class)
        public ResponseEntity<ProblemDetail> handleValidation(MethodArgumentNotValidException ex) {
            String details = ex.getBindingResult().getFieldErrors().stream()
                    .map(err -> err.getField() + ": " + err.getDefaultMessage())
                    .collect(Collectors.joining(", "));
            ProblemDetail problem = ProblemDetail.forStatusAndDetail(BAD_REQUEST, details);
            problem.setTitle("Validation Failure");
            return ResponseEntity.status(BAD_REQUEST).body(problem);
        }

        @ExceptionHandler(IllegalArgumentException.class)
        public ResponseEntity<ProblemDetail> handleIllegalArgument(IllegalArgumentException ex) {
            ProblemDetail problem = ProblemDetail.forStatusAndDetail(BAD_REQUEST, ex.getMessage());
            problem.setTitle("Invalid Argument");
            return ResponseEntity.status(BAD_REQUEST).body(problem);
        }

        @ExceptionHandler(Exception.class)
        public ResponseEntity<ProblemDetail> handleGeneric(Exception ex) {
            ProblemDetail problem = ProblemDetail.forStatusAndDetail(
                    HttpStatus.INTERNAL_SERVER_ERROR,
                    "An unexpected error occurred");
            problem.setTitle("Internal Server Error");
            // In production, consider logging ex with a correlation ID.
            return ResponseEntity.status(INTERNAL_SERVER_ERROR).body(problem);
        }
    }
}
```