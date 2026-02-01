```go
// Code generated for EchoPulse – Real-Time Social Signal Processing Platform.
// Path: src/module_22.go
// Module: DriftWatcher – monitors feature distribution drift and raises
//        model-retraining requests through the central event bus.
//
// This module demonstrates production-grade Go with concurrency, interface
// abstractions, metrics, and defensive programming.
//
// NOTE: In a full deployment the EventBus would be backed by Kafka or NATS.
//       For stand-alone compilation we ship a minimal in-memory implementation
//       that satisfies the same interface so the example remains runnable.

package monitoring

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"sync"
	"sync/atomic"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

//-----------------------------------------------------------------------------
// Event & message definitions
//-----------------------------------------------------------------------------

// FeatureStats is produced by upstream data-profiling workers.  It represents a
// histogramed view of a single feature over a recent sliding window.
type FeatureStats struct {
	Feature   string    `json:"feature"`
	Bins      []float64 `json:"bins"`   // Histogram bin upper-bounds (n+1 slice)
	Counts    []int64   `json:"counts"` // Observations per bin (n slice)
	Timestamp time.Time `json:"ts"`
}

// RetrainRequest is emitted when a monitored feature exceeds its drift
// tolerance or when an aggregate drift signal is detected.
type RetrainRequest struct {
	ModelID   string            `json:"model_id"`
	Triggered map[string]float64 `json:"triggered"` // feature → psi
	Reason    string            `json:"reason"`
	TS        time.Time         `json:"ts"`
}

//-----------------------------------------------------------------------------
// EventBus abstraction (Observer pattern)
//-----------------------------------------------------------------------------

// EventBus provides the minimal API we need.  Backed by Kafka, NATS JetStream,
// or any pub/sub service that supports at-least-once semantics.
type EventBus interface {
	Subscribe(ctx context.Context, topic string, handler func([]byte) error) error
	Publish(ctx context.Context, topic string, data []byte) error
}

// InMemoryBus is a toy implementation useful in tests or local demos.
type InMemoryBus struct {
	mu       sync.RWMutex
	handlers map[string][]func([]byte)
}

// NewInMemoryBus returns an isolated bus.
func NewInMemoryBus() *InMemoryBus {
	return &InMemoryBus{
		handlers: make(map[string][]func([]byte)),
	}
}

func (b *InMemoryBus) Subscribe(_ context.Context, topic string, handler func([]byte) error) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.handlers[topic] = append(b.handlers[topic], handler)
	return nil
}

func (b *InMemoryBus) Publish(_ context.Context, topic string, data []byte) error {
	b.mu.RLock()
	defer b.mu.RUnlock()
	for _, h := range b.handlers[topic] {
		// Fire handlers synchronously; production impl would use goroutines.
		if err := h(data); err != nil {
			return err
		}
	}
	return nil
}

//-----------------------------------------------------------------------------
// DriftWatcher configuration & metrics
//-----------------------------------------------------------------------------

// Config drives a DriftWatcher instance.
type Config struct {
	StatsTopic          string        // incoming FeatureStats topic
	AlertsTopic         string        // outgoing retrain requests
	ModelID             string        // which model we guard
	EvaluateEvery       time.Duration // aggregation cadence
	PSIThreshold        float64       // trigger threshold
	RequiredViolations  int           // consecutive windows > threshold
	Logger              *log.Logger   // optional, falls back to std
	BaselineSampleGrace time.Duration // max age for baseline
}

// Prometheus metrics
var (
	psiGauge = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "echopulse_feature_psi",
			Help: "Population Stability Index per feature vs baseline.",
		},
		[]string{"model_id", "feature"},
	)

	alertCounter = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "echopulse_drift_alert_total",
			Help: "Number of drift alerts emitted.",
		},
		[]string{"model_id"},
	)
)

func init() {
	prometheus.MustRegister(psiGauge, alertCounter)
}

//-----------------------------------------------------------------------------
// DriftWatcher implementation
//-----------------------------------------------------------------------------

// DriftWatcher watches FeatureStats in real-time, compares them to a
// "baseline" distribution obtained from the training data (or the model
// registry), and raises retraining requests if drift is persistent.
type DriftWatcher struct {
	cfg      Config
	bus      EventBus
	baseline map[string][]float64 // feature → expected ratios
	driftCnt map[string]int       // feature → consecutive violations

	started atomic.Bool
	mu      sync.RWMutex // guards baseline & driftCnt
	cancel  context.CancelFunc
	wg      sync.WaitGroup
}

// NewDriftWatcher constructs the watcher with an initial baseline.  The
// baseline maps feature → histogram bin ratios (probabilities) and is usually
// sourced from the feature store / model registry.
func NewDriftWatcher(bus EventBus, cfg Config, baseline map[string][]float64) *DriftWatcher {
	if cfg.Logger == nil {
		cfg.Logger = log.Default()
	}

	return &DriftWatcher{
		cfg:      cfg,
		bus:      bus,
		baseline: baseline,
		driftCnt: make(map[string]int, len(baseline)),
	}
}

// Start registers subscriptions and launches background workers.
func (w *DriftWatcher) Start(ctx context.Context) error {
	if !w.started.CompareAndSwap(false, true) {
		return errors.New("watcher already started")
	}

	ctx, cancel := context.WithCancel(ctx)
	w.cancel = cancel

	// Build message buffer to decouple ingest from evaluation tick.
	msgC := make(chan *FeatureStats, 1024)

	// Subscribe to raw stats stream.
	if err := w.bus.Subscribe(ctx, w.cfg.StatsTopic, func(b []byte) error {
		var fs FeatureStats
		if err := json.Unmarshal(b, &fs); err != nil {
			return fmt.Errorf("decode FeatureStats: %w", err)
		}
		select {
		case msgC <- &fs:
		case <-ctx.Done():
		}
		return nil
	}); err != nil {
		return err
	}

	// Background accumulator.
	acc := make(map[string][]int64) // feature → counts
	var mu sync.Mutex

	w.wg.Add(1)
	go func() {
		defer w.wg.Done()
		for {
			select {
			case <-ctx.Done():
				return
			case s := <-msgC:
				mu.Lock()
				acc[s.Feature] = mergeCounts(acc[s.Feature], s.Counts)
				mu.Unlock()
			}
		}
	}()

	// Evaluator tick.
	w.wg.Add(1)
	go func() {
		defer w.wg.Done()

		ticker := time.NewTicker(w.cfg.EvaluateEvery)
		defer ticker.Stop()

		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				mu.Lock()
				snapshot := make(map[string][]int64, len(acc))
				for f, counts := range acc {
					snapshot[f] = counts
				}
				// Reset accumulator for next window.
				acc = make(map[string][]int64)
				mu.Unlock()

				if err := w.evaluate(ctx, snapshot); err != nil {
					w.cfg.Logger.Printf("drift evaluation error: %v", err)
				}
			}
		}
	}()

	return nil
}

// Stop shuts down the watcher gracefully.
func (w *DriftWatcher) Stop() {
	if !w.started.CompareAndSwap(true, false) {
		return
	}
	w.cancel()
	w.wg.Wait()
}

// evaluate computes PSI for each feature and decides whether to raise alerts.
func (w *DriftWatcher) evaluate(ctx context.Context, counts map[string][]int64) error {
	retrainTriggered := make(map[string]float64)

	for feature, observedCounts := range counts {
		expectedRatios, ok := w.baseline[feature]
		if !ok {
			// Unknown feature – skip but log once.
			w.cfg.Logger.Printf("baseline missing for feature %q", feature)
			continue
		}

		psi, err := computePSI(expectedRatios, observedCounts)
		if err != nil {
			w.cfg.Logger.Printf("psi calculation failed for %q: %v", feature, err)
			continue
		}

		psiGauge.WithLabelValues(w.cfg.ModelID, feature).Set(psi)

		// Drift logic
		if psi >= w.cfg.PSIThreshold {
			w.driftCnt[feature]++
		} else {
			w.driftCnt[feature] = 0
		}

		if w.driftCnt[feature] >= w.cfg.RequiredViolations {
			retrainTriggered[feature] = psi
			w.driftCnt[feature] = 0 // reset after firing
		}
	}

	if len(retrainTriggered) > 0 {
		req := RetrainRequest{
			ModelID:   w.cfg.ModelID,
			Triggered: retrainTriggered,
			Reason:    "psi_threshold_exceeded",
			TS:        time.Now(),
		}
		payload, _ := json.Marshal(req)

		if err := w.bus.Publish(ctx, w.cfg.AlertsTopic, payload); err != nil {
			return fmt.Errorf("publish retrain request: %w", err)
		}
		alertCounter.WithLabelValues(w.cfg.ModelID).Inc()
		w.cfg.Logger.Printf("retrain request emitted: %+v", req)
	}

	return nil
}

//-----------------------------------------------------------------------------
// Helpers
//-----------------------------------------------------------------------------

// mergeCounts adds b into a (a += b) and returns a new slice.
func mergeCounts(a []int64, b []int64) []int64 {
	if len(a) < len(b) {
		a = append(a, make([]int64, len(b)-len(a))...)
	}
	for i := range b {
		a[i] += b[i]
	}
	return a
}

// computePSI returns the Population Stability Index given the expected ratios
// (slice length n) and the observed counts (length n).  Observed counts are
// first converted to ratios.  The function safeguards against zeros by
// replacing with a small epsilon value.
func computePSI(expected []float64, observedCounts []int64) (float64, error) {
	if len(expected) == 0 || len(expected) != len(observedCounts) {
		return 0, fmt.Errorf("mismatched input lengths: expected=%d, observed=%d",
			len(expected), len(observedCounts))
	}

	var totalObserved int64
	for _, c := range observedCounts {
		totalObserved += c
	}
	if totalObserved == 0 {
		return 0, errors.New("no observations in window")
	}

	const eps = 1e-9
	var psi float64
	for i, exp := range expected {
		act := float64(observedCounts[i]) / float64(totalObserved)
		// Avoid div by zero / log of zero.
		if exp < eps {
			exp = eps
		}
		if act < eps {
			act = eps
		}
		psi += (act - exp) * math.Log(act/exp)
	}
	return psi, nil
}
```