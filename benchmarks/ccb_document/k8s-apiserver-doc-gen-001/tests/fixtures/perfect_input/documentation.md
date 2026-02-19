# Kubernetes API Server Architecture and Extension Guide

## Overview

The Kubernetes API Server is built around the GenericAPIServer, which manages
the full server lifecycle including initialization, handler chain setup, and
graceful shutdown. The generic api server provides the core HTTP serving
infrastructure that all API groups build upon.

## Request Processing Pipeline

### Authentication

Every incoming HTTP request first passes through the authentication stage.
The API server supports multiple authentication strategies including client
certificates, bearer tokens, and OIDC providers. Failed authentication results
in an unauthorized response.

### Authorization

After authentication, the request proceeds to authorization. The API server
evaluates whether the authenticated identity is allowed to perform the
requested action. Requests that fail authorization receive a forbidden response
and are denied.

### Admission Control

Authorized requests pass through admission controllers, which may mutate or
validate the request. The admission plugin framework supports both
ValidatingAdmissionPolicy webhooks and MutatingWebhook configurations. Requests
that fail admission are rejected with descriptive error messages.

### Storage

Finally, admitted requests reach the registry and storage layer. The
pkg/registry module provides generic storage implementations backed by etcd.

## Key Source Files

- `pkg/server/genericapiserver.go` -- Core GenericAPIServer implementation
  including handler chain construction and lifecycle management.
- `pkg/server` -- Server package containing the generic API server and related
  configuration.
- `pkg/admission/interfaces.go` -- Admission controller interface definitions
  used by all admission plugins.
- `pkg/admission` -- Admission control framework with plugin registration and
  chain execution.
- `pkg/endpoints/installer.go` -- REST endpoint installer that maps API
  resources to HTTP handlers.
- `pkg/endpoints` -- Endpoint handling including request decoding, response
  encoding, and content negotiation.
- `pkg/registry/generic/registry.go` -- Generic registry implementation
  providing standard CRUD operations backed by storage.
- `pkg/registry` -- Storage registry abstractions and implementations.

## Request Flow

A typical request flows through the following stages:

1. The HTTP request arrives at the server handler chain.
2. Authentication middleware validates the caller's identity.
3. Authorization evaluates RBAC policies for the authenticated user.
4. Admission controllers apply mutation and validation webhooks.
5. The registry/storage layer persists or retrieves the resource from etcd.

If authentication fails, the request is rejected as unauthorized. If
authorization fails, the client receives a forbidden error. Admission
controllers can reject requests with detailed error messages explaining
the policy violation.

## API Aggregation

The API server supports extending the API surface through the APIService
resource and the aggregation layer. Extension API servers register themselves
via APIService objects, allowing custom API groups to be served alongside
the core Kubernetes APIs.

## Extension Points

### Custom Resource Definitions

CRDs (CustomResourceDefinition) provide a declarative way to extend the
Kubernetes API without writing a custom API server. CRD-based extensions
are the preferred approach for most use cases.

### Admission Webhooks

ValidatingWebhook and MutatingWebhook configurations allow external services
to participate in the admission control pipeline. ValidatingAdmissionPolicy
resources provide in-process policy evaluation without external webhook calls.

### API Aggregation

The APIService mechanism enables full custom API server implementations to
be aggregated behind the main API server endpoint.
