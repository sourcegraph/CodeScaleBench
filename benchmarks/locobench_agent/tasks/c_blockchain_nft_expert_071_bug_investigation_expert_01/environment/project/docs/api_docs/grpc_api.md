```markdown
# HoloCanvas gRPC API Reference
_Author: Core HoloCanvas Engineering Team • Version: 1.2.0 • Status: Production_

Welcome to the gRPC API specification for **HoloCanvas**—a micro-gallery blockchain architecture that enables collaborative creation, curation, and financialization of generative NFTs.  
This document is the canonical reference for inter-service communication and SDK integration. It contains:

1. Service‐by‐service `.proto` specifications  
2. Idiomatic C client/server snippets built with **gRPC-C** (`grpc`, `protobuf-c`, `absl`)  
3. Wire-level error models & retry semantics  
4. Performance guidelines and security notes  

> NOTE  
> All `.proto` files are versioned under `api/v1/`.  Backwards-compatible additions MUST use field
> numbers ≥ 128 to avoid collisions with reserved slots for future consensus extensions.

---

## Table of Contents
- [Quick Start](#quick-start)
- [Common Types](#common-types)
- [Cryptograph Service](#cryptograph-service)
- [LedgerCore Service](#ledgercore-service)
- [MintFactory Service](#mintfactory-service)
- [GalleryGateway Streaming API](#gallerygateway-streaming-api)
- [Health & Observability](#health--observability)
- [Error Model](#error-model)
- [Security Considerations](#security-considerations)

---

## Quick Start

```bash
# Install deps (Ubuntu 22.04 LTS)
sudo apt-get update
sudo apt-get install -y protobuf-c-compiler libgrpc-dev \
                        libprotobuf-c-dev libssl-dev cmake ninja-build

# Pull proto definitions (git submodule)
git submodule update --init --recursive

# Generate C stubs
PROTO_DIR=./api/v1
OUT=./gen
mkdir -p $OUT
protoc --proto_path=$PROTO_DIR        \
       --c_out=$OUT                  \
       --grpc_out=$OUT               \
       --plugin=protoc-gen-grpc=`which grpc_c_plugin` \
       $PROTO_DIR/*.proto
```

---

## Common Types

`api/v1/common.proto`

```proto
syntax = "proto3";

package holocanvas.v1;

import "google/protobuf/timestamp.proto";

option csharp_namespace = "HoloCanvas.V1";

enum ErrorCode {
  // Generic catch-all.
  ERROR_CODE_UNSPECIFIED = 0;
  // Immutable storage failure.
  ERROR_CODE_STORAGE     = 1;
  // Cryptographic verification failed.
  ERROR_CODE_CRYPTO      = 2;
  // Invalid or unauthorized request.
  ERROR_CODE_PERMISSION  = 3;
  // Resource not found.
  ERROR_CODE_NOT_FOUND   = 4;
  // Operation timed out.
  ERROR_CODE_DEADLINE    = 5;
}

message ErrorStatus {
  ErrorCode        code        = 1;
  string           message     = 2;
  repeated string  details     = 3;
}

message Empty{}
```

---

## Cryptograph Service
_Performs signature validation, key-pair generation, and VRF proofs._

`api/v1/cryptograph.proto`

```proto
syntax = "proto3";

package holocanvas.v1;

import "common.proto";

service CryptographSvc {
  // Generates a secp256k1 key pair.
  rpc GenKeyPair(GenKeyPairRequest) returns (GenKeyPairResponse);
  // Signs an arbitrary payload using the private key stored in KMS/HSM.
  rpc SignPayload(SignPayloadRequest) returns (SignPayloadResponse);
  // Verifies a signature and returns canonicalized pubkey if valid.
  rpc VerifySignature(VerifySignatureRequest)
      returns (VerifySignatureResponse);
}

message GenKeyPairRequest {
  string kms_keyring   = 1;   // optional KMS identifier
}

message GenKeyPairResponse {
  bytes  public_key    = 1;
  bytes  private_key   = 2;   // only present in dev/test
}

message SignPayloadRequest {
  bytes   payload      = 1;
  bytes   public_key   = 2;   // Which key to use
}

message SignPayloadResponse {
  bytes   signature    = 1;
  ErrorStatus error    = 99;
}

message VerifySignatureRequest {
  bytes   payload      = 1;
  bytes   signature    = 2;
}

message VerifySignatureResponse {
  bool    valid        = 1;
  bytes   public_key   = 2;
  ErrorStatus error    = 99;
}
```

### Minimal C Client Example

```c
/*
 * cryptograph_client.c — Demonstrates an async call to SignPayload.
 */
#include <grpc/grpc.h>
#include <grpc/support/log.h>
#include "cryptograph.pb-c.h"
#include "cryptograph.grpc-c.h"

