```go
// Code generated for EchoPulse (ml_nlp) — DO NOT EDIT MANUALLY.
// Path: src/module_75.go
//
// Package monitoring implements real-time model-output drift detection.  The
// core component is a Jensen–Shannon divergence detector that watches the
// streaming probability vectors emitted by online classifiers.  When the
// observed distribution deviates beyond a configurable threshold, a
// ModelRetrain event is published to the platform’s event bus (Kafka).
//
// The detector is heavily concurrent, observability-first (Prometheus), and
// production-ready (graceful shutdown, structured logging, context
// propagation, and back-pressure awareness).
package monitoring

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"time"

	"github.com/Shopify/sarama"
	"github.com/prometheus/client_golang/prometheus"
	"go.uber.org/zap"
)

// ----------------------------------------------------------------------------
// Public types
// ----------------------------------------------------------------------------

// PredictionEvent is the canonical form of a model prediction that the
// detector consumes.  Each event is delivered over the platform’s event bus
// after the online inference stage has completed.
type PredictionEvent struct {
	ModelID      string    `json:"model_id"`
	// OutputProbs is the complete probability vector for every class.  The
	// detector assumes Σ p_i = 1.0.  It does NOT accept logits.
	OutputProbs  []float64 `json:"output_probs"`
	TimestampUTC time.Time `json:"timestamp_utc"`
}

// DriftEvent is published when the detector determines statistically
// significant drift between the reference distribution and the recent stream.
type DriftEvent struct {
	ModelID       string    `json:"model_id"`
	WindowSize    int       `json:"window_size"`
	JSScore       float64   `json:"js_score"`
	Threshold     float64   `json:"threshold"`
	DetectedAtUTC time.Time `json:"detected_at_utc"`
}

// ----------------------------------------------------------------------------
// Detector interface
// ----------------------------------------------------------------------------

// DriftDetector observes PredictionEvents and produces internal DriftEvents.
// Implementations MUST be goroutine-safe.
type DriftDetector interface {
	// Ingest pushes a single prediction into the detector’s buffer.
	Ingest(PredictionEvent) error
	// Run starts the processing loop in the given ctx.  It returns when ctx is
	// canceled or a fatal error occurs.
	Run(ctx context.Context) error
}

// ----------------------------------------------------------------------------
// Jensen–Shannon divergence detector
// ----------------------------------------------------------------------------

// jsDetector is a production-grade implementation that estimates the
// probability distribution of recent predictions via an exponential-moving
// average (EMA) and compares it to the reference distribution persisted at
// model-training time.
type jsDetector struct {
	modelID string

	refDist    []float64 // immutable reference distribution
	alpha      float64   // EMA smoothing factor
	threshold  float64   // JS divergence threshold
	windowMinN int       // minimum samples before evaluation

	logger   *zap.Logger
	producer sarama.SyncProducer

	cfgMu   sync.RWMutex
	currEMA []float64
	n       int // number of samples observed

	ingestCh chan PredictionEvent
	wg       sync.WaitGroup
}

// NewJSDetector is the factory entry point leveraged by wiring/DI code.
//
// NOTE: Callers retain ownership of producer & logger and are responsible for
// their lifecycle.
func NewJSDetector(
	modelID string,
	refDist []float64,
	alpha float64,
	threshold float64,
	windowMinN int,
	producer sarama.SyncProducer,
	logger *zap.Logger,
) (DriftDetector, error) {

	if len(refDist) == 0 {
		return nil, errors.New("jsdetector: reference distribution must not be empty")
	}

	if math.Abs(sum(refDist)-1.0) > 1e-4 {
		return nil, errors.New("jsdetector: reference distribution must sum to 1")
	}

	ema := make([]float64, len(refDist))
	copy(ema, refDist)

	return &jsDetector{
		modelID:   modelID,
		refDist:   refDist,
		alpha:     alpha,
		threshold: threshold,

		windowMinN: windowMinN,
		logger:     logger.With(zap.String("model_id", modelID)),
		producer:   producer,

		currEMA:  ema,
		ingestCh: make(chan PredictionEvent, 4096), // bounded for back-pressure
	}, nil
}

// Ingest implements DriftDetector.
func (d *jsDetector) Ingest(ev PredictionEvent) error {
	select {
	case d.ingestCh <- ev:
		return nil
	default:
		// channel is full — apply back-pressure and drop
		detectorDroppedEvents.Inc()
		d.logger.Warn("jsdetector: ingest channel full, dropping event")
		return errors.New("jsdetector: ingest channel is full")
	}
}

// Run implements DriftDetector.  It keeps reading from ingestCh until the
// context is canceled, maintaining EMA and firing DriftEvents when the JS
// divergence crosses the configured threshold.
func (d *jsDetector) Run(ctx context.Context) error {
	d.logger.Info("jsdetector: started")
	defer d.logger.Info("jsdetector: stopped")

	d.wg.Add(1)
	defer d.wg.Done()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()

		case ev := <-d.ingestCh:
			d.process(ev)
		}
	}
}

// process updates the EMA and checks for drift.
func (d *jsDetector) process(ev PredictionEvent) {
	if len(ev.OutputProbs) != len(d.refDist) {
		detectorBadInput.Inc()
		d.logger.Error("jsdetector: mismatched output dimension",
			zap.Int("expected", len(d.refDist)),
			zap.Int("got", len(ev.OutputProbs)),
		)
		return
	}

	// Update EMA
	d.cfgMu.Lock()
	for i := 0; i < len(d.currEMA); i++ {
		d.currEMA[i] = d.alpha*ev.OutputProbs[i] + (1.0-d.alpha)*d.currEMA[i]
	}
	d.n++
	emaSnapshot := append([]float64(nil), d.currEMA...) // copy
	nSnapshot := d.n
	d.cfgMu.Unlock()

	// Evaluate drift only after minimum window
	if nSnapshot < d.windowMinN {
		return
	}

	js := jsDivergence(d.refDist, emaSnapshot)
	detectorLastJS.
		WithLabelValues(d.modelID).
		Set(js)

	if js >= d.threshold {
		d.logger.Warn("jsdetector: drift detected",
			zap.Float64("js_score", js),
			zap.Float64("threshold", d.threshold),
		)
		d.emitDriftEvent(js, nSnapshot)
	}
}

// emitDriftEvent pushes a JSON-encoded DriftEvent to Kafka and updates metrics.
func (d *jsDetector) emitDriftEvent(jsScore float64, windowSize int) {
	ev := DriftEvent{
		ModelID:       d.modelID,
		WindowSize:    windowSize,
		JSScore:       jsScore,
		Threshold:     d.threshold,
		DetectedAtUTC: time.Now().UTC(),
	}
	b, err := json.Marshal(&ev)
	if err != nil {
		d.logger.Error("jsdetector: failed to marshal DriftEvent", zap.Error(err))
		return
	}

	msg := &sarama.ProducerMessage{
		Topic: "model-retrain-events",
		Key:   sarama.StringEncoder(d.modelID),
		Value: sarama.ByteEncoder(b),
	}

	start := time.Now()
	_, _, err = d.producer.SendMessage(msg)
	if err != nil {
		detectorKafkaErrors.Inc()
		d.logger.Error("jsdetector: failed to publish DriftEvent", zap.Error(err))
		return
	}

	detectorDriftEvents.Inc()
	detectorKafkaLatency.Observe(time.Since(start).Seconds())
}

// ----------------------------------------------------------------------------
// Utility functions
// ----------------------------------------------------------------------------

func sum(v []float64) float64 {
	var s float64
	for _, x := range v {
		s += x
	}
	return s
}

// jsDivergence computes the symmetric Jensen–Shannon divergence (base-2) of
// two discrete distributions P and Q.
func jsDivergence(p, q []float64) float64 {
	m := make([]float64, len(p))
	for i := range p {
		m[i] = 0.5 * (p[i] + q[i])
	}
	return 0.5*klDiv(p, m) + 0.5*klDiv(q, m)
}

// klDiv returns the Kullback–Leibler divergence D_KL(P || Q).  All inputs must
// be strictly positive & normalized; caller is responsible for pre-conditions.
func klDiv(p, q []float64) float64 {
	var d float64
	for i := range p {
		if p[i] == 0 {
			continue
		}
		d += p[i] * math.Log2(p[i]/q[i])
	}
	return d
}

// ----------------------------------------------------------------------------
// Prometheus metrics — registered by init()
// ----------------------------------------------------------------------------

var (
	detectorDriftEvents = prometheus.NewCounter(
		prometheus.CounterOpts{
			Namespace: "echopulse",
			Subsystem: "drift_detector",
			Name:      "drift_events_total",
			Help:      "Total number of drift events published.",
		})

	detectorDroppedEvents = prometheus.NewCounter(
		prometheus.CounterOpts{
			Namespace: "echopulse",
			Subsystem: "drift_detector",
			Name:      "ingest_dropped_total",
			Help:      "Prediction events dropped due to back-pressure.",
		})

	detectorBadInput = prometheus.NewCounter(
		prometheus.CounterOpts{
			Namespace: "echopulse",
			Subsystem: "drift_detector",
			Name:      "bad_input_total",
			Help:      "Count of prediction events with invalid dimensions.",
		})

	detectorLastJS = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: "echopulse",
			Subsystem: "drift_detector",
			Name:      "last_js_divergence",
			Help:      "The latest JS divergence score observed for a model.",
		},
		[]string{"model_id"},
	)

	detectorKafkaErrors = prometheus.NewCounter(
		prometheus.CounterOpts{
			Namespace: "echopulse",
			Subsystem: "drift_detector",
			Name:      "kafka_errors_total",
			Help:      "Kafka publish errors.",
		})

	detectorKafkaLatency = prometheus.NewHistogram(
		prometheus.HistogramOpts{
			Namespace: "echopulse",
			Subsystem: "drift_detector",
			Name:      "kafka_publish_seconds",
			Help:      "Latency of publishing drift events to Kafka.",
			Buckets:   prometheus.DefBuckets,
		})
)

func init() {
	prometheus.MustRegister(
		detectorDriftEvents,
		detectorDroppedEvents,
		detectorBadInput,
		detectorLastJS,
		detectorKafkaErrors,
		detectorKafkaLatency,
	)
}
```