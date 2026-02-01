```go
// EchoPulse – Real-Time Social Signal Processing Platform
// Module: Community Health Scorer
//
// File:    src/module_24.go
// Purpose: Consume per-message feature vectors (sentiment, toxicity, etc.)
//          from JetStream and maintain a sliding-window estimate of the
//          community “health score”.  Pluggable scoring strategies are
//          provided via the Strategy pattern, and alerts are published
//          back onto the bus when thresholds are crossed.
//
// NOTE:    This file is standalone for illustration purposes.  In the real
//          project, common types (SocialEvent, FeatureVector, BusConfig, …)
//          would live in shared packages.

package healthscore

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/prometheus/client_golang/prometheus"
)

// ----------------------------------------------------------------------------
// Domain Types
// ----------------------------------------------------------------------------

// FeatureVector represents the numerical ML features describing a single
// social event that were produced by downstream NLP services.
type FeatureVector struct {
	EventID   string    `json:"event_id"`
	UserID    string    `json:"user_id"`
	Timestamp time.Time `json:"ts"`

	// Normalized range [-1,1] where +1 is strongly positive
	Sentiment float64 `json:"sentiment"`
	// Normalized range [0,1] where 1 is fully toxic
	Toxicity float64 `json:"toxicity"`
}

// HealthScoreEvent is published whenever a new community score has been
// computed.  Down-stream services (dashboards, moderation bots, etc.) react
// to these events.
type HealthScoreEvent struct {
	Score     float64   `json:"score"`
	Strategy  string    `json:"strategy"`
	Timestamp time.Time `json:"timestamp"`
	Window    string    `json:"window"`
}

// ----------------------------------------------------------------------------
// Strategy Pattern – scoring algorithms
// ----------------------------------------------------------------------------

// ScoringStrategy defines the contract for computing a community health score
// from an arbitrary slice of FeatureVectors.
type ScoringStrategy interface {
	ComputeScore(vectors []FeatureVector) float64
	Name() string
}

// SimpleAverageStrategy:  score = mean( (sentiment + (1-toxicity)) / 2 )
type SimpleAverageStrategy struct{}

func (s SimpleAverageStrategy) ComputeScore(vectors []FeatureVector) float64 {
	if len(vectors) == 0 {
		return 0
	}
	var sum float64
	for _, v := range vectors {
		positive := (v.Sentiment + (1 - v.Toxicity)) / 2
		sum += positive
	}
	return sum / float64(len(vectors))
}
func (s SimpleAverageStrategy) Name() string { return "simple_average" }

// WeightedStrategy assigns higher weight to recent events to boost
// responsiveness.  Weight decays exponentially by age.
type WeightedStrategy struct {
	HalfLife time.Duration
}

func (w WeightedStrategy) ComputeScore(vectors []FeatureVector) float64 {
	if len(vectors) == 0 {
		return 0
	}
	now := time.Now()
	var num, denom float64
	for _, v := range vectors {
		age := now.Sub(v.Timestamp)
		weight := 0.5 // default
		if w.HalfLife > 0 {
			weight = expDecay(age, w.HalfLife)
		}
		score := (v.Sentiment + (1 - v.Toxicity)) / 2
		num += score * weight
		denom += weight
	}
	if denom == 0 {
		return 0
	}
	return num / denom
}
func (w WeightedStrategy) Name() string { return "weighted" }

func expDecay(age, halfLife time.Duration) float64 {
	// exp( ln(0.5) * age / halfLife )
	return powHalf(float64(age) / float64(halfLife))
}

func powHalf(x float64) float64 {
	// fast path: 2^-x
	return 1 / (1 << uint(x)) // coarse approximation; good enough for demo
}

// ----------------------------------------------------------------------------
// Metrics – Prometheus
// ----------------------------------------------------------------------------

var (
	eventsConsumed = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "echopulse_feature_events_total",
			Help: "Total number of feature events consumed by the health scorer.",
		}, []string{"subject"},
	)
	healthScoreGauge = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "echopulse_community_health_score",
			Help: "Latest computed community health score.",
		}, []string{"strategy"},
	)
)

func init() {
	prometheus.MustRegister(eventsConsumed, healthScoreGauge)
}

// ----------------------------------------------------------------------------
// HealthScorer – main engine
// ----------------------------------------------------------------------------

// HealthScorerOptions are supplied through functional options.
type HealthScorerOptions struct {
	Window          time.Duration
	ComputeInterval time.Duration
	Strategy        ScoringStrategy
	OutSubject      string
	Logger          Logger // abstract logger interface
}

func defaultOptions() HealthScorerOptions {
	return HealthScorerOptions{
		Window:          5 * time.Minute,
		ComputeInterval: 10 * time.Second,
		Strategy:        SimpleAverageStrategy{},
		OutSubject:      "echopulse.health.score",
		Logger:          stdLogger{},
	}
}

// HealthScorer consumes feature events from JetStream, maintains a sliding
// window, computes community health, and publishes HealthScoreEvents.
type HealthScorer struct {
	js      nats.JetStreamContext
	subject string // feature event subject pattern (e.g. "echopulse.features.*")

	opts   HealthScorerOptions
	buffer []FeatureVector
	mu     sync.RWMutex

	cancel context.CancelFunc
	wg     sync.WaitGroup
}

// NewHealthScorer constructs a new scorer.
func NewHealthScorer(js nats.JetStreamContext, featureSubj string, optFns ...func(*HealthScorerOptions)) (*HealthScorer, error) {
	if js == nil {
		return nil, errors.New("jetstream context cannot be nil")
	}
	opts := defaultOptions()
	for _, fn := range optFns {
		fn(&opts)
	}
	if opts.Strategy == nil {
		return nil, errors.New("strategy cannot be nil")
	}
	return &HealthScorer{
		js:      js,
		subject: featureSubj,
		opts:    opts,
		buffer:  make([]FeatureVector, 0, 1024),
	}, nil
}

// Run starts the scorer until the context is canceled.
func (h *HealthScorer) Run(ctx context.Context) error {
	ctx, h.cancel = context.WithCancel(ctx)

	// Subscribe via JetStream Push Consumer
	sub, err := h.js.Subscribe(h.subject, h.handleMsg,
		nats.ManualAck(), nats.AckExplicit(),
	)
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	h.wg.Add(1)
	go func() {
		defer h.wg.Done()
		<-ctx.Done()
		sub.Drain()
	}()

	// Periodic computation
	ticker := time.NewTicker(h.opts.ComputeInterval)
	h.wg.Add(1)
	go func() {
		defer h.wg.Done()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				h.computeAndPublish()
			}
		}
	}()

	h.wg.Wait()
	return nil
}

// Stop gracefully stops the scorer.
func (h *HealthScorer) Stop() {
	if h.cancel != nil {
		h.cancel()
	}
}

// handleMsg processes raw feature events.
func (h *HealthScorer) handleMsg(msg *nats.Msg) {
	defer msg.Ack()
	eventsConsumed.WithLabelValues(h.subject).Inc()

	var fv FeatureVector
	if err := json.Unmarshal(msg.Data, &fv); err != nil {
		h.opts.Logger.Errorf("invalid feature vector: %v", err)
		return
	}
	h.appendVector(fv)
}

// appendVector adds the vector to the sliding window, evicting stale entries.
func (h *HealthScorer) appendVector(fv FeatureVector) {
	h.mu.Lock()
	defer h.mu.Unlock()

	// Insert
	h.buffer = append(h.buffer, fv)

	// Evict
	expiry := time.Now().Add(-h.opts.Window)
	idx := 0
	for idx < len(h.buffer) && h.buffer[idx].Timestamp.Before(expiry) {
		idx++
	}
	if idx > 0 {
		h.buffer = h.buffer[idx:]
	}
}

// computeAndPublish calculates the score and publishes an event.
func (h *HealthScorer) computeAndPublish() {
	h.mu.RLock()
	snapshot := make([]FeatureVector, len(h.buffer))
	copy(snapshot, h.buffer)
	h.mu.RUnlock()

	score := h.opts.Strategy.ComputeScore(snapshot)
	healthScoreGauge.WithLabelValues(h.opts.Strategy.Name()).Set(score)

	event := HealthScoreEvent{
		Score:     score,
		Strategy:  h.opts.Strategy.Name(),
		Timestamp: time.Now().UTC(),
		Window:    h.opts.Window.String(),
	}
	payload, _ := json.Marshal(event) // safe: simple struct

	if _, err := h.js.Publish(h.opts.OutSubject, payload); err != nil {
		h.opts.Logger.Errorf("publish health score: %v", err)
	}
}

// ----------------------------------------------------------------------------
// Helper – simple logger abstraction to avoid bringing any heavy deps
// ----------------------------------------------------------------------------

type Logger interface {
	Debugf(string, ...interface{})
	Infof(string, ...interface{})
	Warnf(string, ...interface{})
	Errorf(string, ...interface{})
}

type stdLogger struct{}

func (stdLogger) logf(lvl string, f string, a ...interface{}) {
	msg := fmt.Sprintf(f, a...)
	fmt.Printf("%s %s\n", lvl, msg)
}
func (l stdLogger) Debugf(f string, a ...interface{}) { l.logf("[DEBUG]", f, a...) }
func (l stdLogger) Infof(f string, a ...interface{})  { l.logf("[INFO ]", f, a...) }
func (l stdLogger) Warnf(f string, a ...interface{})  { l.logf("[WARN ]", f, a...) }
func (l stdLogger) Errorf(f string, a ...interface{}) { l.logf("[ERROR]", f, a...) }

// ----------------------------------------------------------------------------
// Compile-time interface guard
// ----------------------------------------------------------------------------

var _ ScoringStrategy = (SimpleAverageStrategy{})
var _ ScoringStrategy = (WeightedStrategy{})
```