```go
// File: src/module_23.go
//
// EchoPulse – Real-Time Social Signal Processing Platform
//
// Module 23: Statistical Feature-Drift Monitor
//
// This package consumes rolling feature-statistics from the online feature
// store, applies configurable drift-detection strategies, and publishes
// drift-alert events back to the event bus.  The module showcases Observer,
// Strategy, and Factory patterns, as well as idiomatic concurrent Go.
//
// NOTE: Replace kafka brokers, topic names, and registry implementation hooks
// with your production parameters.

package drift

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
)

// ----------------------------------------------------------------------------
// Domain Types
// ----------------------------------------------------------------------------

// FeatureStat represents the aggregate statistics of a single feature for a
// given time-bucket, produced by upstream streaming jobs.
type FeatureStat struct {
	ModelID   string    `json:"model_id"`
	Feature   string    `json:"feature"`
	Mean      float64   `json:"mean"`
	StdDev    float64   `json:"std_dev"`
	Count     int64     `json:"count"`
	Timestamp time.Time `json:"ts"`
}

// DriftResult captures the outcome of a drift-detection test.
type DriftResult struct {
	ModelID  string             `json:"model_id"`
	Feature  string             `json:"feature"`
	Method   string             `json:"method"`
	Score    float64            `json:"score"`
	Drifted  bool               `json:"drifted"`
	Details  map[string]float64 `json:"details,omitempty"`
	Observed FeatureStat        `json:"observed"`
	Baseline FeatureStat        `json:"baseline"`
}

// ----------------------------------------------------------------------------
// Strategy Pattern – Drift Detectors
// ----------------------------------------------------------------------------

// DriftDetector defines the interface for statistical drift detectors.
type DriftDetector interface {
	// Detect returns a DriftResult comparing baseline and observed stats.
	Detect(baseline, observed FeatureStat) (DriftResult, error)
	// Name is a human-friendly identifier for the detector.
	Name() string
}

// ksDetector implements a two-sample Kolmogorov–Smirnov test on normal
// distributions parameterized by mean and stddev.
type ksDetector struct {
	alpha float64
}

func (k *ksDetector) Name() string { return "ks_test" }

func (k *ksDetector) Detect(baseline, observed FeatureStat) (DriftResult, error) {
	if baseline.StdDev == 0 || observed.StdDev == 0 {
		return DriftResult{}, errors.New("stddev must be > 0 for KS test")
	}

	// Analytical KS distance between two normals (approx.)
	d := math.Abs(baseline.Mean-observed.Mean) /
		math.Sqrt(baseline.StdDev*baseline.StdDev+observed.StdDev*observed.StdDev)

	drifted := d > k.alpha
	return DriftResult{
		ModelID:  baseline.ModelID,
		Feature:  baseline.Feature,
		Method:   k.Name(),
		Score:    d,
		Drifted:  drifted,
		Observed: observed,
		Baseline: baseline,
	}, nil
}

// jsDetector implements Jensen-Shannon divergence on discretized Gaussians.
// (For brevity we use an analytic proxy.)
type jsDetector struct {
	threshold float64
}

func (j *jsDetector) Name() string { return "js_divergence" }

func (j *jsDetector) Detect(baseline, observed FeatureStat) (DriftResult, error) {
	if baseline.StdDev == 0 || observed.StdDev == 0 {
		return DriftResult{}, errors.New("stddev must be > 0 for JS divergence")
	}

	// Proxy: symmetric KL divergence between normals.
	kl1 := klDivergence(baseline, observed)
	kl2 := klDivergence(observed, baseline)
	js := 0.5 * (kl1 + kl2)

	drifted := js > j.threshold
	return DriftResult{
		ModelID:  baseline.ModelID,
		Feature:  baseline.Feature,
		Method:   j.Name(),
		Score:    js,
		Drifted:  drifted,
		Observed: observed,
		Baseline: baseline,
		Details: map[string]float64{
			"kl1": kl1,
			"kl2": kl2,
		},
	}, nil
}

// klDivergence computes KL(N0 || N1) where each is Normal(mu, sigma^2).
func klDivergence(n0, n1 FeatureStat) float64 {
	s0, s1 := n0.StdDev, n1.StdDev
	m0, m1 := n0.Mean, n1.Mean
	return math.Log(s1/s0) + (s0*s0+(m0-m1)*(m0-m1))/(2*s1*s1) - 0.5
}

// ----------------------------------------------------------------------------
// Factory Pattern – Drift Detector Constructor
// ----------------------------------------------------------------------------

// NewDriftDetector returns a configured DriftDetector by strategy name.
func NewDriftDetector(strategy string, sensitivity float64) (DriftDetector, error) {
	switch strategy {
	case "ks":
		return &ksDetector{alpha: sensitivity}, nil
	case "js":
		return &jsDetector{threshold: sensitivity}, nil
	default:
		return nil, fmt.Errorf("unknown drift detector strategy %q", strategy)
	}
}

// ----------------------------------------------------------------------------
// Observer Pattern – Subscribers of Drift Events
// ----------------------------------------------------------------------------

// DriftListener receives DriftResult notifications.
type DriftListener interface {
	OnDrift(ctx context.Context, result DriftResult)
}

// KafkaPublisher publishes drift events to a Kafka topic.
type KafkaPublisher struct {
	writer *kafka.Writer
}

func NewKafkaPublisher(brokers []string, topic string) *KafkaPublisher {
	return &KafkaPublisher{
		writer: &kafka.Writer{
			Addr:     kafka.TCP(brokers...),
			Topic:    topic,
			Balancer: &kafka.LeastBytes{},
		},
	}
}

func (k *KafkaPublisher) OnDrift(ctx context.Context, result DriftResult) {
	payload, err := json.Marshal(result)
	if err != nil {
		log.Printf("kafka publisher marshal error: %v", err)
		return
	}

	msg := kafka.Message{
		Key:   []byte(result.Feature),
		Value: payload,
		Time:  time.Now(),
	}

	if err := k.writer.WriteMessages(ctx, msg); err != nil {
		log.Printf("kafka publisher write error: %v", err)
	}
}

// Close gracefully closes the underlying writer.
func (k *KafkaPublisher) Close() error { return k.writer.Close() }

// ----------------------------------------------------------------------------
// DriftMonitor – Core Orchestrator
// ----------------------------------------------------------------------------

// DriftMonitor coordinates drift detection and notifies listeners.
type DriftMonitor struct {
	mu          sync.RWMutex
	baselines   map[string]FeatureStat // keyed by modelID|feature
	detector    DriftDetector
	listeners   []DriftListener
	baselineTTL time.Duration
}

// NewDriftMonitor builds a new DriftMonitor.
func NewDriftMonitor(det DriftDetector, baselineTTL time.Duration) *DriftMonitor {
	return &DriftMonitor{
		baselines:   make(map[string]FeatureStat),
		detector:    det,
		baselineTTL: baselineTTL,
	}
}

// Subscribe registers observers for drift events.
func (d *DriftMonitor) Subscribe(l DriftListener) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.listeners = append(d.listeners, l)
}

// Ingest consumes an observed FeatureStat and triggers detection.
func (d *DriftMonitor) Ingest(ctx context.Context, fs FeatureStat) {
	key := compositeKey(fs.ModelID, fs.Feature)

	d.mu.Lock()
	baseline, ok := d.baselines[key]
	d.mu.Unlock()

	// If no baseline yet, treat the first window as baseline.
	if !ok {
		d.setBaseline(key, fs)
		return
	}

	// Discard stale baselines.
	if time.Since(baseline.Timestamp) > d.baselineTTL {
		d.setBaseline(key, fs)
		return
	}

	// Apply detector strategy.
	res, err := d.detector.Detect(baseline, fs)
	if err != nil {
		log.Printf("detector error: %v", err)
		return
	}

	// Broadcast results.
	d.broadcast(ctx, res)

	// If drifted, refresh baseline to avoid duplicate alerts.
	if res.Drifted {
		d.setBaseline(key, fs)
	}
}

func (d *DriftMonitor) broadcast(ctx context.Context, res DriftResult) {
	d.mu.RLock()
	defer d.mu.RUnlock()
	for _, l := range d.listeners {
		l.OnDrift(ctx, res)
	}
}

func (d *DriftMonitor) setBaseline(key string, fs FeatureStat) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.baselines[key] = fs
}

func compositeKey(modelID, feature string) string {
	return modelID + "|" + feature
}

// ----------------------------------------------------------------------------
// Kafka Consumer – Feature Statistics Intake
// ----------------------------------------------------------------------------

// StartFeatureStatConsumer launches a goroutine that reads FeatureStat messages
// from Kafka and feeds them into the provided DriftMonitor.
func StartFeatureStatConsumer(
	ctx context.Context,
	brokers []string,
	topic, groupID string,
	monitor *DriftMonitor,
) (func() error, error) {

	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers: brokers,
		Topic:   topic,
		GroupID: groupID,
		MinBytes: 10e3, // 10KB
		MaxBytes: 10e6, // 10MB
	})

	go func() {
		defer reader.Close()
		for {
			m, err := reader.ReadMessage(ctx)
			if err != nil {
				if errors.Is(err, context.Canceled) {
					return
				}
				log.Printf("kafka read error: %v", err)
				continue
			}

			var stat FeatureStat
			if err := json.Unmarshal(m.Value, &stat); err != nil {
				log.Printf("unmarshal feature stat error: %v", err)
				continue
			}

			monitor.Ingest(ctx, stat)
		}
	}()

	// Return a shutdown function.
	return reader.Close, nil
}
```