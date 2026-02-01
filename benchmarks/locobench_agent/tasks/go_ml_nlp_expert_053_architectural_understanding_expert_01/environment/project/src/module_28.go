```go
// File: src/module_28.go
//
// EchoPulse: Real-Time Social Signal Processing Platform
//
// Module 28 – Community Health Aggregator
//
// This module is responsible for converting low-level sentiment events
// into a rolling “community health” score that is continuously published
// back onto the event bus.  The implementation demonstrates:
//
//   • Observer pattern (EventHandler subscribed to an EventBus)
//   • Strategy pattern (pluggable sentiment merge strategies)
//   • Producer/Consumer concurrency with graceful shutdown
//   • Rolling time-window metrics with efficient eviction
//
// NOTE: External messaging, logging, and metrics libraries are abstracted
// behind interfaces so the module can be consumed by services using
// Apache Kafka, NATS JetStream, or any other pub/sub layer.
//
// Author: EchoPulse engineering team
// SPDX-License-Identifier: Apache-2.0
//
package echopulse

import (
	"context"
	"errors"
	"fmt"
	"log"
	"math"
	"sync"
	"time"
)

// ============================================================================
// Domain Types
// ============================================================================

// SocialEvent encapsulates a single user-generated artifact that has already
// been pre-processed by the upstream NLP pipeline (language detection,
// sentiment model, etc.).
type SocialEvent struct {
	ID         string            // globally unique event id
	UserID     string            // anonymized user id
	ChannelID  string            // e.g. chat room or stream id
	Type       string            // "text", "emoji", "voice", ...
	Text       string            // canonical text (after transcription etc.)
	Sentiment  float64           // normalized sentiment score ∈ [-1, 1]
	CreatedAt  time.Time         // event creation time (UTC)
	Labels     map[string]string // arbitrary KV tags (e.g. lang=en, model=v2)
	RawPayload []byte            // optional payload for audit/debug
}

// HealthScore summarizes the rolling community health for a channel.
type HealthScore struct {
	ChannelID   string    // chat room / stream id
	Score       float64   // ∈ [-1,1] aggregated sentiment
	WindowStart time.Time // start of the measurement window
	WindowEnd   time.Time // end (now) of the window
	EventCount  int       // number of social events aggregated
	GeneratedAt time.Time // when this structure was produced
}

// ============================================================================
// Event Bus & Handler Contracts
// ============================================================================

// EventBus is an abstract pub/sub façade. Any concrete implementation
// (Kafka, JetStream, Redis Streams, gRPC streaming, etc.) can satisfy it.
type EventBus interface {
	Subscribe(ctx context.Context, topic string, h EventHandler) error
	Publish(ctx context.Context, topic string, msg any) error
	Close() error
}

// EventHandler is the Observer callback for a given topic.
type EventHandler interface {
	Handle(ctx context.Context, msg any) error
}

// ============================================================================
// Sentiment Merge Strategy
// ============================================================================

// MergeStrategy combines two sentiment scores into a single one.
// Implementations may apply decays, weightings, or Bayesian updates.
type MergeStrategy interface {
	Merge(current float64, incoming float64) float64
}

// ExponentialDecayMerge merges sentiments with exponential decay factor α.
//   merged = α*incoming + (1-α)*current
// α ∈ (0,1] — higher means faster reaction to new data.
type ExponentialDecayMerge struct{ Alpha float64 }

func (m ExponentialDecayMerge) Merge(current, incoming float64) float64 {
	return m.Alpha*incoming + (1-m.Alpha)*current
}

// ============================================================================
// CommunityHealthAggregator
// ============================================================================

// AggregatorConfig holds tunable parameters for CommunityHealthAggregator.
type AggregatorConfig struct {
	InputTopic        string        // sentiment events topic
	OutputTopic       string        // health-score topic
	WindowSize        time.Duration // rolling window length
	PublishInterval   time.Duration // how often to publish aggregated score
	MergeStrategy     MergeStrategy // strategy to merge sentiments
	MaxChannelBuckets int           // guardrail for memory usage
	Logger            *log.Logger   // optional custom logger
}

// Validate checks invariants.
func (c *AggregatorConfig) Validate() error {
	switch {
	case c.InputTopic == "":
		return errors.New("input topic is required")
	case c.OutputTopic == "":
		return errors.New("output topic is required")
	case c.WindowSize <= 0:
		return errors.New("window size must be >0")
	case c.PublishInterval <= 0:
		return errors.New("publish interval must be >0")
	case c.MergeStrategy == nil:
		return errors.New("merge strategy cannot be nil")
	case c.MaxChannelBuckets <= 0:
		c.MaxChannelBuckets = 1000 // sensible default
	}
	return nil
}

// CommunityHealthAggregator consumes SocialEvent sentiment messages and
// produces rolling HealthScore updates.
type CommunityHealthAggregator struct {
	cfg      AggregatorConfig
	bus      EventBus
	shutdown chan struct{}
	wg       sync.WaitGroup

	// internal state
	mu       sync.RWMutex
	channels map[string]*channelStats
}

type channelStats struct {
	score      float64
	eventCount int
	events     []time.Time // time-ordered ringbuffer of event timestamps
}

// NewCommunityHealthAggregator constructs and starts the aggregator.
func NewCommunityHealthAggregator(bus EventBus, cfg AggregatorConfig) (*CommunityHealthAggregator, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	if cfg.Logger == nil {
		cfg.Logger = log.Default()
	}

	agg := &CommunityHealthAggregator{
		cfg:      cfg,
		bus:      bus,
		shutdown: make(chan struct{}),
		channels: make(map[string]*channelStats),
	}
	agg.wg.Add(2)
	go agg.runEventConsumer()
	go agg.runPublisher()
	return agg, nil
}

// -----------------------------------------------------------------------------
// Event Handling
// -----------------------------------------------------------------------------

// Handle implements EventHandler to satisfy EventBus subscription.
func (a *CommunityHealthAggregator) Handle(ctx context.Context, msg any) error {
	event, ok := msg.(SocialEvent)
	if !ok {
		return fmt.Errorf("CommunityHealthAggregator: unexpected msg type %T", msg)
	}

	if math.IsNaN(event.Sentiment) || event.Sentiment < -1 || event.Sentiment > 1 {
		// malformed sentiment, skip but continue
		return fmt.Errorf("CommunityHealthAggregator: invalid sentiment %v", event.Sentiment)
	}

	a.mu.Lock()
	defer a.mu.Unlock()

	stat, exists := a.channels[event.ChannelID]
	if !exists {
		if len(a.channels) >= a.cfg.MaxChannelBuckets {
			// guardrail: drop least active channel (heuristic: random)
			for ch := range a.channels {
				delete(a.channels, ch)
				break
			}
			a.cfg.Logger.Printf("CommunityHealthAggregator: evicted a channel bucket; new total=%d", len(a.channels))
		}
		stat = &channelStats{score: event.Sentiment}
		a.channels[event.ChannelID] = stat
	} else {
		stat.score = a.cfg.MergeStrategy.Merge(stat.score, event.Sentiment)
	}
	stat.eventCount++
	stat.events = append(stat.events, event.CreatedAt)

	return nil
}

// -----------------------------------------------------------------------------
// Goroutines
// -----------------------------------------------------------------------------

func (a *CommunityHealthAggregator) runEventConsumer() {
	defer a.wg.Done()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := a.bus.Subscribe(ctx, a.cfg.InputTopic, a); err != nil {
		a.cfg.Logger.Printf("CommunityHealthAggregator: subscribe error: %v", err)
		close(a.shutdown) // trigger total shutdown
	}
	<-a.shutdown
}

func (a *CommunityHealthAggregator) runPublisher() {
	defer a.wg.Done()
	ticker := time.NewTicker(a.cfg.PublishInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			now := time.Now().UTC()
			a.publishScores(now)
		case <-a.shutdown:
			return
		}
	}
}

// publishScores computes current health score per channel, cleans stale data,
// and publishes HealthScore messages onto the event bus.
func (a *CommunityHealthAggregator) publishScores(now time.Time) {
	a.mu.Lock()
	defer a.mu.Unlock()

	windowStart := now.Add(-a.cfg.WindowSize)
	for channelID, stat := range a.channels {
		// Evict events outside the window
		idx := 0
		for idx < len(stat.events) && stat.events[idx].Before(windowStart) {
			idx++
		}
		if idx > 0 {
			stat.events = stat.events[idx:]
		}

		if len(stat.events) == 0 {
			// No recent activity, prune bucket
			delete(a.channels, channelID)
			continue
		}

		hs := HealthScore{
			ChannelID:   channelID,
			Score:       stat.score,
			WindowStart: windowStart,
			WindowEnd:   now,
			EventCount:  stat.eventCount,
			GeneratedAt: now,
		}

		// Fire-and-forget publish – best effort
		if err := a.bus.Publish(context.Background(), a.cfg.OutputTopic, hs); err != nil {
			a.cfg.Logger.Printf("CommunityHealthAggregator: publish error: %v", err)
		}
	}
}

// -----------------------------------------------------------------------------
// Shutdown
// -----------------------------------------------------------------------------

// Close gracefully stops all goroutines and unsubscribes from the bus.
func (a *CommunityHealthAggregator) Close() error {
	close(a.shutdown)
	a.wg.Wait()
	return a.bus.Close()
}
```