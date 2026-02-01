```rust
//! ccs_common::error
//! -----------------------------------------------------------------------------
//! Centralised error handling for the CanvasChain Symphony ecosystem.
//!
//! All crates that belong to CanvasChain Symphony should depend on
//! `ccs_common` and use `ccs_common::error::{Error, Result}` instead of rolling
//! their own error types.  This makes it straightforward to convert errors
//! across micro-service boundaries (gRPC / event-bus) and keeps `tonic::Status`
//! mapping in a single place.
//!
//! Error variants are intentionally broad.  Fine-grained details should be
//! encoded in the error message (`#[source]`) instead of proliferating new
//! variants per crate.
//!
//! Design goals:
//!   * Symmetric conversion to/from common third-party error types
//!   * Ergonomic `Result<T>` alias
//!   * Feature-gated conversions (e.g. `sqlx`, `sled`, `web3`)
//!   * Minimal dependencies: thiserror + optional crates via feature flags
//! -----------------------------------------------------------------------------

use std::{io, fmt, time::Duration};
use std::path::PathBuf;

use thiserror::Error;
use tracing::{debug, error};

/// A convenient `Result` alias tied to [`Error`].
pub type Result<T, E = Error> = std::result::Result<T, E>;

/// Top-level application error.
///
/// Each variant represents a category of failures that can occur anywhere
/// inside the project.  When mapping an external/foreign error, pick the
/// *broadest* matching category (e.g. any HTTP/REST client error maps to
/// `Error::Network`).  The original error is *always* preserved as the
/// `source`, allowing downstream callers to downcast when needed.
#[derive(Error)]
#[non_exhaustive]
pub enum Error {
    // ---------------------------------------------------------------------
    // General categories
    // ---------------------------------------------------------------------
    /// I/O error (file system, pipes, sockets …)
    #[error("I/O error: {0}")]
    Io(#[from] io::Error),

    /// (De)serialisation failure (`serde`, `bincode`, `prost`, …)
    #[error("serialization error: {0}")]
    Serialization(#[from] SerializationError),

    /// gRPC layer error (tonic)
    ///
    /// NOTE: This should only be used when *receiving* a Status from a remote
    /// peer.  Local services should convert `Error` → `Status` via
    /// [`Error::into_grpc_status`].
    #[error("gRPC status: {0}")]
    GrpcStatus(tonic::Status),

    /// Database-related failure (`sqlx`, `sled`, `rocksdb`, …)
    #[error("database error: {0}")]
    Database(#[from] DatabaseError),

    /// Cryptographic failure (signature mismatch, invalid key, VRF failure …)
    #[error("crypto error: {0}")]
    Crypto(CryptoError),

    /// Invalid user input or domain-level validation failure.
    #[error("invalid input: {0}")]
    InvalidInput(String),

    /// Requested entity could not be found in storage.
    #[error("not found: {0}")]
    NotFound(String),

    /// Caller is not authorised to perform the requested action.
    #[error("unauthorized: {0}")]
    Unauthorized,

    /// Entity already exists / conflict while creating a resource.
    #[error("resource conflict: {0}")]
    Conflict(String),

    /// Timeout while waiting for an external operation.
    #[error("timeout after {0:?}")]
    Timeout(Duration),

    /// Interaction with external‐service / network endpoint failed.
    #[error("network error: {0}")]
    Network(String),

    /// Generic catch-all for errors we don’t categorise yet.
    #[error("internal error: {0}")]
    Internal(String),
}

// -----------------------------------------------------------------------------
//  Sub error types
// -----------------------------------------------------------------------------

/// Separate enum for (de)serialisation failures so we can add feature-specific
/// conversions without polluting the main [`Error`] variants.
#[derive(Error)]
pub enum SerializationError {
    #[error(transparent)]
    Json(#[from] serde_json::Error),

    #[cfg(feature = "cbor")]
    #[error(transparent)]
    Cbor(#[from] serde_cbor::Error),

    #[cfg(feature = "msgpack")]
    #[error(transparent)]
    Rmp(#[from] rmp_serde::encode::Error),

    #[error("protobuf encode/decode: {0}")]
    Prost(#[from] prost::EncodeError),

    #[error("protobuf decode: {0}")]
    ProstDecode(#[from] prost::DecodeError),

    #[error("yaml error: {0}")]
    Yaml(#[from] serde_yaml::Error),

    #[error("binary encode/decode: {0}")]
    Bincode(#[from] bincode::ErrorKind),
}

#[derive(Error)]
pub enum DatabaseError {
    #[cfg(feature = "sqlx")]
    #[error(transparent)]
    Sqlx(#[from] sqlx::Error),

    #[cfg(feature = "sled")]
    #[error(transparent)]
    Sled(#[from] sled::Error),

    #[error("migration error: {0}")]
    Migration(String),

    #[error("entity constraint violation: {0}")]
    Constraint(String),

    #[error("unknown database error: {0}")]
    Other(String),
}

#[derive(Error, Debug)]
pub enum CryptoError {
    #[error("invalid key: {0}")]
    InvalidKey(String),

    #[error("signature verification failed")]
    InvalidSignature,

    #[error("vrf validation failed: {0}")]
    Vrf(String),

    #[error("unsupported algorithm: {0}")]
    UnsupportedAlgo(String),

    #[error("rng failure: {0}")]
    Rng(String),

    #[error("crypto provider error: {0}")]
    Provider(String),
}

// -----------------------------------------------------------------------------
//  Application-level conversions and helpers
// -----------------------------------------------------------------------------

impl Error {
    /// Convert our `Error` into a `tonic::Status` for gRPC replies.
    ///
    /// Each *category* is mapped to the most appropriate gRPC status code.
    /// The original error message is forwarded *verbatim* to remote clients
    /// (redacted where security sensitive).
    pub fn into_grpc_status(self) -> tonic::Status {
        use tonic::Code::*;

        match self {
            Error::InvalidInput(msg) => tonic::Status::new(InvalidArgument, msg),
            Error::Unauthorized     => tonic::Status::new(PermissionDenied, "unauthorized"),
            Error::NotFound(msg)    => tonic::Status::new(NotFound, msg),
            Error::Conflict(msg)    => tonic::Status::new(AlreadyExists, msg),
            Error::Timeout(dur)     => tonic::Status::new(DeadlineExceeded, format!("timeout after {dur:?}")),
            Error::Network(msg)     => tonic::Status::new(Unavailable, msg),
            Error::Database(err)    => {
                debug!(?err, "database error");
                tonic::Status::new(Internal, err.to_string())
            }
            Error::Serialization(err) => tonic::Status::new(Internal, err.to_string()),
            Error::Crypto(err)         => tonic::Status::new(Internal, err.to_string()),
            Error::Io(err)             => tonic::Status::new(Internal, err.to_string()),
            Error::GrpcStatus(status)  => status, // Already a `Status`
            Error::Internal(msg)       => tonic::Status::new(Internal, msg),
        }
    }

    /// Attach context to any existing error (builder-style).
    ///
    /// ```
    /// use ccs_common::error::{Error, Result};
    ///
    /// fn load_config(path: &str) -> Result<String> {
    ///     std::fs::read_to_string(path)
    ///         .map_err(Error::from)
    ///         .with_context(|| format!("failed to read config file `{path}`"))
    /// }
    /// ```
    pub fn with_context<F>(self, f: F) -> Self
    where
        F: FnOnce() -> String,
    {
        match self {
            Error::InvalidInput(_)       => Error::InvalidInput(f()),
            Error::NotFound(_)           => Error::NotFound(f()),
            Error::Conflict(_)           => Error::Conflict(f()),
            Error::Network(_)            => Error::Network(f()),
            Error::Internal(_)           => Error::Internal(f()),
            other                        => {
                error!(?other, "augmenting non-string error with context");
                other
            }
        }
    }
}

// Convenience method on `Result` to apply `with_context` directly.
pub trait ResultContext<T> {
    fn with_context<F>(self, f: F) -> Result<T>
    where
        F: FnOnce() -> String;
}

impl<T, E> ResultContext<T> for std::result::Result<T, E>
where
    E: Into<Error>,
{
    fn with_context<F>(self, f: F) -> Result<T>
    where
        F: FnOnce() -> String,
    {
        self.map_err(|e| e.into().with_context(f))
    }
}

// -----------------------------------------------------------------------------
//  Custom conversions for frequently used external crates
// -----------------------------------------------------------------------------

impl From<tonic::Status> for Error {
    fn from(status: tonic::Status) -> Self {
        Error::GrpcStatus(status)
    }
}

#[cfg(feature = "axum")]
impl From<axum::http::Error> for Error {
    fn from(err: axum::http::Error) -> Self {
        Error::Network(err.to_string())
    }
}

#[cfg(feature = "web3")]
impl From<web3::Error> for Error {
    fn from(err: web3::Error) -> Self {
        Error::Network(err.to_string())
    }
}

#[cfg(feature = "ring")]
impl From<ring::error::Unspecified> for Error {
    fn from(_: ring::error::Unspecified) -> Self {
        Error::Crypto(CryptoError::Provider("ring unspecified error".into()))
    }
}

#[cfg(feature = "tokio")]
impl From<tokio::task::JoinError> for Error {
    fn from(err: tokio::task::JoinError) -> Self {
        if err.is_cancelled() {
            Error::Timeout(Duration::from_secs(0))
        } else {
            Error::Internal(format!("tokio join error: {err}"))
        }
    }
}

// -----------------------------------------------------------------------------
//  Helper macros
// -----------------------------------------------------------------------------

/// Early return with `Error::InvalidInput`.
#[macro_export]
macro_rules! invalid_arg {
    ($($arg:tt)+) => {
        return Err($crate::error::Error::InvalidInput(format!($($arg)+)).into())
    };
}

/// Log and convert any error into a gRPC status.
///
/// Intended for the `?` operator at the *boundary* of a gRPC service handler:
///
/// ```
/// use tonic::{Request, Response, Status};
/// use ccs_common::error::{Result, into_grpc};
///
/// pub async fn handle(req: Request<ProtoReq>) -> std::result::Result<Response<ProtoRes>, Status> {
///     do_business_logic(req.into_inner())
///         .map(Response::new)
///         .map_err(into_grpc)
/// }
/// ```
#[inline]
pub fn into_grpc<E: Into<Error>>(err: E) -> tonic::Status {
    err.into().into_grpc_status()
}

// -----------------------------------------------------------------------------
//  Display implementation tweaks
// -----------------------------------------------------------------------------

impl fmt::Debug for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, f)
    }
}

// -----------------------------------------------------------------------------
//  Example tests
// -----------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn correctness_of_grpc_mapping() {
        let e = Error::InvalidInput("oops".into());
        let status = e.into_grpc_status();
        assert_eq!(status.code(), tonic::Code::InvalidArgument);
    }

    #[test]
    fn context_is_applied() {
        let err = Error::NotFound("artist wallet".into())
            .with_context(|| "during NFT minting".into());
        assert_eq!(format!("{err}"), "not found: during NFT minting");
    }
}
```