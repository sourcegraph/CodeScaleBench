```go
// Code generated for EchoPulse — Real-Time Social Signal Processing Platform.
// Module   : Drift Monitor (module_65.go)
// Purpose  : Detect statistical drift in feature distributions that flow
//            through the feature-store topics and publish retraining events
//            when the drift score breaches a configurable threshold.
//
// Patterns : Observer ‑ listens to feature distribution events emitted by
//            the feature-store service.
//            Strategy ‑ encapsulates the drift metric (PSI) implementation
//            behind a function type, so we can easily swap it.
//            Pipeline  ‑ forms one stage in the model-monitoring pipeline.
//
// Author   : EchoPulse Engineering
// License  : Apache-2.0
package drift

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"os"
	"os/signal"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/cenkalti/backoff/v4"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/Shopify/sarama"
	"go.uber.org/zap"
)

// -----------------------------------------------------------------------------
// Domain Models
// -----------------------------------------------------------------------------

// FeatureDistributionEvent is emitted by the feature-store service after it
// aggregates feature values over a fixed window.
type FeatureDistributionEvent struct {
	ModelID      string    `json:"model_id"`
	FeatureName  string    `json:"feature_name"`
	BucketCounts []int64   `json:"bucket_counts"` // equi-width buckets
	Total        int64     `json:"total"`
	BucketEdges  []float64 `json:"bucket_edges"`  // n+1 length
	Baseline     bool      `json:"baseline"`      // true when this event is the reference/baseline
	WindowStart  int64     `json:"window_start"`  // unix millis
	WindowEnd    int64     `json:"window_end"`    // unix millis
}

// DriftEvent is published when drift breaches the threshold.
type DriftEvent struct {
	ModelID     string  `json:"model_id"`
	FeatureName string  `json:"feature_name"`
	Metric      string  `json:"metric"`
	Score       float64 `json:"score"`
	Threshold   float64 `json:"threshold"`
	Timestamp   int64   `json:"timestamp"`
}

// -----------------------------------------------------------------------------
// Config / Monitor
// -----------------------------------------------------------------------------

// DriftMonitorConfig holds runtime parameters for the drift monitor.
type DriftMonitorConfig struct {
	Brokers          []string
	InputTopic       string
	OutputTopic      string
	GroupID          string
	Threshold        float64       // e.g. PSI > 0.2
	Logger           *zap.Logger   // caller can inject; fallback to zap.NewProduction
	PromRegistry     *prometheus.Registry
	CommitInterval   time.Duration // how often to commit offsets
	OffsetReset      string        // "oldest" or "newest"
	SessionTimeout   time.Duration
	RebalanceTimeout time.Duration
}

// DriftMonitor consumes feature distributions, runs the drift detector, and
// emits drift events.
type DriftMonitor struct {
	cfg         DriftMonitorConfig
	consumerGrp sarama.ConsumerGroup
	producer    sarama.SyncProducer
	logger      *zap.Logger

	driftMetric DriftMetric // PSI by default, but pluggable

	// baselineCache maps modelID|featureName -> baseline bucket distribution
	baselineCache sync.Map // key string -> []int64

	evProcessed atomic.Int64
	evDrifted   atomic.Int64

	// Prometheus metrics
	psiGauge          *prometheus.GaugeVec
	driftCounter      *prometheus.CounterVec
	messageLagGauge   prometheus.Gauge
	processingLatency prometheus.Summary
}

// DriftMetric defines the signature of drift metric functions.
type DriftMetric func(baseline, observed []int64) (float64, error)

// NewDriftMonitor builds and initializes a new monitor instance.
func NewDriftMonitor(cfg DriftMonitorConfig) (*DriftMonitor, error) {
	if len(cfg.Brokers) == 0 {
		return nil, errors.New("brokers list must not be empty")
	}
	if cfg.InputTopic == "" || cfg.OutputTopic == "" {
		return nil, errors.New("input and output topics must be provided")
	}
	if cfg.GroupID == "" {
		return nil, errors.New("group id must be provided")
	}

	// Logger
	var logger *zap.Logger
	if cfg.Logger != nil {
		logger = cfg.Logger
	} else {
		l, err := zap.NewProduction()
		if err != nil {
			return nil, err
		}
		logger = l
	}

	// Sarama config
	sc := sarama.NewConfig()
	sc.Version = sarama.V2_5_0_0
	sc.Consumer.Group.Rebalance.Strategy = sarama.BalanceStrategyRange
	sc.Consumer.Return.Errors = true
	sc.Consumer.Offsets.AutoCommit.Enable = true
	if cfg.CommitInterval > 0 {
		sc.Consumer.Offsets.AutoCommit.Interval = cfg.CommitInterval
	}
	switch strings.ToLower(cfg.OffsetReset) {
	case "newest":
		sc.Consumer.Offsets.Initial = sarama.OffsetNewest
	default:
		sc.Consumer.Offsets.Initial = sarama.OffsetOldest
	}
	if cfg.SessionTimeout > 0 {
		sc.Consumer.Group.Session.Timeout = cfg.SessionTimeout
	}
	if cfg.RebalanceTimeout > 0 {
		sc.Consumer.Group.Rebalance.Timeout = cfg.RebalanceTimeout
	}

	sc.Producer.Return.Successes = true
	sc.Producer.Idempotent = true
	sc.Producer.RequiredAcks = sarama.WaitForAll

	consumerGrp, err := sarama.NewConsumerGroup(cfg.Brokers, cfg.GroupID, sc)
	if err != nil {
		return nil, err
	}
	producer, err := sarama.NewSyncProducer(cfg.Brokers, sc)
	if err != nil {
		_ = consumerGrp.Close()
		return nil, err
	}

	m := &DriftMonitor{
		cfg:         cfg,
		consumerGrp: consumerGrp,
		producer:    producer,
		logger:      logger,
		driftMetric: populationStabilityIndex,
	}

	m.initMetrics(cfg.PromRegistry)

	return m, nil
}

// initMetrics registers Prometheus metrics.
func (m *DriftMonitor) initMetrics(reg *prometheus.Registry) {
	m.psiGauge = prometheus.NewGaugeVec(prometheus.GaugeOpts{
		Namespace: "echopulse",
		Subsystem: "drift_monitor",
		Name:      "psi_score",
		Help:      "Computed PSI score of observed distributions.",
	}, []string{"model_id", "feature_name"})

	m.driftCounter = prometheus.NewCounterVec(prometheus.CounterOpts{
		Namespace: "echopulse",
		Subsystem: "drift_monitor",
		Name:      "drift_detected_total",
		Help:      "Count of drift events emitted.",
	}, []string{"model_id", "feature_name"})

	m.messageLagGauge = prometheus.NewGauge(prometheus.GaugeOpts{
		Namespace: "echopulse",
		Subsystem: "drift_monitor",
		Name:      "consumer_lag",
		Help:      "Kafka consumer lag (per-partition sum).",
	})

	m.processingLatency = prometheus.NewSummary(prometheus.SummaryOpts{
		Namespace:  "echopulse",
		Subsystem:  "drift_monitor",
		Name:       "processing_latency_ms",
		Help:       "Latency of processing feature distribution events.",
		MaxAge:     5 * time.Minute,
		Objectives: map[float64]float64{0.5: 0.05, 0.9: 0.01, 0.99: 0.001},
	})

	if reg != nil {
		reg.MustRegister(m.psiGauge, m.driftCounter, m.messageLagGauge, m.processingLatency)
	} else {
		prometheus.MustRegister(m.psiGauge, m.driftCounter, m.messageLagGauge, m.processingLatency)
	}
}

// -----------------------------------------------------------------------------
// Public API
// -----------------------------------------------------------------------------

// Run starts the drift monitor loop. It blocks until ctx is cancelled or a
// fatal error occurs.
func (m *DriftMonitor) Run(ctx context.Context) error {
	defer func() {
		_ = m.consumerGrp.Close()
		_ = m.producer.Close()
	}()

	// trap SIGINT/SIGTERM to trigger a shutdown.
	ctx, cancel := signal.NotifyContext(ctx, syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	handler := &consumerHandler{
		parent: m,
	}

	// Run the group in a dedicated goroutine so we can monitor errors.
	errCh := make(chan error, 1)
	go func() {
		for {
			if err := m.consumerGrp.Consume(ctx, []string{m.cfg.InputTopic}, handler); err != nil {
				errCh <- err
				return
			}
			// check if context was cancelled, signaling that we should shut down
			if ctx.Err() != nil {
				return
			}
		}
	}()

	for {
		select {
		case <-ctx.Done():
			m.logger.Info("drift-monitor received shutdown signal")
			return nil
		case err := <-errCh:
			m.logger.Error("consumer group error", zap.Error(err))
			return err
		case err := <-m.consumerGrp.Errors():
			m.logger.Error("sarama consumer error", zap.Error(err))
		}
	}
}

// -----------------------------------------------------------------------------
// Internal: Consumer Handler
// -----------------------------------------------------------------------------

type consumerHandler struct {
	parent *DriftMonitor
}

func (h *consumerHandler) Setup(_ sarama.ConsumerGroupSession) error   { return nil }
func (h *consumerHandler) Cleanup(_ sarama.ConsumerGroupSession) error { return nil }

// ConsumeClaim processes messages for one partition.
func (h *consumerHandler) ConsumeClaim(sess sarama.ConsumerGroupSession, claim sarama.ConsumerGroupClaim) error {
	for msg := range claim.Messages() {
		start := time.Now()
		if err := h.parent.processMessage(sess.Context(), msg); err != nil {
			h.parent.logger.Error("failed processing message", zap.Error(err))
		} else {
			sess.MarkMessage(msg, "") // commit offset asynchronously
		}
		h.parent.processingLatency.Observe(float64(time.Since(start).Milliseconds()))
	}
	return nil
}

// -----------------------------------------------------------------------------
// Internal: Business Logic
// -----------------------------------------------------------------------------

func (m *DriftMonitor) processMessage(ctx context.Context, msg *sarama.ConsumerMessage) error {
	var ev FeatureDistributionEvent
	if err := json.Unmarshal(msg.Value, &ev); err != nil {
		return err
	}

	key := ev.ModelID + "|" + ev.FeatureName

	// If Baseline flag is set, refresh baseline cache.
	if ev.Baseline {
		m.baselineCache.Store(key, ev.BucketCounts)
		m.logger.Info("baseline updated",
			zap.String("model", ev.ModelID),
			zap.String("feature", ev.FeatureName))
		return nil
	}

	// retrieve baseline
	baseRaw, ok := m.baselineCache.Load(key)
	if !ok {
		// punt — we need a baseline to compare; skip or request baseline?
		m.logger.Warn("no baseline found; skipping",
			zap.String("model", ev.ModelID),
			zap.String("feature", ev.FeatureName))
		return nil
	}
	baseline := baseRaw.([]int64)

	psi, err := m.driftMetric(baseline, ev.BucketCounts)
	if err != nil {
		return err
	}
	m.psiGauge.WithLabelValues(ev.ModelID, ev.FeatureName).Set(psi)
	m.evProcessed.Add(1)

	if psi >= m.cfg.Threshold {
		m.evDrifted.Add(1)
		m.driftCounter.WithLabelValues(ev.ModelID, ev.FeatureName).Inc()

		drift := DriftEvent{
			ModelID:     ev.ModelID,
			FeatureName: ev.FeatureName,
			Metric:      "PSI",
			Score:       psi,
			Threshold:   m.cfg.Threshold,
			Timestamp:   time.Now().UnixMilli(),
		}
		return m.publishDriftEvent(ctx, drift)
	}
	return nil
}

func (m *DriftMonitor) publishDriftEvent(ctx context.Context, ev DriftEvent) error {
	payload, err := json.Marshal(ev)
	if err != nil {
		return err
	}

	msg := &sarama.ProducerMessage{
		Topic: m.cfg.OutputTopic,
		Value: sarama.ByteEncoder(payload),
		Key:   sarama.StringEncoder(ev.ModelID + "|" + ev.FeatureName),
	}

	operation := func() error {
		_, _, err := m.producer.SendMessage(msg)
		return err
	}
	notify := func(err error, t time.Duration) {
		m.logger.Warn("failed to publish drift event; retrying",
			zap.Error(err), zap.Duration("next_retry_in", t))
	}

	backoffCfg := backoff.NewExponentialBackOff()
	backoffCfg.MaxElapsedTime = 30 * time.Second

	return backoff.RetryNotify(operation, backoffCfg, notify)
}

// -----------------------------------------------------------------------------
// Drift Metric Implementations
// -----------------------------------------------------------------------------

// populationStabilityIndex computes PSI using baseline and observed buckets.
// Formula: PSI = Σ ((obs_i – base_i) * ln(obs_i / base_i))
func populationStabilityIndex(baseline, observed []int64) (float64, error) {
	if len(baseline) != len(observed) {
		return 0, errors.New("bucket length mismatch")
	}
	totalBase := sumInt64(baseline)
	totalObs := sumInt64(observed)
	if totalBase == 0 || totalObs == 0 {
		return 0, errors.New("empty distributions")
	}

	var psi float64
	for i := range baseline {
		baseRatio := float64(baseline[i]) / float64(totalBase)
		obsRatio := float64(observed[i]) / float64(totalObs)

		// apply Laplace smoothing to avoid zero ratios
		if baseRatio == 0 {
			baseRatio = 0.0001
		}
		if obsRatio == 0 {
			obsRatio = 0.0001
		}
		psi += (obsRatio - baseRatio) * math.Log(obsRatio/baseRatio)
	}
	return psi, nil
}

func sumInt64(xs []int64) int64 {
	var s int64
	for _, v := range xs {
		s += v
	}
	return s
}

// -----------------------------------------------------------------------------
// Helper: Simple bootstrap when executed as a standalone binary.
// -----------------------------------------------------------------------------

// When this file is built as `drift-monitor` cmd, we allow running directly
// (useful in local docker-compose). For library use, this `main` will be
// trimmed by the linker if not referenced.
func main() {
	if os.Getenv("ECHOPULSE_STANDALONE") == "" {
		// not running in standalone mode
		return
	}

	logger, _ := zap.NewProduction()
	defer logger.Sync()

	cfg := DriftMonitorConfig{
		Brokers:    strings.Split(getEnv("KAFKA_BROKERS", "localhost:9092"), ","),
		InputTopic: getEnv("INPUT_TOPIC", "feature_distributions"),
		OutputTopic: getEnv("OUTPUT_TOPIC",
			"drift_events"),
		GroupID:        getEnv("GROUP_ID", "drift_monitor"),
		Threshold:      getEnvFloat("DRIFT_THRESHOLD", 0.2),
		Logger:         logger,
		CommitInterval: 3 * time.Second,
	}
	monitor, err := NewDriftMonitor(cfg)
	if err != nil {
		logger.Fatal("failed to init monitor", zap.Error(err))
	}

	ctx := context.Background()
	if err := monitor.Run(ctx); err != nil {
		logger.Fatal("monitor exited with error", zap.Error(err))
	}
}

// -----------------------------------------------------------------------------
// Helper functions for env vars
// -----------------------------------------------------------------------------

func getEnv(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}

func getEnvFloat(key string, fallback float64) float64 {
	if v, ok := os.LookupEnv(key); ok {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return fallback
}
```