```rust
//! Configuration management for the CanvasChain Symphony node–service.
//!
//! The node–service is the glue between the peer-to-peer layer, the
//! consensus engine and the application logic exposed through gRPC.
//! All runtime behaviour can be tuned through a hierarchical,
//! multi-source configuration system backed by the `config` crate.
//!
//! Priority (lowest → highest):
//! 1. Compile-time defaults (`impl Default`).
//! 2. An optional TOML/YAML/JSON file passed at start-up.
//! 3. Environment variables with `CANVASCHAIN_` prefix.
//!
//!     CANVASCHAIN__NETWORK__P2P_PORT=30555   # double underscore = path separator
//!
//! The final, frozen [`NodeConfig`] instance is published as a global
//! singleton through [`get()`].  Attempting to mutate the configuration
//! after initialisation results in a panic.
//!
//! # Examples
//! ```no_run
//! use canvaschain_node_service::config::ConfigHandle;
//!
//! # fn main() -> Result<(), Box<dyn std::error::Error>> {
//! // bootstrap from `$PWD/node.toml` or environment, whichever is found.
//! let _handle = canvaschain_node_service::config::init(None)?;
//!
//! // read-only access anywhere in the codebase
//! let cfg = canvaschain_node_service::config::get();
//! println!("Running node {} on {}", cfg.service.instance_id, cfg.network.host);
//! # Ok(()) }
//! ```

use std::{
    net::{IpAddr, Ipv4Addr},
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

use config::{Config, ConfigError, Environment, File};
use humantime::parse_duration;
use once_cell::sync::OnceCell;
use serde::{Deserialize, Serialize};

use crate::error::NodeError; // assume a local error module re-exporting anyhow::Error et al.

/// Global singleton holder.
static NODE_CONFIG: OnceCell<Arc<NodeConfig>> = OnceCell::new();

/// Convenient alias returned by [`init`].
pub type ConfigHandle = Arc<NodeConfig>;

/// Initialise the configuration singleton.
///
/// `config_path` – an optional explicit path to a configuration file.  
/// If `None`, the loader will attempt to read `node.{toml,yaml,json}`
/// from the current working directory.
///
/// # Errors
/// - IO issues while reading the file.
/// - Malformed configuration values.
/// - Calling `init` twice.
///
/// On success, returns an [`Arc`] clone to the frozen [`NodeConfig`].
pub fn init(config_path: Option<impl AsRef<Path>>) -> Result<ConfigHandle, ConfigError> {
    // Build layered configuration.
    let mut builder = Config::builder()
        // 1. compile-time defaults (via the type's Default impl)
        .set_default("dummy", "purge_later")?; // we need at least one call to `set_default` or config will be empty

    // 2. Optional file override
    if let Some(path) = config_path {
        builder = builder.add_source(File::from(path.as_ref()).required(true));
    } else {
        // Try a set of well-known filenames if provided `None`.
        for ext in ["toml", "yaml", "json"] {
            let file_name = format!("node.{ext}");
            if Path::new(&file_name).exists() {
                builder = builder.add_source(File::with_name(&file_name).required(false));
                break;
            }
        }
    }

    // 3. Environment variables
    builder = builder.add_source(
        Environment::with_prefix("CANVASCHAIN")
            .separator("__")
            .try_parsing(true)
            .list_separator(","),
    );

    let configuration = builder.build()?;
    let mut config: NodeConfig = configuration.try_deserialize()?;

    // Apply programmatic defaults not expressible through serde/default.
    config.apply_fallbacks();

    // Perform sanity checks.
    config.validate().map_err(|e| ConfigError::Message(e.to_string()))?;

    // Freeze it.
    let arc = Arc::new(config);
    NODE_CONFIG
        .set(arc.clone())
        .map_err(|_| ConfigError::Message("Configuration already initialised".into()))?;

    Ok(arc)
}

/// Obtain an immutable reference to the frozen [`NodeConfig`].  
/// Panics if [`init`] has not been called before.
#[inline(always)]
pub fn get() -> &'static NodeConfig {
    NODE_CONFIG
        .get()
        .expect("Configuration accessed before initialisation")
}

