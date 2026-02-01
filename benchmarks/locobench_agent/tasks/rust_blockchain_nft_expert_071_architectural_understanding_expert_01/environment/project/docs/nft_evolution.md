```markdown
# CanvasChain Symphony — NFT Evolution Specification
*Version: 1.0.0 | Status: Draft | Last-Updated: 2024-05-18*

> “Every artwork is a living organism.  
>  — *V. Kandinsky (probably)”*

---

## 1 ‑ Purpose

The goal of this document is to **formally describe the life-cycle and on-chain
state machine** that governs a _Multilayer NFT_ (mNFT) inside CanvasChain
Symphony.  
It serves as:

1. A contract between backend engineers, smart-contract authors, frontend
   clients, and governance maintainers.
2. A reference for implementers of **`canvaschain-nft-runtime`** (Rust micro-service),
   **gRPC APIs**, and **Protocol Buffers**.
3. A knowledge-base for artists and DAO voters to understand how their decisions
   move an artwork forward.

---

## 2 ‑ High-Level Overview

```
+-------------------+          +-------------------+
|   Composer Node   |  emits   |    Event Bus      |
| (PoI Consensus)   +--------->+ (NATS JetStream)  |
+-------------------+          +----------+--------+
                                         |
                                         |   event::NftEvolved
                                         v
+-------------------+      gRPC   +------+------+
|  NFT Runtime Svc  +------------>+  State DB   |
|  (Rust / tonic)   |  state      | (sled /   ) |
+--------+----------+             | Postgres ) |
         |                        +------------+
         | Observes
         v
+-------------------+            +----------------+
|    Observer UI    |  websockets|   Public API   |
+-------------------+            +----------------+
```

1. **Composer Node** — Selected via *Proof-of-Inspiration* (PoI) to publish
   generative updates.
2. **Event Bus** — Decouples micro-services (NATS).
3. **NFT Runtime Svc** — Maintains canonical state machine + verification.
4. **Observer UI** — Real-time ownership & trait visualization.

---

## 3 ‑ NFT State Machine

```
stateDiagram-v2
    [*] --> Seeded : Minted
    Seeded --> Dormant : Freeze
    Dormant --> Flourishing : Inspire
    Flourishing --> Flourishing : Evolve*
    Flourishing --> Fragmented : Split
    Fragmented --> Dormant : Merge
    Flourishing --> Archived : Burn
    Dormant --> Archived : Burn
    Archived --> [*]

    note right of Seeded : Layer-0 metadata stored
    note left of Flourishing : Layer-N traits evolve
```

### 3.1 ‑ State Definitions

| State        | Description                                                                               |
|--------------|-------------------------------------------------------------------------------------------|
| `Seeded`     | Newly minted. Contains only base DNA and creator signature.                               |
| `Dormant`    | Frozen to preserve a snapshot. Cannot evolve until *Inspire*.                             |
| `Flourishing`| Fully mutable. Traits can be appended, replaced, or decayed.                              |
| `Fragmented` | Temporarily split into derivative pieces for remixing / fractional DAO ownership.         |
| `Archived`   | Finalized. No further state transitions possible.                                         |

### 3.2 ‑ Transition Rules

1. `Freeze` requires multi-sig approval by **creator + ≥51 % current holders**.
2. `Inspire` requires PoI-selected composer **+ gRPC verification**.
3. `Evolve*` may only occur once every _epoch_ (`config.evolution_cadence`).
4. `Merge` requires `Fragmented` tokens to reference the same `origin_hash`.
5. `Burn` is irreversible and must pass the runtime `BurnPolicy` strategy.

---

## 4 ‑ gRPC API (`proto/nft_evolution.proto`)

```proto
syntax = "proto3";

package canvaschain.nft.v1;

service Evolution {
  rpc Inspire(InspireRequest) returns (InspireResponse);
  rpc Freeze(FreezeRequest)   returns (FreezeResponse);
  rpc Evolve(EvolveRequest)   returns (EvolveResponse);
  rpc Split(SplitRequest)     returns (SplitResponse);
  rpc Merge(MergeRequest)     returns (MergeResponse);
  rpc Burn(BurnRequest)       returns (BurnResponse);
}

message InspireRequest  { string nft_id = 1; bytes vrf_proof = 2; }
message InspireResponse { bool   accepted = 1; }

message FreezeRequest   { string nft_id = 1; repeated string signatures = 2; }
message FreezeResponse  { bool   accepted = 1; }

message EvolveRequest   { string nft_id = 1; bytes patch = 2; }
message EvolveResponse  { string new_cid = 1; }

message SplitRequest    { string nft_id = 1; uint32 parts = 2; }
message SplitResponse   { repeated string child_ids = 1; }

message MergeRequest    { repeated string child_ids = 1; }
message MergeResponse   { string merged_id = 1; }

