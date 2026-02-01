```markdown
# CrowdPay Connect 🌐💸  
_Social-first, component-based fintech payments for the modern world_

[![Build Status](https://github.com/your-org/crowdpay_connect/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/crowdpay_connect/actions)  
[![Coverage Status](https://coveralls.io/repos/github/your-org/crowdpay_connect/badge.svg?branch=main)](https://coveralls.io/github/your-org/crowdpay_connect?branch=main)  
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

> CrowdPay Connect enables friends, families, and communities to pool, split, lend, and donate in **190+ currencies**—securely and transparently—while embedding a social layer that incentivises responsible spending through gamified reputation.

---

## Table of Contents
1. [Key Features](#key-features)
2. [Architecture Overview](#architecture-overview)
3. [Getting Started](#getting-started)
4. [Quick Start (5 Minutes)](#quick-start-5-minutes)
5. [Configuration](#configuration)
6. [Security & Compliance](#security--compliance)
7. [Development Guide](#development-guide)
8. [Contributing](#contributing)
9. [License](#license)

---

## Key Features

| Category                 | Highlights                                                                                     |
| ------------------------ | ---------------------------------------------------------------------------------------------- |
| Social Payments          | Followable _CrowdPods_, up-votes, contextual notifications, and gamified trust scores.         |
| Multi-Currency Wallets   | Pool, split or convert money at **real-time FX rates** with auto-hedging options.               |
| Risk & KYC Micro-Services| Real-time AML, fraud scoring, and per-transaction KYC orchestration.                            |
| Saga-based Settlement    | Distributed Saga transactions ensure atomicity across bank rails, PSPs, and on-chain ledgers.  |
| Event Sourcing & CQRS    | Immutable audit trail with re-buildable read models for analytics and compliance reporting.     |
| Developer-First          | Python SDK, WebHooks, GraphQL & REST API, and sandbox environment with seed data.              |


---

## Architecture Overview

```text
┌───────────────────────────┐     Event Bus      ┌───────────────────────────┐
│    Social Service        │◄──────────────────►│   Notification Service     │
└───────────────────────────┘                    └───────────────────────────┘
         ▲                ▲                               ▲
         │                │Saga Commands                  │
         │                │                               │
┌────────┴─────────┐   ┌──┴────────────────┐    ┌─────────┴────────┐
│  API Gateway      │   │   Saga Orchestrator│    │ Audit Trail      │
└────────┬─────────┘   └────────┬───────────┘    └─────────┬────────┘
         │                      │                            │
   REST / GraphQL         ┌─────▼──────┐         Immutable event log
         │                │ Settlement │
┌────────▼─────────┐      │  Engine    │
│ CrowdPod Service │      └─────┬──────┘
└────────┬─────────┘            │FX / PSP Bridges
         │                      ▼
   KYC / Risk Checks     ┌──────────────┐
         │               │ PSP / Banks  │
         ▼               └──────────────┘
```

Core architectural patterns:

* **Security by Design**  
* **Event Sourcing & CQRS**  
* **Saga Pattern** for distributed, long-running transactions  
* **Micro-services** communicating over gRPC + NATS  
* **Audit Trail** guaranteeing tamper-evident logs  

---

## Getting Started

### Prerequisites
* Python 3.9+
* Docker 20.10+
* Docker Compose v2
* Make

### Installation

```bash
# 🔥 Install SDK only
pip install crowdpay-connect

# ▶️ Run full local stack
git clone git@github.com:your-org/crowdpay_connect.git
cd crowdpay_connect
make bootstrap         # Pull images, install hooks
make up                # docker-compose up ‑d
```

When containers are healthy, the API Gateway is reachable at `https://localhost:8080`.

---

## Quick Start (5 Minutes)

