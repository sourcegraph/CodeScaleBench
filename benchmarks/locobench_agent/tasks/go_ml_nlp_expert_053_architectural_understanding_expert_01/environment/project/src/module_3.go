```go
// File: src/module_3.go
// Package processing provides the sentiment-analysis stage of the EchoPulse
// event pipeline.  It demonstrates usage of the Factory, Strategy and Pipeline
// patterns while remaining fully concurrent and observable through Prometheus.
package processing

import (
	"context"
	"errors"
	"math/rand"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/sirupsen/logrus"
)

// -----------------------------------------------------------------------------
// Domain types
// -----------------------------------------------------------------------------

// SocialEvent is the canonical event emitted by upstream ingest services.
type SocialEvent struct {
	ID        string    // globally-unique event identifier
	UserID    string    // user who produced the event
	Timestamp time.Time // wall-clock time the event was created
	Language  string    // ISO-639-1 two-letter language code
	RawText   string    // UTF-8 payload text
}

// SentimentResult captures model output.
type SentimentResult struct {
	Score       int8    // discrete sentiment class in [-3, 3]
	Probability float64 // model confidence
	Model       string  // model identifier/hash
}

// ProcessedEvent is the downstream artifact that combines the original
// SocialEvent with the enrichment produced by this module.
type ProcessedEvent struct {
	SocialEvent
	Sentiment SentimentResult
}

// -----------------------------------------------------------------------------
// Strategy layer
// -----------------------------------------------------------------------------

// SentimentStrategy is a pluggable algorithm for sentiment inference.
type SentimentStrategy interface {
	Analyze(ctx context.Context, text string) (SentimentResult, error)
	Name() string
}

// VaderStrategy is a lightweight rule-based sentiment model.
type VaderStrategy struct{}

func (v *VaderStrategy) Analyze(_ context.Context, text string) (SentimentResult, error) {
	// NAÏVE stubbed implementation — in production this would call into the C
	// port of the original VADER implementation or a SIMD-accelerated port.
	if text == "" {
		return SentimentResult{}, errors.New("empty text")
	}
	score := int8(rand.Intn(7) - 3) // [-3,3]
	return SentimentResult{
		Score:       score,
		Probability: rand.Float64()*0.4 + 0.6, // [0.6,1.0)
		Model:       "vader-1.0.0",
	}, nil
}

func (v *VaderStrategy) Name() string { return "VADER" }

// TransformerStrategy is a heavy transformer-based sentiment model.
type TransformerStrategy struct{}

func (t *TransformerStrategy) Analyze(_ context.Context, text string) (SentimentResult, error) {
	if text == "" {
		return SentimentResult{}, errors.New("empty text")
	}
	score := int8(rand.Intn(7) - 3)
	return SentimentResult{
		Score:       score,
		Probability: rand.Float64()*0.2 + 0.8, // [0.8,1.0)
		Model:       "distilbert-sent-v3",
	}, nil
}

func (t *TransformerStrategy) Name() string { return "Transformer" }

// SentimentStrategyFactory picks the optimal strategy for the given event.
func SentimentStrategyFactory(e SocialEvent) SentimentStrategy {
	// Heuristic: use VADER for short English text, transformer otherwise.
	if e.Language == "en" && len(e.RawText) < 160 {
		return &VaderStrategy{}
	}
	return &TransformerStrategy{}
}

// -----------------------------------------------------------------------------
// Processor implementation
// -----------------------------------------------------------------------------

// SentimentProcessor consumes SocialEvents, enriches them with sentiment
// information, and publishes ProcessedEvents to the configured sink.
type SentimentProcessor struct {
	workerCount int
	jobs        chan SocialEvent
	out         chan<- ProcessedEvent
	wg          sync.WaitGroup
	cancel      context.CancelFunc
}

// NewSentimentProcessor allocates a new processor. `workers` configures the
// parallelism level. `sink` is the channel receiving ProcessedEvents.
func NewSentimentProcessor(workers int, sink chan<- ProcessedEvent) *SentimentProcessor {
	if workers <= 0 {
		workers = 2 * runtimeCPUCount()
	}
	return &SentimentProcessor{
		workerCount: workers,
		jobs:        make(chan SocialEvent, 4096),
		out:         sink,
	}
}

// Start launches the worker pool and returns a channel for pushing jobs.
func (p *SentimentProcessor) Start(parent context.Context) chan<- SocialEvent {
	ctx, cancel := context.WithCancel(parent)
	p.cancel = cancel

	for i := 0; i < p.workerCount; i++ {
		p.wg.Add(1)
		go p.worker(ctx, i)
	}
	return p.jobs
}

// Stop signals the processor to stop accepting new jobs and blocks until all
// workers have terminated.
func (p *SentimentProcessor) Stop() {
	cancel := p.cancel
	if cancel != nil {
		cancel()
	}
	close(p.jobs) // idempotent after cancel but safe
	p.wg.Wait()
}

// worker consumes SocialEvents from the job queue, enriches them, and forwards
// them downstream.  All failures are surfaced via Prometheus and logrus.
func (p *SentimentProcessor) worker(ctx context.Context, id int) {
	defer p.wg.Done()
	logger := logrus.WithField("worker", id)

	for {
		select {
		case <-ctx.Done():
			logger.Debug("context cancelled")
			return
		case evt, ok := <-p.jobs:
			if !ok {
				logger.Debug("job channel closed")
				return
			}
			p.enrich(ctx, logger, evt)
		}
	}
}

// enrich performs the actual sentiment inference for a single SocialEvent.
func (p *SentimentProcessor) enrich(
	ctx context.Context,
	logger *logrus.Entry,
	evt SocialEvent,
) {
	start := time.Now()
	strategy := SentimentStrategyFactory(evt)

	res, err := strategy.Analyze(ctx, evt.RawText)
	duration := time.Since(start).Seconds()

	sentimentLatency.WithLabelValues(strategy.Name()).Observe(duration)

	if err != nil {
		sentimentFailures.WithLabelValues(strategy.Name()).Inc()
		logger.WithFields(logrus.Fields{
			"event_id": evt.ID,
			"strategy": strategy.Name(),
			"error":    err,
		}).Warn("sentiment analysis failed")
		return
	}

	outEvt := ProcessedEvent{
		SocialEvent: evt,
		Sentiment:   res,
	}
	select {
	case p.out <- outEvt:
		sentimentSuccess.WithLabelValues(strategy.Name()).Inc()
	case <-ctx.Done():
		logger.Debug("context cancelled before publishing result")
	}
}

// runtimeCPUCount isolates the standard library call for easier unit testing.
var runtimeCPUCount = func() int { return int64ToInt(safeCPUCount()) }

// separate helpers to avoid CGO on tiny devices.
func safeCPUCount() int64 {
	if c := int64(1); c > 0 {
		return c
	}
	return 1
}

func int64ToInt(i int64) int {
	if i > int64(^uint(0)>>1) {
		return int(^uint(0) >> 1)
	}
	return int(i)
}

// -----------------------------------------------------------------------------
// Metrics
// -----------------------------------------------------------------------------

var (
	sentimentLatency = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: "echopulse",
			Subsystem: "sentiment",
			Name:      "analysis_latency_seconds",
			Help:      "Wall-clock latency of sentiment inference.",
			Buckets:   prometheus.DefBuckets,
		},
		[]string{"strategy"},
	)

	sentimentSuccess = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: "echopulse",
			Subsystem: "sentiment",
			Name:      "analysis_success_total",
			Help:      "Number of successful sentiment analyses.",
		},
		[]string{"strategy"},
	)

	sentimentFailures = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: "echopulse",
			Subsystem: "sentiment",
			Name:      "analysis_failure_total",
			Help:      "Number of failed sentiment analyses.",
		},
		[]string{"strategy"},
	)
)

// init registers Prometheus collectors at module load time.
func init() {
	prometheus.MustRegister(sentimentLatency, sentimentSuccess, sentimentFailures)
	logrus.SetFormatter(&logrus.JSONFormatter{
		TimestampFormat: time.RFC3339Nano,
	})
	logrus.SetLevel(logrus.InfoLevel)
}
```