int main(void)
{
    grpc_init();
    grpc_channel *channel = grpc_insecure_channel_create(
        "localhost:50051", NULL, NULL);

    CryptographSvcClient *client =
        cryptograph_svc__client__create(channel);

    // Build request
    SignPayloadRequest req = SIGN_PAYLOAD_REQUEST__INIT;
    req.payload.data   = (uint8_t *)"hello-holo";
    req.payload.len    = strlen("hello-holo");
    req.public_key.data= NULL;
    req.public_key.len = 0;

    // Prepare call
    grpc_call *call;
    grpc_slice method  = grpc_slice_from_static_string(
        "/holocanvas.v1.CryptographSvc/SignPayload");
    grpc_call_error cerr = GRPC_CALL_OK;

    grpc_metadata_array meta_send, meta_recv;
    grpc_metadata_array_init(&meta_send);
    grpc_metadata_array_init(&meta_recv);

    call = grpc_channel_create_call(
        channel, NULL, GRPC_PROPAGATE_DEFAULTS,
        grpc_completion_queue_create_for_pluck(NULL),
        method, NULL, gpr_inf_future(GPR_CLOCK_REALTIME), NULL);

    if (!call) {
        fprintf(stderr, "Failed to create call\n");
        return EXIT_FAILURE;
    }

    /* Serialize protobuf */
    size_t len = sign_payload_request__get_packed_size(&req);
    uint8_t *buf = malloc(len);
    sign_payload_request__pack(&req, buf);

    grpc_byte_buffer *payload =
        grpc_raw_byte_buffer_create(
            (const grpc_slice[]){
              grpc_slice_from_copied_buffer((char*)buf, len) }, 1);

    cerr = grpc_call_start_batch(call, (grpc_op[]){
        {
            .op = GRPC_OP_SEND_INITIAL_METADATA,
            .data.send_initial_metadata.count = 0
        },
        {
            .op = GRPC_OP_SEND_MESSAGE,
            .data.send_message.send_message = payload
        },
        { .op = GRPC_OP_SEND_CLOSE_FROM_CLIENT },
        { .op = GRPC_OP_RECV_MESSAGE,
          .data.recv_message.recv_message = NULL },
        { .op = GRPC_OP_RECV_STATUS_ON_CLIENT,
          .data.recv_status_on_client.trailing_metadata = &meta_recv,
          .data.recv_status_on_client.status = &(grpc_status_code){0},
          .data.recv_status_on_client.status_details = &(grpc_slice){0}}
      }, 5, (void *)1, NULL);

    if (cerr != GRPC_CALL_OK) {
        fprintf(stderr, "grpc_call_start_batch failed: %d\n", cerr);
    }

    /* Cleanup */
    grpc_byte_buffer_destroy(payload);
    free(buf);
    grpc_call_unref(call);
    cryptograph_svc__client__destroy(client);
    grpc_channel_destroy(channel);
    grpc_shutdown();
    return 0;
}
```

---

## LedgerCore Service
_Implements state transitions, consensus hooks, and transaction finalization._

`api/v1/ledger_core.proto`

```proto
syntax = "proto3";

package holocanvas.v1;

import "common.proto";

service LedgerCoreSvc {
  // Broadcast a new transaction to mempool.
  rpc BroadcastTx(TxRequest) returns (TxAck);
  // Query chain state at a specific height.
  rpc QueryState(StateQuery) returns (StateSnapshot);
  // Subscribe to committed block events (server-side streaming).
  rpc StreamBlocks(BlockStreamRequest) returns (stream BlockEvent);
}

message TxRequest {
  bytes           raw_tx       = 1;
  uint64          gas_limit    = 2;
}

message TxAck {
  bytes           tx_hash      = 1;
  uint64          height       = 2;
  ErrorStatus     error        = 99;
}

message StateQuery {
  uint64          height       = 1;
  repeated string keys         = 2;
}

message StateSnapshot {
  uint64          height       = 1;
  map<string,bytes> kv         = 2;
}

message BlockStreamRequest {
  uint64 start_height          = 1;
}
message BlockEvent {
  uint64 height = 1;
  bytes  block  = 2;
}
```

### Blocking C Server Skeleton

```c
/*
 * ledger_core_server.c — Single-threaded demo server.
 */
#include <grpc/grpc.h>
#include "ledger_core.pb-c.h"
#include "ledger_core.grpc-c.h"

static void handle_broadcast_tx(LedgerCoreSvc_Service *svc,
                                const TxRequest *req,
                                void *user_data)
{
    // TODO(future): validate tx, run state machine
    TxAck ack = TX_ACK__INIT;
    ack.tx_hash.data = gpr_malloc(32);
    ack.tx_hash.len  = 32;
    memset(ack.tx_hash.data, 0xAB, 32);

    ledger_core_svc__broadcast_tx__send_reply(
        (Grpc__ServerContext*)user_data, &ack);
}