message BurnRequest     { string nft_id = 1; }
message BurnResponse    { bool burned = 1; }
```

---

## 5 ‑ Rust Reference Implementation (core excerpt)

```rust
//! nft_runtime/src/state_machine.rs
use crate::error::NftError;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum Phase {
    Seeded,
    Dormant,
    Flourishing,
    Fragmented,
    Archived,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvolutionEvent {
    pub nft_id: String,
    pub from: Phase,
    pub to: Phase,
    pub tx_hash: String,
    pub timestamp: DateTime<Utc>,
}

impl EvolutionEvent {
    pub fn sanity_check(&self) -> Result<(), NftError> {
        if self.from == self.to {
            return Err(NftError::InvalidTransition(
                "from and to phase are identical".into(),
            ));
        }
        Ok(())
    }
}

pub trait Evolvable {
    fn current_phase(&self) -> Phase;
    fn transition(&mut self, to: Phase) -> Result<EvolutionEvent, NftError>;
}

impl Evolvable for Nft {
    fn current_phase(&self) -> Phase {
        self.phase.clone()
    }

    fn transition(&mut self, to: Phase) -> Result<EvolutionEvent, NftError> {
        ensure_transition_is_valid(self.phase.clone(), to.clone())?;
        let event = EvolutionEvent {
            nft_id: self.id.clone(),
            from: self.phase.clone(),
            to: to.clone(),
            tx_hash: blake3::hash(self.id.as_bytes()).to_string(),
            timestamp: Utc::now(),
        };
        event.sanity_check()?;
        self.phase = to;
        Ok(event)
    }
}

fn ensure_transition_is_valid(from: Phase, to: Phase) -> Result<(), NftError> {
    use Phase::*;
    match (from, to) {
        (Seeded, Dormant)
        | (Dormant, Flourishing)
        | (Flourishing, Flourishing)
        | (Flourishing, Fragmented)
        | (Fragmented, Dormant)
        | (Flourishing, Archived)
        | (Dormant, Archived) => Ok(()),

        _ => Err(NftError::InvalidTransition(format!(
            "illegal transition {:?} → {:?}",
            from, to
        ))),
    }
}
```

_Error definitions omitted; see `error.rs`._

---

## 6 ‑ Event-Driven Flow

1. *Client* signs and submits `EvolveRequest`.
2. **NFT Runtime Svc** validates patch and calls `Nft::transition(Flourishing)`.
3. Upon success it publishes:

```json
{
  "topic": "canvaschain.nft.evolved",
  "payload": {
    "nft_id": "0xA11CE",
    "new_cid": "bafybeia...",
    "epoch": 1192
  }
}
```

4. **Observer UI** receives the event via WebSocket bridge and performs a live
   transition animation, fetching the new asset layer from IPFS.

---

## 7 ‑ Strategy-Based Burn Policy (pluggable)

```rust
pub trait BurnPolicy: Send + Sync {
    fn can_burn(&self, nft: &Nft, requester: &Address) -> bool;
}

pub struct SimpleBurn;
impl BurnPolicy for SimpleBurn {
    fn can_burn(&self, nft: &Nft, requester: &Address) -> bool {
        nft.creator == *requester
    }
}

pub struct GovernanceBurn {
    pub quorum: u8,
}
impl BurnPolicy for GovernanceBurn {
    fn can_burn(&self, nft: &Nft, _requester: &Address) -> bool {
        dao::current_support(nft.id()) >= self.quorum
    }
}
```

The active strategy is selected at runtime through a *chain spec* parameter,
enabling experimental collectives to upgrade without a hard-fork.

---

## 8 ‑ Edge Cases & Error Handling

| Case                         | Response                                   |
|------------------------------|--------------------------------------------|
| Transition during lock       | `LOCKED` gRPC status.                     |
| Epoch cadence violation      | `FAILED_PRECONDITION` with retry-after.    |
| Missing VRF proof on Inspire | `UNAUTHENTICATED`.                         |
| Merge with mismatched DNA    | `INVALID_ARGUMENT`.                        |

---

## 9 ‑ Migration Notes (v0.9 → v1.0)

1. `Paused` state removed; use `Dormant`.
2. `Evolve` cadence changed to epoch-based (was block-based).
3. `Split` now returns deterministic `child_ids` derived from BLAKE3 tree.

---

## 10 ‑ Open Questions

1. Store large generative layers on Arweave mirror?
2. Plugging PQC signature strategies (Crystals-Dilithium) — target Q3.

---

## 11 ‑ Changelog

| Version | Date       | By          | Notes                       |
|---------|------------|-------------|-----------------------------|
| 1.0.0   | 2024-05-18 | @core-team  | Initial draft out of RFC-9. |

---

_© CanvasChain DAO 2024_
```