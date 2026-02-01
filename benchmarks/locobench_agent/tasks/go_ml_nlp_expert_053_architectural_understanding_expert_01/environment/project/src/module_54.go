package module_54

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

// NOTE: All identifiers in this file are intentionally scoped to the
//       `module_54` package to avoid name–collision across the large
//       EchoPulse code-base.  The module owns a self-contained domain:
//       real-time community-health scoring.

// -----------------------------------------------------------------------------
// Event & Domain Types
// -----------------------------------------------------------------------------

// SocialEvent is a canonical representation of any user-generated artifact
// flowing through EchoPulse.  Down-stream services (sentiment, toxicity, etc.)
// decorate it with additional attributes; we only need a subset here.
type SocialEvent struct {
	ID           string            `json:"id"`
	UserID       string            `json:"user_id"`
	ChannelID    string            `json:"channel_id"`
	Payload      json.RawMessage   `json:"payload"`       // raw content
	Extracted    map[string]any    `json:"extracted"`     // enriched features
	CreatedAtUTC time.Time         `json:"created_at_utc"`// event time
	Metadata     map[string]string `json:"metadata"`      // transport metadata
}

// HealthScore is emitted after aggregating a batch/window of SocialEvents.
type HealthScore struct {
	ChannelID string    `json:"channel_id"`
	Score     float64   `json:"score"`
	Timestamp time.Time `json:"timestamp_utc"`
	Version   string    `json:"version"` // scoring strategy version
}

// -----------------------------------------------------------------------------
// Configuration
// -----------------------------------------------------------------------------

// ScorerConfig is a runtime configuration structure for CommunityScorer.
type ScorerConfig struct {
	WindowSize               time.Duration // sliding window size
	WindowSlide              time.Duration // slide interval
	MaxPendingEvents         int           // back-pressure bound
	ModelVersion             string        // strategy version tag
	PublishPartialWindows    bool          // allow partials on graceful shutdown
	GracefulShutdownTimeout  time.Duration // across pipelines
}

// validate ensures all required fields are sane.
func (c ScorerConfig) validate() error {
	var errs []string
	if c.WindowSize <= 0 {
		errs = append(errs, "WindowSize must be > 0")
	}
	if c.WindowSlide <= 0 {
		errs = append(errs, "WindowSlide must be > 0")
	}
	if c.MaxPendingEvents <= 0 {
		errs = append(errs, "MaxPendingEvents must be > 0")
	}
	if len(errs) > 0 {
		return errors.New("invalid ScorerConfig: " + joinErr(errs))
	}
	return nil
}

func joinErr(ss []string) string {
	switch len(ss) {
	case 0:
		return ""
	case 1:
		return ss[0]
	default:
		out := ""
		for i, s := range ss {
			out += s
			if i != len(ss)-1 {
				out += ", "
			}
		}
		return out
	}
}

// -----------------------------------------------------------------------------
// Event Bus Abstraction
// -----------------------------------------------------------------------------

// EventBusSubscriber abstracts NATS JetStream, Kafka, etc.
type EventBusSubscriber interface {
	Subscribe(ctx context.Context, topic string) (<-chan SocialEvent, error)
}

// EventBusPublisher abstracts producers for HealthScore results.
type EventBusPublisher interface {
	Publish(ctx context.Context, topic string, msg HealthScore) error
}

// -----------------------------------------------------------------------------
// Strategy Pattern for Health Scoring
// -----------------------------------------------------------------------------

// HealthScoreStrategy encapsulates the algorithm that converts aggregated
// features into a scalar community-health score.
type HealthScoreStrategy interface {
	Compute(window []SocialEvent) (score float64, err error)
	Version() string
}

// WeightedHeuristicsStrategy is a simple, fast, interpretable implementation
// of HealthScoreStrategy.  In production we also ship transformer-based models.
type WeightedHeuristicsStrategy struct {
	weights map[string]float64 // feature -> weight
}

// NewWeightedHeuristicsStrategy returns an opinionated default.
func NewWeightedHeuristicsStrategy() *WeightedHeuristicsStrategy {
	return &WeightedHeuristicsStrategy{
		weights: map[string]float64{
			"sentiment.pos":  +0.6,
			"sentiment.neg":  -0.8,
			"toxicity":       -1.0,
			"engagement":     +0.3,
			"stance.polar":   -0.5,
			"wellness":       +0.4,
			"question_ratio": +0.2,
		},
	}
}

// Version returns a semantic version string—bump when logic changes.
func (w *WeightedHeuristicsStrategy) Version() string { return "weighted-h1.3.4" }

// Compute implements the scoring formula.
// NOTE: It is intentionally simple yet non-trivial for demo purposes.
func (w *WeightedHeuristicsStrategy) Compute(window []SocialEvent) (float64, error) {
	if len(window) == 0 {
		return math.NaN(), errors.New("empty window")
	}

	var acc, totalWeight float64
	for _, evt := range window {
		for k, weight := range w.weights {
			if vAny, ok := evt.Extracted[k]; ok {
				if v, ok := castFloat(vAny); ok {
					acc += v * weight
					totalWeight += math.Abs(weight)
				}
			}
		}
	}

	if totalWeight == 0 {
		return 0, nil
	}
	// Normalize to [-1, 1] for interpretability.
	return clamp(acc/totalWeight, -1.0, 1.0), nil
}