int main(void)
{
    grpc_init();

    GrpcServer *server = grpc_server_create(NULL, NULL);
    grpc_server_register_completion_queue(server,
        grpc_completion_queue_create_for_next(NULL), NULL);
    grpc_server_add_insecure_http2_port(server, "0.0.0.0:50505");

    LedgerCoreSvc_Service *svc = ledger_core_svc__service__create(NULL);
    ledger_core_svc__service__set_broadcast_tx(svc, handle_broadcast_tx, NULL);

    grpc_server_start(server);
    printf("LedgerCore listening on 50505\n");

    /* Block forever */
    for(;;) grpc_server_shutdown_and_notify(server,
            grpc_completion_queue_create_for_pluck(NULL),
            gpr_inf_future(GPR_CLOCK_MONOTONIC));
}
```

---

## MintFactory Service
_Composes generative fragments into finalized, on-chain artifacts._

`api/v1/mint_factory.proto`

```proto
syntax = "proto3";

package holocanvas.v1;

import "common.proto";
import "google/protobuf/timestamp.proto";

service MintFactorySvc {
  rpc SubmitFragment(FragmentRequest) returns (FragmentAck);
  rpc ComposeArtifact(ComposeRequest) returns (ComposeAck);
  rpc GetArtifact(GetArtifactRequest) returns (Artifact);
}

message FragmentRequest {
  string   creator_id     = 1;
  bytes    wasm_blob      = 2;   // Executed in deterministic sandbox
  string   fragment_type  = 3;   // "shader", "audio", "metadata"
}

message FragmentAck {
  uint64        fragment_id  = 1;
  ErrorStatus   error        = 99;
}

message ComposeRequest {
  uint64                    parent_fragment_id = 1;
  repeated uint64           child_fragments    = 2;
  google.protobuf.Timestamp deadline           = 3;
}

message ComposeAck {
  uint64        artifact_id = 1;
  ErrorStatus   error       = 99;
}

enum ArtifactState {
  ARTIFACT_STATE_UNSPECIFIED = 0;
  ARTIFACT_STATE_DRAFT       = 1;
  ARTIFACT_STATE_CURATED     = 2;
  ARTIFACT_STATE_AUCTION     = 3;
  ARTIFACT_STATE_FRACTIONAL  = 4;
  ARTIFACT_STATE_STAKED      = 5;
}

message Artifact {
  uint64                  artifact_id   = 1;
  repeated uint64         fragment_ids  = 2;
  ArtifactState           state         = 3;
  google.protobuf.Timestamp created_at  = 4;
  bytes                   immutable_uri = 5; // IPFS / Arweave
}
```

---

## GalleryGateway Streaming API
_Typically consumed by front-end WebSocket bridge._

`api/v1/gallery_gateway.proto`

```proto
syntax = "proto3";
package holocanvas.v1;
import "common.proto";

service GalleryGatewaySvc {
  rpc EventFeed(EventFeedRequest) returns (stream GatewayEvent);
}

message EventFeedRequest {
  repeated ArtifactState filter_states = 1;
  uint64  last_seen_height            = 2;
}

message GatewayEvent {
  uint64          artifact_id         = 1;
  ArtifactState   state               = 2;
  bytes           preview_image_png   = 3;
}
```

---

## Health & Observability

All services expose the standard gRPC Health protocol plus an
OpenTelemetry span exporter on port **9464/udp** (`OTLP/gRPC`).

```bash
grpcurl -plaintext \
  -d '{}' \
  localhost:50051 grpc.health.v1.Health/Check
```

Service‐specific metrics are reported in protobuf via **/metrics** unary.

---

## Error Model

1. Transport: HTTP/2 errors map to `google.rpc.Status`.  
2. Application: `ErrorStatus` message embedded in every response.  
3. Idempotent retries: Enabled for `UNAVAILABLE` & `DEADLINE_EXCEEDED`.

```proto
// Example status in trailer-metadata
grpc-status: 7   # PERMISSION_DENIED
grpc-message: "signature invalid"
```

---

## Security Considerations

- **mTLS** is mandatory between microservices; public-facing endpoints terminate TLS at Envoy.  
- **WASM fragments** run within Wasmtime sandbox with a 100 MiB memory cap.  
- **Rate limits**: 100 RPS per API key, enforced by `TokenBucketInterceptor`.  
- **Secrets** must **never** traverse gRPC; use Hashicorp Vault sidecar.  

> Reference implementation for auth is located in `lib/auth/jwt_auth_interceptor.c`.

---

## Changelog
| Date       | Version | Change |
|------------|---------|--------|
| 2023-02-01 | 1.0.0   | Initial release |
| 2023-06-15 | 1.1.0   | Added GalleryGateway streaming |
| 2024-03-18 | 1.2.0   | Error model v2; holo-aware retries |

---

© 2024 HoloCanvas Contributors — Released under Apache 2.0
```