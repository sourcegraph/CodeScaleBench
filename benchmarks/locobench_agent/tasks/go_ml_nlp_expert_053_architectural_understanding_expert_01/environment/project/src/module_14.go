```go
// File: src/module_14.go
// Package pipeline implements a real-time health scoring pipeline that consumes
// SocialEvents from an event bus, maintains a sliding window over the most
// recent N seconds, and periodically publishes a CommunityHealthEvent with a
// platform-wide “community heartbeat” score.
//
// The code demonstrates several of EchoPulse’s architectural patterns:
//
//   • Observer Pattern   – event consumption/publication hooks
//   • Strategy Pattern   – pluggable scoring algorithms
//   • Pipeline Pattern   – modular, streaming data-flow
//   • Factory Pattern    – construction helpers for strategies & aggregators
//
// NOTE: Integration with Kafka/NATS is abstracted behind the EventBus
// interface so this module can be compiled and unit-tested in isolation.

package pipeline

import (
	"container/list"
	"context"
	"encoding/json"
	"errors"
	"log"
	"sync"
	"time"
)

// -----------------------------------------------------------------------------
// Domain Types
// -----------------------------------------------------------------------------

// SocialEvent is the canonical, pre-processed artifact produced by upstream
// ingestion services (see modules 3, 4, and 7).
type SocialEvent struct {
	ID        string    `json:"id"`
	UserID    string    `json:"user_id"`
	Timestamp time.Time `json:"ts"`

	// Pre-computed values attached by the upstream sentiment / toxicity models
	Sentiment float64 `json:"sentiment"` // range: [-1, 1]
	Toxicity  float64 `json:"toxicity"`  // probability [0, 1]
}

// CommunityHealthEvent is emitted by this module and can be visualized or fed
// into downstream moderation / alerting systems.
type CommunityHealthEvent struct {
	Version   int       `json:"version"`
	Score     float64   `json:"score"` // higher == healthier
	Window    string    `json:"window"`
	EventCt   int       `json:"event_count"`
	UpdatedAt time.Time `json:"ts"`
}

// -----------------------------------------------------------------------------
// Event Bus Abstractions (minimal subset for this module)
// -----------------------------------------------------------------------------

// EventBus abstracts Kafka/NATS JetStream/etc.
type EventBus interface {
	Subscribe(ctx context.Context, topic string) (<-chan *BusMessage, error)
	Publish(ctx context.Context, topic string, msg *BusMessage) error
}

// BusMessage wraps arbitrary payloads.
type BusMessage struct {
	Key     string
	Payload []byte
}

// -----------------------------------------------------------------------------
// Health Scoring Strategy Pattern
// -----------------------------------------------------------------------------

// ScoringStrategy encapsulates a community-health algorithm.
type ScoringStrategy interface {
	// Compute returns a normalized score in [0, 1] where 1 is “very healthy”.
	Compute(events []*SocialEvent) float64
	Name() string
}

// NewScoringStrategy is a small Factory for built-in strategies.
func NewScoringStrategy(name string) (ScoringStrategy, error) {
	switch name {
	case "simple":
		return &simpleAverage{}, nil
	case "toxicity_weighted":
		return &toxicityWeighted{}, nil
	default:
		return nil, errors.New("unknown scoring strategy: " + name)
	}
}

// --- simpleAverage -----------------------------------------------------------

type simpleAverage struct{}

func (s *simpleAverage) Name() string { return "simple" }

func (s *simpleAverage) Compute(events []*SocialEvent) float64 {
	if len(events) == 0 {
		return 0.5 // neutral default
	}
	var sum float64
	for _, e := range events {
		sum += e.Sentiment
	}
	// Map [-1,1] sentiment average to [0,1] health score.
	return normalize(sum / float64(len(events)))
}

// --- toxicityWeighted --------------------------------------------------------

type toxicityWeighted struct{}

func (t *toxicityWeighted) Name() string { return "toxicity_weighted" }

func (t *toxicityWeighted) Compute(events []*SocialEvent) float64 {
	if len(events) == 0 {
		return 0.5
	}
	var sentimentSum, toxicitySum float64
	for _, e := range events {
		sentimentSum += e.Sentiment
		toxicitySum += e.Toxicity
	}
	avgSent := sentimentSum / float64(len(events))
	avgTox := toxicitySum / float64(len(events))

	// Penalize sentiment by toxicity (simple affine transform).
	score := normalize(avgSent) * (1.0 - avgTox)
	return clamp(score, 0, 1)
}

// -----------------------------------------------------------------------------
// Sliding Window Aggregator (Concurrency-Safe)
// -----------------------------------------------------------------------------

// WindowAggregator keeps only the last <duration> of events.
type WindowAggregator struct {
	window   time.Duration
	strategy ScoringStrategy

	mu     sync.RWMutex
	buffer *list.List // queue of *SocialEvent (oldest → newest)
}

func NewWindowAggregator(d time.Duration, strategy ScoringStrategy) *WindowAggregator {
	return &WindowAggregator{
		window:   d,
		strategy: strategy,
		buffer:   list.New(),
	}
}

// Add inserts a new event and evicts old ones.
func (wa *WindowAggregator) Add(ev *SocialEvent) {
	wa.mu.Lock()
	defer wa.mu.Unlock()

	wa.buffer.PushBack(ev)

	cutoff := time.Now().Add(-wa.window)
	for wa.buffer.Len() > 0 {
		front := wa.buffer.Front()
		if front == nil {
			break
		}
		e := front.Value.(*SocialEvent)
		if e.Timestamp.After(cutoff) {
			break
		}
		wa.buffer.Remove(front)
	}
}

// Snapshot returns a slice copy of the current window contents.
func (wa *WindowAggregator) Snapshot() []*SocialEvent {
	wa.mu.RLock()
	defer wa.mu.RUnlock()

	events := make([]*SocialEvent, 0, wa.buffer.Len())
	for el := wa.buffer.Front(); el != nil; el = el.Next() {
		events = append(events, el.Value.(*SocialEvent))
	}
	return events
}

// Score calculates the health score over the current window.
func (wa *WindowAggregator) Score() float64 {
	return wa.strategy.Compute(wa.Snapshot())
}

// Size returns current event count.
func (wa *WindowAggregator) Size() int {
	wa.mu.RLock()
	defer wa.mu.RUnlock()
	return wa.buffer.Len()
}

// -----------------------------------------------------------------------------
// Pipeline Orchestration
// -----------------------------------------------------------------------------

// HealthPipelineConfig allows fine-grained tuning via environment / config map.
type HealthPipelineConfig struct {
	InTopic        string
	OutTopic       string
	Window         time.Duration
	Strategy       string
	PublishPeriod  time.Duration
	LogGracePeriod time.Duration
}

// HealthPipeline is a long-running goroutine that wires all parts together.
type HealthPipeline struct {
	agg       *WindowAggregator
	bus       EventBus
	inTopic   string
	outTopic  string
	publishTs time.Time
	pubEvery  time.Duration
}

// NewHealthPipeline constructs the pipeline according to cfg.
func NewHealthPipeline(bus EventBus, cfg HealthPipelineConfig) (*HealthPipeline, error) {
	strat, err := NewScoringStrategy(cfg.Strategy)
	if err != nil {
		return nil, err
	}

	agg := NewWindowAggregator(cfg.Window, strat)

	return &HealthPipeline{
		agg:      agg,
		bus:      bus,
		inTopic:  cfg.InTopic,
		outTopic: cfg.OutTopic,
		pubEvery: cfg.PublishPeriod,
	}, nil
}

// Run is blocking until ctx is cancelled.
func (hp *HealthPipeline) Run(ctx context.Context) error {
	eventsCh, err := hp.bus.Subscribe(ctx, hp.inTopic)
	if err != nil {
		return err
	}

	tick := time.NewTicker(hp.pubEvery)
	defer tick.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()

		case msg := <-eventsCh:
			if msg == nil {
				continue
			}
			var ev SocialEvent
			if err := json.Unmarshal(msg.Payload, &ev); err != nil {
				log.Printf("[health-pipeline] invalid SocialEvent: %v", err)
				continue
			}
			hp.agg.Add(&ev)

		case <-tick.C:
			hp.publish(ctx)
		}
	}
}

func (hp *HealthPipeline) publish(ctx context.Context) {
	score := hp.agg.Score()
	count := hp.agg.Size()

	che := CommunityHealthEvent{
		Version:   1,
		Score:     score,
		Window:    hp.agg.window.String(),
		EventCt:   count,
		UpdatedAt: time.Now().UTC(),
	}

	payload, err := json.Marshal(&che)
	if err != nil {
		log.Printf("[health-pipeline] marshal error: %v", err)
		return
	}

	bm := &BusMessage{
		Key:     "community_health",
		Payload: payload,
	}

	if err := hp.bus.Publish(ctx, hp.outTopic, bm); err != nil {
		log.Printf("[health-pipeline] publish error: %v", err)
	}
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

func normalize(sentiment float64) float64 {
	// sentiment in [-1,1] → [0,1]
	return clamp((sentiment+1)/2, 0, 1)
}

func clamp(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
```