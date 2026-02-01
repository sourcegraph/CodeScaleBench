```markdown
<!--
File: docs/api.md
Project: EchoPulse – Real-Time Social Signal Processing Platform
────────────────────────────────────────────────────────────────
This document is the canonical reference for EchoPulse public
service contracts, event schemas, authentication, and usage
patterns.  All code samples are production-grade Go (≥1.22)
and are intended to compile and run as-is when placed inside an
EchoPulse workspace.
-->

# EchoPulse API Specification

*Version: 1.5 – generated 2024-06-27*

---

## Table of Contents

1.  Introduction  
2.  Service Landscape  
3.  Event Bus (Kafka / JetStream)  
4.  gRPC Services  
5.  Authentication & Authorization  
6.  Go Quick-Start  
7.  Advanced Usage Patterns  
8.  Error Model  
9.  Release Compatibility Matrix  

---

## 1. Introduction

EchoPulse is an event-driven ML/NLP platform that ingests raw
social signals and emits higher-level insight streams in near
real-time.  The platform is designed around two public
integration points:

1.  An **Event Bus** for high-throughput firehose integration.  
2.  A **gRPC API** for request/response workloads and control-plane
    operations.

---

## 2. Service Landscape

| Domain             | Service                           | Purpose                                      |
|--------------------|-----------------------------------|----------------------------------------------|
| Ingestion          | `ingestor-svc`                    | Converts raw payloads → `SocialEvent`        |
| Feature Store      | `feature-svc`                     | Online feature retrieval / backfill          |
| Inference          | `infer-svc`                       | Real-time model inference                    |
| Orchestration      | `pipeline-orchestrator`           | Manages data & model pipelines               |
| Monitoring         | `telemetry-svc`                   | Metrics, alerts, drift detection             |

---

## 3. Event Bus

### 3.1 Topic Naming Convention

```
{environment}.{team}.{domain}.{name}.{version}
```

Example: `prod.echo.events.social_event.v1`

### 3.2 Domain Events

The canonical schema for all first-class social signals:

```protobuf
syntax = "proto3";

package echo.v1;

import "google/protobuf/timestamp.proto";

message SocialEvent {
  string   id            = 1;  // ULID
  string   tenant_id     = 2;
  string   user_id       = 3;
  string   channel_id    = 4;
  string   raw_payload   = 5;  // UTF-8 text / JSON / transcript
  map<string, string> meta = 6;
  google.protobuf.Timestamp created_at = 7;
}
```

Derived events are published back on `...derived_event.v1`:

```protobuf
message DerivedEvent {
  string               id            = 1;
  string               source_id     = 2; // SocialEvent.id
  double               sentiment     = 3; // ‑1 → 1
  repeated string      entities      = 4; // PER/ORG/LOC/...
  double               toxicity      = 5; // 0 → 1
  map<string, string>  meta          = 6;
  google.protobuf.Timestamp inferred_at = 7;
}
```

---

## 4. gRPC Services

### 4.1 Ingestion Service

```protobuf
service IngestorService {
  rpc PublishSocialEvent (SocialEvent) returns (PublishAck) {
    option (google.api.http) = {
      post: "/v1/social-events"
      body: "*"
    };
  }
}

message PublishAck {
  string id = 1;
}
```

### 4.2 Feature Service

```protobuf
service FeatureService {
  rpc GetFeatureVector (FeatureRequest) returns (FeatureVector) {}
  rpc BatchWriteFeatures (stream FeatureVector) returns (WriteSummary) {}
}

message FeatureRequest {
  string entity_id = 1;
  repeated string feature_names = 2;
}
```

Complete `.proto` files live under `api/proto/`.

---

## 5. Authentication & Authorization

EchoPulse uses **mTLS** at the transport layer and per-RPC JWT
tokens at the application layer.  Token scopes follow
`<service>.<verb>.<resource>` naming.

Example scope for writing events:

```
ingestor.publish.SocialEvent
```

---

## 6. Go Quick-Start

### 6.1 Producing Events

```go
package main

import (
	"context"
	"encoding/json"
	"log"
	"time"

	kgo "github.com/segmentio/kafka-go" // thin wrapper; swap for NATS if needed
	"github.com/oklog/ulid/v2"
	echo "github.com/echopulse/echo/api/go/echo/v1"
	"google.golang.org/protobuf/proto"
)