/// Top-level configuration structure.
///
/// Keep this flattened – adding a new service-specific section should be
/// done by embedding a dedicated sub-struct to avoid the “everything is
/// optional” anti-pattern.
///
/// ⚠️  When adding new fields, remember to bump the example config file
///     and the accompanying documentation.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct NodeConfig {
    pub service: ServiceConfig,
    pub network: NetworkConfig,
    pub consensus: ConsensusConfig,
    pub database: DatabaseConfig,
    pub event_bus: EventBusConfig,
    pub telemetry: TelemetryConfig,
    pub features: FeatureToggles,
}

impl NodeConfig {
    /// Validate internal consistency and invariants.
    ///
    /// Prefer returning an error over silently fixing things at runtime.
    fn validate(&self) -> Result<(), NodeError> {
        if self.network.max_peers == 0 {
            return Err(NodeError::InvalidConfig(
                "network.max_peers must be > 0".into(),
            ));
        }

        if self.database.pool_size == 0 {
            return Err(NodeError::InvalidConfig(
                "database.pool_size must be > 0".into(),
            ));
        }

        if self.consensus.composer_selection_interval < Duration::from_secs(30) {
            return Err(NodeError::InvalidConfig(
                "consensus.composer_selection_interval is unrealistically low".into(),
            ));
        }

        Ok(())
    }

    /// Fill in fallback values that require runtime computation
    /// (e.g., hostnames, random instance IDs).
    fn apply_fallbacks(&mut self) {
        // Generate a random 6-byte instance id if not specified by the user.
        if self.service.instance_id.is_empty() {
            let id: [u8; 6] = rand::random();
            self.service.instance_id = hex::encode(id);
        }

        // Derive the advertised address if none set.
        if self.network.advertised_host.is_none() {
            self.network.advertised_host = Some(self.network.host);
        }
    }
}

impl Default for NodeConfig {
    fn default() -> Self {
        Self {
            service: ServiceConfig::default(),
            network: NetworkConfig::default(),
            consensus: ConsensusConfig::default(),
            database: DatabaseConfig::default(),
            event_bus: EventBusConfig::default(),
            telemetry: TelemetryConfig::default(),
            features: FeatureToggles::default(),
        }
    }
}

/// Metadata & housekeeping.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ServiceConfig {
    /// Logical service name – appears in logs & metrics.
    pub name: String,
    /// Unique instance identifier – auto-generated unless provided.
    pub instance_id: String,
    /// Graceful shutdown timeout.
    #[serde(with = "humantime_serde")]
    pub shutdown_timeout: Duration,
}

impl Default for ServiceConfig {
    fn default() -> Self {
        Self {
            name: "canvaschain-node".into(),
            instance_id: String::new(),
            shutdown_timeout: Duration::from_secs(15),
        }
    }
}

/// P2P and RPC settings.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct NetworkConfig {
    /// The IP address to bind to.
    #[serde(with = "serde_ipaddr")]
    pub host: IpAddr,
    /// Advertised address (useful behind NATs).
    #[serde(with = "serde_option_ipaddr")]
    pub advertised_host: Option<IpAddr>,
    /// TCP port for the custom CanvasChain P2P protocol.
    pub p2p_port: u16,
    /// TCP port for the public gRPC API.
    pub grpc_port: u16,
    /// Maximum simultaneous peer connections.
    pub max_peers: usize,
    /// Initial peers to connect to.
    pub bootstrap_nodes: Vec<String>,
    /// Enable TLS for the external gRPC endpoint.
    pub tls: Option<TlsConfig>,
}

impl Default for NetworkConfig {
    fn default() -> Self {
        Self {
            host: IpAddr::V4(Ipv4Addr::UNSPECIFIED),
            advertised_host: None,
            p2p_port: 30333,
            grpc_port: 50051,
            max_peers: 64,
            bootstrap_nodes: vec![],
            tls: None,
        }
    }
}

/// mTLS configuration for gRPC.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TlsConfig {
    /// Certificate chain in PEM format.
    pub cert_path: PathBuf,
    /// Private key in PEM format.
    pub key_path: PathBuf,
    /// Optional CA for client authentication.
    pub ca_path: Option<PathBuf>,
}

