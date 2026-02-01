```rust
//! Proposal state-machine and domain logic for the governance micro-service.
//!
//! The state–machine is **deterministic** and therefore can be executed
//! independently by every node.  Transitions are validated before they are
//! applied so an invalid state change can never be persisted nor propagated.
//!
//! ┌──────────┐     activate()     ┌─────────────┐
//! │  Draft   │ ─────────────────► │   Voting    │
//! └──────────┘                    └─────────────┘
//!                                       │  (voting_end)
//!                                       ▼
//!                               ┌────────────────┐
//!                               │   Tallying     │
//!                               └────────────────┘
//!                               │ tally()                │
//!                  ┌────────────┴────────────┐
//!                  ▼                         ▼
//!        ┌────────────────┐      ┌─────────────────┐
//!        │    Passed      │      │     Failed      │
//!        └────────────────┘      └─────────────────┘
//!                  │ execute()                 │ (terminal)
//!                  ▼                           ▼
//!           ┌──────────────┐
//!           │  Executed    │
//!           └──────────────┘
//!
//! A proposal may also `expire()` from `Draft` or `Voting`.
//!
//! NOTE: All time-related decisions are performed with UTC timestamps to
//! guarantee determinism across time-zones.

use std::collections::HashSet;
use std::fmt;

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Unique identifier for a proposal inside the governance service.
///
/// For simplicity we use `u64`, but in a production chain this could be a
/// 256-bit hash or a content-addressed CID.
pub type ProposalId = u64;

/// The decision a voter can take.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum VoteKind {
    Yes,
    No,
}

/// A single voter’s ballot.  The *weight* is typically the voter’s stake at the
/// time the vote is cast.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Ballot {
    pub voter: String, // Wallet or account address in bech32/hex format.
    pub weight: u64,
    pub kind: VoteKind,
}

/// Domain errors that can be produced by the [`ProposalState`] state machine.
#[derive(Debug, Error, Serialize, Deserialize)]
pub enum ProposalStateError {
    #[error("attempted an illegal state transition from {0:?} with action {1}")]
    IllegalTransition(ProposalPhase, &'static str),

    #[error("proposal has already expired")]
    Expired,

    #[error("duplicate vote from voter {0}")]
    DuplicateVote(String),

    #[error("voting period has not ended yet")]
    VotingStillInProgress,

    #[error("tallying has already been finalised")]
    AlreadyTallied,

    #[error("proposal execution window has elapsed")]
    ExecutionWindowElapsed,
}

/// Discrete states of a proposal lifecycle.
///
/// The enum is `repr(u8)` so it can be stored compactly in a database.
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, strum::Display,
)]
#[repr(u8)]
pub enum ProposalPhase {
    Draft = 0,
    Voting = 1,
    Tallying = 2,
    Passed = 3,
    Failed = 4,
    Executed = 5,
    Expired = 6,
}

/// Aggregate that represents the *current* state of a proposal.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProposalState {
    pub id: ProposalId,
    pub title: String,
    pub description: String,

    pub created_at: DateTime<Utc>,

    /// When the voting period ends (`Voting` → `Tallying`).
    pub voting_end: DateTime<Utc>,

    /// The maximum time after `Passed` during which the proposal can be
    /// executed.
    pub execution_deadline: DateTime<Utc>,

    phase: ProposalPhase,

    // Vote accounting
    yes_votes: u128,
    no_votes: u128,
    voters: HashSet<String>, // Prevent duplicate voting

    // Snapshot taken once tallying is finished.
    tally_finalised_at: Option<DateTime<Utc>>,
}

impl ProposalState {
    /// Create a proposal in the `Draft` phase.
    ///
    /// - `voting_period` and `execution_period` are expressed in *seconds*.
    pub fn new(
        id: ProposalId,
        title: impl Into<String>,
        description: impl Into<String>,
        voting_period: Duration,
        execution_period: Duration,
    ) -> Self {
        let now = Utc::now();
        Self {
            id,
            title: title.into(),
            description: description.into(),
            created_at: now,
            voting_end: now + voting_period,
            execution_deadline: now + voting_period + execution_period,
            phase: ProposalPhase::Draft,
            yes_votes: 0,
            no_votes: 0,
            voters: HashSet::new(),
            tally_finalised_at: None,
        }
    }

    /// Returns the current phase.
    pub fn phase(&self) -> ProposalPhase {
        self.phase
    }

    /// Transitions a proposal from `Draft` to `Voting`.
    ///
    /// Anyone can activate a draft at any time before the voting deadline.
    pub fn activate(&mut self, now: DateTime<Utc>) -> Result<(), ProposalStateError> {
        match self.phase {
            ProposalPhase::Draft => {
                if now >= self.voting_end {
                    return Err(ProposalStateError::Expired);
                }
                self.phase = ProposalPhase::Voting;
                Ok(())
            }
            current => Err(ProposalStateError::IllegalTransition(
                current,
                "activate",
            )),
        }
    }

    /// Record a vote during the *Voting* phase.
    pub fn cast_vote(&mut self, ballot: Ballot) -> Result<(), ProposalStateError> {
        if self.phase != ProposalPhase::Voting {
            return Err(ProposalStateError::IllegalTransition(
                self.phase,
                "cast_vote",
            ));
        }

        if Utc::now() >= self.voting_end {
            return Err(ProposalStateError::VotingStillInProgress);
        }

        // Prevent duplicate voting.
        if !self.voters.insert(ballot.voter.clone()) {
            return Err(ProposalStateError::DuplicateVote(ballot.voter));
        }

        match ballot.kind {
            VoteKind::Yes => self.yes_votes += ballot.weight as u128,
            VoteKind::No => self.no_votes += ballot.weight as u128,
        }

        Ok(())
    }

    /// End of voting period. Moves to `Tallying`.
    pub fn finish_voting(&mut self, now: DateTime<Utc>) -> Result<(), ProposalStateError> {
        if self.phase != ProposalPhase::Voting {
            return Err(ProposalStateError::IllegalTransition(
                self.phase,
                "finish_voting",
            ));
        }
        if now < self.voting_end {
            return Err(ProposalStateError::VotingStillInProgress);
        }
        self.phase = ProposalPhase::Tallying;
        Ok(())
    }

    /// Tallies the votes and decides `Passed` or `Failed`.
    ///
    /// *Quorum* and *threshold* are supplied externally so the blockchain can
    /// upgrade them via governance without redeploying this micro-service.
    pub fn tally(
        &mut self,
        quorum: u128,
        threshold_ratio: f64,
        now: DateTime<Utc>,
    ) -> Result<(), ProposalStateError> {
        if self.phase != ProposalPhase::Tallying {
            return Err(ProposalStateError::IllegalTransition(self.phase, "tally"));
        }
        if self.tally_finalised_at.is_some() {
            return Err(ProposalStateError::AlreadyTallied);
        }

        // Enforce quorum.
        let total_votes = self.yes_votes + self.no_votes;
        if total_votes < quorum {
            self.phase = ProposalPhase::Failed;
            self.tally_finalised_at = Some(now);
            return Ok(());
        }

        // Enforce acceptance threshold.
        let yes_ratio = self.yes_votes as f64 / total_votes as f64;
        if yes_ratio >= threshold_ratio {
            self.phase = ProposalPhase::Passed;
        } else {
            self.phase = ProposalPhase::Failed;
        };
        self.tally_finalised_at = Some(now);
        Ok(())
    }

    /// Executes a `Passed` proposal, moving it to `Executed`.
    pub fn execute(&mut self, now: DateTime<Utc>) -> Result<(), ProposalStateError> {
        match self.phase {
            ProposalPhase::Passed => {
                if now > self.execution_deadline {
                    return Err(ProposalStateError::ExecutionWindowElapsed);
                }
                self.phase = ProposalPhase::Executed;
                Ok(())
            }
            current => Err(ProposalStateError::IllegalTransition(current, "execute")),
        }
    }

    /// Expires a proposal that is still waiting either in `Draft` or `Voting`.
    pub fn expire(&mut self, now: DateTime<Utc>) -> Result<(), ProposalStateError> {
        if self.phase == ProposalPhase::Expired
            || self.phase == ProposalPhase::Executed
            || self.phase == ProposalPhase::Failed
            || self.phase == ProposalPhase::Passed
        {
            return Err(ProposalStateError::IllegalTransition(
                self.phase,
                "expire",
            ));
        }

        if now < self.execution_deadline {
            // Don’t allow premature expirations.
            return Err(ProposalStateError::IllegalTransition(
                self.phase,
                "expire (deadline not reached)",
            ));
        }

        self.phase = ProposalPhase::Expired;
        Ok(())
    }

    /// Helper that automatically transitions based on timeouts.
    ///
    /// SHOULD be called periodically by the orchestration runtime.
    pub fn tick(&mut self, now: DateTime<Utc>) -> Result<(), ProposalStateError> {
        match self.phase {
            ProposalPhase::Voting if now >= self.voting_end => {
                self.finish_voting(now)?;
            }
            ProposalPhase::Passed if now > self.execution_deadline => {
                self.phase = ProposalPhase::Expired;
            }
            ProposalPhase::Draft | ProposalPhase::Voting
                if now > self.execution_deadline =>
            {
                self.phase = ProposalPhase::Expired;
            }
            _ => { /* no-op */ }
        }
        Ok(())
    }
}

/* ============================== Display ============================== */

impl fmt::Display for ProposalState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        writeln!(f, "Proposal #{id}: {title}", id = self.id, title = self.title)?;
        writeln!(f, "Phase      : {}", self.phase)?;
        writeln!(f, "Yes / No   : {} / {}", self.yes_votes, self.no_votes)?;
        writeln!(f, "Created at : {}", self.created_at)?;
        writeln!(f, "Vote end   : {}", self.voting_end)?;
        writeln!(f, "Exec until : {}", self.execution_deadline)?;
        Ok(())
    }
}

/* ============================== Tests ============================== */

#[cfg(test)]
mod tests {
    use super::*;

    fn setup_proposal() -> ProposalState {
        ProposalState::new(
            1,
            "Test Proposal",
            "A proposal used for unit testing",
            Duration::seconds(10),
            Duration::seconds(20),
        )
    }

    #[test]
    fn lifecycle_happy_path() {
        let mut proposal = setup_proposal();
        let creation_time = proposal.created_at;

        // Activate
        proposal.activate(creation_time).unwrap();
        assert_eq!(proposal.phase(), ProposalPhase::Voting);

        // Cast votes
        proposal
            .cast_vote(Ballot {
                voter: "alice".into(),
                weight: 50,
                kind: VoteKind::Yes,
            })
            .unwrap();
        proposal
            .cast_vote(Ballot {
                voter: "bob".into(),
                weight: 10,
                kind: VoteKind::No,
            })
            .unwrap();

        // Move time forward to end of voting
        let after_vote_end = creation_time + Duration::seconds(11);
        proposal.finish_voting(after_vote_end).unwrap();
        assert_eq!(proposal.phase(), ProposalPhase::Tallying);

        // Tally with quorum 1 and threshold 0.5
        proposal
            .tally(1, 0.6, after_vote_end + Duration::seconds(1))
            .unwrap();
        assert_eq!(proposal.phase(), ProposalPhase::Passed);

        // Execute
        let exec_time = creation_time + Duration::seconds(25);
        proposal.execute(exec_time).unwrap();
        assert_eq!(proposal.phase(), ProposalPhase::Executed);
    }

    #[test]
    fn quorum_failure() {
        let mut proposal = setup_proposal();
        proposal.activate(proposal.created_at).unwrap();

        let after_vote_end = proposal.created_at + Duration::seconds(11);
        proposal.finish_voting(after_vote_end).unwrap();
        // No votes -> should fail quorum
        proposal
            .tally(1, 0.5, after_vote_end + Duration::seconds(1))
            .unwrap();
        assert_eq!(proposal.phase(), ProposalPhase::Failed);
    }

    #[test]
    fn duplicate_vote() {
        let mut proposal = setup_proposal();
        proposal.activate(proposal.created_at).unwrap();

        proposal
            .cast_vote(Ballot {
                voter: "alice".into(),
                weight: 1,
                kind: VoteKind::Yes,
            })
            .unwrap();
        let res = proposal.cast_vote(Ballot {
            voter: "alice".into(),
            weight: 1,
            kind: VoteKind::No,
        });
        assert!(matches!(res, Err(ProposalStateError::DuplicateVote(_))));
    }
}
```