func castFloat(v any) (float64, bool) {
	switch t := v.(type) {
	case float64:
		return t, true
	case float32:
		return float64(t), true
	case int64:
		return float64(t), true
	case int32:
		return float64(t), true
	case int:
		return float64(t), true
	default:
		return 0, false
	}
}

func clamp(val, min, max float64) float64 {
	if val < min {
		return min
	}
	if val > max {
		return max
	}
	return val
}

// -----------------------------------------------------------------------------
// Windowed Event Aggregator
// -----------------------------------------------------------------------------

// windowBucket holds events that fall into the bucket's time-range.
type windowBucket struct {
	from time.Time
	to   time.Time
	evts []SocialEvent
}

// SlidingWindowAggregator collects events into overlapping windows that
// advance by `slide` every `slide` duration until a full window of
// `size` has been accumulated.
type SlidingWindowAggregator struct {
	size, slide time.Duration
	buckets     []windowBucket
	mtx         sync.Mutex
}

func NewSlidingWindowAggregator(size, slide time.Duration) *SlidingWindowAggregator {
	return &SlidingWindowAggregator{
		size:    size,
		slide:   slide,
		buckets: make([]windowBucket, 0, int(size/slide)+1),
	}
}

// addEvent inserts the event into all overlapping buckets.
func (agg *SlidingWindowAggregator) addEvent(evt SocialEvent) {
	agg.mtx.Lock()
	defer agg.mtx.Unlock()

	// Remove expired buckets.
	now := evt.CreatedAtUTC
	cutoff := now.Add(-agg.size)
	idx := 0
	for idx < len(agg.buckets) && agg.buckets[idx].to.Before(cutoff) {
		idx++
	}
	agg.buckets = agg.buckets[idx:]

	// Ensure buckets up to current time exist.
	latest := agg.latestBucketEnd()
	for latest.Before(now) {
		start := latest
		end := start.Add(agg.slide)
		agg.buckets = append(agg.buckets, windowBucket{from: start, to: end})
		latest = end
	}

	// Insert event into relevant buckets.
	for i := range agg.buckets {
		if evt.CreatedAtUTC.After(agg.buckets[i].from) && !evt.CreatedAtUTC.After(agg.buckets[i].to) {
			agg.buckets[i].evts = append(agg.buckets[i].evts, evt)
		}
	}
}

func (agg *SlidingWindowAggregator) latestBucketEnd() time.Time {
	if len(agg.buckets) == 0 {
		return time.Now().UTC().Truncate(agg.slide)
	}
	return agg.buckets[len(agg.buckets)-1].to
}

// popWindows returns and deletes buckets whose end‐time <= now ‑ slide.
func (agg *SlidingWindowAggregator) popWindows(now time.Time) []windowBucket {
	agg.mtx.Lock()
	defer agg.mtx.Unlock()

	var ready []windowBucket
	cut := 0
	for ; cut < len(agg.buckets); cut++ {
		if agg.buckets[cut].to.After(now.Add(-agg.slide)) {
			break
		}
		ready = append(ready, agg.buckets[cut])
	}
	agg.buckets = agg.buckets[cut:]
	return ready
}

// -----------------------------------------------------------------------------
// Community Health Scorer (Observer + Pipeline)
// -----------------------------------------------------------------------------

// CommunityScorer consumes SocialEvents, aggregates them in real-time,
// calculates community-health scores, and publishes HealthScore events.
type CommunityScorer struct {
	cfg        ScorerConfig
	strategy   HealthScoreStrategy
	sub        EventBusSubscriber
	pub        EventBusPublisher
	aggregator *SlidingWindowAggregator
	metrics    scorerMetrics
}

// scorerMetrics exposes internal metrics for Prometheus scraping.
type scorerMetrics struct {
	incomingEvents       prometheus.Counter
	publishedScores      prometheus.Counter
	strategyFailures     prometheus.Counter
	windowProcessingTime prometheus.Histogram
}

func newScorerMetrics() scorerMetrics {
	return scorerMetrics{
		incomingEvents: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "echopulse_scorer_incoming_events_total",
			Help: "Total number of social events ingested by CommunityScorer.",
		}),
		publishedScores: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "echopulse_scorer_published_scores_total",
			Help: "Total number of health scores published by CommunityScorer.",
		}),
		strategyFailures: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "echopulse_scorer_strategy_failures_total",
			Help: "Total number of strategy compute failures.",
		}),
		windowProcessingTime: prometheus.NewHistogram(prometheus.HistogramOpts{
			Name:    "echopulse_scorer_window_processing_seconds",
			Help:    "Time it takes to process one window of events.",
			Buckets: prometheus.ExponentialBuckets(0.0005, 2, 15),
		}),
	}
}

