```go
// File: src/module_36.go
//
// EchoPulse – Real-Time Social Signal Processing Platform
//
// Sliding window community-health aggregation and publishing module.
//
// This component consumes fine-grained SocialEvents from the internal event bus,
// maintains a time-bounded sliding window, converts the window into a single
// HealthScoreEvent using a pluggable scoring strategy, then notifies any number
// of observers (e.g. a Kafka publisher, metrics exporter, or in-memory cache).
//
// Author: EchoPulse Engineering
// License: Apache-2.0

package echopulse

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
)

// SocialEvent is the canonical minimal representation of a user-generated action
// after it has passed through the early stages of the EchoPulse ingestion
// pipeline.
type SocialEvent struct {
	ID         string    `json:"id"`
	Community  string    `json:"community_id"`
	Timestamp  time.Time `json:"ts"`
	Sentiment  float64   `json:"sentiment"` // range −1 .. 1
	Toxicity   float64   `json:"toxicity"`  // range  0 .. 1
	Confidence float64   `json:"confidence"`
}

// HealthScoreEvent is an aggregate KPI for a community over a time window.
type HealthScoreEvent struct {
	CommunityID string    `json:"community_id"`
	WindowStart time.Time `json:"window_start"`
	WindowEnd   time.Time `json:"window_end"`
	Score       float64   `json:"score"`      // range 0 .. 1
	N           int       `json:"num_events"` // number of events aggregated
	GeneratedAt time.Time `json:"generated_at"`
	Version     string    `json:"model_version"`
}

// HealthScoreObserver is the Observer interface; callers can register any
// number of implementations to receive score updates.
type HealthScoreObserver interface {
	OnHealthScore(ctx context.Context, e HealthScoreEvent) error
}

// HealthScorer is the Strategy interface for turning a slice of SocialEvents
// into a single scalar health score.
type HealthScorer interface {
	Score(events []SocialEvent) (float64, error)
	Version() string
}

// SentimentToxicityScorer is the default scoring strategy.
//
// score = (normalize(sentiment) * (1 - toxicity)) ^ gamma
// where normalize(sentiment) maps (−1,1) → (0,1).
type SentimentToxicityScorer struct {
	// Gamma tunes how aggressively negative signals drag the score down.
	Gamma float64
}

// Score implements HealthScorer.
func (s SentimentToxicityScorer) Score(events []SocialEvent) (float64, error) {
	if len(events) == 0 {
		return 0, errors.New("no events")
	}
	var sumSent, sumTox float64
	for _, e := range events {
		sumSent += (e.Sentiment + 1) / 2      // normalize sentiment
		sumTox += e.Toxicity
	}
	avgSent := sumSent / float64(len(events))
	avgTox := sumTox / float64(len(events))
	score := avgSent * (1 - avgTox)
	if s.Gamma <= 0 {
		s.Gamma = 1
	}
	for i := 1; i < int(s.Gamma); i++ {
		score *= score
	}
	return clamp(score, 0, 1), nil
}

// Version returns strategy version meta.
func (s SentimentToxicityScorer) Version() string { return "sentiment_toxicity/v1" }

// AggregatorConfig parameterizes a SlidingWindowAggregator instance.
type AggregatorConfig struct {
	CommunityID    string
	WindowDuration time.Duration
	TickInterval   time.Duration
	// MaxBuffer caps the in-memory buffer to prevent unbounded growth if the
	// aggregator is starved and cannot emit scores.
	MaxBuffer int
	Scorer    HealthScorer
}

// SlidingWindowAggregator maintains a time-bounded sliding window of events for
// one community and periodically collapses it into a HealthScoreEvent.
type SlidingWindowAggregator struct {
	cfg        AggregatorConfig
	mu         sync.RWMutex
	events     []SocialEvent
	observers  []HealthScoreObserver
	cancelFunc context.CancelFunc
	startOnce  sync.Once
	stopOnce   sync.Once
}

// NewSlidingWindowAggregator returns a ready-to-use aggregator. Call Start to
// spawn the periodic score calculation goroutine.
func NewSlidingWindowAggregator(cfg AggregatorConfig) (*SlidingWindowAggregator, error) {
	if cfg.CommunityID == "" {
		return nil, errors.New("community id required")
	}
	if cfg.WindowDuration <= 0 {
		cfg.WindowDuration = 1 * time.Minute
	}
	if cfg.TickInterval <= 0 {
		cfg.TickInterval = 10 * time.Second
	}
	if cfg.MaxBuffer <= 0 {
		cfg.MaxBuffer = 10_000
	}
	if cfg.Scorer == nil {
		cfg.Scorer = &SentimentToxicityScorer{Gamma: 1}
	}
	return &SlidingWindowAggregator{
		cfg: cfg,
	}, nil
}

// RegisterObserver attaches an observer. Registration is thread-safe.
func (a *SlidingWindowAggregator) RegisterObserver(obs HealthScoreObserver) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.observers = append(a.observers, obs)
}

// Consume adds a SocialEvent to the sliding window. If the buffer is full, the
// oldest event is dropped.
func (a *SlidingWindowAggregator) Consume(e SocialEvent) {
	if e.Community != a.cfg.CommunityID {
		// Guardrail: mis-routed events are ignored.
		return
	}
	a.mu.Lock()
	defer a.mu.Unlock()

	// Append new event.
	a.events = append(a.events, e)

	// Evict if buffer exceeds capacity.
	if len(a.events) > a.cfg.MaxBuffer {
		a.events = a.events[len(a.events)-a.cfg.MaxBuffer:]
	}

	// Evict events that fall out of the window.
	cutoff := time.Now().Add(-a.cfg.WindowDuration)
	i := 0
	for ; i < len(a.events); i++ {
		if a.events[i].Timestamp.After(cutoff) {
			break
		}
	}
	if i > 0 {
		a.events = a.events[i:]
	}
}

// Start spawns a goroutine that ticks at cfg.TickInterval, computes the window
// score, then notifies observers.
func (a *SlidingWindowAggregator) Start(ctx context.Context) {
	a.startOnce.Do(func() {
		ctx, cancel := context.WithCancel(ctx)
		a.cancelFunc = cancel
		go a.run(ctx)
	})
}

// Stop terminates the background goroutine. Idempotent.
func (a *SlidingWindowAggregator) Stop() {
	a.stopOnce.Do(func() {
		if a.cancelFunc != nil {
			a.cancelFunc()
		}
	})
}

func (a *SlidingWindowAggregator) run(ctx context.Context) {
	ticker := time.NewTicker(a.cfg.TickInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Printf("[aggregator:%s] shutting down", a.cfg.CommunityID)
			return
		case <-ticker.C:
			a.emitScore(ctx)
		}
	}
}

func (a *SlidingWindowAggregator) emitScore(ctx context.Context) {
	a.mu.RLock()
	window := make([]SocialEvent, len(a.events))
	copy(window, a.events)
	a.mu.RUnlock()

	score, err := a.cfg.Scorer.Score(window)
	if err != nil {
		// Empty window is normal; don't spam logs.
		return
	}
	evt := HealthScoreEvent{
		CommunityID: a.cfg.CommunityID,
		WindowEnd:   time.Now().UTC(),
		WindowStart: time.Now().Add(-a.cfg.WindowDuration).UTC(),
		Score:       score,
		N:           len(window),
		GeneratedAt: time.Now().UTC(),
		Version:     a.cfg.Scorer.Version(),
	}

	// Notify observers. We fan out sequentially; consider fan-out concurrency if
	// observers become slow.
	a.mu.RLock()
	defer a.mu.RUnlock()
	for _, obs := range a.observers {
		if err := obs.OnHealthScore(ctx, evt); err != nil {
			log.Printf("[aggregator:%s] observer error: %v", a.cfg.CommunityID, err)
		}
	}
}

// -----------------------------------------------------------------------------
// Observer implementation: Kafka publisher
// -----------------------------------------------------------------------------

// KafkaHealthScorePublisher publishes HealthScoreEvents to a Kafka topic.
type KafkaHealthScorePublisher struct {
	Writer     *kafka.Writer
	JSONIndent bool
}

// OnHealthScore satisfies HealthScoreObserver.
func (k KafkaHealthScorePublisher) OnHealthScore(ctx context.Context, e HealthScoreEvent) error {
	var payload []byte
	var err error
	if k.JSONIndent {
		payload, err = json.MarshalIndent(e, "", "  ")
	} else {
		payload, err = json.Marshal(e)
	}
	if err != nil {
		return err
	}
	msg := kafka.Message{
		Key:   []byte(e.CommunityID),
		Value: payload,
		Time:  e.GeneratedAt,
	}
	return k.Writer.WriteMessages(ctx, msg)
}

// -----------------------------------------------------------------------------
// Utility
// -----------------------------------------------------------------------------

func clamp(val, min, max float64) float64 {
	switch {
	case val < min:
		return min
	case val > max:
		return max
	default:
		return val
	}
}
```