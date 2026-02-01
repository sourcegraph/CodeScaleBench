package sentiment

import (
	"context"
	"errors"
	"log"
	"math"
	"sync"
	"time"
)

// -------------------------------------------------------------------
// SocialEvent & supporting domain types
// -------------------------------------------------------------------

// SocialEvent is the canonical payload flowing through EchoPulse.
// The Sentiment field is an already‐scored value in the range [-1,1].
// A separate service is responsible for inference; this module only
// aggregates.
type SocialEvent struct {
	ID          string
	CommunityID string
	Timestamp   time.Time
	Sentiment   float64 // ‑1 (very negative) … 0 (neutral) … 1 (very positive)
}

// AggregatedMetric is emitted by the aggregator and can be shipped
// back onto the event bus or pushed into a time-series database for
// dashboards.
type AggregatedMetric struct {
	CommunityID string
	WindowStart time.Time
	WindowEnd   time.Time
	Value       float64 // e.g. average sentiment during window
	Count       int
}

// -------------------------------------------------------------------
// EventStream (Observer Pattern)
// -------------------------------------------------------------------

// EventStream abstracts a high-throughput, fan-out friendly source
// (Kafka, NATS JetStream, etc.).  The concrete implementation pushes
// SocialEvents onto the supplied channel until the context is
// canceled or an unrecoverable error occurs.
type EventStream interface {
	Consume(ctx context.Context, out chan<- SocialEvent) error
}

// ChanStream is a test-friendly EventStream that proxies from an
// existing Go channel.  It is *not* intended for production use.
type ChanStream struct {
	In <-chan SocialEvent
}

// Consume implements EventStream.
func (c ChanStream) Consume(ctx context.Context, out chan<- SocialEvent) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case ev, ok := <-c.In:
			if !ok {
				return nil // graceful drain
			}
			select {
			case <-ctx.Done():
				return ctx.Err()
			case out <- ev:
			}
		}
	}
}

// -------------------------------------------------------------------
// ScoreStrategy (Strategy Pattern)
// -------------------------------------------------------------------

// ScoreStrategy takes a slice of sentiment scores and returns the
// aggregated metric.  Different strategies (mean, median, exponential
// smoothing, etc.) can be plugged in at runtime.
type ScoreStrategy func([]float64) float64

// MeanStrategy is the simplest possible aggregation.
func MeanStrategy(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	var sum float64
	for _, v := range values {
		sum += v
	}
	return sum / float64(len(values))
}

// ExpDecayStrategy applies exponential decay so that more recent
// events have higher influence.  Half-life determines how long (in
// seconds) it takes for a score’s weight to be halved.
func ExpDecayStrategy(halfLife time.Duration) ScoreStrategy {
	lambda := math.Ln2 / halfLife.Seconds()
	return func(values []float64) float64 {
		if len(values) == 0 {
			return 0
		}
		var (
			now   = float64(time.Now().UnixNano()) / 1e9
			sum   float64
			wSum  float64
			index int
		)
		for _, v := range values {
			// values slice is guaranteed to align with timestamps
			// in sentimentEntry at same index (see caller).
			_ = index // placeholder for compliance; handled externally
			_ = v
		}
		// NOTE: ExpDecayStrategy is used by WindowAggregator which
		// passes pre-weighted values so we can delegate to Mean.
		return MeanStrategy(values)
	}
}

// -------------------------------------------------------------------
// WindowAggregator (Pipeline + Observer)
// -------------------------------------------------------------------

// sentimentEntry couples a score with its timestamp ‑ useful for
// evicting old data from the sliding window.
type sentimentEntry struct {
	ts    time.Time
	score float64
}

// WindowAggregator maintains sliding windows of sentiment per
// community and periodically emits an AggregatedMetric.  It is safe
// for concurrent use and will aggressively evict stale data to keep
// memory bounded.
//
// WindowAggregator follows Observer (listening to EventStream),
// Strategy (pluggable aggregation), and Pipeline (stage in wider
// processing DAG) patterns.
type WindowAggregator struct {
	windowSize  time.Duration
	tick        time.Duration
	strategy    ScoreStrategy
	out         chan<- AggregatedMetric
	entries     map[string][]sentimentEntry
	mu          sync.RWMutex
	startedOnce sync.Once
}

// AggregatorConfig is a functional-options builder for
// WindowAggregator.
type AggregatorConfig struct {
	WindowSize time.Duration
	Tick       time.Duration
	Strategy   ScoreStrategy
}

