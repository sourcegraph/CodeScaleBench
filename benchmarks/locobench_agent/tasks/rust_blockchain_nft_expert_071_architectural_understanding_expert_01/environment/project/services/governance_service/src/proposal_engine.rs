```rust
//! Proposal Engine
//!
//! This module owns the lifecycle of a governance proposal—from
//! creation to finalization—inside the CanvasChain Symphony governance
//! micro-service.  It is intentionally decoupled from concrete storage,
//! crypto or transport layers via small, test-friendly traits so that
//! the engine can be reused inside CLI tools, HTTP controllers or gRPC
//! handlers without recompilation.

#![allow(clippy::module_name_repetitions)]

use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
    time::Duration,
};

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use log::{debug, error, info, warn};
use rand::Rng;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::{
    sync::RwLock,
    task::JoinHandle,
    time::{self, Instant},
};
use uuid::Uuid;

/// Error type returned by the proposal engine.
#[derive(Debug, Error)]
pub enum ProposalError {
    #[error("storage error: {0}")]
    Storage(String),
    #[error("signature verification failed")]
    InvalidSignature,
    #[error("proposal not found: {0}")]
    NotFound(Uuid),
    #[error("vote already cast by voter")]
    DuplicateVote,
    #[error("proposal already finalized")]
    Finalized,
    #[error("internal error: {0}")]
    Internal(String),
}

/// Supported vote choices.
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub enum VoteChoice {
    Yes,
    No,
    Abstain,
}

/// Current status of a proposal.
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub enum ProposalStatus {
    Pending,
    Active,
    Finalized,
}

/// A governance proposal.  The semantics of the payload are opaque to
/// the proposal engine and can encode anything from smart-contract
/// upgrades to art-movement parameters.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Proposal {
    pub id: Uuid,
    pub author: String,
    pub status: ProposalStatus,
    pub created_at: DateTime<Utc>,
    pub expires_at: DateTime<Utc>,
    pub payload: serde_json::Value,
    pub votes: HashMap<String, VoteChoice>,
}

/// Governance parameters under which a proposal is evaluated.
#[derive(Clone, Debug)]
pub struct GovernanceParameters {
    /// Minimum voting period.
    pub voting_period: Duration,
    /// Quorum required as percentage (0–100).
    pub quorum_pct: u8,
    /// Minimum “Yes” ratio required to pass (0–100).
    pub pass_threshold_pct: u8,
}

/// Event emitted by the proposal engine to the wider event-bus.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum GovernanceEvent {
    ProposalCreated { proposal_id: Uuid, author: String },
    VoteCast {
        proposal_id: Uuid,
        voter: String,
        choice: VoteChoice,
    },
    ProposalFinalized {
        proposal_id: Uuid,
        result: ProposalOutcome,
    },
}

/// Finalization result.
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub enum ProposalOutcome {
    Accepted,
    Rejected,
    QuorumNotMet,
}

/// Storage abstraction – can be backed by Postgres, RocksDB, Redis, etc.
#[async_trait]
pub trait ProposalStore: Send + Sync + 'static {
    async fn save_proposal(&self, proposal: &Proposal) -> Result<(), ProposalError>;

    async fn load_proposal(&self, id: Uuid) -> Result<Proposal, ProposalError>;

    async fn save_vote(
        &self,
        proposal_id: Uuid,
        voter: &str,
        choice: VoteChoice,
    ) -> Result<(), ProposalError>;

    async fn list_active(&self) -> Result<Vec<Proposal>, ProposalError>;

    async fn finalize(
        &self,
        proposal_id: Uuid,
        outcome: ProposalOutcome,
    ) -> Result<(), ProposalError>;
}

/// Event publisher abstraction – decouples the engine from concrete
/// transport: NATS, Kafka, in-process channel, etc.
#[async_trait]
pub trait EventPublisher: Send + Sync + 'static {
    async fn publish(&self, event: GovernanceEvent);
}

/// Signature verification strategy.  Each wallet/curve implementation
/// can plug its own verifier (Ed25519, BLS, post-quantum…).
#[async_trait]
pub trait SignatureVerifier: Send + Sync + 'static {
    async fn verify(
        &self,
        wallet_address: &str,
        payload: &[u8],
        signature: &[u8],
    ) -> Result<(), ProposalError>;
}

/// A default in-memory storage for local testing.
///
/// THIS IS NOT SUITABLE FOR PRODUCTION but helps keeping the code
/// self-contained for demonstration purposes.
#[derive(Default)]
pub struct InMemoryStore {
    proposals: RwLock<HashMap<Uuid, Proposal>>,
}

#[async_trait]
impl ProposalStore for InMemoryStore {
    async fn save_proposal(&self, proposal: &Proposal) -> Result<(), ProposalError> {
        self.proposals
            .write()
            .await
            .insert(proposal.id, proposal.clone());
        Ok(())
    }

    async fn load_proposal(&self, id: Uuid) -> Result<Proposal, ProposalError> {
        self.proposals
            .read()
            .await
            .get(&id)
            .cloned()
            .ok_or(ProposalError::NotFound(id))
    }

    async fn save_vote(
        &self,
        proposal_id: Uuid,
        voter: &str,
        choice: VoteChoice,
    ) -> Result<(), ProposalError> {
        let mut map = self.proposals.write().await;
        let proposal = map
            .get_mut(&proposal_id)
            .ok_or(ProposalError::NotFound(proposal_id))?;

        if proposal.status != ProposalStatus::Active {
            return Err(ProposalError::Finalized);
        }
        if proposal.votes.contains_key(voter) {
            return Err(ProposalError::DuplicateVote);
        }

        proposal.votes.insert(voter.to_owned(), choice);
        Ok(())
    }

    async fn list_active(&self) -> Result<Vec<Proposal>, ProposalError> {
        Ok(self
            .proposals
            .read()
            .await
            .values()
            .filter(|p| p.status == ProposalStatus::Active)
            .cloned()
            .collect())
    }

    async fn finalize(
        &self,
        proposal_id: Uuid,
        _outcome: ProposalOutcome,
    ) -> Result<(), ProposalError> {
        let mut map = self.proposals.write().await;
        let proposal = map
            .get_mut(&proposal_id)
            .ok_or(ProposalError::NotFound(proposal_id))?;
        proposal.status = ProposalStatus::Finalized;
        Ok(())
    }
}

/// A no-op event publisher, useful for CLI & tests.
pub struct NullPublisher;

#[async_trait]
impl EventPublisher for NullPublisher {
    async fn publish(&self, _event: GovernanceEvent) {
        // swallow
    }
}

/// The main façade exposed to the outer world.  All methods are
/// thread-safe and async aware.
pub struct ProposalEngine<S, E, V>
where
    S: ProposalStore,
    E: EventPublisher,
    V: SignatureVerifier,
{
    store: Arc<S>,
    events: Arc<E>,
    verifier: Arc<V>,
    config: GovernanceParameters,
    /// Task handle for the background finalizer loop.
    finalizer_task: RwLock<Option<JoinHandle<()>>>,
}

impl<S, E, V> ProposalEngine<S, E, V>
where
    S: ProposalStore,
    E: EventPublisher,
    V: SignatureVerifier,
{
    pub fn new(store: Arc<S>, events: Arc<E>, verifier: Arc<V>) -> Self {
        let config = GovernanceParameters {
            voting_period: Duration::from_secs(60 * 60 * 24), // 24h
            quorum_pct: 15,
            pass_threshold_pct: 50,
        };

        Self {
            store,
            events,
            verifier,
            config,
            finalizer_task: RwLock::new(None),
        }
    }

    /// Spawns the periodic finalization loop.  Calling this twice is a
    /// no-op.
    pub async fn start(&self) {
        let mut guard = self.finalizer_task.write().await;
        if guard.is_some() {
            return;
        }
        let store = Arc::clone(&self.store);
        let events = Arc::clone(&self.events);
        let params = self.config.clone();

        *guard = Some(tokio::spawn(async move {
            let mut ticker = time::interval(Duration::from_secs(30));
            loop {
                ticker.tick().await;
                if let Err(err) = finalize_expired(&store, &events, &params).await {
                    error!("auto-finalization cycle failed: {err:?}");
                }
            }
        }));
    }

    /// Creates and stores a new proposal.  The caller is responsible for
    /// signing the payload.
    ///
    /// `signature` must verify against `author` and the payload bytes
    /// (as canonical JSON).
    pub async fn create_proposal(
        &self,
        author: &str,
        payload: serde_json::Value,
        signature: &[u8],
    ) -> Result<Uuid, ProposalError> {
        let json_bytes = serde_json::to_vec(&payload)
            .map_err(|e| ProposalError::Internal(e.to_string()))?;

        self.verifier
            .verify(author, &json_bytes, signature)
            .await?;

        let now = Utc::now();
        let expires_at = now + chrono::Duration::from_std(self.config.voting_period)
            .map_err(|e| ProposalError::Internal(e.to_string()))?;

        let proposal = Proposal {
            id: Uuid::new_v4(),
            author: author.to_owned(),
            status: ProposalStatus::Active,
            created_at: now,
            expires_at,
            payload,
            votes: HashMap::default(),
        };

        self.store.save_proposal(&proposal).await?;
        self.events
            .publish(GovernanceEvent::ProposalCreated {
                proposal_id: proposal.id,
                author: author.to_owned(),
            })
            .await;

        Ok(proposal.id)
    }

    /// Cast a vote on an active proposal.
    pub async fn cast_vote(
        &self,
        proposal_id: Uuid,
        voter: &str,
        choice: VoteChoice,
        signature: &[u8],
    ) -> Result<(), ProposalError> {
        // Message to sign = proposal_id (16 bytes) || choice (1 byte)
        let mut msg = proposal_id.as_bytes().to_vec();
        msg.push(choice as u8);

        self.verifier.verify(voter, &msg, signature).await?;

        self.store
            .save_vote(proposal_id, voter, choice)
            .await
            .map_err(|e| {
                debug!("save_vote failed: {e}");
                e
            })?;

        self.events
            .publish(GovernanceEvent::VoteCast {
                proposal_id,
                voter: voter.to_owned(),
                choice,
            })
            .await;

        Ok(())
    }

    /// Forces finalization of an active proposal, ignoring `expires_at`
    /// (useful for emergency admin operations).
    pub async fn finalize_now(&self, proposal_id: Uuid) -> Result<(), ProposalError> {
        let proposal = self.store.load_proposal(proposal_id).await?;
        let outcome = compute_outcome(&proposal, &self.config);
        self.store.finalize(proposal_id, outcome).await?;
        self.events
            .publish(GovernanceEvent::ProposalFinalized { proposal_id, result: outcome })
            .await;
        Ok(())
    }
}

/// Computes the outcome according to yes/no/abstain counts and the
/// engine’s governance parameters.
fn compute_outcome(proposal: &Proposal, params: &GovernanceParameters) -> ProposalOutcome {
    let total_votes = proposal.votes.len() as u64;
    if total_votes == 0 {
        return ProposalOutcome::QuorumNotMet;
    }

    let yes = proposal
        .votes
        .values()
        .filter(|&&c| c == VoteChoice::Yes)
        .count() as u64;
    let no = proposal
        .votes
        .values()
        .filter(|&&c| c == VoteChoice::No)
        .count() as u64;
    let abstain = total_votes - yes - no;

    debug!(
        "Computing outcome – yes:{yes}, no:{no}, abstain:{abstain}, total:{total_votes}"
    );

    let quorum_met = (total_votes * 100 / u64::MAX.max(total_votes)) >= params.quorum_pct as u64;

    if !quorum_met {
        return ProposalOutcome::QuorumNotMet;
    }

    let yes_pct = yes * 100 / total_votes;
    if yes_pct >= params.pass_threshold_pct as u64 {
        ProposalOutcome::Accepted
    } else {
        ProposalOutcome::Rejected
    }
}

/// Periodic task for auto-finalizing expired proposals.
async fn finalize_expired<S: ProposalStore, E: EventPublisher>(
    store: &Arc<S>,
    events: &Arc<E>,
    params: &GovernanceParameters,
) -> Result<(), ProposalError> {
    let now = Utc::now();
    for mut proposal in store.list_active().await? {
        if proposal.expires_at <= now {
            let outcome = compute_outcome(&proposal, params);
            store.finalize(proposal.id, outcome).await?;
            events
                .publish(GovernanceEvent::ProposalFinalized {
                    proposal_id: proposal.id,
                    result: outcome,
                })
                .await;
            info!("proposal {} finalized with result {:?}", proposal.id, outcome);
        }
    }
    Ok(())
}

/// A mock signature verifier that accepts 1% of the messages randomly
/// as invalid.  Replace with a real crypto verifier in production.
pub struct PseudoVerifier;

#[async_trait]
impl SignatureVerifier for PseudoVerifier {
    async fn verify(
        &self,
        _wallet_address: &str,
        _payload: &[u8],
        _signature: &[u8],
    ) -> Result<(), ProposalError> {
        let mut rng = rand::thread_rng();
        let rejected: bool = rng.gen_bool(0.01);
        if rejected {
            Err(ProposalError::InvalidSignature)
        } else {
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[tokio::test]
    async fn happy_path() {
        let engine = ProposalEngine::new(
            Arc::new(InMemoryStore::default()),
            Arc::new(NullPublisher),
            Arc::new(PseudoVerifier),
        );

        let payload = json!({
            "type": "change_quorum",
            "new_quorum": 20
        });
        let author = "wallet_1";

        let proposal_id = engine
            .create_proposal(author, payload, &[0u8; 64])
            .await
            .expect("create proposal");

        engine
            .cast_vote(proposal_id, "voter_a", VoteChoice::Yes, &[0u8; 64])
            .await
            .expect("vote a");

        engine
            .cast_vote(proposal_id, "voter_b", VoteChoice::Yes, &[0u8; 64])
            .await
            .expect("vote b");

        engine.finalize_now(proposal_id).await.expect("finalize");

        let proposal = engine
            .store
            .load_proposal(proposal_id)
            .await
            .expect("load final");
        assert_eq!(proposal.status, ProposalStatus::Finalized);
    }
}
```