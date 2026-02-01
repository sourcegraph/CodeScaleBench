```go
// File: src/module_69.go
//
// EchoPulse – Real-Time Social Signal Processing Platform
//
// Sliding-window sentiment aggregation and community-health signalling
// -------------------------------------------------------------------
// This module consumes canonical SocialEvents, analyzes their sentiment
// by means of a pluggable strategy, aggregates scores inside sliding
// time-windows and publishes CommunityHealthEvents whenever the rolling
// sentiment of a community breaches a configurable threshold.
//
// Architectural patterns used here:
//   • Strategy          – SentimentAnalyzer interchangeable at runtime
//   • Factory           – NewSentimentAnalyzer articulates creation logic
//   • Observer/Pipeline – Aggregator observes SocialEvents and emits
//                         derived events further down the processing
//                         pipeline.
//
// NOTE: external integrations such as Kafka/NATS are abstracted behind
//       a Publisher interface to stay transport-agnostic.

package echopulse

import (
	"context"
	"errors"
	"fmt"
	"math"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
)

// ----------------------------------------------------------------------------
// Domain types
// ----------------------------------------------------------------------------

// SocialEvent is the canonical representation of a single user activity
// already normalised by upstream ingestion services.
type SocialEvent struct {
	ID          string    // globally unique event id
	CommunityID string    // e.g. Slack workspace, Twitch channel, Mastodon instance
	UserID      string    // anonymised user identifier
	Language    string    // iso-639-1 code
	Payload     string    // UTF-8 textual content
	CreatedAt   time.Time // client timestamp (best-effort)
}

// SentimentScore couples a SocialEvent with its computed sentiment polarity.
type SentimentScore struct {
	Event SocialEvent
	// Score ranges in [-1, 1] where -1 = negative, 0 = neutral, 1 = positive
	Score float64
}

// CommunityHealthEvent is emitted by the aggregator when the rolling
// sentiment for a community crosses the alert/ok thresholds.
type CommunityHealthEvent struct {
	ID          string    // event id
	CommunityID string
	Timestamp   time.Time
	// Rolling average sentiment inside the last window
	MeanSentiment float64
	// True if health is degraded (mean sentiment below threshold)
	Degraded bool
	Window    time.Duration
	Reason    string
}

// ----------------------------------------------------------------------------
// Strategy: Sentiment Analyzer
// ----------------------------------------------------------------------------

// SentimentAnalyzer scores arbitrary text in a given language.
type SentimentAnalyzer interface {
	// Analyze should return a polarity in the range [-1, 1].
	Analyze(text, lang string) (float64, error)
	// Name is used for metrics / debugging.
	Name() string
}

// NewSentimentAnalyzer is a factory method returning a concrete analyzer by
// name.  Additional options may configure external APIs, credentials, etc.
func NewSentimentAnalyzer(name string, opts ...AnalyzerOption) (SentimentAnalyzer, error) {
	cfg := analyzerConfig{}
	for _, opt := range opts {
		opt(&cfg)
	}

	switch strings.ToLower(name) {
	case "", "vader":
		return newVADERAnalyzer(cfg), nil
	default:
		return nil, fmt.Errorf("analyzer %q not registered", name)
	}
}

// ----------------------------------------------------------------------------
// Analyzer Options / configuration private to the strategy implementation
// ----------------------------------------------------------------------------

type analyzerConfig struct {
	lexiconPath string
}

type AnalyzerOption func(*analyzerConfig)

// WithLexicon allows callers to override the default lexicon resource path.
func WithLexicon(path string) AnalyzerOption {
	return func(c *analyzerConfig) { c.lexiconPath = path }
}

// ----------------------------------------------------------------------------
// Very-lightweight VADER port (stub)
// ----------------------------------------------------------------------------

// vaderAnalyzer is a skeletal, offline analyzer that uses a rudimentary
// sentiment lexicon.  Production builds swap this out for a full-fledged
// implementation or an on-line model.
type vaderAnalyzer struct {
	lexicon map[string]float64
	name    string
}

func newVADERAnalyzer(cfg analyzerConfig) *vaderAnalyzer {
	a := &vaderAnalyzer{
		lexicon: defaultLexicon(),
		name:    "vader-mini",
	}

	// In production we would load custom lexicon from cfg.lexiconPath here.
	return a
}

func (v *vaderAnalyzer) Name() string { return v.name }

func (v *vaderAnalyzer) Analyze(text, lang string) (float64, error) {
	if lang != "" && !strings.HasPrefix(lang, "en") {
		// naïve language gating; real code would route to language-specific
		// models.  Neutral assumption for unknown languages.
		return 0, nil
	}

	if text == "" {
		return 0, nil
	}

	var (
		tokens = tokenize(text)
		sum    float64
		count  int
	)

	for _, t := range tokens {
		if val, ok := v.lexicon[strings.ToLower(t)]; ok {
			sum += val
			count++
		}
	}

	if count == 0 {
		return 0, nil
	}

	// Clamp result to [-1, 1]
	score := sum / float64(count)
	if score > 1 {
		score = 1
	}
	if score < -1 {
		score = -1
	}
	return score, nil
}

// defaultLexicon provides a minimal hard-coded lexicon to keep the example
// fully self-contained.
func defaultLexicon() map[string]float64 {
	return map[string]float64{
		"love":  1.0,
		"like":  0.7,
		"good":  0.6,
		"nice":  0.6,
		"great": 0.8,
		"lol":   0.4,

		"hate":   -1.0,
		"bad":    -0.6,
		"awful":  -0.8,
		"angry":  -0.7,
		"terrible": -1.0,
	}
}

func tokenize(text string) []string {
	return strings.FieldsFunc(text, func(r rune) bool { return r == ' ' || r == ',' || r == '.' || r == '!' || r == '?' })
}

// ----------------------------------------------------------------------------
// Publisher abstraction – hides Kafka/NATS/etc. behind an interface
// ----------------------------------------------------------------------------

// Publisher pushes events onto a message bus.
type Publisher interface {
	Publish(ctx context.Context, key string, v any) error
}

// ----------------------------------------------------------------------------
// Sliding window sentiment aggregator
// ----------------------------------------------------------------------------

// AggregatorConfig enumerates runtime configuration knobs.
type AggregatorConfig struct {
	WindowSize    time.Duration // logical size of the rolling window
	FlushInterval time.Duration // background flush cadence
	AlertThresh   float64       // mean sentiment below → degraded
	AnalyzerName  string        // which sentiment strategy to use
	InputBuf      int           // channel buffer
}

// Validate returns an error on invalid configurations.
func (c AggregatorConfig) Validate() error {
	switch {
	case c.WindowSize <= 0:
		return errors.New("window size must be positive")
	case c.FlushInterval <= 0:
		return errors.New("flush interval must be positive")
	case c.InputBuf < 0:
		return errors.New("input buffer negative")
	}
	return nil
}

// SlidingWindowAggregator implements the Observer role: it consumes
// SocialEvents, analyzes and aggregates them, then publishes high-level
// CommunityHealthEvents to the rest of the system.
//
// Thread-safe; supports hot-shutdown via context cancellation.
type SlidingWindowAggregator struct {
	cfg       AggregatorConfig
	input     chan SocialEvent
	analyzer  SentimentAnalyzer
	publisher Publisher

	mu      sync.Mutex                       // guards state
	rolling map[string]*communitySentiment   // per community

	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
}

// communitySentiment keeps running stats for a community window.
type communitySentiment struct {
	sum   float64
	count int
}

// Metrics exported via Prometheus.
var (
	metricMeanSentiment = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: "echopulse",
			Subsystem: "sentiment_agg",
			Name:      "mean_sentiment",
			Help:      "Rolling mean sentiment per community",
		},
		[]string{"community"},
	)
	metricTotalEvents = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: "echopulse",
			Subsystem: "sentiment_agg",
			Name:      "events_total",
			Help:      "Total number of events processed",
		},
		[]string{"community"},
	)
	metricHealthAlerts = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: "echopulse",
			Subsystem: "sentiment_agg",
			Name:      "health_alerts_total",
			Help:      "Total number of health alerts emitted",
		},
		[]string{"community"},
	)
)

// NewSlidingWindowAggregator returns a fully initialised aggregator.
func NewSlidingWindowAggregator(cfg AggregatorConfig, publisher Publisher) (*SlidingWindowAggregator, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	analyzer, err := NewSentimentAnalyzer(cfg.AnalyzerName)
	if err != nil {
		return nil, err
	}

	ctx, cancel := context.WithCancel(context.Background())

	agg := &SlidingWindowAggregator{
		cfg:       cfg,
		input:     make(chan SocialEvent, cfg.InputBuf),
		analyzer:  analyzer,
		publisher: publisher,
		rolling:   make(map[string]*communitySentiment),
		ctx:       ctx,
		cancel:    cancel,
	}

	// Register prometheus collectors. (idempotent if already registered)
	prometheus.MustRegister(metricMeanSentiment, metricTotalEvents, metricHealthAlerts)

	agg.wg.Add(2)
	go agg.runProcessingLoop()
	go agg.runFlushLoop()

	return agg, nil
}

// PublishEvent allows external components (e.g., Kafka consumer handlers)
// to feed SocialEvents into the aggregator.
func (a *SlidingWindowAggregator) PublishEvent(evt SocialEvent) {
	select {
	case a.input <- evt:
	case <-a.ctx.Done():
		// aggregator shutting down – drop event
	}
}

// Shutdown gracefully shuts down all background goroutines.
func (a *SlidingWindowAggregator) Shutdown(ctx context.Context) error {
	a.cancel()

	ch := make(chan struct{})
	go func() {
		a.wg.Wait()
		close(ch)
	}()

	select {
	case <-ch:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// runProcessingLoop is event-driven: it consumes SocialEvents, scores them,
// and updates rolling stats.
func (a *SlidingWindowAggregator) runProcessingLoop() {
	defer a.wg.Done()

	for {
		select {
		case evt := <-a.input:
			score, err := a.analyzer.Analyze(evt.Payload, evt.Language)
			if err != nil {
				// log and skip – for brevity we print to stderr.
				fmt.Printf("sentiment analyze error: %v\n", err)
				continue
			}
			a.ingestScore(evt, score)

		case <-a.ctx.Done():
			return
		}
	}
}

// ingestScore mutates aggregate stats in a concurrency-safe manner.
func (a *SlidingWindowAggregator) ingestScore(evt SocialEvent, score float64) {
	a.mu.Lock()
	defer a.mu.Unlock()

	cs, ok := a.rolling[evt.CommunityID]
	if !ok {
		cs = &communitySentiment{}
		a.rolling[evt.CommunityID] = cs
	}

	cs.sum += score
	cs.count++

	metricTotalEvents.WithLabelValues(evt.CommunityID).Inc()
}

// runFlushLoop periodically computes window means and publishes
// CommunityHealthEvents if thresholds are crossed.
func (a *SlidingWindowAggregator) runFlushLoop() {
	defer a.wg.Done()

	ticker := time.NewTicker(a.cfg.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			a.flushWindow()
		case <-a.ctx.Done():
			return
		}
	}
}

// flushWindow resets the rolling stats atomically and handles signalling.
func (a *SlidingWindowAggregator) flushWindow() {
	now := time.Now()

	a.mu.Lock()
	defer a.mu.Unlock()

	for community, cs := range a.rolling {
		if cs.count == 0 {
			continue
		}
		mean := cs.sum / float64(cs.count)
		metricMeanSentiment.WithLabelValues(community).Set(mean)

		// Determine if sentiment is degraded.
		degraded := mean < a.cfg.AlertThresh

		evt := CommunityHealthEvent{
			ID:            uuid.NewString(),
			CommunityID:   community,
			Timestamp:     now,
			MeanSentiment: mean,
			Degraded:      degraded,
			Window:        a.cfg.WindowSize,
			Reason:        fmt.Sprintf("rolling_mean=%0.3f threshold=%0.3f", mean, a.cfg.AlertThresh),
		}

		if degraded {
			metricHealthAlerts.WithLabelValues(community).Inc()
		}

		// We intentionally ignore publish errors because they can be transient,
		// but production code should have proper retry/backoff strategies.
		go func(e CommunityHealthEvent) {
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			defer cancel()
			_ = a.publisher.Publish(ctx, e.CommunityID, e)
		}(evt)

		// zero out stats for next window
		cs.sum, cs.count = 0, 0
	}
}

// ----------------------------------------------------------------------------
// In-memory publisher for tests / local runs
// ----------------------------------------------------------------------------

// MemoryPublisher is a thread-safe, bounded queue publisher useful for tests.
type MemoryPublisher struct {
	mu    sync.Mutex
	queue []any
}

func NewMemoryPublisher() *MemoryPublisher { return &MemoryPublisher{} }

func (m *MemoryPublisher) Publish(_ context.Context, _ string, v any) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.queue = append(m.queue, v)
	return nil
}

// Drain returns and clears the internal queue.
func (m *MemoryPublisher) Drain() []any {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]any, len(m.queue))
	copy(out, m.queue)
	m.queue = m.queue[:0]
	return out
}

// ----------------------------------------------------------------------------
// Example usage (would live in a different package/file in real code)
// ----------------------------------------------------------------------------
/*
func main() {
	pub := NewMemoryPublisher()

	cfg := AggregatorConfig{
		WindowSize:    60 * time.Second,
		FlushInterval: 15 * time.Second,
		AlertThresh:   -0.2,
		AnalyzerName:  "vader",
		InputBuf:      1024,
	}

	agg, err := NewSlidingWindowAggregator(cfg, pub)
	if err != nil {
		log.Fatalf("failed to init aggregator: %v", err)
	}
	defer agg.Shutdown(context.Background())

	// Simulate incoming traffic
	go func() {
		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		for range ticker.C {
			agg.PublishEvent(SocialEvent{
				ID:          uuid.NewString(),
				CommunityID: "go-lang",
				UserID:      "user-123",
				Language:    "en",
				Payload:     "I love Go – it's great!",
				CreatedAt:   time.Now(),
			})
		}
	}()

	select {}
}
*/
// ----------------------------------------------------------------------------
```