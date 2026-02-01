```go
// Code generated for EchoPulse – Real-Time Social Signal Processing Platform.
// File: src/module_6.go
//
// Module 6: Real-Time Community-Health Aggregator
//
// This module listens to per-message toxicity/sentiment inference events coming
// from the event-bus, aggregates them in sliding time-windows, and publishes a
// smoothed “community-health” score.  The design combines the Observer pattern
// (subscribers receive HealthScoreEvents), the Strategy pattern (different
// aggregation rules), and a simple factory for pluggable strategies.
//
// NOTE:  To keep this example self-contained, external systems such as Kafka or
// a feature-store are represented by lightweight interfaces. Production builds
// should bind these interfaces to real implementations (JetStream, Redis,
// Feast, etc.).

package module6

import (
	"context"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"
)

// ---------- Domain Types ----------------------------------------------------

// SocialEvent represents the canonical message envelope produced by upstream
// NLP classifiers (toxicity, sentiment, stance, …).
type SocialEvent struct {
	ID        string            // immutable message UUID
	Timestamp time.Time         // original message time (not ingestion time)
	Scores    map[string]float64 // model-specific scores (e.g. "toxicity":0.83)
	Meta      map[string]string // arbitrary metadata (room, user-id, …)
}

// HealthScoreEvent is broadcast by this module after each aggregation tick.
type HealthScoreEvent struct {
	RoomID     string    // chat-room / community identifier
	WindowFrom time.Time // left-edge of the aggregation window (inclusive)
	WindowTo   time.Time // right-edge (exclusive)
	Score      float64   // normalized [0,1] health score (higher == healthier)
}

// ---------- Event-Bus Abstractions -----------------------------------------

// EventBusSubscriber wraps the real message bus (Kafka, NATS, …).  The module
// only needs a channel of SocialEvent and no semantics about partitions, etc.
type EventBusSubscriber interface {
	Subscribe(ctx context.Context, topic string, opts ...SubscribeOption) (<-chan SocialEvent, error)
}

// SubscribeOption pattern allows future configuration additions.
type SubscribeOption func(cfg *subscribeCfg)

type subscribeCfg struct {
	roomFilter string
}

func WithRoomFilter(roomID string) SubscribeOption {
	return func(cfg *subscribeCfg) { cfg.roomFilter = roomID }
}

// Observer is a downstream consumer interested in community health updates.
type Observer interface {
	NotifyHealth(ctx context.Context, ev HealthScoreEvent) error
}

// ---------- Strategy Pattern -----------------------------------------------

// HealthMetricStrategy transforms a batch of SocialEvent into a single
// community-health score in [0,1].  It must be safe to call from multiple
// goroutines.
type HealthMetricStrategy interface {
	Compute(events []SocialEvent) (float64, error)
	Name() string
}

// ToxicityInverseStrategy computes health = 1 ‑ mean(toxicity).
type ToxicityInverseStrategy struct{}

func (ToxicityInverseStrategy) Name() string { return "toxicity_inverse_mean" }

func (ToxicityInverseStrategy) Compute(events []SocialEvent) (float64, error) {
	if len(events) == 0 {
		return 1, nil // Undefined == perfectly healthy.
	}
	var sum float64
	for _, ev := range events {
		if v, ok := ev.Scores["toxicity"]; ok {
			sum += v
		}
	}
	mean := sum / float64(len(events))
	health := 1.0 - mean
	return clamp01(health), nil
}

// SentimentStrategy uses sentiment polarity in (-1,1).  Maps to (0,1) health.
type SentimentStrategy struct{}

func (SentimentStrategy) Name() string { return "sentiment_shift" }

func (SentimentStrategy) Compute(events []SocialEvent) (float64, error) {
	if len(events) == 0 {
		return 0.5, nil
	}
	var sum float64
	for _, ev := range events {
		if v, ok := ev.Scores["sentiment"]; ok {
			sum += v // assuming ‑1 … +1
		}
	}
	mean := sum / float64(len(events))
	health := (mean + 1.0) / 2.0 // shift to 0…1
	return clamp01(health), nil
}

// StrategyFactory registers known strategies.
var StrategyFactory = map[string]func() HealthMetricStrategy{
	"toxicity_inverse_mean": func() HealthMetricStrategy { return ToxicityInverseStrategy{} },
	"sentiment_shift":       func() HealthMetricStrategy { return SentimentStrategy{} },
}

// ---------- Aggregator Implementation --------------------------------------

// AggregatorConfig controls the behaviour of the health-score aggregator.
type AggregatorConfig struct {
	WindowSize       time.Duration // length of window (e.g. 1m)
	WindowStep       time.Duration // sliding step (<= WindowSize)
	RoomID           string        // filter by room
	StrategyName     string        // key into StrategyFactory
	EventTopic       string        // incoming bus topic
	BackpressureSize int           // channel buffer; 0 == unbuffered
}

func (cfg *AggregatorConfig) validate() error {
	if cfg.WindowSize <= 0 {
		return errors.New("WindowSize must be >0")
	}
	if cfg.WindowStep <= 0 || cfg.WindowStep > cfg.WindowSize {
		return errors.New("WindowStep must be in (0, WindowSize]")
	}
	if cfg.StrategyName == "" {
		return errors.New("StrategyName required")
	}
	if _, ok := StrategyFactory[cfg.StrategyName]; !ok {
		return fmt.Errorf("unknown strategy %q", cfg.StrategyName)
	}
	if cfg.BackpressureSize < 0 {
		cfg.BackpressureSize = 0
	}
	return nil
}

// Aggregator wires the event bus, the strategy, and a window buffer.
type Aggregator struct {
	cfg        AggregatorConfig
	strategy   HealthMetricStrategy
	bus        EventBusSubscriber
	observers  []Observer
	obsMu      sync.RWMutex
	buf        *ringBuffer
	cancelFunc context.CancelFunc
	stopOnce   sync.Once
}

// NewAggregator constructs and validates an Aggregator.
func NewAggregator(bus EventBusSubscriber, cfg AggregatorConfig) (*Aggregator, error) {
	if err := cfg.validate(); err != nil {
		return nil, err
	}
	strat := StrategyFactory[cfg.StrategyName]()
	return &Aggregator{
		cfg:      cfg,
		strategy: strat,
		bus:      bus,
		buf:      newRingBuffer(int(cfg.WindowSize / cfg.WindowStep)),
	}, nil
}

// Register adds an Observer; thread-safe.
func (a *Aggregator) Register(obs Observer) {
	a.obsMu.Lock()
	defer a.obsMu.Unlock()
	a.observers = append(a.observers, obs)
}

// Start spawns goroutines; it returns immediately.
func (a *Aggregator) Start(parent context.Context) error {
	if a.cancelFunc != nil {
		return errors.New("aggregator already started")
	}

	ctx, cancel := context.WithCancel(parent)
	a.cancelFunc = cancel

	eventsCh, err := a.bus.Subscribe(ctx, a.cfg.EventTopic, WithRoomFilter(a.cfg.RoomID))
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}

	// Worker 1: ingest events into ring-buffer.
	go a.ingestLoop(ctx, eventsCh)

	// Worker 2: periodic aggregation ticks.
	go a.tickLoop(ctx)

	return nil
}

// Stop is idempotent.
func (a *Aggregator) Stop() {
	a.stopOnce.Do(func() {
		if a.cancelFunc != nil {
			a.cancelFunc()
		}
	})
}

// ingestLoop continually reads from the bus and pushes into buffer.
func (a *Aggregator) ingestLoop(ctx context.Context, in <-chan SocialEvent) {
	for {
		select {
		case <-ctx.Done():
			return
		case ev, ok := <-in:
			if !ok {
				return
			}
			a.buf.push(ev)
		}
	}
}

// tickLoop fires every WindowStep; computes score and notifies observers.
func (a *Aggregator) tickLoop(ctx context.Context) {
	ticker := time.NewTicker(a.cfg.WindowStep)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			from := now.Add(-a.cfg.WindowSize)
			events := a.buf.slice(from, now)
			score, err := a.strategy.Compute(events)
			if err != nil {
				// keep running but log; we don’t have logger in example
				continue
			}
			a.broadcast(ctx, HealthScoreEvent{
				RoomID:     a.cfg.RoomID,
				WindowFrom: from,
				WindowTo:   now,
				Score:      score,
			})
		}
	}
}

// broadcast notifies every registered Observer (non-blocking).
func (a *Aggregator) broadcast(ctx context.Context, ev HealthScoreEvent) {
	a.obsMu.RLock()
	defer a.obsMu.RUnlock()
	for _, obs := range a.observers {
		// deliver concurrently to avoid slow observer blocking everyone
		go func(o Observer) {
			_ = o.NotifyHealth(ctx, ev) // ignore individual errors
		}(obs)
	}
}

// ---------- Sliding Window Buffer ------------------------------------------

// ringBuffer is a fixed-length circular buffer holding SocialEvent.
type ringBuffer struct {
	mu    sync.RWMutex
	data  []SocialEvent
	ptr   int // next write pointer
	filled bool
}

func newRingBuffer(capacity int) *ringBuffer {
	return &ringBuffer{
		data: make([]SocialEvent, capacity),
	}
}

// push inserts an event at ptr and advances.
func (rb *ringBuffer) push(ev SocialEvent) {
	rb.mu.Lock()
	defer rb.mu.Unlock()
	rb.data[rb.ptr] = ev
	rb.ptr = (rb.ptr + 1) % len(rb.data)
	if rb.ptr == 0 {
		rb.filled = true
	}
}

// slice returns all events whose Timestamp ∈ [from, to).
func (rb *ringBuffer) slice(from, to time.Time) []SocialEvent {
	rb.mu.RLock()
	defer rb.mu.RUnlock()

	if !rb.filled && rb.ptr == 0 {
		return nil
	}

	var out []SocialEvent
	iter := func(idx int, ev SocialEvent) {
		if !ev.Timestamp.Before(from) && ev.Timestamp.Before(to) {
			out = append(out, ev)
		}
	}

	if rb.filled {
		for i := 0; i < len(rb.data); i++ {
			iter(i, rb.data[i])
		}
	} else {
		for i := 0; i < rb.ptr; i++ {
			iter(i, rb.data[i])
		}
	}
	return out
}

// ---------- Helpers ---------------------------------------------------------

func clamp01(v float64) float64 {
	if math.IsNaN(v) {
		return 0
	}
	switch {
	case v < 0:
		return 0
	case v > 1:
		return 1
	default:
		return v
	}
}
```