```go
// File: src/module_40.go
//
// Package analytics implements online sentiment aggregation and health-score
// generation for EchoPulse.  It consumes sentiment-enriched SocialEvents from
// the event bus, maintains rolling statistics per community, detects sudden
// sentiment shifts, and publishes CommunityHealthEvents that can be consumed
// by downstream moderation / visualization services.
package analytics

import (
	"context"
	"errors"
	"log"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
)

/*
   =============================================================================
      Domain Models
   =============================================================================
*/

// SocialEvent is the canonical unit flowing through EchoPulse.  By the time it
// reaches this module it has already undergone NLP processing and carries a
// sentiment score in the range [-1, 1].
type SocialEvent struct {
	EventID       uuid.UUID `json:"event_id"`
	CommunityID   string    `json:"community_id"`
	Sentiment     float64   `json:"sentiment"` // Normalized sentiment score
	OriginalUTC   time.Time `json:"original_utc"`
	IngestedUTC   time.Time `json:"ingested_utc"`
	CorrelationID uuid.UUID `json:"correlation_id"`
}

// CommunityHealthEvent is emitted whenever the rolling sentiment for a
// community crosses a configurable threshold.
type CommunityHealthEvent struct {
	HealthEventID uuid.UUID `json:"health_event_id"`
	CommunityID   string    `json:"community_id"`
	WindowSize    time.Duration
	RollingAvg    float64
	Status        HealthStatus
	GeneratedUTC  time.Time `json:"generated_utc"`
}

// HealthStatus encodes the qualitative community health state derived from the
// rolling sentiment average.
type HealthStatus string

// Possible values for HealthStatus
const (
	StatusHealthy  HealthStatus = "HEALTHY"
	StatusWarning  HealthStatus = "WARNING"
	StatusCritical HealthStatus = "CRITICAL"
)

/*
   =============================================================================
      Event Bus Contracts (decouples from Kafka / NATS / etc.)
   =============================================================================
*/

// EventBusConsumer abstracts the underlying event bus implementation.
type EventBusConsumer interface {
	Subscribe(ctx context.Context, topic string) (<-chan *SocialEvent, error)
}

// EventBusProducer abstracts the underlying event bus implementation.
type EventBusProducer interface {
	Publish(ctx context.Context, topic string, evt *CommunityHealthEvent) error
}

/*
   =============================================================================
      Configuration
   =============================================================================
*/

// AnalyzerConfig controls runtime behavior.
type AnalyzerConfig struct {
	// Sliding window size for rolling average computation.
	WindowSize time.Duration

	// Interval at which communities are evaluated for potential alerting.
	EvaluationInterval time.Duration

	// Sentiment boundaries for WARNING and CRITICAL health states.
	WarningThreshold  float64 // e.g. -0.25
	CriticalThreshold float64 // e.g. -0.5

	// Down-stream topic for CommunityHealthEvents.
	HealthEventTopic string
}

// Validate returns an error if the configuration is invalid.
func (c AnalyzerConfig) Validate() error {
	switch {
	case c.WindowSize <= 0:
		return errors.New("WindowSize must be > 0")
	case c.EvaluationInterval <= 0:
		return errors.New("EvaluationInterval must be > 0")
	case c.CriticalThreshold >= c.WarningThreshold:
		return errors.New("CriticalThreshold must be < WarningThreshold")
	case c.HealthEventTopic == "":
		return errors.New("HealthEventTopic cannot be empty")
	}
	return nil
}

/*
   =============================================================================
      Sliding Window Data Structure
   =============================================================================
*/

// slidingWindow implements an efficient time-based sliding window for
// real-time aggregations.  It stores (timestamp, value) pairs in insertion
// order and keeps a running sum to allow O(1) average computation.
type slidingWindow struct {
	mu    sync.Mutex
	data  []datapoint
	sum   float64
	count int
}

type datapoint struct {
	ts    time.Time
	value float64
}

func newSlidingWindow() *slidingWindow {
	return &slidingWindow{
		data: make([]datapoint, 0, 1024),
	}
}

// add inserts a new data point.
func (w *slidingWindow) add(ts time.Time, v float64) {
	w.mu.Lock()
	defer w.mu.Unlock()

	w.data = append(w.data, datapoint{ts: ts, value: v})
	w.sum += v
	w.count++
}

// purge removes data points older than cutoff.
func (w *slidingWindow) purge(cutoff time.Time) {
	w.mu.Lock()
	defer w.mu.Unlock()

	idx := 0
	for idx < len(w.data) && w.data[idx].ts.Before(cutoff) {
		w.sum -= w.data[idx].value
		w.count--
		idx++
	}
	w.data = w.data[idx:]
}

// avg returns the current rolling average; ok is false when count == 0.
func (w *slidingWindow) avg() (avg float64, ok bool) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.count == 0 {
		return 0, false
	}
	return w.sum / float64(w.count), true
}

/*
   =============================================================================
      SentimentTrendAnalyzer
   =============================================================================
*/

// SentimentTrendAnalyzer consumes SocialEvents and emits CommunityHealthEvents.
type SentimentTrendAnalyzer struct {
	cfg       AnalyzerConfig
	consumer  EventBusConsumer
	producer  EventBusProducer
	logger    *log.Logger
	cancel    context.CancelFunc
	wg        sync.WaitGroup
	windowsMu sync.RWMutex
	// Map: communityID -> slidingWindow
	windows map[string]*slidingWindow
	metrics healthMetrics
}

// healthMetrics exposes Prometheus counters / gauges for observability.
type healthMetrics struct {
	rollingAvg *prometheus.GaugeVec
	alerts     *prometheus.CounterVec
	eventsIn   prometheus.Counter
}

func newHealthMetrics() healthMetrics {
	return healthMetrics{
		rollingAvg: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Name: "echopulse_rolling_sentiment_average",
				Help: "Rolling sentiment average per community.",
			},
			[]string{"community_id"},
		),
		alerts: prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Name: "echopulse_health_alert_total",
				Help: "Count of community health alerts emitted.",
			},
			[]string{"community_id", "status"},
		),
		eventsIn: prometheus.NewCounter(
			prometheus.CounterOpts{
				Name: "echopulse_sentiment_event_ingest_total",
				Help: "Total SocialEvents ingested by the analyzer.",
			},
		),
	}
}

// Register registers the metrics with Prometheus's default registry.
func (m healthMetrics) Register() {
	prometheus.MustRegister(m.rollingAvg, m.alerts, m.eventsIn)
}

// NewSentimentTrendAnalyzer returns an initialized analyzer.
func NewSentimentTrendAnalyzer(
	cfg AnalyzerConfig,
	consumer EventBusConsumer,
	producer EventBusProducer,
	logger *log.Logger,
) (*SentimentTrendAnalyzer, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	if logger == nil {
		logger = log.Default()
	}

	metrics := newHealthMetrics()
	metrics.Register()

	return &SentimentTrendAnalyzer{
		cfg:      cfg,
		consumer: consumer,
		producer: producer,
		logger:   logger,
		windows:  make(map[string]*slidingWindow),
		metrics:  metrics,
	}, nil
}

// Run starts the analyzer loop; it blocks until ctx is cancelled or an error
// occurs in the consumer.
func (a *SentimentTrendAnalyzer) Run(ctx context.Context, sentimentTopic string) error {
	ctx, cancel := context.WithCancel(ctx)
	a.cancel = cancel

	eventsCh, err := a.consumer.Subscribe(ctx, sentimentTopic)
	if err != nil {
		return err
	}

	a.wg.Add(2)
	go func() {
		defer a.wg.Done()
		a.consumeLoop(ctx, eventsCh)
	}()

	go func() {
		defer a.wg.Done()
		a.evaluationLoop(ctx)
	}()

	<-ctx.Done()
	a.logger.Printf("SentimentTrendAnalyzer shutting down: %v", ctx.Err())

	// Wait for goroutines to complete.
	a.wg.Wait()
	return nil
}

// Stop gracefully terminates the analyzer.
func (a *SentimentTrendAnalyzer) Stop() {
	if a.cancel != nil {
		a.cancel()
	}
}

// consumeLoop continuously ingests SocialEvents from the event bus.
func (a *SentimentTrendAnalyzer) consumeLoop(ctx context.Context, ch <-chan *SocialEvent) {
	for {
		select {
		case <-ctx.Done():
			return
		case evt, ok := <-ch:
			if !ok {
				// Consumer channel closed unexpectedly.
				a.logger.Println("event channel closed")
				a.Stop()
				return
			}
			a.handleEvent(evt)
		}
	}
}

func (a *SentimentTrendAnalyzer) handleEvent(evt *SocialEvent) {
	if evt == nil {
		return
	}

	a.metrics.eventsIn.Inc()

	a.windowsMu.RLock()
	window, exists := a.windows[evt.CommunityID]
	a.windowsMu.RUnlock()

	if !exists {
		window = newSlidingWindow()
		a.windowsMu.Lock()
		a.windows[evt.CommunityID] = window
		a.windowsMu.Unlock()
	}

	window.add(evt.IngestedUTC, evt.Sentiment)
}

// evaluationLoop periodically inspects rolling averages and publishes alerts.
func (a *SentimentTrendAnalyzer) evaluationLoop(ctx context.Context) {
	ticker := time.NewTicker(a.cfg.EvaluationInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			a.evaluateCommunities(now)
		}
	}
}

// evaluateCommunities iterates over all communities and determines health.
func (a *SentimentTrendAnalyzer) evaluateCommunities(now time.Time) {
	cutoff := now.Add(-a.cfg.WindowSize)

	a.windowsMu.RLock()
	defer a.windowsMu.RUnlock()

	for cid, window := range a.windows {
		window.purge(cutoff)
		avg, ok := window.avg()
		if !ok {
			continue // no data in window
		}

		a.metrics.rollingAvg.WithLabelValues(cid).Set(avg)

		var status HealthStatus
		switch {
		case avg <= a.cfg.CriticalThreshold:
			status = StatusCritical
		case avg <= a.cfg.WarningThreshold:
			status = StatusWarning
		default:
			status = StatusHealthy
		}

		// Only emit events for non-healthy states to reduce noise.
		if status != StatusHealthy {
			if err := a.emitHealthEvent(cid, avg, status); err != nil {
				a.logger.Printf("emitHealthEvent error: %v", err)
			}
		}
	}
}

func (a *SentimentTrendAnalyzer) emitHealthEvent(
	cid string,
	avg float64,
	status HealthStatus,
) error {
	evt := &CommunityHealthEvent{
		HealthEventID: uuid.New(),
		CommunityID:   cid,
		WindowSize:    a.cfg.WindowSize,
		RollingAvg:    avg,
		Status:        status,
		GeneratedUTC:  time.Now().UTC(),
	}

	a.metrics.alerts.WithLabelValues(cid, string(status)).Inc()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	return a.producer.Publish(ctx, a.cfg.HealthEventTopic, evt)
}
```