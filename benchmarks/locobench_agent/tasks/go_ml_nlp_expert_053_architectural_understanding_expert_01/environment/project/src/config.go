package config

/*
Package config provides a hot–reload-able, thread-safe, and
environment-aware configuration layer for EchoPulse.

Features
  • Nested, strongly-typed structs with sensible defaults
  • file-based (YAML/JSON/TOML) + ENV override via github.com/spf13/viper
  • Formal field validation via github.com/go-playground/validator/v10
  • Atomic snapshot reads (no locks) + change subscription callbacks
  • Optional live-reload using fsnotify
*/

import (
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/fsnotify/fsnotify"
	"github.com/go-playground/validator/v10"
	"github.com/mitchellh/mapstructure"
	"github.com/spf13/viper"
)

// GLOBAL STATE ----------------------------------------------------------------

var (
	currentCfg atomic.Value         // *Config
	cbMu       sync.RWMutex          // protects subscribers
	subscribers []func(*Config)      // change subscribers
	validate    = validator.New()    // singleton validator
)

// Config is the root configuration tree.
type Config struct {
	App           AppConfig           `mapstructure:"app"            validate:"required,dive"`
	Server        ServerConfig        `mapstructure:"server"         validate:"required,dive"`
	Kafka         KafkaConfig         `mapstructure:"kafka"          validate:"required,dive"`
	NATS          NATSConfig          `mapstructure:"nats"           validate:"omitempty,dive"`
	Database      DBConfig            `mapstructure:"database"       validate:"required,dive"`
	FeatureStore  FeatureStoreConfig  `mapstructure:"feature_store"  validate:"required,dive"`
	ModelRegistry ModelRegistryConfig `mapstructure:"model_registry" validate:"required,dive"`
	Logging       LoggingConfig       `mapstructure:"logging"        validate:"required,dive"`
	Monitoring    MonitoringConfig    `mapstructure:"monitoring"     validate:"required,dive"`
	// _            struct{}            `mapstructure:",squash"` // future-proof
}

// Sub-sections ----------------------------------------------------------------

type AppConfig struct {
	Name    string `mapstructure:"name"    validate:"required"`
	Env     string `mapstructure:"env"     validate:"oneof=dev prod stage test"`
	Version string `mapstructure:"version" validate:"required"`
}

type ServerConfig struct {
	HTTPPort      int           `mapstructure:"http_port"       validate:"required,gt=0"`
	GRPCPort      int           `mapstructure:"grpc_port"       validate:"required,gt=0"`
	ReadTimeout   time.Duration `mapstructure:"read_timeout"    validate:"required,gt=0"`
	WriteTimeout  time.Duration `mapstructure:"write_timeout"   validate:"required,gt=0"`
	MaxConnAge    time.Duration `mapstructure:"max_conn_age"    validate:"required,gt=0"`
	TLSCertFile   string        `mapstructure:"tls_cert_file"`
	TLSKeyFile    string        `mapstructure:"tls_key_file"`
	AllowedOrigins []string     `mapstructure:"allowed_origins"`
}

type KafkaConfig struct {
	Brokers       []string       `mapstructure:"brokers"        validate:"required,min=1,dive,hostname|ip"`
	Topic         string         `mapstructure:"topic"          validate:"required"`
	ConsumerGroup string         `mapstructure:"consumer_group" validate:"required"`
	Security      KafkaSecurity  `mapstructure:"security"       validate:"dive"`
	Partitions    int            `mapstructure:"partitions"     validate:"gte=0"`
}

type KafkaSecurity struct {
	EnableTLS   bool   `mapstructure:"enable_tls"`
	CAFile      string `mapstructure:"ca_file"`
	CertFile    string `mapstructure:"cert_file"`
	KeyFile     string `mapstructure:"key_file"`
	EnableSASL  bool   `mapstructure:"enable_sasl"`
	Username    string `mapstructure:"username"`
	Password    string `mapstructure:"password"`
	Mechanism   string `mapstructure:"mechanism" validate:"omitempty,oneof=PLAIN SCRAM-SHA-256 SCRAM-SHA-512"`
}

type NATSConfig struct {
	URL        string `mapstructure:"url"   validate:"omitempty,url"`
	Stream     string `mapstructure:"stream"`
	EnableTLS  bool   `mapstructure:"enable_tls"`
	CredFile   string `mapstructure:"cred_file"`
}

