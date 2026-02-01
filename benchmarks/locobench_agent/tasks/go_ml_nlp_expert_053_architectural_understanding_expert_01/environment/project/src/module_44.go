```go
// src/module_44.go
//
// EchoPulse – Real-Time Social Signal Processing Platform
//
// Module 44: ModelDriftWatcher
//
// Overview
// --------
// The ModelDriftWatcher is a long-running pipeline stage responsible for on-line
// distribution-shift detection for any model that emits prediction or feature
// telemetry.  The service pulls a continuous prediction stream from the event
// bus, maintains reference/production windows, applies a configurable statistical
// test (KL-Divergence or PSI), and publishes a “drift detected” event once a
// threshold is crossed.
//
// The implementation showcases several architectural patterns employed by
// EchoPulse:
//
//   * Observer Pattern  – Kafka consumer/producer react to bus events.
//   * Strategy Pattern  – Pluggable statistical tests via `DistributionTester`.
//   * Pipeline Pattern  – Can be composed with other stages via the event bus.
//   * Robust MLOps Loop – Feeds drift signals to the model registry for automated
//                         retraining or shadow-deployment.
//
// Production-quality details included:
//   * Context-cancellation + graceful shutdown
//   * Structured logging
//   * Metrics counters (prometheus)
//   * Exhaustive error handling
//   * Dependency inversion for easier unit-testing
//
package drift

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
	"github.com/prometheus/client_golang/prometheus"
	"go.uber.org/zap"
)

// ----------------------------------------------------------------------------
// Domain Types
// ----------------------------------------------------------------------------

// PredictionEvent is the canonical telemetry emitted by inference services.
type PredictionEvent struct {
	ModelID    string    `json:"model_id"`
	Prediction float64   `json:"prediction"`
	Timestamp  time.Time `json:"ts"`
}

// DriftEvent captures the metadata broadcast when a model violates shift
// thresholds.
type DriftEvent struct {
	ModelID       string    `json:"model_id"`
	Metric        string    `json:"metric"`
	Score         float64   `json:"score"`
	Threshold     float64   `json:"threshold"`
	WindowSize    int       `json:"window_size"`
	ProductionAge time.Time `json:"production_window_start"`
	DetectedAt    time.Time `json:"detected_at"`
}

// DistributionTester is a Strategy that measures distance between two
// distributions.
type DistributionTester interface {
	MetricName() string
	Compute(reference, production []float64) (float64, error)
}

// ----------------------------------------------------------------------------
// Strategy Implementations
// ----------------------------------------------------------------------------

// KLDivergenceTester implements symmetric KL divergence on discretized bins
// under the assumption of pre–normalized histograms.
type KLDivergenceTester struct{}

func (KLDivergenceTester) MetricName() string { return "KL_DIVERGENCE" }

// Compute returns symmetric KL divergence between the two distributions.
func (KLDivergenceTester) Compute(ref, prod []float64) (float64, error) {
	if len(ref) != len(prod) {
		return 0, errors.New("kl: reference and production vectors differ in length")
	}
	var forward, reverse float64
	eps := 1e-12
	for i := range ref {
		r := math.Max(ref[i], eps)
		p := math.Max(prod[i], eps)

		forward += r * math.Log(r/p)
		reverse += p * math.Log(p/r)
	}
	return 0.5 * (forward + reverse), nil
}

// PSITester implements the Population Stability Index on equal-width bins.
type PSITester struct{}

func (PSITester) MetricName() string { return "PSI" }

func (PSITester) Compute(ref, prod []float64) (float64, error) {
	if len(ref) != len(prod) {
		return 0, errors.New("psi: reference and production vectors differ in length")
	}
	var psi float64
	eps := 1e-12
	for i := range ref {
		r := math.Max(ref[i], eps)
		p := math.Max(prod[i], eps)

		psi += (p - r) * math.Log(p/r)
	}
	return psi, nil
}

// ----------------------------------------------------------------------------
// Kafka Facade (simplified)
// ----------------------------------------------------------------------------

// EventBus allows unit-tests to stub Kafka without gnarly mocks.
type EventBus interface {
	Consume(ctx context.Context) (<-chan kafka.Message, error)
	Publish(ctx context.Context, key string, value []byte) error
	Close() error
}

// kafkaBus is a thin wrapper around segmentio/kafka-go reader/writer.
type kafkaBus struct {
	reader *kafka.Reader
	writer *kafka.Writer
}

func NewKafkaBus(brokers []string, consumerTopic, producerTopic, groupID string) EventBus {
	return &kafkaBus{
		reader: kafka.NewReader(kafka.ReaderConfig{
			Brokers: brokers,
			Topic:   consumerTopic,
			GroupID: groupID,
		}),
		writer: &kafka.Writer{
			Addr:     kafka.TCP(brokers...),
			Topic:    producerTopic,
			Balancer: &kafka.LeastBytes{},
		},
	}
}

func (b *kafkaBus) Consume(ctx context.Context) (<-chan kafka.Message, error) {
	ch := make(chan kafka.Message)
	go func() {
		defer close(ch)
		for {
			msg, err := b.reader.ReadMessage(ctx)
			if err != nil {
				return // ctx cancelled or fatal error
			}
			ch <- msg
		}
	}()
	return ch, nil
}

func (b *kafkaBus) Publish(ctx context.Context, key string, value []byte) error {
	return b.writer.WriteMessages(ctx, kafka.Message{
		Key:   []byte(key),
		Value: value,
		Time:  time.Now(),
	})
}

func (b *kafkaBus) Close() error {
	if err := b.reader.Close(); err != nil {
		return err
	}
	return b.writer.Close()
}

// ----------------------------------------------------------------------------
// Watcher Configuration
// ----------------------------------------------------------------------------

type DriftWatcherConfig struct {
	Brokers        []string
	ConsumerTopic  string
	ProducerTopic  string
	GroupID        string
	WindowSize     int           // sliding window length
	Threshold      float64       // alarm threshold
	GracePeriod    time.Duration // wait before responding to first events
	BinCount       int           // histogram bins for tester
	Tester         string        // "kl" or "psi"
	L              *zap.Logger
	MetricsEnabled bool
}

// ----------------------------------------------------------------------------
// Internal helpers
// ----------------------------------------------------------------------------

type window struct {
	samples []float64
	mu      sync.RWMutex
}

func newWindow(size int) *window {
	return &window{samples: make([]float64, 0, size)}
}

func (w *window) add(v float64) {
	w.mu.Lock()
	defer w.mu.Unlock()

	if len(w.samples) == cap(w.samples) {
		// drop the oldest
		w.samples = w.samples[1:]
	}
	w.samples = append(w.samples, v)
}

func (w *window) snapshot() []float64 {
	w.mu.RLock()
	defer w.mu.RUnlock()
	out := make([]float64, len(w.samples))
	copy(out, w.samples)
	return out
}

// histogram converts raw floats into equal-width histogram counts that sum to 1
func histogram(vals []float64, bins int) []float64 {
	if len(vals) == 0 {
		return make([]float64, bins)
	}
	min, max := vals[0], vals[0]
	for _, v := range vals {
		if v < min {
			min = v
		}
		if v > max {
			max = v
		}
	}
	// degenerate
	if math.Abs(max-min) < 1e-9 {
		hist := make([]float64, bins)
		hist[0] = 1.0
		return hist
	}
	binSize := (max - min) / float64(bins)
	hist := make([]float64, bins)
	for _, v := range vals {
		idx := int(math.Min(float64(bins-1), math.Floor((v-min)/binSize)))
		hist[idx]++
	}
	// normalize
	for i := range hist {
		hist[i] /= float64(len(vals))
	}
	return hist
}

// ----------------------------------------------------------------------------
// Prometheus metrics
// ----------------------------------------------------------------------------

var (
	driftMetric = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "echopulse_drift_score",
			Help: "Latest drift metric for a model",
		},
		[]string{"model_id", "metric"},
	)
	driftEventCounter = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "echopulse_drift_events_total",
			Help: "Number of drift events published",
		},
		[]string{"model_id"},
	)
)

func init() {
	prometheus.MustRegister(driftMetric, driftEventCounter)
}

// ----------------------------------------------------------------------------
// ModelDriftWatcher
// ----------------------------------------------------------------------------

// ModelDriftWatcher orchestrates drift detection.
type ModelDriftWatcher struct {
	cfg    DriftWatcherConfig
	bus    EventBus
	tester DistributionTester
	refWin *window
	prodWin *window
}

// NewModelDriftWatcher wires dependencies.
func NewModelDriftWatcher(cfg DriftWatcherConfig) (*ModelDriftWatcher, error) {
	if cfg.WindowSize <= 1 {
		return nil, errors.New("drift watcher: window size must be >1")
	}
	var tester DistributionTester
	switch cfg.Tester {
	case "kl":
		tester = KLDivergenceTester{}
	case "psi":
		tester = PSITester{}
	default:
		return nil, errors.New("drift watcher: unknown tester " + cfg.Tester)
	}

	if cfg.L == nil {
		cfg.L = zap.NewNop()
	}

	bus := NewKafkaBus(cfg.Brokers, cfg.ConsumerTopic, cfg.ProducerTopic, cfg.GroupID)

	return &ModelDriftWatcher{
		cfg:     cfg,
		bus:     bus,
		tester:  tester,
		refWin:  newWindow(cfg.WindowSize),
		prodWin: newWindow(cfg.WindowSize),
	}, nil
}

// Run blocks until ctx is cancelled or a fatal error happens.
func (w *ModelDriftWatcher) Run(ctx context.Context) error {
	msgCh, err := w.bus.Consume(ctx)
	if err != nil {
		return err
	}

	// Grace period – accumulate reference window.
	w.cfg.L.Info("drift watcher started, warming up", zap.Duration("grace", w.cfg.GracePeriod))
	graceCtx, cancel := context.WithTimeout(ctx, w.cfg.GracePeriod)
	defer cancel()
	if err := w.bootstrapReference(graceCtx, msgCh); err != nil {
		return err
	}
	w.cfg.L.Info("reference window bootstrapped", zap.Int("size", w.cfg.WindowSize))

	// Main loop
	for {
		select {
		case <-ctx.Done():
			_ = w.bus.Close()
			return ctx.Err()
		case msg, ok := <-msgCh:
			if !ok {
				return errors.New("consumer channel closed unexpectedly")
			}
			if err := w.handleMessage(ctx, msg); err != nil {
				w.cfg.L.Error("failed handling message", zap.Error(err))
			}
		}
	}
}

// bootstrapReference fills the reference window before drift checks begin.
func (w *ModelDriftWatcher) bootstrapReference(ctx context.Context, msgCh <-chan kafka.Message) error {
	for len(w.refWin.snapshot()) < w.cfg.WindowSize {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case msg := <-msgCh:
			var evt PredictionEvent
			if err := json.Unmarshal(msg.Value, &evt); err != nil {
				w.cfg.L.Warn("malformed prediction event", zap.Error(err))
				continue
			}
			w.refWin.add(evt.Prediction)
		}
	}
	return nil
}

func (w *ModelDriftWatcher) handleMessage(ctx context.Context, msg kafka.Message) error {
	var evt PredictionEvent
	if err := json.Unmarshal(msg.Value, &evt); err != nil {
		return err
	}

	// slide production window
	w.prodWin.add(evt.Prediction)

	// need both windows filled
	if len(w.prodWin.snapshot()) < w.cfg.WindowSize {
		return nil
	}

	score, err := w.evaluate()
	if err != nil {
		return err
	}

	labels := prometheus.Labels{
		"model_id": evt.ModelID,
		"metric":   w.tester.MetricName(),
	}
	driftMetric.With(labels).Set(score)

	if score > w.cfg.Threshold {
		w.cfg.L.Warn("drift detected",
			zap.String("model", evt.ModelID),
			zap.Float64("score", score),
			zap.Float64("threshold", w.cfg.Threshold))

		if w.cfg.MetricsEnabled {
			driftEventCounter.With(prometheus.Labels{"model_id": evt.ModelID}).Inc()
		}

		event := DriftEvent{
			ModelID:       evt.ModelID,
			Metric:        w.tester.MetricName(),
			Score:         score,
			Threshold:     w.cfg.Threshold,
			WindowSize:    w.cfg.WindowSize,
			ProductionAge: time.Now().Add(-1 * time.Duration(w.cfg.WindowSize) * time.Second),
			DetectedAt:    time.Now(),
		}
		payload, _ := json.Marshal(event) // guaranteed marshable
		if err := w.bus.Publish(ctx, evt.ModelID, payload); err != nil {
			return err
		}
		// Swap windows: current prod becomes new reference to avoid duplicate alerts
		w.swapWindows()
	}

	return nil
}

func (w *ModelDriftWatcher) evaluate() (float64, error) {
	refHist := histogram(w.refWin.snapshot(), w.cfg.BinCount)
	prodHist := histogram(w.prodWin.snapshot(), w.cfg.BinCount)
	return w.tester.Compute(refHist, prodHist)
}

// swapWindows resets production window and makes it the new reference baseline.
func (w *ModelDriftWatcher) swapWindows() {
	w.refWin.mu.Lock()
	defer w.refWin.mu.Unlock()
	w.prodWin.mu.Lock()
	defer w.prodWin.mu.Unlock()

	w.refWin.samples, w.prodWin.samples = w.prodWin.samples, make([]float64, 0, w.cfg.WindowSize)
}
```