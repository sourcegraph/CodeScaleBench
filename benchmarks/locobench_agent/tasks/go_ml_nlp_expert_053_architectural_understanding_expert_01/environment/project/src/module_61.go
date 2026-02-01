```go
// File: src/module_61.go
//
// EchoPulse – Real-Time Social Signal Processing Platform
// Module: Community Sentiment Aggregator
//
// Description:
//   Listens to the “social.events.sentiment” NATS JetStream subject for
//   per-message sentiment scores.  For each community it maintains a rolling
//   aggregation (EWMA or Sliding-Window) to calculate a “community-health”
//   score, which is then re-published to “social.events.community-health” so
//   that other downstream services (dashboards, moderation bots, alerting
//   rules, etc.) can react in near-real-time.
//
//   The module showcases the Strategy, Pipeline, and Observer patterns and is
//   instrumented with Prometheus metrics for easy monitoring.
//

package aggregator

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"sync"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/prometheus/client_golang/prometheus"
)

// -----------------------------------------------------------------------------
// Configuration & DTOs
// -----------------------------------------------------------------------------

// Config drives runtime behaviour of the Aggregator.
type Config struct {
	// NATS connectivity
	NATSUrl       string
	Stream        string
	ConsumerName  string
	SubscribeSubj string
	PublishSubj   string

	// Aggregation parameters
	Strategy   string        // "ewma" | "window"
	Alpha      float64       // EWMA smoothing factor (0,1]
	WindowSize time.Duration // Sliding-window width

	// General
	Prefetch int           // Max in-flight messages
	Shutdown time.Duration // Maximum graceful-shutdown time
}

// SocialEvent is the canonical input event published by upstream NLP pipeline.
type SocialEvent struct {
	MessageID   string    `json:"message_id"`
	CommunityID string    `json:"community_id"`
	Sentiment   float64   `json:"sentiment"` // normalized ­1 .. +1
	OccurredAt  time.Time `json:"occurred_at"`
}

// CommunityHealthEvent represents the aggregated health score output.
type CommunityHealthEvent struct {
	CommunityID string    `json:"community_id"`
	HealthScore float64   `json:"health_score"`
	Window      string    `json:"window"`
	UpdatedAt   time.Time `json:"updated_at"`
	Version     int       `json:"version"`
}

// -----------------------------------------------------------------------------
// Aggregation Strategy (Strategy Pattern)
// -----------------------------------------------------------------------------

// AggregationStrategy defines how incremental sentiment updates are combined
// into a single community-level health score.
type AggregationStrategy interface {
	Update(commID string, val float64, ts time.Time) (score float64)
}

// ---------------------- EWMA Strategy ----------------------------------------

// ewmaStrategy implements an Exponentially Weighted Moving Average with decay
// factor α.  Lower α “remembers” the past longer.
type ewmaStrategy struct {
	alpha float64
	mu    sync.RWMutex
	state map[string]float64
}

func newEWMA(alpha float64) (*ewmaStrategy, error) {
	if alpha <= 0 || alpha > 1 {
		return nil, errors.New("alpha must be 0 < α ≤ 1")
	}
	return &ewmaStrategy{
		alpha: alpha,
		state: make(map[string]float64),
	}, nil
}

func (e *ewmaStrategy) Update(commID string, val float64, _ time.Time) float64 {
	e.mu.Lock()
	defer e.mu.Unlock()

	prev := e.state[commID]
	next := e.alpha*val + (1.0-e.alpha)*prev
	e.state[commID] = next
	return next
}

// ---------------------- Sliding Window Strategy ------------------------------

type dataPoint struct {
	v  float64
	ts time.Time
}

type windowStrategy struct {
	window time.Duration
	mu     sync.RWMutex
	buf    map[string][]dataPoint
}

func newWindow(window time.Duration) *windowStrategy {
	return &windowStrategy{
		window: window,
		buf:    make(map[string][]dataPoint),
	}
}

func (w *windowStrategy) Update(commID string, val float64, ts time.Time) float64 {
	w.mu.Lock()
	defer w.mu.Unlock()

	points := append(w.buf[commID], dataPoint{v: val, ts: ts})

	// Drop points outside window
	cut := ts.Add(-w.window)
	idx := 0
	for idx < len(points) && points[idx].ts.Before(cut) {
		idx++
	}
	points = points[idx:]
	w.buf[commID] = points

	// Compute mean
	var sum float64
	for _, p := range points {
		sum += p.v
	}
	return sum / float64(len(points))
}

// -----------------------------------------------------------------------------
// Prometheus Metrics
// -----------------------------------------------------------------------------

var (
	metricProcessed = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "echopulse_sentiment_processed_total",
			Help: "Total sentiment events processed",
		}, []string{"strategy"},
	)
	metricFailed = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "echopulse_sentiment_failed_total",
			Help: "Total sentiment events that failed processing",
		}, []string{"cause"},
	)
	metricPublished = prometheus.NewCounter(
		prometheus.CounterOpts{
			Name: "echopulse_community_health_published_total",
			Help: "Total community-health events published",
		},
	)
)

func init() {
	prometheus.MustRegister(metricProcessed, metricFailed, metricPublished)
}

// -----------------------------------------------------------------------------
// Aggregator Service
// -----------------------------------------------------------------------------

// Aggregator consumes sentiment events, aggregates them, and publishes
// community-health events.
type Aggregator struct {
	cfg       Config
	nc        *nats.Conn
	js        nats.JetStreamContext
	sub       *nats.Subscription
	strategy  AggregationStrategy
	stopOnce  sync.Once
	stoppedCh chan struct{}
}

// NewAggregator sets up all external resources but does NOT start consuming.
func NewAggregator(cfg Config) (*Aggregator, error) {
	if cfg.SubscribeSubj == "" || cfg.PublishSubj == "" {
		return nil, errors.New("subscribe and publish subjects must be provided")
	}

	// Initialize strategy
	var strat AggregationStrategy
	var err error
	switch cfg.Strategy {
	case "ewma", "":
		alpha := cfg.Alpha
		if alpha == 0 {
			alpha = 0.2
		}
		strat, err = newEWMA(alpha)
	case "window":
		if cfg.WindowSize == 0 {
			cfg.WindowSize = 5 * time.Minute
		}
		strat = newWindow(cfg.WindowSize)
	default:
		return nil, fmt.Errorf("unknown strategy: %s", cfg.Strategy)
	}
	if err != nil {
		return nil, err
	}

	// Connect to NATS
	nc, err := nats.Connect(cfg.NATSUrl,
		nats.MaxReconnects(-1),
		nats.ReconnectWait(2*time.Second),
	)
	if err != nil {
		return nil, fmt.Errorf("connect nats: %w", err)
	}

	js, err := nc.JetStream()
	if err != nil {
		_ = nc.Drain()
		return nil, fmt.Errorf("jetstream: %w", err)
	}

	// Configure pull consumer
	sub, err := js.PullSubscribe(cfg.SubscribeSubj, cfg.ConsumerName,
		nats.BindStream(cfg.Stream),
		nats.ManualAck(),
		nats.MaxAckPending(cfg.Prefetch),
	)
	if err != nil {
		_ = nc.Drain()
		return nil, fmt.Errorf("pull subscribe: %w", err)
	}

	return &Aggregator{
		cfg:       cfg,
		nc:        nc,
		js:        js,
		sub:       sub,
		strategy:  strat,
		stoppedCh: make(chan struct{}),
	}, nil
}

// Run starts consuming messages until context cancellation or fatal error.
func (a *Aggregator) Run(ctx context.Context) error {
	defer close(a.stoppedCh)
	defer a.nc.Drain()

	batch := a.cfg.Prefetch
	if batch <= 0 {
		batch = 256
	}

	for {
		select {
		case <-ctx.Done():
			log.Println("aggregator: context cancelled")
			return nil
		default:
		}

		msgs, err := a.sub.Fetch(batch, nats.MaxWait(2*time.Second))
		if err != nil && !errors.Is(err, nats.ErrTimeout) {
			metricFailed.WithLabelValues("fetch").Inc()
			log.Printf("aggregator: fetch error: %v", err)
			continue
		}

		for _, msg := range msgs {
			if err := a.handleMsg(ctx, msg); err != nil {
				metricFailed.WithLabelValues("process").Inc()
				log.Printf("aggregator: processing error: %v", err)
				_ = msg.Term()
			} else {
				_ = msg.Ack()
			}
		}
	}
}

// handleMsg deserializes the input event, updates aggregation, and publishes
// a new community-health event.
func (a *Aggregator) handleMsg(ctx context.Context, msg *nats.Msg) error {
	var ev SocialEvent
	if err := json.Unmarshal(msg.Data, &ev); err != nil {
		return fmt.Errorf("unmarshal social event: %w", err)
	}
	metricProcessed.WithLabelValues(a.cfg.Strategy).Inc()

	score := a.strategy.Update(ev.CommunityID, ev.Sentiment, ev.OccurredAt)

	health := CommunityHealthEvent{
		CommunityID: ev.CommunityID,
		HealthScore: score,
		Window:      a.cfg.Strategy,
		UpdatedAt:   time.Now().UTC(),
		Version:     1,
	}

	raw, err := json.Marshal(&health)
	if err != nil {
		return fmt.Errorf("marshal community health: %w", err)
	}

	// Publish with context for timeout handling.
	pubCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	if err := a.js.PublishMsgAsync(&nats.Msg{
		Subject: a.cfg.PublishSubj,
		Data:    raw,
	}, nats.Context(pubCtx)); err != nil {
		return fmt.Errorf("publish: %w", err)
	}
	metricPublished.Inc()
	return nil
}

// Stop gracefully stops Run().  It is idempotent.
func (a *Aggregator) Stop() {
	a.stopOnce.Do(func() {
		a.nc.Drain()
		<-a.stoppedCh
	})
}
```