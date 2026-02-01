package monitoring

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"time"

	"go.uber.org/zap"
	"gonum.org/v1/gonum/stat/distuv"
)

// ========= Interfaces =======================================================

// BusConsumer defines the minimal contract for a message-bus consumer.
// It intentionally mirrors the subset of the sarama.ConsumerGroup interface
// that we actually need, which makes the implementation easily swappable
// for Kafka, NATS JetStream, in-memory mocks, etc.
type BusConsumer interface {
	Consume(ctx context.Context, topics []string, handler MessageHandler) error
	Close() error
}

// MessageHandler is called by the BusConsumer for every new message.
type MessageHandler func(ctx context.Context, raw []byte, ts time.Time) error

// FeatureStore provides access to persistent reference distributions that were
// calculated during model training/validation.  This abstraction hides the
// implementation details (SQL, S3, in-memory, …).
type FeatureStore interface {
	GetReferenceDistribution(model, feature string) (map[string]float64, error)
}

// EventEmitter delivers DriftEvents to downstream services (observability
// dashboards, alerting brokers, retraining pipelines, …).
type EventEmitter interface {
	EmitDriftEvent(ctx context.Context, evt DriftEvent) error
}

// ========= Public Types =====================================================

// DriftEvent is published whenever the statistical divergence between the
// observed and reference distributions crosses the configured alpha.
// Downstream consumers may decide to escalate, trigger retraining, etc.
type DriftEvent struct {
	Model               string             `json:"model"`
	Feature             string             `json:"feature"`
	WindowStart         time.Time          `json:"window_start"`
	WindowEnd           time.Time          `json:"window_end"`
	ObservedCounts      map[string]int64   `json:"observed_counts"`
	ReferenceProbs      map[string]float64 `json:"reference_probs"`
	ChiSquareStatistic  float64            `json:"chi_square_statistic"`
	PValue              float64            `json:"p_value"`
	SignificanceWarning bool               `json:"significance_warning"`
}

// DriftMonitorConfig drives the runtime behavior of the monitor.
type DriftMonitorConfig struct {
	ModelName   string        // Name of the model we are monitoring
	Feature     string        // Name of the categorical output feature (e.g. "sentiment")
	Topic       string        // Kafka/NATS topic carrying predictions
	WindowSize  time.Duration // Sliding window length
	BucketSize  time.Duration // Granularity of time buckets inside the window
	MinSamples  int           // Minimum n to calculate drift
	Alpha       float64       // Significance level for chi-square test (e.g. 0.05)
	Logger      *zap.Logger   // Optional; falls back to zap.NewNop()
}

// ========= Implementation ===================================================

// DriftMonitor consumes model predictions in real time, aggregates them into a
// sliding window, compares the observed class distribution with the reference
// distribution fetched from the FeatureStore, and emits DriftEvents whenever
// statistical drift is detected with significance < alpha.
type DriftMonitor struct {
	cfg          DriftMonitorConfig
	bus          BusConsumer
	fs           FeatureStore
	emitter      EventEmitter
	mu           sync.RWMutex                   // protects buckets
	buckets      map[int64]map[string]int64     // epoch bucket -> class -> count
	totalPerBuck map[int64]int64                // epoch bucket -> total count
	logger       *zap.Logger
}

// NewDriftMonitor wires together a new monitor instance.
func NewDriftMonitor(cfg DriftMonitorConfig, bus BusConsumer, fs FeatureStore, emitter EventEmitter) (*DriftMonitor, error) {
	if cfg.WindowSize <= 0 || cfg.BucketSize <= 0 {
		return nil, errors.New("window and bucket durations must be > 0")
	}
	if cfg.WindowSize%cfg.BucketSize != 0 {
		return nil, errors.New("window size must be a multiple of bucket size")
	}
	if cfg.Alpha <= 0 || cfg.Alpha >= 1 {
		return nil, errors.New("alpha must be in (0,1)")
	}
	if cfg.Logger == nil {
		cfg.Logger = zap.NewNop()
	}

	return &DriftMonitor{
		cfg:          cfg,
		bus:          bus,
		fs:           fs,
		emitter:      emitter,
		buckets:      make(map[int64]map[string]int64),
		totalPerBuck: make(map[int64]int64),
		logger:       cfg.Logger,
	}, nil
}

// Start blocks until ctx is canceled or the BusConsumer stops with error.
func (dm *DriftMonitor) Start(ctx context.Context) error {
	dm.logger.Info("starting drift monitor",
		zap.String("model", dm.cfg.ModelName),
		zap.String("feature", dm.cfg.Feature),
		zap.String("topic", dm.cfg.Topic))

	// Start periodic evaluator.
	go dm.evaluationLoop(ctx)

	// Attach consumer handler.
	handler := func(c context.Context, raw []byte, ts time.Time) error {
		return dm.handleMessage(raw, ts)
	}

	// This blocks until ctx.Done() or an error occurs.
	if err := dm.bus.Consume(ctx, []string{dm.cfg.Topic}, handler); err != nil && !errors.Is(err, context.Canceled) {
		return fmt.Errorf("bus consume failed: %w", err)
	}
	return nil
}