```python
"""
Minimal example: create a CrowdPod, invite a friend, and send money in two currencies.
"""
from crowdpay_connect import CrowdPayClient
from crowdpay_connect.models import Currency, Invitee

# 1️⃣  Initialise client (uses ~/.crowdpay/credentials by default)
client = CrowdPayClient(
    api_key="sandbox_xxx",
    api_url="https://sandbox.api.crowdpay.dev"
)

# 2️⃣  Create a CrowdPod
pod = client.crowdpods.create(
    name="EuroTrip 2025",
    description="Group wallet for flights, hostels, and pizza",
    base_currency=Currency.EUR
)
print(f"Created pod → {pod.id}")

# 3️⃣  Invite a friend
client.crowdpods.invite(
    pod_id=pod.id,
    invitee=Invitee(
        email="friend@example.com",
        role="member"
    )
)

# 4️⃣  Top-up in USD (automatically converted to EUR)
tx_topup = client.wallets.top_up(
    pod_id=pod.id,
    amount_minor=200_00,   # $200.00
    currency=Currency.USD,
    payment_method_id="pm_1234"
)
print("Top-up:", tx_topup.status)

# 5️⃣  Pay merchant in GBP – FX handled by backend
tx_pay = client.transactions.pay(
    pod_id=pod.id,
    merchant_id="mcn_9876",
    amount_minor=85_00,    # £85.00
    currency=Currency.GBP,
)
print("Payment:", tx_pay.status)
```

➡️ Open `https://sandbox.console.crowdpay.dev` to see live Saga steps, event logs, and social feed updates.

---

## Configuration

Environment variables (or `crowdpay.toml`) drive runtime behaviour:

| Variable                       | Default                 | Purpose                           |
| ------------------------------ | ----------------------- | --------------------------------- |
| `CP_API_KEY`                   | _None_ (required)       | Auth token for SDK / CLI          |
| `CP_API_URL`                   | `https://api.crowdpay.io`| Base URL for REST/GraphQL         |
| `CP_ENV`                       | `production`            | Selects config profile            |
| `CP_ENCRYPTION_MASTER_KEY`     | _rotated in Vault_      | AES-256 encryption key            |
| `CP_DB_DSN`                    | `postgres://…`          | Write-model DB (events)           |
| `CP_READ_DB_DSN`               | `postgres://…_ro…`      | Read-model DB                     |
| `CP_NATS_URL`                  | `nats://localhost:4222` | Event bus                         |

For a full list, run:

```bash
crowdpay --help
```

---

## Security & Compliance

* **PCI-DSS SAQ-D** audited, tokenised cards / vaulted credentials.  
* All sensitive fields are end-to-end encrypted using **AES-256-GCM** with envelope keys in HashiCorp Vault.  
* Continuous **KYC/AML** screening via Chainalysis & ComplyAdvantage feeds.  
* GDPR & CCPA tooling with automated data-subject export/delete flows.  
* Immutable, append-only event store for regulator audits (FCA, FINTRAC).  

---

## Development Guide

1. Code style: `black`, `ruff`, `mypy`.
2. Conventional commits with semantic versioning.
3. Pre-commit hooks are enforced:

```bash
pre-commit install
```

4. Run unit & integration tests:

```bash
make test          # pytest -q
make int-test      # docker-compose -f docker-compose.test.yml up
```

5. Local docs:

```bash
mkdocs serve
```

### Branching Strategy

* `main`: always deployable (protected).
* `release/*`: tagged for production, triggers CD.
* `feat/*`, `fix/*`, `chore/*`: short-lived feature branches.

---

## Contributing

We 💛 contributions—issues, pull requests, and RFCs are all welcome.

1. Fork & clone
2. Create your branch: `git checkout -b feat/my-awesome-feature`
3. Commit with sign-off: `git commit -s -m 'feat: my awesome feature'`
4. Push: `git push origin feat/my-awesome-feature`
5. Open a PR and fill out the template.

Please check the [Contributor Guide](CONTRIBUTING.md) first.

---

## License
CrowdPay Connect is licensed under the **Apache License 2.0**.  
See [LICENSE](LICENSE) for the full text.

---

_© 2024 CrowdPay Technologies Ltd. All rights reserved._
```