/// Custom Proof-of-Inspiration (PoI) consensus parameters.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ConsensusConfig {
    /// Minimum total stake required to participate.
    pub stake_threshold: u128,
    /// Time between composer selection rounds.
    #[serde(with = "humantime_serde")]
    pub composer_selection_interval: Duration,
    /// VRF seed refresh cadence.
    #[serde(with = "humantime_serde")]
    pub vrf_seed_refresh: Duration,
    /// Allow nodes to propose blocks when behind by this many slots.
    pub max_slot_skew: u16,
}

impl Default for ConsensusConfig {
    fn default() -> Self {
        Self {
            stake_threshold: 1_000,
            composer_selection_interval: Duration::from_secs(120),
            vrf_seed_refresh: Duration::from_secs(600),
            max_slot_skew: 3,
        }
    }
}

/// Postgres / SQLite etc.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct DatabaseConfig {
    /// SQLX-compatible connection string.
    pub url: String,
    /// Connection-pool upper bound.
    pub pool_size: u32,
    /// Automatically run migrations on start.
    pub run_migrations: bool,
}

impl Default for DatabaseConfig {
    fn default() -> Self {
        Self {
            url: "sqlite://:memory:".into(),
            pool_size: 10,
            run_migrations: true,
        }
    }
}

/// NATS / Kafka / Redis Streams – we support different backends using
/// the Strategy pattern.  Currently only NATS is implemented.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct EventBusConfig {
    /// Tags the selected backend implementation.
    pub backend: EventBusBackend,
    /// Connection URI, e.g. `nats://localhost:4222`.
    pub endpoint: String,
    /// Subject / topic prefix.
    pub namespace: String,
}

impl Default for EventBusConfig {
    fn default() -> Self {
        Self {
            backend: EventBusBackend::Nats,
            endpoint: "nats://127.0.0.1:4222".into(),
            namespace: "canvaschain".into(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum EventBusBackend {
    Nats,
    Redis,
    Kafka,
}

/// Prometheus / OTLP etc.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct TelemetryConfig {
    pub enable_metrics: bool,
    pub prometheus_port: u16,
    pub otlp_endpoint: Option<String>,
}

impl Default for TelemetryConfig {
    fn default() -> Self {
        Self {
            enable_metrics: true,
            prometheus_port: 9090,
            otlp_endpoint: None,
        }
    }
}

/// Optional compile-time subsystems toggles.
/// Disable unused heavy features in constrained deployments.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct FeatureToggles {
    pub wallet_integration: bool,
    pub governance: bool,
    pub token_management: bool,
    pub defi_protocols: bool,
    pub smart_contracts: bool,
}

impl Default for FeatureToggles {
    fn default() -> Self {
        Self {
            wallet_integration: true,
            governance: true,
            token_management: true,
            defi_protocols: false,
            smart_contracts: true,
        }
    }
}

/* ──────────────────────────────────────────────────────────────────────────
 * Serde helpers
 * ---------------------------------------------------------------------- */

mod serde_ipaddr {
    use std::net::IpAddr;

    use serde::{de::Error, Deserialize, Deserializer, Serializer};

    pub fn serialize<S>(addr: &IpAddr, s: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        s.serialize_str(&addr.to_string())
    }

    pub fn deserialize<'de, D>(d: D) -> Result<IpAddr, D::Error>
    where
        D: Deserializer<'de>,
    {
        let raw = String::deserialize(d)?;
        raw.parse().map_err(D::Error::custom)
    }
}

mod serde_option_ipaddr {
    use std::net::IpAddr;

    use serde::{de::Error, Deserialize, Deserializer, Serializer};

    pub fn serialize<S>(addr: &Option<IpAddr>, s: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match addr {
            Some(a) => s.serialize_some(&a.to_string()),
            None => s.serialize_none(),
        }
    }

    pub fn deserialize<'de, D>(d: D) -> Result<Option<IpAddr>, D::Error>
    where
        D: Deserializer<'de>,
    {
        let opt = Option::<String>::deserialize(d)?;
        match opt {
            Some(raw) => raw.parse().map(Some).map_err(D::Error::custom),
            None => Ok(None),
        }
    }
}

/* ──────────────────────────────────────────────────────────────────────────
 * Custom deserialisers for humane durations.
 * We delegate to `humantime_serde`, re-export to simplify attribute usage.
 * ---------------------------------------------------------------------- */

mod humantime_serde {
    pub use humantime::serde::*;
}
```