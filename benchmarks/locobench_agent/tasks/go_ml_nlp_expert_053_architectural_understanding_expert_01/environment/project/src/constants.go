package constants

import (
	"errors"
	"os"
	"strings"
	"time"
)

// -----------------------------------------------------------------------------
// Global Environment (DEV / STAGING / PROD)
// -----------------------------------------------------------------------------

// Environment enumerates all supported deployment environments.
type Environment string

const (
	EnvDev     Environment = "development"
	EnvStaging Environment = "staging"
	EnvProd    Environment = "production"
)

// CurrentEnv returns the process-level environment, defaulting to development
// when ECHOPULSE_ENV is unset or invalid.
func CurrentEnv() Environment {
	raw := strings.ToLower(strings.TrimSpace(os.Getenv("ECHOPULSE_ENV")))
	switch Environment(raw) {
	case EnvDev, EnvStaging, EnvProd:
		return Environment(raw)
	default:
		return EnvDev
	}
}

// MustEnv parses an explicit string and returns an error if the value is
// unknown. This is useful for parsing configuration files or CLI flags where
// lenient defaults are undesirable.
func MustEnv(raw string) (Environment, error) {
	raw = strings.ToLower(strings.TrimSpace(raw))
	switch Environment(raw) {
	case EnvDev, EnvStaging, EnvProd:
		return Environment(raw), nil
	default:
		return "", ErrUnknownEnvironment
	}
}

// -----------------------------------------------------------------------------
// Kafka / JetStream Topic Names (canonicalized across the platform)
// -----------------------------------------------------------------------------

const (
	TopicSocialEvents         = "echopulse.social.events.v1"
	TopicFeatureStore         = "echopulse.features.v1"
	TopicModelRegistry        = "echopulse.models.v1"
	TopicExperimentTracking   = "echopulse.experiments.v1"
	TopicModerationGuidance   = "echopulse.guidance.v1"
	TopicCommunityHealthScore = "echopulse.community.health.v1"
)

// Partitioning strategy keys
const (
	PartitionKeyUserID    = "user_id"
	PartitionKeyChannelID = "channel_id"
	PartitionKeyEventID   = "event_id"
)

// -----------------------------------------------------------------------------
// Social Event Types & Signals
// -----------------------------------------------------------------------------

// SocialEventType represents the canonical set of social artifacts we ingest.
type SocialEventType string

const (
	EventTextMessage   SocialEventType = "text_message"
	EventReaction      SocialEventType = "reaction"
	EventEmoji         SocialEventType = "emoji"
	EventAudioTranscript SocialEventType = "audio_transcript"
	EventSystemNotice  SocialEventType = "system_notice"
)

// ParseEventType converts a raw string to a SocialEventType, validating the
// input and returning an error on failure.
func ParseEventType(raw string) (SocialEventType, error) {
	raw = strings.ToLower(strings.TrimSpace(raw))
	switch SocialEventType(raw) {
	case EventTextMessage,
		EventReaction,
		EventEmoji,
		EventAudioTranscript,
		EventSystemNotice:
		return SocialEventType(raw), nil
	default:
		return "", ErrUnknownEventType
	}
}

// -----------------------------------------------------------------------------
// ML Feature & Model Lifecycle Constants
// -----------------------------------------------------------------------------

// FeatureNamespace is the top-level namespace used to version features in the
// offline & online feature stores.
const FeatureNamespace = "echopulse"

// ModelStatus indicates where in the model life-cycle a version currently sits.
type ModelStatus string

const (
	ModelStatusStaging   ModelStatus = "staging"
	ModelStatusProduction ModelStatus = "production"
	ModelStatusArchived   ModelStatus = "archived"
)

// DriftThresholds enumerates default statistical drift thresholds that kick off
// automated retraining jobs. Down-stream teams can override these via config.
const (
	DriftKLDefault     = 0.15 // Kullback-Leibler divergence
	DriftJSDefault     = 0.10 // Jensen-Shannon distance
	DriftPopulationMin = 500  // Minimum sample size for drift detection
)

// -----------------------------------------------------------------------------
// HTTP / gRPC Metadata Keys
// -----------------------------------------------------------------------------

const (
	// MetadataCorrelationID is propagated across service boundaries for
	// distributed tracing and log correlation.
	MetadataCorrelationID = "x-correlation-id"
	// MetadataRequestID is a unique identifier for the request scope.
	MetadataRequestID = "x-request-id"
	// MetadataUserID is the authenticated user identifier, when available.
	MetadataUserID = "x-user-id"
)

// -----------------------------------------------------------------------------
// Timeouts & Intervals
// -----------------------------------------------------------------------------

const (
	// HTTPServerShutdownGrace is the maximum duration the service will wait
	// for in-flight requests to finish during a graceful shutdown.
	HTTPServerShutdownGrace = 10 * time.Second

	// ModelHeartbeatInterval controls how often each live model instance
	// publishes metrics to the monitoring subsystem.
	ModelHeartbeatInterval = 30 * time.Second

	// ExperimentPollInterval drives the watch loop that looks for new
	// experiment configurations pushed by the experiment-tracking service.
	ExperimentPollInterval = 15 * time.Second
)

// -----------------------------------------------------------------------------
// Sentinel Errors
// -----------------------------------------------------------------------------

var (
	ErrUnknownEnvironment = errors.New("constants: unknown environment")
	ErrUnknownEventType   = errors.New("constants: unknown social event type")
)

// -----------------------------------------------------------------------------
// Misc. Utility Constants
// -----------------------------------------------------------------------------

const (
	// DefaultBufferSize is the default channel buffer size used across the
	// platform for fan-out and worker pools, chosen to balance throughput and
	// memory usage under typical load.
	DefaultBufferSize = 1024

	// HealthCheckEndpoint is exposed by every microservice to allow the
	// orchestrator (Kubernetes, Nomad, etc.) to determine readiness.
	HealthCheckEndpoint = "/healthz"
)

// UserAgent constructs a canonical User-Agent string for HTTP clients.
func UserAgent(service string) string {
	return "EchoPulse/" + strings.TrimSpace(service)
}