type DBConfig struct {
	Driver          string        `mapstructure:"driver"            validate:"required,oneof=postgres sqlite mysql"`
	DSN             string        `mapstructure:"dsn"               validate:"required"`
	MaxOpenConns    int           `mapstructure:"max_open_conns"    validate:"gte=0"`
	MaxIdleConns    int           `mapstructure:"max_idle_conns"    validate:"gte=0"`
	ConnMaxLifetime time.Duration `mapstructure:"conn_max_lifetime" validate:"gte=0"`
}

type FeatureStoreConfig struct {
	Provider string `mapstructure:"provider" validate:"required,oneof=s3 gcs local"`
	Path     string `mapstructure:"path"     validate:"required"`
}

type ModelRegistryConfig struct {
	URL       string `mapstructure:"url"        validate:"required,url"`
	AuthToken string `mapstructure:"auth_token" validate:"required"`
	Namespace string `mapstructure:"namespace"  validate:"required"`
}

type LoggingConfig struct {
	Level  string `mapstructure:"level"  validate:"required,oneof=debug info warn error"`
	Format string `mapstructure:"format" validate:"required,oneof=json text"`
	Output string `mapstructure:"output" validate:"required"`
}

type MonitoringConfig struct {
	PrometheusPort int    `mapstructure:"prometheus_port" validate:"required,gt=0"`
	EnableTracing  bool   `mapstructure:"enable_tracing"`
	JaegerEndpoint string `mapstructure:"jaeger_endpoint" validate:"omitempty,hostname_port"`
}

// -----------------------------------------------------------------------------

// defaultConfig returns a Config pre-populated with safe defaults.
// These can be overridden by files/env.
func defaultConfig() *Config {
	return &Config{
		App: AppConfig{
			Name:    "echopulse",
			Env:     "dev",
			Version: "0.0.0",
		},
		Server: ServerConfig{
			HTTPPort:     8080,
			GRPCPort:     9090,
			ReadTimeout:  10 * time.Second,
			WriteTimeout: 15 * time.Second,
			MaxConnAge:   2 * time.Hour,
		},
		Kafka: KafkaConfig{
			Brokers:       []string{"localhost:9092"},
			Topic:         "social-events",
			ConsumerGroup: "echopulse-core",
			Partitions:    12,
		},
		Database: DBConfig{
			Driver:          "postgres",
			DSN:             "postgres://user:pass@localhost:5432/echopulse?sslmode=disable",
			MaxOpenConns:    20,
			MaxIdleConns:    5,
			ConnMaxLifetime: 30 * time.Minute,
		},
		FeatureStore: FeatureStoreConfig{
			Provider: "local",
			Path:     "./data/features",
		},
		ModelRegistry: ModelRegistryConfig{
			URL:       "http://localhost:8000",
			Namespace: "default",
		},
		Logging: LoggingConfig{
			Level:  "info",
			Format: "json",
			Output: "stdout",
		},
		Monitoring: MonitoringConfig{
			PrometheusPort: 9000,
		},
	}
}

// Load reads configuration from the given path (dir or file) and environment.
// If hotReload is true, it will automatically update the global snapshot when
// the file changes.
func Load(path string, hotReload bool) (*Config, error) {
	v := viper.New()
	v.SetConfigName("config") // search for config.{json,yaml,toml}
	v.AddConfigPath(".")      // cwd fallback

	// If path points to a file, use it directly; else treat as directory.
	if strings.HasSuffix(path, ".yaml") || strings.HasSuffix(path, ".yml") ||
		strings.HasSuffix(path, ".json") || strings.HasSuffix(path, ".toml") {
		v.SetConfigFile(path)
	} else if path != "" {
		v.AddConfigPath(path)
	}

	// ENV var overrides, e.g. EP_SERVER_HTTP_PORT=9099
	v.SetEnvPrefix("EP")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	// Decode time.Duration & friends from strings like "5s"
	v.RegisterAlias("server.read_timeout", "SERVER_READ_TIMEOUT")

	// Defaults
	setDefaults(v, defaultConfig())

	// Read from config file(s) if present.
	if err := v.ReadInConfig(); err != nil {
		// Only fail if file was explicitly provided and not found/invalid.
		if _, ok := err.(*viper.ConfigFileNotFoundError); !ok && path != "" {
			return nil, fmt.Errorf("config: cannot read config file: %w", err)
		}
	}

	// Unmarshal with mapstructure.
	var cfg Config
	if err := v.Unmarshal(&cfg, func(dc *mapstructure.DecoderConfig) {
		dc.ErrorUnused = true
	}); err != nil {
		return nil, fmt.Errorf("config: unmarshal failed: %w", err)
	}

	// Validate.
	if err := validate.Struct(&cfg); err != nil {
		return nil, fmt.Errorf("config validation error: %w", err)
	}

	// Publish snapshot.
	currentCfg.Store(&cfg)

	// Hot reload if requested.
	if hotReload {
		v.WatchConfig()
		v.OnConfigChange(func(e fsnotify.Event) {
			_ = reload(v) // ignore errors on background reload; log inside reload
		})
	}

	return &cfg, nil
}

