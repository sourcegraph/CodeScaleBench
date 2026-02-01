```go
// Code generated for EchoPulse — Real-Time Social Signal Processing Platform.
// File: src/module_66.go
//
// Package realtime provides a windowed community-health scoring service that
// consumes SocialEvent messages from the event bus (NATS JetStream), performs
// lightweight aggregation over a sliding time window, and publishes
// HealthScoreEvent messages back onto the bus.
//
// The module demonstrates several production-grade patterns:
//   • Context-aware lifecycle management
//   • Functional-options configuration
//   • Thread-safe, lock-based sliding window
//   • Decoupled scoring strategy via an interface
//   • Robust JSON (un)marshalling with error surfaces
//   • Structured logging
//
// The public entry point is NewHealthScoreProcessor; start the processor with
// ctx, and cancel the ctx to shut it down gracefully.
package realtime

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/nats-io/nats.go"
)

// -----------------------------------------------
// Canonical message representations
// -----------------------------------------------

// SocialEvent is the canonical representation of a user-generated artifact
// (text, emoji, reaction, audio transcript, …) after fan-in by upstream
// ingestion pipelines.
type SocialEvent struct {
	ID          string    `json:"id"`
	CommunityID string    `json:"community_id"`
	CreatedAt   time.Time `json:"created_at"`

	// Pre-computed low-level features
	Sentiment float64 `json:"sentiment"` // −1.0 (neg) … +1.0 (pos)
	Toxicity  float64 `json:"toxicity"`  //  0.0 (clean) … +1.0 (toxic)

	// Additional features (redacted)
	// …
}

// HealthScoreEvent is produced by this module and expresses an aggregated
// health score for a community within a given time window.
type HealthScoreEvent struct {
	CommunityID string    `json:"community_id"`
	Score       float64   `json:"score"`
	WindowStart time.Time `json:"window_start"`
	WindowEnd   time.Time `json:"window_end"`
	GeneratedAt time.Time `json:"generated_at"`
	Version     string    `json:"version"` // schema version
}

// -----------------------------------------------
// Sliding Window — in-memory, lock-based
// -----------------------------------------------

type slidingWindow struct {
	windowSize time.Duration

	mu     sync.RWMutex
	events map[string][]SocialEvent // keyed by CommunityID
}

func newSlidingWindow(size time.Duration) *slidingWindow {
	return &slidingWindow{
		windowSize: size,
		events:     make(map[string][]SocialEvent),
	}
}

// add inserts e into the window, discarding events that fall out of range.
func (w *slidingWindow) add(e SocialEvent) {
	cutoff := time.Now().Add(-w.windowSize)

	w.mu.Lock()
	defer w.mu.Unlock()

	evts := append(w.events[e.CommunityID], e)
	// Compaction: drop old events per community.
	var fresh []SocialEvent
	for _, evt := range evts {
		if evt.CreatedAt.After(cutoff) {
			fresh = append(fresh, evt)
		}
	}
	w.events[e.CommunityID] = fresh
}

// snapshot returns a copy of the current window for processing. Caller owns it.
func (w *slidingWindow) snapshot() map[string][]SocialEvent {
	w.mu.RLock()
	defer w.mu.RUnlock()

	out := make(map[string][]SocialEvent, len(w.events))
	for community, evts := range w.events {
		clone := make([]SocialEvent, len(evts))
		copy(clone, evts)
		out[community] = clone
	}
	return out
}

// -----------------------------------------------
// Scoring Strategy
// -----------------------------------------------

// ScoreCalculator converts a slice of SocialEvents into a holistic health score
// for a community. Implementations are hot-swappable at runtime.
type ScoreCalculator interface {
	Score(events []SocialEvent) (float64, error)
}

// DefaultScoreCalculator is a naive linear blend of sentiment & toxicity.
type DefaultScoreCalculator struct{}

// Score returns a value in range [0,1], higher means healthier community.
func (c DefaultScoreCalculator) Score(events []SocialEvent) (float64, error) {
	if len(events) == 0 {
		return 0, errors.New("no events to score")
	}

	var sentimentSum, toxicitySum float64
	for _, e := range events {
		sentimentSum += e.Sentiment + 1 // shift to [0,2]
		toxicitySum += (1 - e.Toxicity) // invert toxicity so higher is better
	}
	n := float64(len(events))
	score := 0.5*((sentimentSum/n)/2) + 0.5*(toxicitySum/n) // smooth blend

	if score < 0 {
		score = 0
	}
	if score > 1 {
		score = 1
	}
	return score, nil
}

// -----------------------------------------------
// Processor Configuration
// -----------------------------------------------

// HealthScoreProcessor ingests SocialEvents, maintains a sliding window, and
// periodically publishes HealthScoreEvents.
type HealthScoreProcessor struct {
	log *slog.Logger

	// bus handles
	nc      *nats.Conn
	js      nats.JetStreamContext
	subject string // SocialEvent in
	target  string // HealthScoreEvent out

	// domain
	window     *slidingWindow
	calculator ScoreCalculator

	// runtime
	flushInterval time.Duration
	maxPending    int
}

// Option configures a HealthScoreProcessor.
type Option func(*HealthScoreProcessor) error

// WithCalculator injects a custom ScoreCalculator.
func WithCalculator(c ScoreCalculator) Option {
	return func(p *HealthScoreProcessor) error {
		if c == nil {
			return errors.New("nil calculator")
		}
		p.calculator = c
		return nil
	}
}

// WithFlushInterval overrides the default flush interval.
func WithFlushInterval(d time.Duration) Option {
	return func(p *HealthScoreProcessor) error {
		if d <= 0 {
			return errors.New("flush interval must be positive")
		}
		p.flushInterval = d
		return nil
	}
}

// WithLogger sets a custom slog.Logger.
func WithLogger(l *slog.Logger) Option {
	return func(p *HealthScoreProcessor) error {
		if l == nil {
			return errors.New("nil logger")
		}
		p.log = l
		return nil
	}
}

// NewHealthScoreProcessor wires everything together.
//   - nc: an established NATS connection
//   - js: JetStream context (may be nil; raw publish will be used instead)
//   - opts: functional options
func NewHealthScoreProcessor(
	nc *nats.Conn,
	js nats.JetStreamContext,
	opts ...Option,
) (*HealthScoreProcessor, error) {
	if nc == nil {
		return nil, errors.New("nats connection cannot be nil")
	}

	p := &HealthScoreProcessor{
		log:           slog.Default(),
		nc:            nc,
		js:            js,
		subject:       "social.event.*",
		target:        "health.score",
		window:        newSlidingWindow(5 * time.Minute),
		calculator:    DefaultScoreCalculator{},
		flushInterval: 30 * time.Second,
		maxPending:    4096,
	}

	for _, opt := range opts {
		if err := opt(p); err != nil {
			return nil, err
		}
	}
	return p, nil
}

// -----------------------------------------------
// Life-cycle
// -----------------------------------------------

// Start subscribes to the event bus and starts the flush loop.
// It blocks until ctx is canceled or an unrecoverable error occurs.
func (p *HealthScoreProcessor) Start(ctx context.Context) error {
	// Buffered channel helps decouple bus I/O from window updates.
	ingestCh := make(chan *nats.Msg, p.maxPending)

	// Subscription — push each message onto the ingest channel.
	sub, err := p.nc.ChanSubscribe(p.subject, ingestCh)
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	defer sub.Unsubscribe()

	p.log.Info("health-score processor started",
		slog.String("consume_subject", p.subject),
		slog.String("publish_subject", p.target))

	// Flush ticker
	ticker := time.NewTicker(p.flushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			p.log.Info("health-score processor shutting down")
			return nil

		case msg := <-ingestCh:
			p.handleMessage(msg)

		case <-ticker.C:
			if err := p.flushWindow(); err != nil {
				p.log.Error("flush error", slog.Any("err", err))
			}
		}
	}
}

// -----------------------------------------------
// Internal helpers
// -----------------------------------------------

func (p *HealthScoreProcessor) handleMessage(msg *nats.Msg) {
	var evt SocialEvent
	if err := json.Unmarshal(msg.Data, &evt); err != nil {
		p.log.Warn("discarding invalid SocialEvent",
			slog.Any("err", err),
			slog.ByteString("payload", msg.Data))
		return
	}
	p.window.add(evt)
}

func (p *HealthScoreProcessor) flushWindow() error {
	snap := p.window.snapshot()
	now := time.Now()

	for communityID, events := range snap {
		score, err := p.calculator.Score(events)
		if err != nil {
			p.log.Warn("score calculation failed",
				slog.String("community", communityID),
				slog.Any("err", err))
			continue
		}

		out := HealthScoreEvent{
			CommunityID: communityID,
			Score:       score,
			WindowStart: now.Add(-p.window.windowSize),
			WindowEnd:   now,
			GeneratedAt: now,
			Version:     "v1",
		}
		if err := p.publish(out); err != nil {
			p.log.Error("publish failed",
				slog.String("community", communityID),
				slog.Any("err", err))
		}
	}
	return nil
}

func (p *HealthScoreProcessor) publish(evt HealthScoreEvent) error {
	data, err := json.Marshal(evt)
	if err != nil {
		return fmt.Errorf("json encode: %w", err)
	}

	if p.js != nil {
		_, err = p.js.Publish(p.target, data)
	} else {
		err = p.nc.Publish(p.target, data)
	}
	if err != nil {
		return fmt.Errorf("nats publish: %w", err)
	}
	p.log.Debug("health score published",
		slog.String("community", evt.CommunityID),
		slog.Float64("score", evt.Score))
	return nil
}
```