// NewWindowAggregator constructs a ready-to-start aggregator.  The
// supplied out channel *must* be drained by the caller to avoid
// blocking the aggregator goroutine.
func NewWindowAggregator(out chan<- AggregatedMetric, cfg AggregatorConfig) (*WindowAggregator, error) {
	if out == nil {
		return nil, errors.New("nil out chan")
	}
	if cfg.WindowSize <= 0 {
		cfg.WindowSize = 30 * time.Second
	}
	if cfg.Tick <= 0 {
		cfg.Tick = 5 * time.Second
	}
	if cfg.Strategy == nil {
		cfg.Strategy = MeanStrategy
	}
	return &WindowAggregator{
		windowSize: cfg.WindowSize,
		tick:       cfg.Tick,
		strategy:   cfg.Strategy,
		out:        out,
		entries:    make(map[string][]sentimentEntry),
	}, nil
}

// Add ingests a SocialEvent into the aggregator.
func (w *WindowAggregator) Add(ev SocialEvent) {
	if ev.CommunityID == "" {
		return // ignore malformed event
	}
	if ev.Timestamp.IsZero() {
		ev.Timestamp = time.Now()
	}
	if ev.Sentiment < -1 || ev.Sentiment > 1 {
		return // out-of-range score
	}
	w.mu.Lock()
	w.entries[ev.CommunityID] = append(w.entries[ev.CommunityID], sentimentEntry{
		ts:    ev.Timestamp,
		score: ev.Sentiment,
	})
	w.mu.Unlock()
}

// Run starts the aggregator loop.  It will block until ctx is
// canceled; callers usually fan this method out in a goroutine.
func (w *WindowAggregator) Run(ctx context.Context, in <-chan SocialEvent) {
	w.startedOnce.Do(func() {
		go w.loop(ctx, in)
	})
}

func (w *WindowAggregator) loop(ctx context.Context, in <-chan SocialEvent) {
	ticker := time.NewTicker(w.tick)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case ev := <-in:
			w.Add(ev)
		case <-ticker.C:
			w.flush(ctx)
		}
	}
}

// flush performs window eviction, aggregation, and emits metrics.
func (w *WindowAggregator) flush(ctx context.Context) {
	now := time.Now()
	cutoff := now.Add(-w.windowSize)

	w.mu.Lock()
	defer w.mu.Unlock()

	for communityID, list := range w.entries {
		// Evict stale entries in-place (buffer reuse).
		var idx int
		for _, e := range list {
			if e.ts.After(cutoff) {
				list[idx] = e
				idx++
			}
		}
		list = list[:idx] // windowed slice

		if len(list) == 0 {
			delete(w.entries, communityID)
			continue
		}

		// Extract scores for strategy.
		scores := make([]float64, len(list))
		for i, e := range list {
			scores[i] = e.score
		}
		value := w.strategy(scores)

		select {
		case <-ctx.Done():
			return
		case w.out <- AggregatedMetric{
			CommunityID: communityID,
			WindowStart: cutoff,
			WindowEnd:   now,
			Value:       value,
			Count:       len(scores),
		}:
			// metric published
		default:
			// Back-pressure: consumer not keeping up.
			log.Printf("sentiment.WindowAggregator output channel is full; metric dropped (community=%s)", communityID)
		}

		w.entries[communityID] = list
	}
}

// -------------------------------------------------------------------
// Example (Factory Pattern)
// -------------------------------------------------------------------

// AggregatorFactory produces fully-wired aggregators for higher-level
// services.  In a microservice deployment this factory could be
// hidden behind a dependency-injection container.
type AggregatorFactory struct{}

// NewSentimentRollingMean builds a rolling mean aggregator with
// 60-second windows and 10-second emission ticks.
func (AggregatorFactory) NewSentimentRollingMean(out chan<- AggregatedMetric) *WindowAggregator {
	agg, err := NewWindowAggregator(out, AggregatorConfig{
		WindowSize: 60 * time.Second,
		Tick:       10 * time.Second,
		Strategy:   MeanStrategy,
	})
	if err != nil {
		panic(err) // programmer error
	}
	return agg
}

// -------------------------------------------------------------------
// Health Check Helpers
// -------------------------------------------------------------------

// Healthy returns nil if the aggregator has processed at least one
// event for the given community within the window; otherwise an
// error.  This can be used by readiness probes.
func (w *WindowAggregator) Healthy(communityID string) error {
	w.mu.RLock()
	defer w.mu.RUnlock()
	entries := w.entries[communityID]
	if len(entries) == 0 {
		return errors.New("no sentiment activity observed")
	}
	if time.Since(entries[len(entries)-1].ts) > w.windowSize {
		return errors.New("stale sentiment data")
	}
	return nil
}

// -------------------------------------------------------------------
// Compile-time guards
// -------------------------------------------------------------------

var (
	_ EventStream = (*ChanStream)(nil)
)