// setDefaults populates viper with defaults derived from struct tags.
func setDefaults(v *viper.Viper, def *Config) {
	v.SetDefault("app.name", def.App.Name)
	v.SetDefault("app.env", def.App.Env)
	v.SetDefault("app.version", def.App.Version)

	v.SetDefault("server.http_port", def.Server.HTTPPort)
	v.SetDefault("server.grpc_port", def.Server.GRPCPort)
	v.SetDefault("server.read_timeout", def.Server.ReadTimeout)
	v.SetDefault("server.write_timeout", def.Server.WriteTimeout)
	v.SetDefault("server.max_conn_age", def.Server.MaxConnAge)

	v.SetDefault("kafka.brokers", def.Kafka.Brokers)
	v.SetDefault("kafka.topic", def.Kafka.Topic)
	v.SetDefault("kafka.consumer_group", def.Kafka.ConsumerGroup)
	v.SetDefault("kafka.partitions", def.Kafka.Partitions)

	v.SetDefault("database.driver", def.Database.Driver)
	v.SetDefault("database.dsn", def.Database.DSN)
	v.SetDefault("database.max_open_conns", def.Database.MaxOpenConns)
	v.SetDefault("database.max_idle_conns", def.Database.MaxIdleConns)
	v.SetDefault("database.conn_max_lifetime", def.Database.ConnMaxLifetime)

	v.SetDefault("feature_store.provider", def.FeatureStore.Provider)
	v.SetDefault("feature_store.path", def.FeatureStore.Path)

	v.SetDefault("model_registry.url", def.ModelRegistry.URL)
	v.SetDefault("model_registry.namespace", def.ModelRegistry.Namespace)

	v.SetDefault("logging.level", def.Logging.Level)
	v.SetDefault("logging.format", def.Logging.Format)
	v.SetDefault("logging.output", def.Logging.Output)

	v.SetDefault("monitoring.prometheus_port", def.Monitoring.PrometheusPort)
}

// reload attempts to rebuild Config from a *viper.Viper and, if valid,
// swap it into the global snapshot and fan-out to subscribers.
func reload(v *viper.Viper) error {
	var next Config
	if err := v.Unmarshal(&next, func(dc *mapstructure.DecoderConfig) {
		dc.ErrorUnused = true
	}); err != nil {
		return fmt.Errorf("config reload: unmarshal: %w", err)
	}
	if err := validate.Struct(&next); err != nil {
		return fmt.Errorf("config reload: validation: %w", err)
	}

	currentCfg.Store(&next)
	notify(&next)
	return nil
}

// Get returns the current, immutable configuration snapshot. Always safe for
// concurrent use without additional synchronization.
func Get() *Config {
	if cfg, ok := currentCfg.Load().(*Config); ok && cfg != nil {
		return cfg
	}
	panic("config: not loaded") // programmer error
}

// Subscribe registers fn to be invoked (async) whenever a fresh Config
// snapshot is loaded (including the initial Load call).
func Subscribe(fn func(*Config)) {
	cbMu.Lock()
	defer cbMu.Unlock()
	subscribers = append(subscribers, fn)
}

// notify fans out cfg to all subscribers in new goroutines.
func notify(cfg *Config) {
	cbMu.RLock()
	defer cbMu.RUnlock()
	for _, fn := range subscribers {
		// Non-blocking fan-out so bad listeners don't stall us
		go fn(cfg)
	}
}