func (dm *DriftMonitor) handleMessage(raw []byte, ts time.Time) error {
	var envelope struct {
		Sentiment string `json:"sentiment"` // e.g., "positive", "neutral", "negative"
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		dm.logger.Warn("failed to unmarshal prediction", zap.Error(err))
		return nil // swallow to keep pipeline alive
	}
	if envelope.Sentiment == "" {
		return nil
	}

	bucket := ts.Unix() / int64(dm.cfg.BucketSize.Seconds())

	dm.mu.Lock()
	defer dm.mu.Unlock()

	if _, ok := dm.buckets[bucket]; !ok {
		dm.buckets[bucket] = make(map[string]int64)
	}
	dm.buckets[bucket][envelope.Sentiment]++
	dm.totalPerBuck[bucket]++
	return nil
}

// evaluationLoop runs a ticker that fires every BucketSize, sliding the window
// and computing the chi-square drift metric.
func (dm *DriftMonitor) evaluationLoop(ctx context.Context) {
	ticker := time.NewTicker(dm.cfg.BucketSize)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			if err := dm.evaluateAndEmit(ctx); err != nil {
				dm.logger.Error("evaluation failed", zap.Error(err))
			}
		case <-ctx.Done():
			return
		}
	}
}

func (dm *DriftMonitor) evaluateAndEmit(ctx context.Context) error {
	// Determine window range
	end := time.Now()
	start := end.Add(-dm.cfg.WindowSize)

	startBucket := start.Unix() / int64(dm.cfg.BucketSize.Seconds())
	endBucket := end.Unix() / int64(dm.cfg.BucketSize.Seconds())

	// Aggregate counts inside window
	dm.mu.RLock()
	defer dm.mu.RUnlock()

	observed := make(map[string]int64)
	var total int64
	for b := startBucket; b <= endBucket; b++ {
		cnt := dm.buckets[b]
		for class, n := range cnt {
			observed[class] += n
			total += n
		}
	}

	if int(total) < dm.cfg.MinSamples {
		dm.logger.Debug("skip drift eval, not enough samples", zap.Int64("total", total))
		return nil
	}

	// Reference distribution
	refProbs, err := dm.fs.GetReferenceDistribution(dm.cfg.ModelName, dm.cfg.Feature)
	if err != nil {
		return fmt.Errorf("feature store: %w", err)
	}
	if len(refProbs) == 0 {
		return errors.New("reference distribution is empty")
	}

	chiSquare, pValue := chiSquareTest(observed, refProbs, total)

	evt := DriftEvent{
		Model:               dm.cfg.ModelName,
		Feature:             dm.cfg.Feature,
		WindowStart:         start,
		WindowEnd:           end,
		ObservedCounts:      observed,
		ReferenceProbs:      refProbs,
		ChiSquareStatistic:  chiSquare,
		PValue:              pValue,
		SignificanceWarning: pValue < dm.cfg.Alpha,
	}

	// Emit event
	if err := dm.emitter.EmitDriftEvent(ctx, evt); err != nil {
		return fmt.Errorf("emit: %w", err)
	}

	dm.logger.Debug("drift evaluated",
		zap.Float64("chi_square", chiSquare),
		zap.Float64("p_value", pValue),
		zap.Bool("warning", evt.SignificanceWarning))

	// Garbage collection of old buckets
	go dm.gcOldBuckets(startBucket)

	return nil
}

func (dm *DriftMonitor) gcOldBuckets(keepFrom int64) {
	dm.mu.Lock()
	defer dm.mu.Unlock()
	for b := range dm.buckets {
		if b < keepFrom {
			delete(dm.buckets, b)
			delete(dm.totalPerBuck, b)
		}
	}
}

// ========= Statistics Helpers ==============================================

// chiSquareTest returns the chi-square statistic and two-tailed p-value.
func chiSquareTest(observed map[string]int64, refProbs map[string]float64, total int64) (float64, float64) {
	var chiSquare float64
	var k int // degrees of freedom

	for class, expProb := range refProbs {
		exp := float64(total) * expProb
		obs := float64(observed[class])
		if exp == 0 {
			// skip zero expected counts (not enough data for that class)
			continue
		}
		diff := obs - exp
		chiSquare += diff * diff / exp
		k++
	}

	// If no degrees of freedom, p-value is 1
	if k == 0 {
		return 0, 1
	}

	dist := distuv.ChiSquared{K: float64(k - 1)}
	pValue := 1 - dist.CDF(chiSquare)
	return chiSquare, pValue
}