func main() {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	w := &kgo.Writer{
		Addr:         kgo.TCP("kafka-broker-0:9092", "kafka-broker-1:9092"),
		Topic:        "prod.echo.events.social_event.v1",
		Balancer:     &kgo.LeastBytes{},
		RequiredAcks: kgo.RequireAll,
	}

	msg := &echo.SocialEvent{
		Id:        ulid.Make().String(),
		TenantId:  "club-alpha",
		UserId:    "user-42",
		ChannelId: "general",
		RawPayload: json.RawMessage(`{
			"text":"Hello 👋 this platform is amazing!"
		}`).String(),
		CreatedAt: timestamppb.Now(),
	}

	payload, err := proto.Marshal(msg)
	if err != nil {
		log.Fatalf("marshal: %v", err)
	}

	err = w.WriteMessages(ctx, kgo.Message{
		Key:   []byte(msg.UserId),
		Value: payload,
		Time:  time.Now(),
	})
	if err != nil {
		log.Fatalf("write: %v", err)
	}
	log.Printf("published event %s", msg.Id)
}
```

### 6.2 Calling gRPC

```go
package main

import (
	"context"
	"crypto/tls"
	"log"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"

	echo "github.com/echopulse/echo/api/go/echo/v1"
)

func main() {
	creds := credentials.NewTLS(&tls.Config{
		InsecureSkipVerify: false, // prod: set CA
	})
	conn, err := grpc.Dial("ingestor-svc.prod.svc.cluster.local:8080",
		grpc.WithTransportCredentials(creds),
		grpc.WithBlock(),
	)
	if err != nil {
		log.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	client := echo.NewIngestorServiceClient(conn)

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	resp, err := client.PublishSocialEvent(ctx, &echo.SocialEvent{
		// minimal example
		RawPayload: "Ping!",
	})
	if err != nil {
		log.Fatalf("grpc: %v", err)
	}
	log.Printf("ack id=%s", resp.Id)
}
```

---

## 7. Advanced Usage Patterns

### 7.1 Building a Custom Observer

```go
// cmd/observer/main.go
package main

import (
	"context"
	"log"
	"time"

	"github.com/echopulse/echo/pkg/observer"
)

func main() {
	cfg := observer.Config{
		Topic:       "prod.echo.events.derived_event.v1",
		Concurrency: 8,
		GroupID:     "trend-surfacing-svc",
	}

	o, err := observer.New(cfg, trendSurfacingHandler)
	if err != nil {
		log.Fatalf("observer: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := o.Run(ctx); err != nil {
		log.Fatalf("run: %v", err)
	}
}

func trendSurfacingHandler(ctx context.Context, evt observer.Event) error {
	// heavy computation should honor ctx deadline
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
	}

	// TODO: Add trend detection logic
	time.Sleep(50 * time.Millisecond)
	log.Printf("processed %s (type=%T)", evt.ID, evt.Payload)
	return nil
}
```

### 7.2 Creating a Pipeline Stage (Strategy Pattern)

```go
package sentiment

import (
	"context"

	"github.com/echopulse/echo/pkg/pipeline"
)

type Analyzer struct {
	model pipeline.Model // runtime-loaded model
}

func New(model pipeline.Model) *Analyzer { return &Analyzer{model: model} }

func (a *Analyzer) Name() string { return "sentiment-analyzer" }

func (a *Analyzer) Process(ctx context.Context, in pipeline.Record) (out pipeline.Record, err error) {
	score := a.model.Predict(in.Payload)
	in.Meta["sentiment"] = score
	return in, nil
}
```

---

## 8. Error Model

Every RPC returns a canonical error structure:

```protobuf
message ErrorStatus {
  int32               code        = 1; // gRPC codes
  string              message     = 2;
  repeated FieldError details     = 3;
}

message FieldError {
  string field   = 1;
  string reason  = 2;
}
```

gRPC errors are encoded using `google.rpc.Status`.

Kafka-side errors follow the [CloudEvents](https://cloudevents.io/) spec
with `data` → `ErrorStatus`.

---

## 9. Release Compatibility

| API                      | 1.3 | 1.4 | 1.5 |
|--------------------------|-----|-----|-----|
| SocialEvent.id type      | ULID| ULID| ULID|
| FeatureService RPCs      | ✔   | ✔   | ✔   |
| DerivedEvent.entities    |  –  | ✔   | ✔   |
| Sentiment score range    |-1→1 |-1→1 |-1→1 |

---

© 2024 EchoPulse Inc.  All rights reserved.
```