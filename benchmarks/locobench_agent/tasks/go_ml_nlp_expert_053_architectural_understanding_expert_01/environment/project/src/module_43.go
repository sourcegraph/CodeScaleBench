```go
// File: src/module_43.go
//
// Package monitoring implements online statistical-drift monitoring for model
// inputs and predictions.  It uses the Observer and Strategy patterns to
// decouple drift detection algorithms from downstream reactions (automatic
// retraining, alerting, adaptive sampling, …).
//
// The implementation is Kafka-backed, but the message source is abstracted
// behind a pluggable FeatureStatsSource interface so that the same monitor can
// run against JetStream or any custom collector.
//
// NOTE: this file belongs to the EchoPulse code-base.  Some domain‐specific
// types (e.g. featurestore.FeatureVector) live in sibling packages and are only
// referenced by interface.  This file therefore compiles inside the monorepo
// where those packages exist.
package monitoring

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/trace"
	"go.uber.org/zap"
)

// ============================================================================
// Public domain model
// ============================================================================

// DriftEvent is emitted whenever a statistically significant distribution shift
// is detected between the baseline data set and the current sliding window.
type DriftEvent struct {
	Namespace       string            // e.g. "sentiment.v1.input"
	Feature         string            // feature name inside the vector
	Metric          string            // e.g. "PSI"
	Score           float64           // numeric metric value
	Threshold       float64           // threshold that triggered the event
	ObservedAt      time.Time         // when the shift was observed
	WindowDuration  time.Duration     // size of the sliding window
	AdditionalAttrs map[string]string // free-form diagnostic metadata
}

// DriftObserver is the Observer interface.  Consumers register callbacks to
// receive DriftEvents.
type DriftObserver interface {
	OnDrift(ctx context.Context, evt DriftEvent)
}

// ============================================================================
// Streaming feature stats source abstraction
// ============================================================================

// FeatureStats holds binned frequency counts for a single feature.  Downstream
// algorithms decide how many bins are desirable.
type FeatureStats struct {
	FeatureName string
	Bins        []float64 // absolute frequencies, len(Bins) must match baseline
	Total       float64   // sum(Bins)
	T0          time.Time // beginning of aggregation window
	T1          time.Time // end of aggregation window
}

// FeatureStatsSource delivers batched FeatureStats over a channel.  The
// implementation may wrap a Kafka consumer, JetStream subscription, or any
// other transport layer.
type FeatureStatsSource interface {
	// Stream publishes stats to the returned channel until the context
	// terminates.  Implementations MUST close the channel before returning.
	Stream(ctx context.Context) (<-chan FeatureStats, error)
}

// ============================================================================
// Drift-detection strategy abstraction (Strategy Pattern)
// ============================================================================

// DriftDetectionStrategy decides whether statistical drift occurred between a
// baseline and an observation window.
type DriftDetectionStrategy interface {
	// Detect runs the strategy and returns the metric value along with a
	// boolean flag that indicates if drift is significant.
	Detect(baseline FeatureStats, current FeatureStats) (metric float64, drift bool, err error)

	// Name returns the canonical name of the strategy (e.g. "psi").
	Name() string
}

// PSIThresholdStrategy is a configurable Population-Stability-Index detector.
type PSIThresholdStrategy struct {
	Baseline  FeatureStats // baseline distribution
	Threshold float64      // PSI ≥ Threshold triggers drift
}

// Name implements DriftDetectionStrategy.
func (s *PSIThresholdStrategy) Name() string { return "psi" }

// Detect implements DriftDetectionStrategy.
func (s *PSIThresholdStrategy) Detect(_ FeatureStats, current FeatureStats) (float64, bool, error) {
	if len(s.Baseline.Bins) == 0 ||
		len(s.Baseline.Bins) != len(current.Bins) {
		return 0, false, errors.New("bins length mismatch")
	}

	bTotal := s.Baseline.Total
	cTotal := current.Total
	if bTotal == 0 || cTotal == 0 {
		return 0, false, errors.New("zero total frequency")
	}

	var psi float64
	for i := range s.Baseline.Bins {
		expected := s.Baseline.Bins[i] / bTotal
		actual := current.Bins[i] / cTotal
		if expected == 0 {
			continue // ignore bins that never occur in baseline
		}
		psi += (actual - expected) * math.Log(actual/expected)
	}

	return psi, psi >= s.Threshold, nil
}

// ============================================================================
// DriftMonitor
// ============================================================================

// Config provides runtime customization knobs.
type Config struct {
	Namespace  string        // logical namespace of the feature set
	PollPeriod time.Duration // health-check / liveness probes
	Logger     *zap.Logger   // optional custom logger
	Tracer     trace.Tracer  // optional OpenTelemetry tracer
}

// DriftMonitor orchestrates a source, a strategy, and a set of observers.
type DriftMonitor struct {
	cfg       Config
	source    FeatureStatsSource
	strategy  DriftDetectionStrategy
	observers []DriftObserver

	mu      sync.RWMutex
	running bool
}

// NewDriftMonitor builds a new monitor instance.
func NewDriftMonitor(cfg Config, source FeatureStatsSource, strategy DriftDetectionStrategy) *DriftMonitor {
	if cfg.Logger == nil {
		cfg.Logger = zap.L().Named("drift-monitor")
	}
	if cfg.Tracer == nil {
		cfg.Tracer = otel.Tracer("echopulse/monitoring")
	}

	return &DriftMonitor{
		cfg:      cfg,
		source:   source,
		strategy: strategy,
	}
}

// Register attaches a new observer.  Thread-safe.
func (m *DriftMonitor) Register(obs DriftObserver) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.observers = append(m.observers, obs)
}

// Start launches the monitor loop.  Non-blocking.
func (m *DriftMonitor) Start(ctx context.Context) error {
	m.mu.Lock()
	if m.running {
		m.mu.Unlock()
		return errors.New("monitor already running")
	}
	m.running = true
	m.mu.Unlock()

	statsCh, err := m.source.Stream(ctx)
	if err != nil {
		return err
	}

	go m.run(ctx, statsCh)
	return nil
}

// run is the event loop.
func (m *DriftMonitor) run(ctx context.Context, statsCh <-chan FeatureStats) {
	logger := m.cfg.Logger
	tracer := m.cfg.Tracer
	defer func() {
		logger.Info("drift monitor shutting down")
	}()

	ticker := time.NewTicker(m.cfg.PollPeriod)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case fs, ok := <-statsCh:
			if !ok {
				logger.Warn("stats source closed channel")
				return
			}
			m.process(ctx, fs)
		case <-ticker.C:
			logger.Debug("drift monitor heartbeat", zap.String("namespace", m.cfg.Namespace))
		}
	}
}

// process applies the detection strategy and, if drift is present, notifies
// observers.
func (m *DriftMonitor) process(ctx context.Context, fs FeatureStats) {
	ctx, span := m.cfg.Tracer.Start(ctx, "drift/process", trace.WithAttributes(
		attribute.String("namespace", m.cfg.Namespace),
		attribute.String("feature", fs.FeatureName),
	))
	defer span.End()

	metric, drift, err := m.strategy.Detect(FeatureStats{}, fs) // baseline is embedded in strategy
	if err != nil {
		span.RecordError(err)
		m.cfg.Logger.Error("failed to detect drift", zap.Error(err))
		return
	}

	if !drift {
		return
	}

	evt := DriftEvent{
		Namespace:      m.cfg.Namespace,
		Feature:        fs.FeatureName,
		Metric:         m.strategy.Name(),
		Score:          metric,
		Threshold:      m.strategy.(*PSIThresholdStrategy).Threshold,
		ObservedAt:     time.Now().UTC(),
		WindowDuration: fs.T1.Sub(fs.T0),
		AdditionalAttrs: map[string]string{
			"strategy": m.strategy.Name(),
		},
	}

	// fan-out to observers
	m.mu.RLock()
	defer m.mu.RUnlock()
	for _, obs := range m.observers {
		obs.OnDrift(ctx, evt)
	}
}

// ============================================================================
// Kafka implementation of FeatureStatsSource
// ============================================================================

// KafkaStatsSource consumes a compacted topic where each message contains a
// FeatureStats payload in JSON format.
//
// Topic layout: key = feature_name, value = FeatureStats JSON, partitioned by
// feature to guarantee in-order updates.
type KafkaStatsSource struct {
	Reader *kafka.Reader
	Logger *zap.Logger
}

// NewKafkaStatsSource constructs a new KafkaStatsSource.
func NewKafkaStatsSource(brokers []string, topic string, groupID string, logger *zap.Logger) *KafkaStatsSource {
	if logger == nil {
		logger = zap.L().Named("kafka-stats-source")
	}

	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:  brokers,
		Topic:    topic,
		GroupID:  groupID,
		MinBytes: 10e3,  // 10KB
		MaxBytes: 10e6,  // 10MB
	})
	return &KafkaStatsSource{
		Reader: reader,
		Logger: logger,
	}
}

// Stream implements FeatureStatsSource.
func (k *KafkaStatsSource) Stream(ctx context.Context) (<-chan FeatureStats, error) {
	out := make(chan FeatureStats, 64)

	go func() {
		defer close(out)
		for {
			m, err := k.Reader.FetchMessage(ctx)
			if err != nil {
				if errors.Is(err, context.Canceled) {
					return
				}
				k.Logger.Error("failed to fetch kafka message", zap.Error(err))
				time.Sleep(time.Second) // crude back-off
				continue
			}

			var fs FeatureStats
			if err := json.Unmarshal(m.Value, &fs); err != nil {
				k.Logger.Error("failed to unmarshal feature stats", zap.Error(err))
				continue
			}

			select {
			case out <- fs:
			case <-ctx.Done():
				return
			}

			if err := k.Reader.CommitMessages(ctx, m); err != nil {
				k.Logger.Warn("failed to commit message", zap.Error(err))
			}
		}
	}()

	return out, nil
}

// Close releases underlying resources.
func (k *KafkaStatsSource) Close() error {
	return k.Reader.Close()
}
```