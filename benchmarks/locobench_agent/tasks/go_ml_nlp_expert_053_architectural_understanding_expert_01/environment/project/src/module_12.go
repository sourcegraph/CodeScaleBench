```go
// File: src/module_12.go
//
// EchoPulse – Real-Time Social Signal Processing Platform
//
// Module 12: DriftMonitor
// -----------------------
// DriftMonitor is responsible for watching live model-serving metrics coming
// from Kafka (or NATS JetStream) and triggering automated retraining pipelines
// when statistical drift is detected.  It demonstrates usage of the Observer
// and Strategy patterns, shows how to integrate with Prometheus for metrics,
// and publishes re-train requests back onto the event bus so that the
// Model-Orchestrator service can pick them up.
//
// Author: EchoPulse Engineering
// License: Apache-2.0

package mlnlp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
	"github.com/prometheus/client_golang/prometheus"
)

// ------------------------------------------------------------------
// Configuration
// ------------------------------------------------------------------

// DriftMonitorConfig parameterises a DriftMonitor instance.
type DriftMonitorConfig struct {
	BootstrapServers   []string      // Kafka brokers
	MetricsTopic       string        // topic producing model-serving metrics
	RetrainTopic       string        // topic to publish retrain requests to
	ConsumerGroupID    string        // kafka consumer group
	WorkerPoolSize     int           // number of concurrent metric-workers
	DriftThreshold     float64       // PSI threshold triggering retrain
	MaxBatchAge        time.Duration // how long to buffer messages before flush
	FlushBatchSize     int           // maximum buffered messages
	InstrumentationNS  string        // Prometheus namespace
	Logger             Logger        // pluggable logger, may be nil
}

// Validate verifies the config is sane.
func (c DriftMonitorConfig) Validate() error {
	if len(c.BootstrapServers) == 0 {
		return errors.New("bootstrap servers required")
	}
	if c.MetricsTopic == "" || c.RetrainTopic == "" {
		return errors.New("both MetricsTopic and RetrainTopic required")
	}
	if c.WorkerPoolSize <= 0 {
		c.WorkerPoolSize = 4 // sensible default
	}
	if c.DriftThreshold <= 0 {
		c.DriftThreshold = 0.25
	}
	if c.MaxBatchAge <= 0 {
		c.MaxBatchAge = 3 * time.Second
	}
	if c.FlushBatchSize <= 0 {
		c.FlushBatchSize = 256
	}
	if c.InstrumentationNS == "" {
		c.InstrumentationNS = "echopulse"
	}
	return nil
}

// ------------------------------------------------------------------
// Contracts & Types
// ------------------------------------------------------------------

// Logger is small interface to decouple from a concrete logging lib.
type Logger interface {
	Infof(string, ...interface{})
	Errorf(string, ...interface{})
	Debugf(string, ...interface{})
}

// MetricsPayload is the incoming Kafka message value describing latest
// serving-time statistics of a model version.
type MetricsPayload struct {
	ModelID       string            `json:"model_id"`
	ModelVersion  string            `json:"model_version"`
	FeatureDrifts map[string]Bucket `json:"feature_drifts"`
	Timestamp     int64             `json:"timestamp"` // unix millis
}

// Bucket describes observed vs expected histogram for one feature.
type Bucket struct {
	Expected []float64 `json:"expected"`
	Observed []float64 `json:"observed"`
}

// RetrainRequest encapsulates a single retrain event.
type RetrainRequest struct {
	ModelID         string  `json:"model_id"`
	CurrentVersion  string  `json:"current_version"`
	DriftMagnitude  float64 `json:"drift_magnitude"`
	TriggeredAt     int64   `json:"triggered_at"`
	Reason          string  `json:"reason"`
	CorrelationID   string  `json:"correlation_id"`
}

// ------------------------------------------------------------------
// DriftMonitor
// ------------------------------------------------------------------

// DriftMonitor consumes MetricsPayload, computes drift, and triggers retrain.
type DriftMonitor struct {
	cfg     DriftMonitorConfig
	reader  *kafka.Reader
	writer  *kafka.Writer
	ctx     context.Context
	cancel  context.CancelFunc
	wg      sync.WaitGroup
	metrics struct {
		driftGauge         *prometheus.GaugeVec
		retrainCounter     *prometheus.CounterVec
		processingDuration prometheus.Histogram
	}
}

// NewDriftMonitor constructs and validates a DriftMonitor.
func NewDriftMonitor(cfg DriftMonitorConfig) (*DriftMonitor, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	// Prometheus instrumentation objects.
	dm := &DriftMonitor{cfg: cfg}
	dm.ctx, dm.cancel = context.WithCancel(context.Background())
	dm.metrics.driftGauge = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: cfg.InstrumentationNS,
			Subsystem: "drift_monitor",
			Name:      "psi",
			Help:      "Population Stability Index per model",
		},
		[]string{"model_id"},
	)
	dm.metrics.retrainCounter = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: cfg.InstrumentationNS,
			Subsystem: "drift_monitor",
			Name:      "retrain_total",
			Help:      "Total retrain events triggered",
		},
		[]string{"model_id"},
	)
	dm.metrics.processingDuration = prometheus.NewHistogram(
		prometheus.HistogramOpts{
			Namespace: cfg.InstrumentationNS,
			Subsystem: "drift_monitor",
			Name:      "processing_seconds",
			Help:      "Time spent processing metric messages",
			Buckets:   prometheus.DefBuckets,
		},
	)

	// Register metrics; ignore already registered errors.
	_ = prometheus.Register(dm.metrics.driftGauge)
	_ = prometheus.Register(dm.metrics.retrainCounter)
	_ = prometheus.Register(dm.metrics.processingDuration)

	// Kafka reader and writer.
	dm.reader = kafka.NewReader(kafka.ReaderConfig{
		Brokers:        cfg.BootstrapServers,
		GroupID:        cfg.ConsumerGroupID,
		Topic:          cfg.MetricsTopic,
		MinBytes:       10e3,  // 10KB
		MaxBytes:       10e6,  // 10MB
		MaxWait:        250 * time.Millisecond,
		CommitInterval: 0, // synchronous commit
	})
	dm.writer = &kafka.Writer{
		Addr:         kafka.TCP(cfg.BootstrapServers...),
		Topic:        cfg.RetrainTopic,
		RequiredAcks: kafka.RequireAll,
		Async:        true,
		BatchTimeout: 500 * time.Millisecond,
	}

	return dm, nil
}

// Start launches the processing goroutines.
func (d *DriftMonitor) Start() {
	for i := 0; i < d.cfg.WorkerPoolSize; i++ {
		d.wg.Add(1)
		go d.workerLoop(i)
	}
	if d.cfg.Logger != nil {
		d.cfg.Logger.Infof("DriftMonitor started with %d workers", d.cfg.WorkerPoolSize)
	}
}

// Stop shuts down the monitor gracefully.
func (d *DriftMonitor) Stop(ctx context.Context) error {
	if d.cfg.Logger != nil {
		d.cfg.Logger.Infof("DriftMonitor shutting down")
	}
	d.cancel()
	stopped := make(chan struct{})
	go func() {
		d.wg.Wait()
		stopped <- struct{}{}
	}()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-stopped:
	}
	if err := d.reader.Close(); err != nil {
		return fmt.Errorf("reader close: %w", err)
	}
	if err := d.writer.Close(); err != nil {
		return fmt.Errorf("writer close: %w", err)
	}
	return nil
}

// workerLoop consumes messages and processes them.
func (d *DriftMonitor) workerLoop(workerID int) {
	defer d.wg.Done()
	for {
		m, err := d.reader.ReadMessage(d.ctx)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return
			}
			if d.cfg.Logger != nil {
				d.cfg.Logger.Errorf("worker %d read error: %v", workerID, err)
			}
			continue
		}
		start := time.Now()
		if err := d.handleMessage(m); err != nil && d.cfg.Logger != nil {
			d.cfg.Logger.Errorf("handleMessage error: %v", err)
		}
		d.metrics.processingDuration.Observe(time.Since(start).Seconds())
	}
}

// handleMessage parses the Kafka message and decides whether to trigger retrain.
func (d *DriftMonitor) handleMessage(m kafka.Message) error {
	var payload MetricsPayload
	if err := json.Unmarshal(m.Value, &payload); err != nil {
		return fmt.Errorf("unmarshal MetricsPayload: %w", err)
	}

	// Compute aggregate drift across all features.
	var psiSum float64
	var count int
	for _, bucket := range payload.FeatureDrifts {
		psiSum += populationStabilityIndex(bucket.Expected, bucket.Observed)
		count++
	}
	if count == 0 {
		return errors.New("empty feature drift data")
	}
	avgPSI := psiSum / float64(count)
	d.metrics.driftGauge.WithLabelValues(payload.ModelID).Set(avgPSI)

	if d.cfg.Logger != nil {
		d.cfg.Logger.Debugf("model=%s version=%s avgPSI=%.4f", payload.ModelID, payload.ModelVersion, avgPSI)
	}

	// Determine if retrain is needed.
	if avgPSI >= d.cfg.DriftThreshold {
		req := RetrainRequest{
			ModelID:        payload.ModelID,
			CurrentVersion: payload.ModelVersion,
			DriftMagnitude: avgPSI,
			TriggeredAt:    time.Now().UnixMilli(),
			Reason:         fmt.Sprintf("PSI above threshold (%.2f >= %.2f)", avgPSI, d.cfg.DriftThreshold),
			CorrelationID:  fmt.Sprintf("%s_%d", payload.ModelID, m.Offset),
		}
		b, _ := json.Marshal(&req)
		msg := kafka.Message{
			Key:   []byte(req.ModelID),
			Value: b,
		}
		if err := d.writer.WriteMessages(d.ctx, msg); err != nil {
			return fmt.Errorf("write retrain request: %w", err)
		}
		d.metrics.retrainCounter.WithLabelValues(req.ModelID).Inc()
		if d.cfg.Logger != nil {
			d.cfg.Logger.Infof("Triggered retrain for %s (PSI=%.3f)", req.ModelID, avgPSI)
		}
	}
	return nil
}

// populationStabilityIndex computes PSI between expected and observed histograms.
// It returns math.NaN() if arrays have different sizes or contain invalid values.
//
// Note: In production, you might move this to its own math/stats package and
// use higher precision numerics.  Here we apply a pragmatic approach.
func populationStabilityIndex(expected, observed []float64) float64 {
	if len(expected) != len(observed) || len(expected) == 0 {
		return math.NaN()
	}

	var psi float64
	for i, e := range expected {
		o := observed[i]
		if e <= 0 || o <= 0 {
			continue // skip zero buckets to avoid divide-by-zero/log
		}
		psi += (o - e) * math.Log(o/e)
	}
	return psi
}
```