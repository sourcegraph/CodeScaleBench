```rust
//! CanvasChain Symphony – CCS DB Crate
//! -----------------------------------
//! Persistent data-layer for the CanvasChain Symphony platform.  
//! This crate exposes a feature-gated, runtime-agnostic storage layer that
//! supports both PostgreSQL and SQLite back-ends via `sqlx`.  All database
//! interactions are asynchronous, connection-pooled, and instrumented with
//! `tracing` for observability.
//!
//! # Cargo Features
//!
//! - `postgres` – Enable PostgreSQL back-end via `sqlx-postgres`.
//! - `sqlite`   – Enable SQLite     back-end via `sqlx-sqlite`.
//!
//! At least one of the above features **must** be enabled.

#![deny(unsafe_code)]
#![forbid(missing_docs)]
#![warn(missing_docs)]

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use once_cell::sync::OnceCell;
use serde::{Deserialize, Serialize};
use std::{fmt, sync::Arc};
use thiserror::Error;
use tracing::{error, info, instrument};

/// Maximum number of pooled connections per DB replica.
const MAX_POOL_SIZE: u32 = 20;

/// DB-level errors surfaced by this crate.
#[derive(Debug, Error)]
pub enum DbError {
    /// A connectivity or driver-level failure.
    #[error("connection error: {0}")]
    Connection(#[from] sqlx::Error),

    /// Returned when an expected row is not found.
    #[error("entity not found")]
    NotFound,

    /// Returned when invalid input is supplied.
    #[error("validation error: {0}")]
    Validation(String),
}

/// A canonical result alias for fallible DB operations.
pub type Result<T, E = DbError> = std::result::Result<T, E>;

#[cfg(feature = "postgres")]
use sqlx::postgres::{PgPool, PgPoolOptions};

#[cfg(feature = "sqlite")]
use sqlx::sqlite::{SqlitePool, SqlitePoolOptions};

/// The runtime connection pool—wrapped in an `Arc` for cheap cloning.
#[derive(Clone)]
pub struct Db(Arc<Inner>);

enum Inner {
    #[cfg(feature = "postgres")]
    Postgres(PgPool),

    #[cfg(feature = "sqlite")]
    Sqlite(SqlitePool),
}

impl fmt::Debug for Db {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match &*self.0 {
            #[cfg(feature = "postgres")]
            Inner::Postgres(_) => write!(f, "Db<Postgres>"),

            #[cfg(feature = "sqlite")]
            Inner::Sqlite(_) => write!(f, "Db<Sqlite>"),
        }
    }
}

/// Database configuration.
#[derive(Clone, Debug, Deserialize)]
pub struct DbConfig {
    /// Connection string / URL.
    pub url: String,

    /// Maximum concurrent connections.
    #[serde(default = "default_pool_size")]
    pub max_connections: u32,
}

fn default_pool_size() -> u32 {
    MAX_POOL_SIZE
}

impl DbConfig {
    /// Load config from the `DATABASE_URL` environment variable.
    pub fn from_env() -> anyhow::Result<Self> {
        let url =
            std::env::var("DATABASE_URL").map_err(|_| anyhow::anyhow!("DATABASE_URL not set"))?;
        Ok(Self {
            url,
            max_connections: MAX_POOL_SIZE,
        })
    }
}

impl Db {
    /// Establish a new connection pool using the supplied [`DbConfig`].
    #[instrument(name = "db_connect", skip(config))]
    pub async fn connect(config: &DbConfig) -> Result<Self> {
        #[cfg(all(not(feature = "postgres"), not(feature = "sqlite")))]
        compile_error!("At least one of the features `postgres` or `sqlite` must be enabled.");

        #[cfg(feature = "postgres")]
        if config.url.starts_with("postgres") {
            let pool = PgPoolOptions::new()
                .max_connections(config.max_connections)
                .connect(&config.url)
                .await?;
            return Ok(Self(Arc::new(Inner::Postgres(pool))));
        }

        #[cfg(feature = "sqlite")]
        if config.url.starts_with("sqlite") {
            let pool = SqlitePoolOptions::new()
                .max_connections(config.max_connections)
                .connect(&config.url)
                .await?;
            return Ok(Self(Arc::new(Inner::Sqlite(pool))));
        }

        Err(DbError::Validation(format!(
            "URL scheme not supported by enabled features: {}",
            config.url
        )))
    }

    /// Perform a simple `SELECT 1` to validate liveness.
    #[instrument(skip_all)]
    pub async fn healthcheck(&self) -> Result<()> {
        match &*self.0 {
            #[cfg(feature = "postgres")]
            Inner::Postgres(pool) => {
                sqlx::query_scalar::<_, i64>("SELECT 1")
                    .fetch_one(pool)
                    .await?;
            }

            #[cfg(feature = "sqlite")]
            Inner::Sqlite(pool) => {
                sqlx::query_scalar::<_, i64>("SELECT 1")
                    .fetch_one(pool)
                    .await?;
            }
        }
        Ok(())
    }

    /// Acquire a [`sqlx::Transaction`].
    pub async fn begin_tx<'a>(&'a self) -> Result<sqlx::Transaction<'a, sqlx::Any>> {
        let conn = match &*self.0 {
            #[cfg(feature = "postgres")]
            Inner::Postgres(pool) => pool.acquire().await?.into(),

            #[cfg(feature = "sqlite")]
            Inner::Sqlite(pool) => pool.acquire().await?.into(),
        };

        Ok(sqlx::Transaction::begin(conn).await?)
    }
}

/* ---------- DOMAIN MODELS ---------- */

/// On-chain NFT instrument metadata.
///
/// Each record represents the latest immutable snapshot;  
/// realtime evolution is tracked via `nft_event_log`.
#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct NftMetadata {
    /// Primary key (token id).
    pub token_id: i64,
    /// Human-readable title.
    pub title: String,
    /// JSON with multilayer traits.
    pub manifest: serde_json::Value,
    /// Owner public address.
    pub owner: String,
    /// Last modified timestamp.
    pub updated_at: DateTime<Utc>,
}

/// Observability event for NFT state-changes and governance votes.
#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct EventLog {
    /// Auto-incremented primary key.
    pub id: i64,
    /// Foreign key – NFT token id.
    pub token_id: i64,
    /// Discriminated union – event type.
    pub kind: String,
    /// Optional JSON payload.
    pub data: serde_json::Value,
    /// Block height the event was committed at.
    pub block_height: i64,
    /// Transaction hash.
    pub tx_hash: String,
    /// Created at timestamp.
    pub created_at: DateTime<Utc>,
}

/* ---------- REPOSITORY TRAITS ---------- */

/// NFT metadata repository abstraction.
#[async_trait]
pub trait NftRepository: Send + Sync {
    /// Insert or update NFT metadata.
    async fn upsert_metadata(&self, nft: &NftMetadata) -> Result<()>;

    /// Fetch NFT metadata by token id.
    async fn fetch_metadata(&self, token_id: i64) -> Result<NftMetadata>;

    /// Record an event for a given NFT.
    async fn record_event(&self, event: &EventLog) -> Result<()>;

    /// Stream events (`tail -f`) starting from `offset`.
    async fn stream_events(
        &self,
        token_id: i64,
        offset: i64,
    ) -> Result<Box<dyn futures_core::Stream<Item = Result<EventLog>> + Send + Unpin>>;
}

#[async_trait]
impl NftRepository for Db {
    #[instrument(skip_all, fields(token_id = nft.token_id))]
    async fn upsert_metadata(&self, nft: &NftMetadata) -> Result<()> {
        match &*self.0 {
            #[cfg(feature = "postgres")]
            Inner::Postgres(pool) => {
                sqlx::query!(
                    r#"
                        INSERT INTO nft_metadata
                            (token_id, title, manifest, owner, updated_at)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (token_id) DO UPDATE
                        SET    title       = EXCLUDED.title,
                               manifest    = EXCLUDED.manifest,
                               owner       = EXCLUDED.owner,
                               updated_at  = EXCLUDED.updated_at
                    "#,
                    nft.token_id,
                    nft.title,
                    nft.manifest,
                    nft.owner,
                    nft.updated_at,
                )
                .execute(pool)
                .await?;
            }

            #[cfg(feature = "sqlite")]
            Inner::Sqlite(pool) => {
                sqlx::query!(
                    r#"
                        INSERT INTO nft_metadata
                            (token_id, title, manifest, owner, updated_at)
                        VALUES (?1, ?2, ?3, ?4, ?5)
                        ON CONFLICT(token_id) DO UPDATE SET
                               title      = excluded.title,
                               manifest   = excluded.manifest,
                               owner      = excluded.owner,
                               updated_at = excluded.updated_at
                    "#,
                    nft.token_id,
                    nft.title,
                    nft.manifest,
                    nft.owner,
                    nft.updated_at,
                )
                .execute(pool)
                .await?;
            }
        }
        Ok(())
    }

    #[instrument(skip_all, fields(token_id))]
    async fn fetch_metadata(&self, token_id: i64) -> Result<NftMetadata> {
        let result = match &*self.0 {
            #[cfg(feature = "postgres")]
            Inner::Postgres(pool) => {
                sqlx::query_as::<_, NftMetadata>(
                    r#"SELECT * FROM nft_metadata WHERE token_id = $1"#,
                )
                .bind(token_id)
                .fetch_optional(pool)
                .await?
            }

            #[cfg(feature = "sqlite")]
            Inner::Sqlite(pool) => {
                sqlx::query_as::<_, NftMetadata>(
                    r#"SELECT * FROM nft_metadata WHERE token_id = ?"#,
                )
                .bind(token_id)
                .fetch_optional(pool)
                .await?
            }
        };

        result.ok_or(DbError::NotFound)
    }

    #[instrument(skip_all, fields(token_id = event.token_id, kind = %event.kind))]
    async fn record_event(&self, event: &EventLog) -> Result<()> {
        match &*self.0 {
            #[cfg(feature = "postgres")]
            Inner::Postgres(pool) => {
                sqlx::query!(
                    r#"
                        INSERT INTO nft_event_log
                            (token_id, kind, data, block_height, tx_hash, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    "#,
                    event.token_id,
                    event.kind,
                    event.data,
                    event.block_height,
                    event.tx_hash,
                    event.created_at,
                )
                .execute(pool)
                .await?;
            }

            #[cfg(feature = "sqlite")]
            Inner::Sqlite(pool) => {
                sqlx::query!(
                    r#"
                        INSERT INTO nft_event_log
                            (token_id, kind, data, block_height, tx_hash, created_at)
                        VALUES (?1, ?2, ?3, ?4, ?5, ?6)
                    "#,
                    event.token_id,
                    event.kind,
                    event.data,
                    event.block_height,
                    event.tx_hash,
                    event.created_at,
                )
                .execute(pool)
                .await?;
            }
        }

        Ok(())
    }

    #[instrument(skip_all, fields(token_id, offset))]
    async fn stream_events(
        &self,
        token_id: i64,
        offset: i64,
    ) -> Result<Box<dyn futures_core::Stream<Item = Result<EventLog>> + Send + Unpin>>
    {
        use futures_util::stream::TryStreamExt;

        let stream = match &*self.0 {
            #[cfg(feature = "postgres")]
            Inner::Postgres(pool) => {
                sqlx::query_as::<_, EventLog>(
                    r#"
                        SELECT * FROM nft_event_log
                        WHERE token_id = $1 AND id > $2
                        ORDER BY id ASC
                    "#,
                )
                .bind(token_id)
                .bind(offset)
                .fetch(pool)
                .map_err(DbError::from)
            }

            #[cfg(feature = "sqlite")]
            Inner::Sqlite(pool) => {
                sqlx::query_as::<_, EventLog>(
                    r#"
                        SELECT * FROM nft_event_log
                        WHERE token_id = ? AND id > ?
                        ORDER BY id ASC
                    "#,
                )
                .bind(token_id)
                .bind(offset)
                .fetch(pool)
                .map_err(DbError::from)
            }
        };

        Ok(Box::new(stream))
    }
}

/* ---------- MIGRATIONS ---------- */

static MIGRATOR: OnceCell<sqlx::migrate::Migrator> = OnceCell::new();

/// Run DB schema migrations embedded at compile-time.
///
/// This method is idempotent and can be safely called by multiple service
/// instances on start-up.
#[instrument(skip(db))]
pub async fn run_migrations(db: &Db) -> Result<()> {
    let migrator = MIGRATOR.get_or_init(|| {
        // The "./migrations" directory is bundled by `sqlx::migrate!()`
        sqlx::migrate!()
    });

    match &*db.0 {
        #[cfg(feature = "postgres")]
        Inner::Postgres(pool) => migrator.run(pool).await?,

        #[cfg(feature = "sqlite")]
        Inner::Sqlite(pool) => migrator.run(pool).await?,
    }

    info!("database migrations applied successfully");
    Ok(())
}

/* ---------- UNIT TESTS ---------- */

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use uuid::Uuid;

    // NOTE: To run these tests locally, set `DATABASE_URL` to a valid sqlite memory URI:
    // export DATABASE_URL=sqlite::memory:
    #[tokio::test]
    async fn test_metadata_lifecycle() -> anyhow::Result<()> {
        if std::env::var("DATABASE_URL").is_err() {
            tracing::warn!("Skipping DB test – DATABASE_URL not set");
            return Ok(());
        }

        let cfg = DbConfig::from_env()?;
        let db = Db::connect(&cfg).await?;
        run_migrations(&db).await?;

        let token_id = rand::random::<u32>() as i64;
        let meta = NftMetadata {
            token_id,
            title: "Test Symphony".into(),
            manifest: json!({"layers": []}),
            owner: Uuid::new_v4().to_string(),
            updated_at: Utc::now(),
        };

        db.upsert_metadata(&meta).await?;
        let fetched = db.fetch_metadata(token_id).await?;

        assert_eq!(fetched.token_id, meta.token_id);
        assert_eq!(fetched.title, meta.title);

        Ok(())
    }
}
```