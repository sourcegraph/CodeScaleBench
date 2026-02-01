```go
// Code generated for EchoPulse — Real-Time Social Signal Processing Platform.
// Path: src/module_16.go
//
// Module 16: Community Health Scoring Pipeline Stage.
//
// This file implements a concurrent, pluggable community-health scoring stage
// that consumes canonical SocialEvents, evaluates them with a registered
// ScoreStrategy, publishes ScoreEvents to downstream subscribers, and keeps a
// rolling aggregate of community health.  The design showcases several of the
// architectural patterns employed throughout the code-base:
//
//   • Factory / Strategy  – score strategies are discovered via a registry
//   • Observer            – an in-process event bus for pub/sub fan-out
//   • Pipeline            – discrete processing stages with strong back-pressure
//
// The code here is self-contained for compilation purposes; integrations with
// Kafka / NATS and the full feature-store are delegated out to production
// bridges implemented elsewhere in the project.

package pipeline

import (
	"context"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"
)

/* ----------------------------------------------------------------------
   Canonical Event Types
---------------------------------------------------------------------- */

// SocialEvent represents a normalized user artifact that flows through the
// EchoPulse event bus.  All downstream analysis hinges on this struct.
type SocialEvent struct {
	ID        string                 // Unique event identifier
	UserID    string                 // Author identifier
	Text      string                 // Canonical text representation
	Timestamp time.Time              // Original creation time (UTC)
	Metadata  map[string]interface{} // Arbitrary ML/NLP features (sentiment, toxicity, etc.)
}

// ScoreEvent represents the real-time community health score derived from an
// individual SocialEvent.  This event is emitted into the bus for downstream
// aggregation, monitoring, and action suggestions.
type ScoreEvent struct {
	SocialEventID string    // Reference to source event
	Score         float64   // Normalized [0,1] community health score
	Strategy      string    // Name of the strategy used
	Timestamp     time.Time // Time of scoring (UTC)
}

/* ----------------------------------------------------------------------
   Strategy Pattern – Pluggable Health Scoring Algorithms
---------------------------------------------------------------------- */

// ScoreStrategy encapsulates a concrete method for converting a SocialEvent
// into a normalized community health score.
type ScoreStrategy interface {
	Name() string
	Evaluate(ctx context.Context, evt SocialEvent) (float64, error)
}

// strategyFactory provides runtime registration / lookup of ScoreStrategies.
var strategyFactory = struct {
	mu        sync.RWMutex
	strategies map[string]ScoreStrategy
}{
	strategies: make(map[string]ScoreStrategy),
}

// RegisterScoreStrategy makes a strategy available to the factory.  Calling
// code (usually init funcs of separate packages) should invoke this once.
func RegisterScoreStrategy(s ScoreStrategy) error {
	if s == nil {
		return errors.New("pipeline: cannot register <nil> ScoreStrategy")
	}
	name := s.Name()
	if name == "" {
		return errors.New("pipeline: ScoreStrategy must declare a Name()")
	}

	strategyFactory.mu.Lock()
	defer strategyFactory.mu.Unlock()

	if _, exists := strategyFactory.strategies[name]; exists {
		return fmt.Errorf("pipeline: ScoreStrategy '%s' already registered", name)
	}
	strategyFactory.strategies[name] = s

	return nil
}

// GetScoreStrategy retrieves a registered strategy by name.
func GetScoreStrategy(name string) (ScoreStrategy, error) {
	strategyFactory.mu.RLock()
	defer strategyFactory.mu.RUnlock()

	s, ok := strategyFactory.strategies[name]
	if !ok {
		return nil, fmt.Errorf("pipeline: ScoreStrategy '%s' not found", name)
	}
	return s, nil
}

/* ----------------------------------------------------------------------
   Example Strategy Implementations
---------------------------------------------------------------------- */

// naiveSentimentStrategy is a reference implementation used out-of-box.  It
// expects the SocialEvent to carry pre-computed "sentiment" and "toxicity"
// floats in the Metadata map.  Production builds swap this out for more
// sophisticated, model-driven variants registered at init time elsewhere.
type naiveSentimentStrategy struct{}

func (naiveSentimentStrategy) Name() string { return "naive_sentiment_v1" }

func (naiveSentimentStrategy) Evaluate(_ context.Context, evt SocialEvent) (float64, error) {
	const (
		defaultSentiment = 0.5 // neutral
		defaultToxicity  = 0.0
	)

	sent, ok := evt.Metadata["sentiment"].(float64)
	if !ok {
		sent = defaultSentiment
	}

	tox, ok := evt.Metadata["toxicity"].(float64)
	if !ok {
		tox = defaultToxicity
	}

	// Basic heuristic: positive sentiment increases score, toxicity penalizes.
	score := clamp((sent*(1.0-tox))+0.5*(1.0-tox), 0, 1)
	return score, nil
}

func clamp(v, min, max float64) float64 {
	return math.Max(min, math.Min(max, v))
}

func init() {
	// Self-register the default strategy so the pipeline can function without
	// additional configuration in dev/test environments.
	_ = RegisterScoreStrategy(naiveSentimentStrategy{})
}

/* ----------------------------------------------------------------------
   Observer Pattern – Lightweight In-Process Event Bus
---------------------------------------------------------------------- */

// EventBus is a simple, type-safe pub/sub hub intended for local fan-out.  The
// production deployment uses Kafka / JetStream, but this implementation makes
// unit testing a breeze and keeps the module self-contained.
type EventBus struct {
	mu          sync.RWMutex
	subscribers map[string][]chan any
	closed      bool
}

// NewEventBus returns a new, ready-to-use bus.
func NewEventBus() *EventBus {
	return &EventBus{
		subscribers: make(map[string][]chan any),
	}
}

// Publish pushes a message onto the bus under the given topic.
func (b *EventBus) Publish(topic string, msg any) {
	b.mu.RLock()
	defer b.mu.RUnlock()

	if b.closed {
		return
	}
	for _, ch := range b.subscribers[topic] {
		// Non-blocking send to avoid slow consumer poisoning the publisher.
		select {
		case ch <- msg:
		default:
		}
	}
}

// Subscribe creates a new channel subscription for a topic.
func (b *EventBus) Subscribe(topic string, buf int) (<-chan any, func()) {
	ch := make(chan any, buf)

	b.mu.Lock()
	defer b.mu.Unlock()
	if b.closed {
		close(ch)
		return ch, func() {}
	}

	b.subscribers[topic] = append(b.subscribers[topic], ch)

	// Unsubscribe closure.
	return ch, func() {
		b.mu.Lock()
		defer b.mu.Unlock()
		for i, sub := range b.subscribers[topic] {
			if sub == ch {
				b.subscribers[topic] = append(b.subscribers[topic][:i], b.subscribers[topic][i+1:]...)
				break
			}
		}
		close(ch)
	}
}

// Close terminates the bus, closing all subscriber channels.
func (b *EventBus) Close() {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.closed {
		return
	}
	for _, subs := range b.subscribers {
		for _, ch := range subs {
			close(ch)
		}
	}
	b.closed = true
}

/* ----------------------------------------------------------------------
   Pipeline Stage – HealthScoringProcessor
---------------------------------------------------------------------- */

// HealthScoringProcessor orchestrates concurrent scoring of SocialEvents using
// a selected ScoreStrategy.  Results are emitted to the EventBus for further
// handling (aggregation, monitoring, alerting).
type HealthScoringProcessor struct {
	bus      *EventBus
	strategy ScoreStrategy
	workers  int
	in       <-chan SocialEvent
	topicOut string

	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
}

// HealthScoringConfig parameterises a new processor.
type HealthScoringConfig struct {
	Bus          *EventBus
	StrategyName string
	Workers      int
	Inbound      <-chan SocialEvent
	Outbound     string // topic to publish ScoreEvents to
}

// NewHealthScoringProcessor builds and starts the processor.
func NewHealthScoringProcessor(cfg HealthScoringConfig) (*HealthScoringProcessor, error) {
	if cfg.Bus == nil {
		return nil, errors.New("pipeline: nil EventBus supplied to HealthScoringProcessor")
	}
	if cfg.Workers <= 0 {
		cfg.Workers = 1
	}
	if cfg.Inbound == nil {
		return nil, errors.New("pipeline: inbound channel is nil")
	}
	if cfg.Outbound == "" {
		cfg.Outbound = "score_events"
	}

	strategy, err := GetScoreStrategy(cfg.StrategyName)
	if err != nil {
		return nil, err
	}

	ctx, cancel := context.WithCancel(context.Background())
	p := &HealthScoringProcessor{
		bus:      cfg.Bus,
		strategy: strategy,
		workers:  cfg.Workers,
		in:       cfg.Inbound,
		topicOut: cfg.Outbound,
		ctx:      ctx,
		cancel:   cancel,
	}

	p.start()
	return p, nil
}

// start spins up worker goroutines that perform the scoring.
func (p *HealthScoringProcessor) start() {
	for i := 0; i < p.workers; i++ {
		p.wg.Add(1)
		go p.worker(i)
	}
}

// Stop signals the processor to drain and waits for workers to exit.
func (p *HealthScoringProcessor) Stop() {
	p.cancel()
	p.wg.Wait()
}

func (p *HealthScoringProcessor) worker(workerID int) {
	defer p.wg.Done()

	for {
		select {
		case <-p.ctx.Done():
			return
		case evt, ok := <-p.in:
			if !ok {
				return
			}

			score, err := p.strategy.Evaluate(p.ctx, evt)
			if err != nil {
				// In production, we'd forward an error event or increment metrics.
				continue
			}

			sev := ScoreEvent{
				SocialEventID: evt.ID,
				Score:         score,
				Strategy:      p.strategy.Name(),
				Timestamp:     time.Now().UTC(),
			}
			p.bus.Publish(p.topicOut, sev)
		}
	}
}

/* ----------------------------------------------------------------------
   Rolling Aggregator – Community Health Metric
---------------------------------------------------------------------- */

// RollingHealthAggregator subscribes to ScoreEvents and maintains an EWMA of
// recent community health, exposing it for dashboards & adaptive feedback.
type RollingHealthAggregator struct {
	alpha      float64 // smoothing factor ∈ (0,1]
	current    float64 // last EWMA
	init       bool
	topic      string
	cancelFunc func()
	mu         sync.RWMutex
}

// NewRollingHealthAggregator returns a new aggregator wired into the bus.  The
// aggregator starts immediately; call Stop() to detach.
func NewRollingHealthAggregator(bus *EventBus, topic string, alpha float64) *RollingHealthAggregator {
	if alpha <= 0 || alpha > 1 {
		alpha = 0.3 // sane default
	}
	sub, unsubscribe := bus.Subscribe(topic, 1024)
	agg := &RollingHealthAggregator{
		alpha:      alpha,
		topic:      topic,
		cancelFunc: unsubscribe,
	}

	go agg.loop(sub)
	return agg
}

// Stop detaches the aggregator from the bus.
func (a *RollingHealthAggregator) Stop() {
	a.cancelFunc()
}

func (a *RollingHealthAggregator) loop(ch <-chan any) {
	for msg := range ch {
		ev, ok := msg.(ScoreEvent)
		if !ok {
			continue
		}
		a.ingest(ev.Score)
	}
}

func (a *RollingHealthAggregator) ingest(score float64) {
	a.mu.Lock()
	defer a.mu.Unlock()

	if !a.init {
		a.current = score
		a.init = true
		return
	}
	a.current = (a.alpha * score) + ((1.0 - a.alpha) * a.current)
}

// CurrentScore returns the latest EWMA health score.
func (a *RollingHealthAggregator) CurrentScore() float64 {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.current
}
```