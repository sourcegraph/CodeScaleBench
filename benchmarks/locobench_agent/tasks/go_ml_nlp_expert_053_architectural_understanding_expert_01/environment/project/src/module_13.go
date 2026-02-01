```go
// Code generated for EchoPulse — Real-Time Social Signal Processing Platform.
// Module 13: Online statistical drift monitoring.
//
// This package provides a high-throughput “DriftWatcher” that listens to live
// feature-statistics events, compares them against the active model baseline,
// and publishes a DriftAlert when statistically significant drift is detected.
//
// The code purposefully keeps transport details abstract behind interfaces so
// that the same business logic can run on top of Kafka, NATS JetStream, or an
// in-memory event bus for unit testing.
package drift

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"
)

// ----------------------------------------------------------------------------
// Public event definitions
// ----------------------------------------------------------------------------

// FeatureStatsEvent represents a histogram of a single feature collected over a
// rolling time-window in production traffic.
type FeatureStatsEvent struct {
	ModelID     string            `json:"model_id"`
	FeatureName string            `json:"feature_name"`
	Buckets     map[string]uint64 `json:"buckets"` // bucket_name -> count
	WindowStart time.Time         `json:"window_start"`
	WindowEnd   time.Time         `json:"window_end"`
}

// DriftAlert is emitted when drift passes a configured threshold.
type DriftAlert struct {
	ModelID        string    `json:"model_id"`
	FeatureName    string    `json:"feature_name"`
	JSdivergence   float64   `json:"js_divergence"`
	WindowEnd      time.Time `json:"window_end"`
	BaselineSHA256 string    `json:"baseline_sha256"`
}

// ----------------------------------------------------------------------------
// Transport layer abstraction
// ----------------------------------------------------------------------------

// EventConsumer pulls bytes from a topic/subject and passes them to a handler.
// Real implementations will wrap *kafka.Reader, nats.Subscription, etc.
type EventConsumer interface {
	// Consume blocks until ctx is done or the underlying connection closes.
	Consume(ctx context.Context, handler func([]byte)) error
}

// EventPublisher pushes data to a topic/subject.
type EventPublisher interface {
	Publish(ctx context.Context, payload []byte) error
}

// ----------------------------------------------------------------------------
// Baseline management
// ----------------------------------------------------------------------------

// BaselineProvider returns a canonical histogram for a model/feature pair.
// How the data is stored is left to the implementer (S3, DB, model registry).
type BaselineProvider interface {
	// Baseline returns histogram buckets as probabilities (they MUST sum to 1.0).
	Baseline(ctx context.Context, modelID, feature string) (Histogram, string, error) // sha256 for versioning
}

// ----------------------------------------------------------------------------
// DriftWatcher configuration
// ----------------------------------------------------------------------------

// WatcherConfig governs sensitivity and concurrency settings.
type WatcherConfig struct {
	JSDriftThreshold float64       // divergence threshold that triggers alert
	MaxConcurrency   int           // number of goroutines for concurrent events
	Linger           time.Duration // time to linger before shutting down
}

// Validate returns an error if the config is invalid.
func (c WatcherConfig) Validate() error {
	switch {
	case c.JSDriftThreshold <= 0 || math.IsNaN(c.JSDriftThreshold):
		return fmt.Errorf("invalid JSDriftThreshold: %.4f", c.JSDriftThreshold)
	case c.MaxConcurrency <= 0:
		return fmt.Errorf("MaxConcurrency must be > 0")
	default:
		return nil
	}
}

// ----------------------------------------------------------------------------
// Histogram helpers
// ----------------------------------------------------------------------------

// Histogram maps bucket_name -> probability/count. All math is done on float64.
type Histogram map[string]float64

// Normalize converts absolute counts into probabilities.
func (h Histogram) Normalize() Histogram {
	total := 0.0
	for _, v := range h {
		total += v
	}
	if total == 0 {
		return h // keep zeros to avoid division by zero—will be handled upstream
	}
	normalized := make(Histogram, len(h))
	for k, v := range h {
		normalized[k] = v / total
	}
	return normalized
}

// Aligned returns union of keys in both histograms with missing buckets filled
// by zeros so that metrics have aligned dimensions.
func (h Histogram) Aligned(other Histogram) (Histogram, Histogram) {
	union := make(map[string]struct{}, len(h)+len(other))
	for k := range h {
		union[k] = struct{}{}
	}
	for k := range other {
		union[k] = struct{}{}
	}
	h1 := make(Histogram, len(union))
	h2 := make(Histogram, len(union))
	for k := range union {
		h1[k] = h[k]
		h2[k] = other[k]
	}
	return h1, h2
}

// JensenShannonDistance computes JS divergence (symmetrized KL) between two
// discrete probability distributions. The result is bounded [0, 1].
func JensenShannonDistance(p, q Histogram) (float64, error) {
	p, q = p.Normalize().Aligned(q.Normalize())
	m := make(Histogram, len(p))
	for k := range p {
		m[k] = 0.5*(p[k] + q[k])
	}
	kl1, err := klDiv(p, m)
	if err != nil {
		return 0, err
	}
	kl2, err := klDiv(q, m)
	if err != nil {
		return 0, err
	}
	return 0.5 * (kl1 + kl2), nil
}

// klDiv computes Kullback-Leibler divergence D_KL(p‖q).
func klDiv(p, q Histogram) (float64, error) {
	var kl float64
	for k := range p {
		if p[k] == 0 {
			continue
		}
		if q[k] == 0 {
			return 0, errors.New("q has 0 probability where p > 0")
		}
		kl += p[k] * math.Log2(p[k]/q[k])
	}
	return kl, nil
}

// ----------------------------------------------------------------------------
// DriftWatcher implementation
// ----------------------------------------------------------------------------

// DriftWatcher consumes FeatureStatsEvents, computes drift, and emits alerts.
type DriftWatcher struct {
	cfg      WatcherConfig
	consumer EventConsumer
	provider BaselineProvider
	publisher EventPublisher
}

// New creates a new DriftWatcher with validated configuration.
func New(cfg WatcherConfig, c EventConsumer, p BaselineProvider, pub EventPublisher) (*DriftWatcher, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	if c == nil || p == nil || pub == nil {
		return nil, errors.New("consumer, provider, and publisher must be non-nil")
	}
	return &DriftWatcher{
		cfg:       cfg,
		consumer:  c,
		provider:  p,
		publisher: pub,
	}, nil
}

// Start launches the watcher and blocks until ctx is cancelled.
func (w *DriftWatcher) Start(ctx context.Context) error {
	sem := make(chan struct{}, w.cfg.MaxConcurrency)

	handler := func(raw []byte) {
		select {
		case sem <- struct{}{}:
			// acquired slot
		case <-ctx.Done():
			return
		}

		go func() {
			defer func() { <-sem }()
			if err := w.processEvent(ctx, raw); err != nil {
				// In production you'd push this to an observability stack.
				fmt.Printf("drift watcher: %v\n", err)
			}
		}()
	}

	if err := w.consumer.Consume(ctx, handler); err != nil {
		return err
	}

	// Drain active goroutines
	timer := time.NewTimer(w.cfg.Linger)
	defer timer.Stop()
	for i := 0; i < w.cfg.MaxConcurrency; i++ {
		select {
		case sem <- struct{}{}: // wait for goroutine to finish
		case <-timer.C:
			return errors.New("shutdown linger timed out")
		}
	}
	return nil
}

// processEvent performs baseline retrieval, divergence computation, and alert
// publication. Errors are logged but do not stop the stream.
func (w *DriftWatcher) processEvent(ctx context.Context, raw []byte) error {
	var event FeatureStatsEvent
	if err := json.Unmarshal(raw, &event); err != nil {
		return fmt.Errorf("decode FeatureStatsEvent: %w", err)
	}

	current := make(Histogram, len(event.Buckets))
	for k, v := range event.Buckets {
		current[k] = float64(v)
	}

	baseline, sha, err := w.provider.Baseline(ctx, event.ModelID, event.FeatureName)
	if err != nil {
		return fmt.Errorf("fetch baseline: %w", err)
	}

	js, err := JensenShannonDistance(current, baseline)
	if err != nil {
		return fmt.Errorf("compute JS: %w", err)
	}

	if js < w.cfg.JSDriftThreshold {
		return nil // nothing to do
	}

	alert := DriftAlert{
		ModelID:        event.ModelID,
		FeatureName:    event.FeatureName,
		JSdivergence:   js,
		WindowEnd:      event.WindowEnd,
		BaselineSHA256: sha,
	}
	payload, err := json.Marshal(alert)
	if err != nil {
		return fmt.Errorf("marshal alert: %w", err)
	}
	if err := w.publisher.Publish(ctx, payload); err != nil {
		return fmt.Errorf("publish alert: %w", err)
	}
	return nil
}

// ----------------------------------------------------------------------------
// In-memory mocks for unit testing and local dev
// ----------------------------------------------------------------------------

// memoryProvider is a threadsafe in-memory BaselineProvider.
type memoryProvider struct {
	mu        sync.RWMutex
	baselines map[string]map[string]baselineEntry // modelID -> feature -> entry
}

type baselineEntry struct {
	hist Histogram
	sha  string
}

// NewMemoryBaselineProvider returns a provider intended for tests.
func NewMemoryBaselineProvider() *memoryProvider {
	return &memoryProvider{
		baselines: make(map[string]map[string]baselineEntry),
	}
}

func (m *memoryProvider) Baseline(_ context.Context, modelID, feature string) (Histogram, string, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if model, ok := m.baselines[modelID]; ok {
		if entry, ok := model[feature]; ok {
			return entry.hist, entry.sha, nil
		}
	}
	return nil, "", fmt.Errorf("baseline not found for model=%s feature=%s", modelID, feature)
}

// SetBaseline allows tests to preload data.
func (m *memoryProvider) SetBaseline(modelID, feature, sha string, h Histogram) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.baselines[modelID]; !ok {
		m.baselines[modelID] = make(map[string]baselineEntry)
	}
	m.baselines[modelID][feature] = baselineEntry{hist: h.Normalize(), sha: sha}
}
```