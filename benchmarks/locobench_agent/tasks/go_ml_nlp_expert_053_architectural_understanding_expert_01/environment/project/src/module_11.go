```go
// Code generated for EchoPulse – Real-Time Social Signal Processing Platform.
// Source: src/module_11.go
// Purpose: Real-time model-drift monitoring component.
//
// The component subscribes to an event-bus topic that streams histogram
// summaries of live feature distributions.  It applies configurable drift-
// detection strategies (KS, KL, PSI) and publishes a DriftAlarm event when
// statistically significant distributional change is observed.
//
// Architectural notes:
//   • Observer pattern        – reacts to FeatureHistogram events.
//   • Strategy pattern        – pluggable drift-detection algorithms.
//   • Factory pattern         – builds strategies from config at runtime.
//   • Pipeline pattern        – (ingest → detect → publish) processing chain.
//
//   Author: EchoPulse Engineering
//   License: Apache-2.0
package drift

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"math"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
)

// ===========================
// Domain-level event payloads
// ===========================

// FeatureHistogram is produced by upstream Feature-Store statistics jobs.
// Bucket counts are normalized to probabilities before arriving here.
type FeatureHistogram struct {
	Feature   string    `json:"feature"`    // Feature name (e.g. "sentiment_score")
	Histogram []float64 `json:"histogram"`  // Probability mass function; len == nBuckets
	Timestamp time.Time `json:"timestamp"`  // Wall-clock time of observation
}

// DriftAlarm is emitted whenever we detect statistically significant drift.
type DriftAlarm struct {
	Feature      string    `json:"feature"`
	Score        float64   `json:"score"`
	Drift        bool      `json:"drift"`
	Algorithm    string    `json:"algorithm"`
	Threshold    float64   `json:"threshold"`
	TriggeredAt  time.Time `json:"triggered_at"`
	ReferenceTS  time.Time `json:"reference_ts"`  // When reference histogram was recorded
	ObservationTS time.Time `json:"observation_ts"`
}

// ===============
// Error variables
// ===============
var (
	ErrIncompatibleBins = errors.New("histograms must have the same number of bins")
	ErrZeroDivision     = errors.New("division by zero encountered in histogram")
)

// ===================================
// Drift-detection Strategy interface
// ===================================

// DetectorStrategy encapsulates a statistical test / divergence metric.
type DetectorStrategy interface {
	Name() string
	Compute(reference, observed []float64) (score float64, err error)
	ExceedsThreshold(score float64) bool
}

// ============================
// Strategy-factory and helpers
// ============================

type detectorConfig struct {
	name      string
	threshold float64
}

func newDetector(cfg detectorConfig) DetectorStrategy {
	switch cfg.name {
	case "ks":
		return &ksDetector{alpha: cfg.threshold}
	case "kl":
		return &klDetector{threshold: cfg.threshold}
	case "psi":
		return &psiDetector{threshold: cfg.threshold}
	default:
		return &ksDetector{alpha: cfg.threshold} // sensible default
	}
}

// ---------------------------------------------
// Kolmogorov-Smirnov Test implementation
// ---------------------------------------------
type ksDetector struct {
	alpha float64 // critical value (e.g., 0.1)
}

func (k *ksDetector) Name() string { return "ks" }

func (k *ksDetector) Compute(p, q []float64) (float64, error) {
	if len(p) != len(q) {
		return 0, ErrIncompatibleBins
	}

	var (
		cdfP, cdfQ   float64
		maxDeviation float64
	)

	for i := range p {
		cdfP += p[i]
		cdfQ += q[i]
		dev := math.Abs(cdfP - cdfQ)
		if dev > maxDeviation {
			maxDeviation = dev
		}
	}
	return maxDeviation, nil
}

func (k *ksDetector) ExceedsThreshold(score float64) bool {
	return score > k.alpha
}

// ---------------------------------------------
// Kullback-Leibler Divergence implementation
// ---------------------------------------------
type klDetector struct {
	threshold float64 // e.g., 0.2
}

func (k *klDetector) Name() string { return "kl" }

func (k *klDetector) Compute(p, q []float64) (float64, error) {
	if len(p) != len(q) {
		return 0, ErrIncompatibleBins
	}

	var kl float64
	for i := range p {
		if p[i] == 0 {
			continue
		}
		if q[i] == 0 {
			return math.Inf(1), nil
		}
		kl += p[i] * math.Log(p[i]/q[i])
	}
	return kl, nil
}

func (k *klDetector) ExceedsThreshold(score float64) bool {
	return score > k.threshold
}

// ---------------------------------------------
// Population Stability Index (PSI) implementation
// ---------------------------------------------
type psiDetector struct {
	threshold float64 // e.g., 0.1
}

func (p *psiDetector) Name() string { return "psi" }

func (p *psiDetector) Compute(ref, obs []float64) (float64, error) {
	if len(ref) != len(obs) {
		return 0, ErrIncompatibleBins
	}

	const eps = 1e-9
	var psi float64
	for i := range ref {
		r := ref[i]
		o := obs[i]
		if r == 0 {
			r = eps
		}
		if o == 0 {
			o = eps
		}
		psi += (o - r) * math.Log(o/r)
	}
	return psi, nil
}

func (p *psiDetector) ExceedsThreshold(score float64) bool {
	return score > p.threshold
}

// ======================================
// DriftMonitor – main high-level struct
// ======================================
type DriftMonitor struct {
	ctx        context.Context
	cancel     context.CancelFunc
	cfg        detectorConfig
	detector   DetectorStrategy
	reference  map[string][]float64 // feature → reference histogram
	refTS      map[string]time.Time
	mu         sync.RWMutex

	consumer *kafka.Reader
	producer *kafka.Writer
	outTopic string
}

// NewDriftMonitor constructs a fully-wired monitor.
func NewDriftMonitor(
	parent context.Context,
	brokers []string,
	inTopic, outTopic, group string,
	reference map[string][]float64,
	referenceTS time.Time,
	algorithm string,
	threshold float64,
) *DriftMonitor {
	ctx, cancel := context.WithCancel(parent)

	consumer := kafka.NewReader(kafka.ReaderConfig{
		Brokers:  brokers,
		GroupID:  group,
		Topic:    inTopic,
		MaxBytes: 10e6, // 10MB
	})

	producer := &kafka.Writer{
		Addr:         kafka.TCP(brokers...),
		Topic:        outTopic,
		Balancer:     &kafka.LeastBytes{},
		RequiredAcks: kafka.RequireAll,
	}

	refCopies := make(map[string][]float64, len(reference))
	refTimestamps := make(map[string]time.Time, len(reference))
	for feat, hist := range reference {
		refCopies[feat] = cloneSlice(hist)
		refTimestamps[feat] = referenceTS
	}

	cfg := detectorConfig{name: algorithm, threshold: threshold}

	return &DriftMonitor{
		ctx:       ctx,
		cancel:    cancel,
		cfg:       cfg,
		detector:  newDetector(cfg),
		reference: refCopies,
		refTS:     refTimestamps,
		consumer:  consumer,
		producer:  producer,
		outTopic:  outTopic,
	}
}

// Start launches the monitoring loop (blocking).
func (m *DriftMonitor) Start() error {
	log.Printf("[drift] monitor started using %q detector", m.detector.Name())
	defer m.consumer.Close()
	defer m.producer.Close()

	for {
		select {
		case <-m.ctx.Done():
			log.Print("[drift] shutting down monitor")
			return nil
		default:
		}

		msg, err := m.consumer.ReadMessage(m.ctx)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return nil
			}
			log.Printf("[drift] consumer error: %v", err)
			continue
		}

		var fh FeatureHistogram
		if err := json.Unmarshal(msg.Value, &fh); err != nil {
			log.Printf("[drift] failed to decode histogram: %v", err)
			continue
		}

		go m.handleHistogram(fh)
	}
}

// Stop gracefully terminates the monitor.
func (m *DriftMonitor) Stop() {
	m.cancel()
}

// handleHistogram performs drift computation and publishes alarms.
func (m *DriftMonitor) handleHistogram(obs FeatureHistogram) {
	m.mu.RLock()
	refHist, ok := m.reference[obs.Feature]
	refTS := m.refTS[obs.Feature]
	m.mu.RUnlock()

	if !ok {
		log.Printf("[drift] no reference histogram for feature=%s, initializing", obs.Feature)
		m.mu.Lock()
		m.reference[obs.Feature] = cloneSlice(obs.Histogram)
		m.refTS[obs.Feature] = obs.Timestamp
		m.mu.Unlock()
		return
	}

	score, err := m.detector.Compute(refHist, obs.Histogram)
	if err != nil {
		log.Printf("[drift] detector error for feature=%s: %v", obs.Feature, err)
		return
	}

	drift := m.detector.ExceedsThreshold(score)
	if drift {
		alarm := DriftAlarm{
			Feature:       obs.Feature,
			Score:         score,
			Drift:         drift,
			Algorithm:     m.detector.Name(),
			Threshold:     m.cfg.threshold,
			TriggeredAt:   time.Now().UTC(),
			ReferenceTS:   refTS,
			ObservationTS: obs.Timestamp,
		}
		if err := m.publishAlarm(alarm); err != nil {
			log.Printf("[drift] failed to publish alarm: %v", err)
		}
		// Update the reference to the new distribution to avoid alert storms.
		m.mu.Lock()
		m.reference[obs.Feature] = cloneSlice(obs.Histogram)
		m.refTS[obs.Feature] = obs.Timestamp
		m.mu.Unlock()
	}
}

func (m *DriftMonitor) publishAlarm(alarm DriftAlarm) error {
	payload, err := json.Marshal(alarm)
	if err != nil {
		return err
	}
	return m.producer.WriteMessages(m.ctx, kafka.Message{
		Key:   []byte(alarm.Feature),
		Value: payload,
		Time:  alarm.TriggeredAt,
	})
}

// cloneSlice performs a deep copy of a slice.
func cloneSlice(in []float64) []float64 {
	out := make([]float64, len(in))
	copy(out, in)
	return out
}
```