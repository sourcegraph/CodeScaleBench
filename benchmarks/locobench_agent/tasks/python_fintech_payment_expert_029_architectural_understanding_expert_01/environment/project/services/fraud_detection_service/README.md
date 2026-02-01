```markdown
# CrowdPay Connect — Fraud Detection Service

Welcome to the Fraud Detection Service (FDS) of **CrowdPay Connect**.  
This micro-service performs real-time fraud assessment for every transactional
event flowing through the platform.  
It combines rule-based heuristics, machine-learning models, and social-graph
signals to produce a risk score that is later consumed by the
`risk_assessment` and `compliance_reporting` services.

---

## Table of Contents
1. [Service Highlights](#service-highlights)  
2. [High-Level Architecture](#high-level-architecture)  
3. [Installation](#installation)  
4. [Configuration](#configuration)  
5. [Quick-Start](#quick-start)  
6. [Event Schema](#event-schema)  
7. [REST API](#rest-api)  
8. [Testing](#testing)  
9. [Deployment](#deployment)  
10. [Contributing](#contributing)  

---

## Service Highlights
* **Real-time risk scoring** — median latency < 40 ms.  
* **Pluggable models** — swap in new ML pipelines without downtime.  
* **Self-healing** — automatic rollback on model performance regression.  
* **Event-sourced** — every decision is immutable and auditable.  
* **Cross-service enrichment** — integrates KYC, social-graph, & geolocation.  

---

## High-Level Architecture

```text
┌──────────┐   Kafka    ┌────────────────┐   gRPC    ┌─────────────────────┐
│ CrowdPod │ ────────▶ │ Event Gateway  │ ────────▶ │ Fraud Detection Svc │
│  Wallet  │           │  (NATS Jet)    │           │  (This repo)        │
└──────────┘           └────────────────┘           │  |  Inference Pool  │
                                                    │  |  Feature Store  │
                                                    └──┬──────────────────┘
                                                       │  Postgres (audit)
                                                       │  Redis (cache)
                                                       ▼
                                                   Compliance & Risk Svc
```

> NOTE – The service is stateless by design; any stateful artifact lives in
> Postgres, Redis, or the Feature Store (Feast).

---

## Installation

```bash
git clone https://github.com/crowdpay-connect/fraud_detection_service.git
cd fraud_detection_service

# Python 3.10+ is required
python -m venv .venv
source .venv/bin/activate

pip install -U pip
pip install -r requirements.txt
```

---

## Configuration

All configuration is environment-driven.  
A `.env.example` file is provided.  The full list:

| Variable                      | Default                | Description                             |
| ----------------------------- | ---------------------- | --------------------------------------- |
| `FDS_KAFKA_BROKERS`           | `localhost:9092`       | Kafka bootstrap servers                 |
| `FDS_KAFKA_TXN_TOPIC`         | `cp.txn.payments.v1`   | Transaction events topic                |
| `FDS_KAFKA_RISK_TOPIC`        | `cp.risk.scores.v1`    | Output risk scores topic                |
| `FDS_POSTGRES_URI`            | `postgresql://...`     | Audit trail database                    |
| `FDS_REDIS_URI`               | `redis://localhost:6379/0` | Feature cache                        |
| `FDS_MODEL_REGISTRY_URI`      | `s3://cp-model-registry` | MLflow/registry location            |
| `FDS_INFERENCE_BATCH`         | `64`                   | Maximum events processed per batch      |
| `FDS_LOG_LEVEL`               | `INFO`                 | Logging level                           |

```bash
cp .env.example .env
export $(cat .env | xargs)
```

---

## Quick-Start

Below is a minimal Python snippet illustrating how to emit a transaction event
and synchronously obtain its fraud score by hitting the service’s gRPC API.

```python
import os
import uuid
from datetime import datetime, timezone

from google.protobuf.json_format import ParseDict  # type: ignore
import grpc

from cp_fraud_detection_sdk.v1 import scoring_pb2, scoring_pb2_grpc

# gRPC channel
channel = grpc.insecure_channel(os.getenv("FDS_GRPC_ENDPOINT", "localhost:55055"))
client = scoring_pb2_grpc.FraudScoringStub(channel)

txn_event_dict = {
    "event_id": str(uuid.uuid4()),
    "crowdpod_id": "pod_4a697c13",
    "actor_user_id": "user_173",
    "amount": {"value": "29.99", "currency": "EUR"},
    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    "payment_method": "CARD",
    "card_last4": "1337",
    "ip_address": "185.199.110.153",
    "geo_location": {"lat": 48.8566, "lon": 2.3522},
}

request = scoring_pb2.ScoringRequest(
    transaction=ParseDict(txn_event_dict, scoring_pb2.TransactionEvent())
)

response: scoring_pb2.ScoringResponse = client.ScoreTransaction(request, timeout=2)

print(
    f'Risk Score: {response.score:.4f} '
    f'| Classification: {"FRAUD" if response.is_fraud else "LEGIT"}'
)
```

---

## Event Schema

The service uses protobuf v3 definitions (see `proto/`).

High-level fields:

```protobuf
message TransactionEvent {
  string event_id         = 1;
  string crowdpod_id      = 2;
  string actor_user_id    = 3;
  Money amount            = 4;
  string payment_method   = 5;
  string card_last4       = 6;
  string ip_address       = 7;
  GeoLocation geo_location= 8;
  google.protobuf.Timestamp timestamp = 9;
}
```

---

## REST API

While gRPC is the preferred protocol, an HTTP 1.1 façade is also exposed for
browser-based dashboards.

```text
POST /v1/score
Content-Type: application/json

{
  "event_id": "754e8e30...",
  "amount": {"value": "12.00", "currency": "USD"},
  ...
}
```

Response:

```json
{
  "score": 0.9821,
  "is_fraud": true,
  "explanation": {
    "top_features": [
      {"name": "amount_to_income_ratio", "value": 0.74},
      {"name": "ip_reputation", "value": 0.91}
    ]
  }
}
```

OpenAPI spec lives in `openapi/fraud_scoring.yaml`.

---

## Testing

1. Unit tests (pytest)
2. Contract tests (pact-python)
3. Data-drift checks (`great_expectations`)

```bash
make test           # unit & integration
make coverage       # HTML coverage report
```

---

## Deployment

### Docker (local)

```bash
docker-compose -f docker-compose.local.yml up --build
```

### Kubernetes

Helm charts are in `deploy/helm/fraud-detection-service/`.  
Key values:

```yaml
replicaCount: 4
image:
  repository: ghcr.io/crowdpay/fds
resources:
  limits:
    cpu: "1"
    memory: 1024Mi
autoscaling:
  enabled: true
  maxReplicas: 10
```

---

## Contributing

1. Fork the repo & create a feature branch.
2. Follow the commit message convention (`type(scope): subject`).
3. Run `pre-commit run --all-files`.
4. Open a PR and fill in the PR template.

---

## License
Copyright © CrowdPay  
Released under the Apache-2.0 license.
```