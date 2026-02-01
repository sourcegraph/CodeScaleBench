```go
// File: src/module_64.go
//
// Description:
// CommunityHealthScorer is a streaming‐first component that consumes canonical
// SocialEvents from the event bus, scores them with a pluggable HealthModel
// strategy, performs windowed aggregation, and publishes CommunityHealthScore
// results back onto an output channel.  It is intended to run as a long‐lived
// goroutine inside a service that orchestrates multiple pipelines.
//
// Patterns in play:
//   • Strategy Pattern   — interchangeable HealthModel implementations
//   • Observer Pattern   — internal pub/sub of score updates
//   • Pipeline Pattern   — source → transform → sink streaming flow
//
// The implementation is self-contained and illustrates real-world conventions:
//   • context-aware, cancellation-safe goroutines
//   • log/slog structured logging
//   • functional options for configuration
//   • metrics hooks (Prometheus) with graceful degradation
//   • exhaustive error handling

package pipeline

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

// ----------------------------------------------------------------------------
// Domain Types
// ----------------------------------------------------------------------------

// SocialEvent is the canonical message emitted by upstream ingestion.
// Only fields needed for health scoring are kept here;
// the real object in the ingestion module is much richer.
type SocialEvent struct {
	ID        string
	UserID    string
	Timestamp time.Time
	Text      string
	Sentiment float64 // range [-1, 1]
	Toxicity  float64 // range [0, 1]
}

// CommunityHealthScore is the window-level aggregate produced by this module.
type CommunityHealthScore struct {
	WindowStart time.Time
	WindowEnd   time.Time
	Score       float64 // range [0, 100]
	Events      int
}

// ----------------------------------------------------------------------------
// Dependencies (abstracted via interfaces)
// ----------------------------------------------------------------------------

// EventStream is a read-only source of SocialEvents.  Concrete implementations
// may read from Kafka, NATS, or an in-memory test channel.
type EventStream interface {
	// Events returns a receive-only channel that will close when the stream ends
	// or its parent context is cancelled.
	Events(ctx context.Context) <-chan SocialEvent

	// Name returns a human-readable identifier used for metrics and logs.
	Name() string
}

// HealthModel scores an individual SocialEvent.  The implementation could be a
// local Go model, a gRPC/REST call, or a fully-managed service (e.g., Vertex AI).
type HealthModel interface {
	Score(ctx context.Context, e SocialEvent) (float64, error)
	Name() string
}

// ----------------------------------------------------------------------------
// Functional Options
// ----------------------------------------------------------------------------

// Config holds tunable parameters for CommunityHealthScorer.
type Config struct {
	WindowSize    time.Duration // logical window length for aggregation
	FlushInterval time.Duration // how often we emit an aggregated score
	// If nil, the scorer falls back to slog.Default().
	Logger *slog.Logger
	// If nil, metrics are flushed to a no-op collector.
	Metrics *metrics
}

func (c *Config) validate() error {
	if c.WindowSize <= 0 {
		return errors.New("window size must be > 0")
	}
	if c.FlushInterval <= 0 {
		return errors.New("flush interval must be > 0")
	}
	return nil
}

// Option mutation function.
type Option func(*Config)

// WithWindowSize overrides the default aggregation window.
func WithWindowSize(d time.Duration) Option {
	return func(c *Config) { c.WindowSize = d }
}

// WithFlushInterval overrides how often a score is published downstream.
func WithFlushInterval(d time.Duration) Option {
	return func(c *Config) { c.FlushInterval = d }
}

// WithLogger injects a slog.Logger.
func WithLogger(l *slog.Logger) Option {
	return func(c *Config) { c.Logger = l }
}

// WithMetrics allows users to provide a metrics collector (Prometheus).
func WithMetrics(reg prometheus.Registerer) Option {
	return func(c *Config) { c.Metrics = newMetrics(reg) }
}

// ----------------------------------------------------------------------------
// CommunityHealthScorer
// ----------------------------------------------------------------------------

type CommunityHealthScorer struct {
	stream  EventStream
	model   HealthModel
	cfg     Config
	outCh   chan CommunityHealthScore
	ctx     context.Context
	cancel  context.CancelFunc
	wg      sync.WaitGroup
	mu      sync.Mutex // protects agg state below
	// aggregation state
	windowStart time.Time
	windowEnd   time.Time
	accumScore  float64
	events      int
}

// NewCommunityHealthScorer wires up a new scorer with sane defaults.
//
// By default, WindowSize = 1m, FlushInterval = 10s, no-op metrics, and
// slog.Default logger.
func NewCommunityHealthScorer(
	stream EventStream,
	model HealthModel,
	opts ...Option,
) (*CommunityHealthScorer, error) {
	// defaults
	cfg := Config{
		WindowSize:    time.Minute,
		FlushInterval: 10 * time.Second,
		Logger:        slog.Default(),
		Metrics:       newMetrics(nil),
	}

	for _, o := range opts {
		o(&cfg)
	}
	if err := cfg.validate(); err != nil {
		return nil, fmt.Errorf("invalid config: %w", err)
	}

	ctx, cancel := context.WithCancel(context.Background())

	scorer := &CommunityHealthScorer{
		stream: stream,
		model:  model,
		cfg:    cfg,
		outCh:  make(chan CommunityHealthScore, 1),
		ctx:    ctx,
		cancel: cancel,
	}

	return scorer, nil
}

// Start spins up internal goroutines.  It is safe to call once.
func (s *CommunityHealthScorer) Start() {
	s.wg.Add(2)
	go s.consumeLoop()
	go s.flushLoop()
}

// Stop cancels the context, waits for goroutines, and closes Out().
func (s *CommunityHealthScorer) Stop() {
	s.cancel()
	s.wg.Wait()
	close(s.outCh)
}

// Out returns a receive-only channel carrying CommunityHealthScore values.
func (s *CommunityHealthScorer) Out() <-chan CommunityHealthScore { return s.outCh }

// ----------------------------------------------------------------------------
// Internal loops
// ----------------------------------------------------------------------------

func (s *CommunityHealthScorer) consumeLoop() {
	defer s.wg.Done()

	log := s.cfg.Logger.With(
		slog.String("component", "CommunityHealthScorer"),
		slog.String("stream", s.stream.Name()),
		slog.String("model", s.model.Name()),
	)

	for {
		select {
		case <-s.ctx.Done():
			log.Info("consume loop exit", slog.String("reason", "context_cancelled"))
			return
		case evt, ok := <-s.stream.Events(s.ctx):
			if !ok {
				log.Info("event stream closed")
				return
			}
			// Update metrics for ingest
			s.cfg.Metrics.ingested.Inc()

			// Model inference
			score, err := s.model.Score(s.ctx, evt)
			if err != nil {
				log.Error("model score failed",
					slog.String("event_id", evt.ID),
					slog.String("user_id", evt.UserID),
					slog.Any("error", err),
				)
				s.cfg.Metrics.modelErrs.Inc()
				continue
			}

			// Log noisy debug in development only
			if log.Enabled(slog.LevelDebug) {
				log.Debug("scored event",
					slog.String("event_id", evt.ID),
					slog.Float64("score", score),
				)
			}

			// Accumulate into current window
			s.add(score, evt.Timestamp)
		}
	}
}

// flushLoop flushes the aggregate at cfg.FlushInterval cadence.
func (s *CommunityHealthScorer) flushLoop() {
	defer s.wg.Done()

	ticker := time.NewTicker(s.cfg.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-s.ctx.Done():
			return
		case <-ticker.C:
			if agg, ok := s.snapshotAndReset(); ok {
				s.outCh <- agg
				s.cfg.Metrics.published.Inc()
			}
		}
	}
}

// ----------------------------------------------------------------------------
// Aggregation helpers
// ----------------------------------------------------------------------------

// add merges a new event score into the current window.
func (s *CommunityHealthScorer) add(score float64, ts time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Initialize window on first event
	if s.events == 0 {
		s.windowStart = ts.Truncate(s.cfg.WindowSize)
		s.windowEnd = s.windowStart.Add(s.cfg.WindowSize)
	}

	// Advance window if event is outside the current one.
	for !ts.Before(s.windowEnd) {
		s.windowStart = s.windowEnd
		s.windowEnd = s.windowStart.Add(s.cfg.WindowSize)
		// Reset accumulators for new window
		s.accumScore = 0
		s.events = 0
	}

	s.accumScore += score
	s.events++
}

// snapshotAndReset computes final score and resets counters. Returns false if
// window is empty (no events since last flush).
func (s *CommunityHealthScorer) snapshotAndReset() (CommunityHealthScore, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.events == 0 {
		return CommunityHealthScore{}, false
	}

	avg := s.accumScore / float64(s.events)
	// Scale average into [0, 100] for display convenience.
	scaled := (avg + 1) * 50 // assuming model score ∈ [-1,1]

	agg := CommunityHealthScore{
		WindowStart: s.windowStart,
		WindowEnd:   s.windowEnd,
		Score:       scaled,
		Events:      s.events,
	}

	// Reset accumulators
	s.accumScore = 0
	s.events = 0

	return agg, true
}

// ----------------------------------------------------------------------------
// Metrics (Prometheus)
// ----------------------------------------------------------------------------

type metrics struct {
	ingested  prometheus.Counter
	modelErrs prometheus.Counter
	published prometheus.Counter
}

func newMetrics(reg prometheus.Registerer) *metrics {
	ns := "echopulse"
	sub := "community_health"

	m := &metrics{
		ingested: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: ns,
			Subsystem: sub,
			Name:      "events_ingested_total",
			Help:      "total social events processed by CommunityHealthScorer",
		}),
		modelErrs: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: ns,
			Subsystem: sub,
			Name:      "model_errors_total",
			Help:      "total model inference failures",
		}),
		published: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: ns,
			Subsystem: sub,
			Name:      "scores_published_total",
			Help:      "total aggregated scores published",
		}),
	}

	if reg != nil {
		reg.MustRegister(m.ingested, m.modelErrs, m.published)
	} else {
		// Provide no-op collectors for unit tests / dev mode.
		m.ingested = prometheus.NewCounter(prometheus.CounterOpts{})
		m.modelErrs = prometheus.NewCounter(prometheus.CounterOpts{})
		m.published = prometheus.NewCounter(prometheus.CounterOpts{})
	}

	return m
}

// ----------------------------------------------------------------------------
// DefaultHealthModel (example strategy)
// ----------------------------------------------------------------------------

// DefaultHealthModel is an in-process, heuristic model useful for development
// and unit tests.  Production deployments are expected to inject a fully
// trained model via the HealthModel interface.
type DefaultHealthModel struct{}

// NewDefaultHealthModel returns the reference implementation.
func NewDefaultHealthModel() *DefaultHealthModel { return &DefaultHealthModel{} }

// Name implements HealthModel.
func (DefaultHealthModel) Name() string { return "default_heuristic_v1" }

// Score implements HealthModel by combining sentiment and toxicity with hand-
// tuned weights.  The output is clipped to [-1, 1] to satisfy downstream
// assumptions.
func (DefaultHealthModel) Score(_ context.Context, e SocialEvent) (float64, error) {
	const (
		wSentiment = 0.7
		wToxicity  = 0.3
	)

	if e.Sentiment < -1 || e.Sentiment > 1 || e.Toxicity < 0 || e.Toxicity > 1 {
		return 0, fmt.Errorf("invalid field values (sentiment=%f toxicity=%f)", e.Sentiment, e.Toxicity)
	}

	raw := wSentiment*e.Sentiment - wToxicity*e.Toxicity
	if raw > 1 {
		raw = 1
	}
	if raw < -1 {
		raw = -1
	}
	return raw, nil
}
```