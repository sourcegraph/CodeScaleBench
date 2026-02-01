package echopulse

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"sync"
	"time"
)

/*
Package echopulse implements core utilities for the “EchoPulse” real-time
social-signal processing platform.  This source file (module_19.go) contains
a drift-detection service that continuously evaluates feature-distribution
metrics published by upstream analytics jobs.  When statistically significant
drift is detected, the service emits a ModelDriftEvent on the event bus,
triggering automated re-training pipelines downstream.

Key design goals:
  • Thread-safety and back-pressure handling (internal channel buffer +
    context cancellation).
  • Pluggable event-bus interface (Kafka, NATS, or the in-memory fallback
    provided in this file for unit-testing).
  • Production-grade error handling with exponential back-off on publish
    failures.
*/

// EventBus defines the minimal contract expected by DriftDetector
// for publishing events onto the platform’s high-throughput event bus.
type EventBus interface {
	// Publish serialises msg and delivers it to topic.
	// Implementations MUST be thread-safe.
	Publish(ctx context.Context, topic string, msg interface{}) error
}

// DriftDetectionConfig encapsulates run-time settings for the
// distribution-drift detection engine.
type DriftDetectionConfig struct {
	// PSIThreshold is the minimum Population Stability Index that will be
	// considered statistically significant.
	PSIThreshold float64

	// Cooldown controls how often (per feature) a drift notification may be
	// sent.  This prevents alert storms for unstable features.
	Cooldown time.Duration

	// PublishTopic is the logical event-bus topic to which ModelDriftEvent
	// messages will be published.
	PublishTopic string

	// MaxRetry controls how many times the detector will retry a publish
	// operation before giving up.  Retries use exponential back-off.
	MaxRetry int
}

// Bin represents a single histogram bucket for the PSI computation.
type Bin struct {
	LowerBound float64 // inclusive
	UpperBound float64 // exclusive
	Expected   float64 // expected (training) probability mass
	Actual     float64 // actual (live) probability mass
}

// FeatureHistogram aggregates bins for a single feature.
type FeatureHistogram struct {
	Feature string
	Bins    []Bin
}

// ModelDriftEvent represents the payload emitted when drift is detected.
type ModelDriftEvent struct {
	Feature     string    `json:"feature"`
	PSI         float64   `json:"psi"`
	TriggeredAt time.Time `json:"triggered_at"`
}

// DriftDetector consumes FeatureHistogram objects, computes PSI, and publishes
// ModelDriftEvent when the PSI exceeds the configured threshold.
type DriftDetector struct {
	cfg           DriftDetectionConfig
	bus           EventBus
	inCh          chan FeatureHistogram
	wg            sync.WaitGroup
	lastTriggered sync.Map // map[string]time.Time
	ctx           context.Context
	cancel        context.CancelFunc
}

// NewDriftDetector constructs a detector with an internal worker pool.
// buffer controls the size of the inbound channel; workers controls
// concurrency for PSI computation / publishing.
func NewDriftDetector(
	cfg DriftDetectionConfig,
	bus EventBus,
	buffer int,
	workers int,
) *DriftDetector {
	if cfg.PSIThreshold <= 0 {
		cfg.PSIThreshold = 0.2 // sensible default
	}
	if cfg.Cooldown <= 0 {
		cfg.Cooldown = 30 * time.Minute
	}
	if cfg.MaxRetry <= 0 {
		cfg.MaxRetry = 5
	}
	ctx, cancel := context.WithCancel(context.Background())
	d := &DriftDetector{
		cfg:    cfg,
		bus:    bus,
		inCh:   make(chan FeatureHistogram, buffer),
		ctx:    ctx,
		cancel: cancel,
	}

	for i := 0; i < workers; i++ {
		d.wg.Add(1)
		go d.worker()
	}
	return d
}

// Close gracefully shuts down the drift detector, waiting for all in-flight
// work to complete.
func (d *DriftDetector) Close() error {
	d.cancel()
	d.wg.Wait()
	return nil
}

// Submit pushes a histogram into the detector’s internal buffer.
// This call is non-blocking as long as the buffer is not full.
func (d *DriftDetector) Submit(hist FeatureHistogram) error {
	select {
	case <-d.ctx.Done():
		return errors.New("drift detector is shutting down")
	case d.inCh <- hist:
		return nil
	}
}