// Register all metrics to the provided registry; caller decides global vs local.
func (m *scorerMetrics) Register(reg *prometheus.Registry) {
	reg.MustRegister(
		m.incomingEvents,
		m.publishedScores,
		m.strategyFailures,
		m.windowProcessingTime,
	)
}

// NewCommunityScorer constructs a scorer with a default heuristic strategy.
func NewCommunityScorer(cfg ScorerConfig, sub EventBusSubscriber, pub EventBusPublisher, reg *prometheus.Registry) (*CommunityScorer, error) {
	if err := cfg.validate(); err != nil {
		return nil, err
	}
	metrics := newScorerMetrics()
	if reg != nil {
		metrics.Register(reg)
	}

	return &CommunityScorer{
		cfg:        cfg,
		strategy:   NewWeightedHeuristicsStrategy(),
		sub:        sub,
		pub:        pub,
		aggregator: NewSlidingWindowAggregator(cfg.WindowSize, cfg.WindowSlide),
		metrics:    metrics,
	}, nil
}

// Run wires up subscriptions and blocks until ctx is cancelled.
// It spawns two goroutines:
//   1. eventLoop:   consumes incoming SocialEvents
//   2. windowLoop:  periodically evaluates completed windows
func (s *CommunityScorer) Run(ctx context.Context, topicIn, topicOut string) error {
	evtCh, err := s.sub.Subscribe(ctx, topicIn)
	if err != nil {
		return err
	}

	// Using errgroup ensures both goroutines finish cleanly.
	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		s.eventLoop(ctx, evtCh)
	}()

	go func() {
		defer wg.Done()
		s.windowLoop(ctx, topicOut)
	}()

	<-ctx.Done()
	doneCh := make(chan struct{})
	go func() {
		wg.Wait()
		close(doneCh)
	}()

	select {
	case <-doneCh:
	case <-time.After(s.cfg.GracefulShutdownTimeout):
	}

	// publish remaining partial windows if configured
	if s.cfg.PublishPartialWindows {
		now := time.Now().UTC()
		windows := s.aggregator.popWindows(now.Add(s.cfg.WindowSize))
		for _, w := range windows {
			_ = s.processWindow(ctx, topicOut, w.evts) // best effort
		}
	}

	return nil
}

// eventLoop ingests events and feeds them to the aggregator.
func (s *CommunityScorer) eventLoop(ctx context.Context, evtCh <-chan SocialEvent) {
	for {
		select {
		case <-ctx.Done():
			return
		case evt, ok := <-evtCh:
			if !ok {
				return
			}
			s.metrics.incomingEvents.Inc()
			s.aggregator.addEvent(evt)
		}
	}
}

// windowLoop periodically asks the aggregator for completed windows.
func (s *CommunityScorer) windowLoop(ctx context.Context, topicOut string) {
	ticker := time.NewTicker(s.cfg.WindowSlide)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case ts := <-ticker.C:
			windows := s.aggregator.popWindows(ts)
			for _, w := range windows {
				start := time.Now()
				if err := s.processWindow(ctx, topicOut, w.evts); err != nil {
					s.metrics.strategyFailures.Inc()
				}
				s.metrics.windowProcessingTime.Observe(time.Since(start).Seconds())
			}
		}
	}
}

// processWindow applies the strategy and publishes the score.
func (s *CommunityScorer) processWindow(ctx context.Context, topicOut string, events []SocialEvent) error {
	scoreVal, err := s.strategy.Compute(events)
	if err != nil {
		return err
	}

	// We create one HealthScore per channel.
	perChannel := make(map[string][]SocialEvent)
	for _, e := range events {
		perChannel[e.ChannelID] = append(perChannel[e.ChannelID], e)
	}

	for chID, evts := range perChannel {
		scoreVal, err = s.strategy.Compute(evts)
		if err != nil {
			return err
		}
		score := HealthScore{
			ChannelID: chID,
			Score:     scoreVal,
			Timestamp: time.Now().UTC(),
			Version:   s.strategy.Version(),
		}
		if err := s.pub.Publish(ctx, topicOut, score); err != nil {
			return err
		}
		s.metrics.publishedScores.Inc()
	}
	return nil
}

// -----------------------------------------------------------------------------
// Compile-time interface assertions (a popular Go idiom).
// -----------------------------------------------------------------------------

var (
	_ HealthScoreStrategy = (*WeightedHeuristicsStrategy)(nil)
)

// -----------------------------------------------------------------------------
// Utility
// -----------------------------------------------------------------------------

// Within a monorepo we want to be explicit about logging instead of using a
// global logger.  By doing so we can plug in zap, zerolog, slog, etc.  For
// brevity we use stdlib log here, while still encouraging dependency injection.
//
// In a production build replace the stub below with a structured logger
// interface and pass it into CommunityScorer.
var logStub = struct {
	Errorf func(string, ...any)
	Infof  func(string, ...any)
}{
	Errorf: func(format string, args ...any) {},
	Infof:  func(format string, args ...any) {},
}