```go
// Code generated for EchoPulse (ml_nlp) — DO NOT EDIT MANUALLY.
// Path: src/module_48.go
//
// Module 48: Statistical Drift Detector
//
// This module implements a streaming χ²–based statistical drift detector that
// monitors the marginal distribution of categorical features (e.g., token,
// emoji, reaction type) in real-time.  If the distribution within the sliding
// window diverges significantly from a configurable reference distribution, the
// detector emits a DriftAlert event onto the event-bus.  Model-orchestration
// services can listen for these alerts and trigger automated re-training or
// alternative remediation strategies.
//
// The detector is entirely event-driven and safe for concurrent use.
// Dependencies outside the standard library are kept minimal (only gonum/stat
// for χ² CDF computation).

package ml_nlp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"sync"
	"time"

	"gonum.org/v1/gonum/stat/distuv"
)

// ----------------------------------------------------------------------------
// Domain types (simplified)
//
// NOTE: In the full EchoPulse code-base these live in a shared pkg; they are
// re-declared here at reduced scope for compilation independence.
// -----------------------------------------------------------------------------

// SocialEvent represents the canonical event emitted by upstream ingestion
// pipelines (chat messages, tweets, reactions, etc.).
type SocialEvent struct {
	EventID   string            `json:"event_id"`
	Timestamp time.Time         `json:"ts"`
	UserID    string            `json:"user_id"`
	Channel   string            `json:"channel"`
	Payload   map[string]string `json:"payload"` // e.g. { "token": "🔥" }
}

// DriftAlert is produced by the detector when statistically significant drift
// is discovered.
type DriftAlert struct {
	AlertID        string    `json:"alert_id"`
	DetectedAt     time.Time `json:"detected_at"`
	Feature        string    `json:"feature"`
	ChiSqStatistic float64   `json:"chi_sq"`
	PValue         float64   `json:"p_val"`
	WindowSize     int       `json:"window_size"`
	ReferenceSize  int       `json:"reference_size"`
	Severity       string    `json:"severity"` // info|warning|critical
}

// ----------------------------------------------------------------------------
// Event-bus abstraction (Kafka, JetStream, etc.)
// -----------------------------------------------------------------------------

// EventBusProducer publishes bytes to a topic/subject.
type EventBusProducer interface {
	Publish(ctx context.Context, topic string, payload []byte) error
}

// EventBusConsumer subscribes to a topic and invokes the handler for each msg.
type EventBusConsumer interface {
	Subscribe(ctx context.Context, topic string, handler func([]byte) error) (Subscription, error)
}

// Subscription allows unsubscribing/closing the consumer stream.
type Subscription interface {
	Unsubscribe() error
}

// ----------------------------------------------------------------------------
// DriftDetector
// -----------------------------------------------------------------------------

// DriftDetectorConfig parameterizes NewDriftDetector.
type DriftDetectorConfig struct {
	EventTopic       string        // topic/subject receiving the SocialEvents
	AlertTopic       string        // topic to publish DriftAlert messages
	FeatureKey       string        // which payload key to monitor (e.g., "token")
	ReferenceWindow  int           // number of events to build reference distribution
	SlidingWindow    int           // number of events per live window
	PValueThreshold  float64       // significance level; defaults to 0.05
	CoolDownPeriod   time.Duration // min distance between alerts
	Logger           *log.Logger   // optional; falls back to std logger
	RawEventConsumer EventBusConsumer
	AlertProducer    EventBusProducer
}

// DriftDetector monitors a categorical feature stream for distribution drift.
type DriftDetector struct {
	cfg DriftDetectorConfig

	// referenceCounts holds counts of feature categories in reference period.
	referenceCounts map[string]int
	// liveCounts holds counts for current sliding window.
	liveCounts map[string]int
	// ring buffer to evict old events from liveCounts.
	windowBuffer []string
	windowIdx    int

	mu sync.Mutex

	// bookkeeping
	totalReference int
	totalLive      int
	lastAlert      time.Time
	cancelFn       context.CancelFunc
	sub            Subscription
}

// NewDriftDetector creates and starts a new detector in its own goroutine.
func NewDriftDetector(ctx context.Context, cfg DriftDetectorConfig) (*DriftDetector, error) {
	if cfg.FeatureKey == "" {
		return nil, errors.New("FeatureKey required")
	}
	if cfg.ReferenceWindow < 100 {
		return nil, errors.New("ReferenceWindow must be >= 100 for statistical power")
	}
	if cfg.SlidingWindow < 50 {
		return nil, errors.New("SlidingWindow must be >= 50")
	}
	if cfg.PValueThreshold == 0 {
		cfg.PValueThreshold = 0.05
	}
	if cfg.CoolDownPeriod == 0 {
		cfg.CoolDownPeriod = time.Minute
	}
	if cfg.Logger == nil {
		cfg.Logger = log.Default()
	}
	if cfg.RawEventConsumer == nil || cfg.AlertProducer == nil {
		return nil, errors.New("EventBusConsumer and AlertProducer are required")
	}

	d := &DriftDetector{
		cfg:             cfg,
		referenceCounts: make(map[string]int),
		liveCounts:      make(map[string]int),
		windowBuffer:    make([]string, cfg.SlidingWindow),
	}

	// Kick-off background handling loop.
	cctx, cancel := context.WithCancel(ctx)
	d.cancelFn = cancel
	var err error
	d.sub, err = cfg.RawEventConsumer.Subscribe(cctx, cfg.EventTopic, d.handleRawEvent)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("subscribe error: %w", err)
	}

	cfg.Logger.Printf("drift_detector: started feature=%q ref=%d window=%d p<=%.3f topic=%q",
		cfg.FeatureKey, cfg.ReferenceWindow, cfg.SlidingWindow, cfg.PValueThreshold, cfg.EventTopic)
	return d, nil
}

// Stop terminates the detector and unsubscribes from the bus.
func (d *DriftDetector) Stop() error {
	d.cancelFn()
	if d.sub != nil {
		return d.sub.Unsubscribe()
	}
	return nil
}

// handleRawEvent satisfies EventBusConsumer handler signature.
func (d *DriftDetector) handleRawEvent(msg []byte) error {
	evt := SocialEvent{}
	if err := json.Unmarshal(msg, &evt); err != nil {
		// Malformed messages are skipped but logged.
		d.cfg.Logger.Printf("drift_detector: unmarshal error: %v", err)
		return nil
	}

	val, ok := evt.Payload[d.cfg.FeatureKey]
	if !ok || val == "" {
		return nil // feature absent — ignore
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	if d.totalReference < d.cfg.ReferenceWindow {
		d.referenceCounts[val]++
		d.totalReference++
		return nil // still building baseline
	}

	// Update sliding window.
	evicted := d.windowBuffer[d.windowIdx]
	if evicted != "" {
		d.liveCounts[evicted]--
		d.totalLive--
	}
	d.windowBuffer[d.windowIdx] = val
	d.windowIdx = (d.windowIdx + 1) % d.cfg.SlidingWindow

	d.liveCounts[val]++
	d.totalLive++

	if d.totalLive >= d.cfg.SlidingWindow {
		d.maybeDetectDrift(evt.Timestamp)
	}

	return nil
}

// maybeDetectDrift computes χ² statistic over live window and emits alert if drift.
func (d *DriftDetector) maybeDetectDrift(ts time.Time) {
	chiSq, pVal := chiSquareTest(d.liveCounts, d.totalLive, d.referenceCounts, d.totalReference)
	if math.IsNaN(pVal) {
		return
	}
	if pVal > d.cfg.PValueThreshold {
		return // no significant drift
	}

	if time.Since(d.lastAlert) < d.cfg.CoolDownPeriod {
		return // avoid alert storms
	}

	severity := classifySeverity(pVal)
	alert := DriftAlert{
		AlertID:        fmt.Sprintf("drift_%d", ts.UnixNano()),
		DetectedAt:     ts,
		Feature:        d.cfg.FeatureKey,
		ChiSqStatistic: chiSq,
		PValue:         pVal,
		WindowSize:     d.totalLive,
		ReferenceSize:  d.totalReference,
		Severity:       severity,
	}

	d.lastAlert = ts
	d.emitAlert(alert)
}

// emitAlert publishes DriftAlert to the configured topic.
func (d *DriftDetector) emitAlert(alert DriftAlert) {
	b, _ := json.Marshal(alert) // safe: DriftAlert has no unsupported types
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := d.cfg.AlertProducer.Publish(ctx, d.cfg.AlertTopic, b); err != nil {
		d.cfg.Logger.Printf("drift_detector: publish alert error: %v", err)
	} else {
		d.cfg.Logger.Printf("drift_detector: ALERT p=%.4f chi²=%.2f severity=%s",
			alert.PValue, alert.ChiSqStatistic, alert.Severity)
	}
}

// ----------------------------------------------------------------------------
// Statistics utilities
// -----------------------------------------------------------------------------

// chiSquareTest returns (χ² statistic, p-value) comparing live vs reference.
func chiSquareTest(live map[string]int, nLive int, ref map[string]int, nRef int) (float64, float64) {
	var chiSq float64
	df := len(ref) - 1
	if df <= 0 {
		return math.NaN(), math.NaN()
	}

	for category, refCount := range ref {
		expected := float64(refCount) / float64(nRef) * float64(nLive)
		observed := float64(live[category])
		if expected == 0 {
			continue
		}
		chiSq += math.Pow(observed-expected, 2) / expected
	}

	pVal := 1 - distuv.ChiSquared{K: float64(df)}.CDF(chiSq)
	return chiSq, pVal
}

// classifySeverity heuristically maps p-value to severity buckets.
func classifySeverity(p float64) string {
	switch {
	case p < 0.0001:
		return "critical"
	case p < 0.001:
		return "warning"
	default:
		return "info"
	}
}
```