func (d *DriftDetector) worker() {
	defer d.wg.Done()
	for {
		select {
		case <-d.ctx.Done():
			return
		case hist := <-d.inCh:
			d.handle(hist)
		}
	}
}

func (d *DriftDetector) handle(hist FeatureHistogram) {
	psi, err := ComputePSI(hist)
	if err != nil {
		log.Printf("drift-detector: compute PSI failed for %s: %v", hist.Feature, err)
		return
	}
	if psi < d.cfg.PSIThreshold {
		return // no drift
	}

	now := time.Now()
	if lastAny, ok := d.lastTriggered.Load(hist.Feature); ok {
		last := lastAny.(time.Time)
		if now.Sub(last) < d.cfg.Cooldown {
			return // within cooldown window, drop event
		}
	}

	event := ModelDriftEvent{
		Feature:     hist.Feature,
		PSI:         psi,
		TriggeredAt: now,
	}

	if err := d.publishWithRetry(event); err != nil {
		log.Printf("drift-detector: failed to publish drift event for %s: %v", hist.Feature, err)
		return
	}
	d.lastTriggered.Store(hist.Feature, now)
}

func (d *DriftDetector) publishWithRetry(evt ModelDriftEvent) error {
	var attempt int
	for {
		attempt++
		err := d.bus.Publish(d.ctx, d.cfg.PublishTopic, evt)
		if err == nil {
			return nil
		}
		if attempt >= d.cfg.MaxRetry {
			return fmt.Errorf("publish failed after %d attempts: %w", attempt, err)
		}
		backoff := time.Duration(1<<attempt) * 100 * time.Millisecond
		select {
		case <-d.ctx.Done():
			return d.ctx.Err()
		case <-time.After(backoff):
			// retry
		}
	}
}

// ComputePSI calculates the Population Stability Index for the provided
// histogram.  An error is returned if inputs are malformed.
func ComputePSI(hist FeatureHistogram) (float64, error) {
	if len(hist.Bins) == 0 {
		return 0, errors.New("no bins present")
	}
	var psi float64
	for idx, b := range hist.Bins {
		if b.Expected < 0 || b.Actual < 0 {
			return 0, fmt.Errorf("negative probability mass in bin %d", idx)
		}
		if b.Expected == 0 && b.Actual == 0 {
			continue // skip empty bin
		}
		// To avoid divide-by-zero, apply small epsilon.
		exp := clamp(b.Expected, 1e-9, 1)
		act := clamp(b.Actual, 1e-9, 1)
		psi += (act - exp) * math.Log(act/exp)
	}
	return psi, nil
}

func clamp(v, min, max float64) float64 {
	if v < min {
		return min
	}
	if v > max {
		return max
	}
	return v
}

/************  In-Memory EventBus (fallback & testing) *************/

// MemoryBus is an in-memory implementation of EventBus.
// It is NOT designed for production environments, but is extremely
// convenient for unit-tests and local experimentation.
type MemoryBus struct {
	mu     sync.RWMutex
	topics map[string][]chan []byte
}

// NewMemoryBus returns a new MemoryBus instance.
func NewMemoryBus() *MemoryBus {
	return &MemoryBus{
		topics: make(map[string][]chan []byte),
	}
}

// Subscribe returns a read-only channel that will receive raw JSON
// messages published to the supplied topic.
func (m *MemoryBus) Subscribe(topic string, buffer int) <-chan []byte {
	m.mu.Lock()
	defer m.mu.Unlock()
	ch := make(chan []byte, buffer)
	m.topics[topic] = append(m.topics[topic], ch)
	return ch
}

// Publish serialises msg to JSON and delivers it to all subscribers
// of the topic.  It blocks if subscriber channels are full.
func (m *MemoryBus) Publish(_ context.Context, topic string, msg interface{}) error {
	m.mu.RLock()
	subs, ok := m.topics[topic]
	m.mu.RUnlock()
	if !ok {
		return nil // no subscribers; silently drop
	}

	payload, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("memory bus marshal: %w", err)
	}

	for _, ch := range subs {
		select {
		case ch <- payload:
		default:
			log.Printf("memory bus: subscriber backlog on topic %s (dropping message)", topic)
		}
	}
	return nil
}