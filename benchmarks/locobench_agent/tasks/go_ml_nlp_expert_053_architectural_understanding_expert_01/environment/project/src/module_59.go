package pipeline

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"go.uber.org/zap"
)

//-----------------------------------------------------------------------------
// Public Interfaces
//-----------------------------------------------------------------------------

// EventBus is a very small abstraction around the project-wide
// event backbone (Kafka, JetStream, etc.).
// Only the subset needed by DriftDetector is defined here.
// The implementation is supplied by the wiring layer of the platform.
type EventBus interface {
	Publish(ctx context.Context, topic string, payload []byte) error
}

// FeatureStats represents the output of a feature-monitoring job that
// periodically summarizes the empirical distribution of a feature.
//
// For now we assume buckets are already aligned across time and contain
// probability masses that sum to 1.0.
type FeatureStats struct {
	Feature   string    `json:"feature"`
	Histogram []float64 `json:"histogram"`
	Timestamp time.Time `json:"timestamp"`
}

//-----------------------------------------------------------------------------
// Drift Event
//-----------------------------------------------------------------------------

// DriftEvent is emitted on the event bus whenever population drift is detected.
type DriftEvent struct {
	ModelVersion   string    `json:"model_version"`
	Feature        string    `json:"feature"`
	PSI            float64   `json:"psi"`
	DetectedAt     time.Time `json:"detected_at"`
	DetectionStage string    `json:"detection_stage"` // e.g. "pre-processing","serving"
}

//-----------------------------------------------------------------------------
// Drift Detector
//-----------------------------------------------------------------------------

// DriftDetectorConfig parameterizes behavior of DriftDetector.
type DriftDetectorConfig struct {
	// PSIThreshold triggers an alert whenever the Population Stability Index
	// exceeds this value. Industry heuristics: 0.1 = slight, 0.25 = major drift.
	PSIThreshold float64
	// WindowSize is the number of sliding windows used to form the baseline
	// distribution. A value of 0 disables internal baselining; the caller must
	// provide a separate baseline.
	WindowSize int
	// Cooldown prevents spamming downstream retraining pipelines by enforcing a
	// minimum duration between two drift events for the same feature.
	Cooldown time.Duration
	// Topic is the event bus topic that drift events should be published to.
	Topic string
}

// DriftDetector consumes a stream of FeatureStats, computes drift relative to
// a baseline distribution, and publishes DriftEvents when the PSI metric
// crosses a predefined threshold.
//
// DriftDetector is goroutine-safe and can be hot-reconfigured by swapping the
// underlying config atomically.
type DriftDetector struct {
	cfg   *DriftDetectorConfig
	bus   EventBus
	log   *zap.Logger
	clock func() time.Time

	mx sync.RWMutex
	// baseline[feature] -> histogram
	baseline map[string][]float64
	// lastEvent[feature] -> time
	lastEvent map[string]time.Time
}

// NewDriftDetector constructs a ready-to-use DriftDetector. The baseline map
// may be left nil to initialize lazily from the first observation.
func NewDriftDetector(bus EventBus, cfg *DriftDetectorConfig, logger *zap.Logger) (*DriftDetector, error) {
	if bus == nil {
		return nil, errors.New("bus must not be nil")
	}
	if cfg == nil {
		return nil, errors.New("config must not be nil")
	}
	if cfg.PSIThreshold <= 0 {
		return nil, errors.New("PSIThreshold must be positive")
	}
	if cfg.Topic == "" {
		return nil, errors.New("Topic must be non-empty")
	}
	if logger == nil {
		logger = zap.NewNop()
	}

	d := &DriftDetector{
		cfg:       cfg,
		bus:       bus,
		log:       logger.Named("drift_detector"),
		clock:     time.Now,
		baseline:  make(map[string][]float64),
		lastEvent: make(map[string]time.Time),
	}
	return d, nil
}

//-----------------------------------------------------------------------------
// Prometheus Metrics
//-----------------------------------------------------------------------------

var (
	psiGauge = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: "echopulse",
			Subsystem: "drift_detector",
			Name:      "psi",
			Help:      "Population Stability Index for feature distributions.",
		},
		[]string{"feature"},
	)
	driftEventsTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: "echopulse",
			Subsystem: "drift_detector",
			Name:      "events_total",
			Help:      "Total number of drift events published.",
		},
		[]string{"feature"},
	)
)

func init() {
	prometheus.MustRegister(psiGauge, driftEventsTotal)
}

//-----------------------------------------------------------------------------
// Processing
//-----------------------------------------------------------------------------

// Start runs the detector loop until the provided context is cancelled.
// It is safe to call Start multiple times with different input channels.
func (d *DriftDetector) Start(ctx context.Context, input <-chan FeatureStats) error {
	if input == nil {
		return errors.New("input channel must not be nil")
	}

	go func() {
		for {
			select {
			case <-ctx.Done():
				d.log.Info("drift detector shutting down", zap.Error(ctx.Err()))
				return
			case stats, ok := <-input:
				if !ok {
					d.log.Info("input channel closed, stopping drift detector")
					return
				}
				d.handle(stats)
			}
		}
	}()
	return nil
}

// handle applies PSI calculation and publishes events when necessary.
func (d *DriftDetector) handle(fs FeatureStats) {
	if len(fs.Histogram) == 0 {
		d.log.Warn("empty histogram received, skipping", zap.String("feature", fs.Feature))
		return
	}

	// Make local copies to avoid locking throughout computation.
	d.mx.RLock()
	base, exists := d.baseline[fs.Feature]
	d.mx.RUnlock()

	if !exists {
		d.bootstrap(fs)
		return
	}
	if len(base) != len(fs.Histogram) {
		d.log.Warn("histogram bucket mismatch, resetting baseline",
			zap.String("feature", fs.Feature),
			zap.Int("baseline_buckets", len(base)),
			zap.Int("incoming_buckets", len(fs.Histogram)),
		)
		d.bootstrap(fs)
		return
	}

	psi := populationStabilityIndex(base, fs.Histogram)
	psiGauge.WithLabelValues(fs.Feature).Set(psi)

	if psi < d.cfg.PSIThreshold {
		d.maybeUpdateBaseline(fs.Feature, fs.Histogram)
		return
	}

	now := d.clock()
	d.mx.RLock()
	last := d.lastEvent[fs.Feature]
	d.mx.RUnlock()

	if now.Sub(last) < d.cfg.Cooldown {
		d.log.Debug("cooldown active, no drift event published",
			zap.String("feature", fs.Feature),
			zap.Duration("remaining", d.cfg.Cooldown-now.Sub(last)))
		return
	}

	if err := d.publishDrift(fs, psi); err != nil {
		d.log.Error("failed to publish drift event", zap.Error(err))
		return
	}

	d.mx.Lock()
	d.lastEvent[fs.Feature] = now
	d.mx.Unlock()
}

// bootstrap initializes baseline from first observation.
func (d *DriftDetector) bootstrap(fs FeatureStats) {
	d.mx.Lock()
	d.baseline[fs.Feature] = cloneHist(fs.Histogram)
	d.mx.Unlock()
	d.log.Info("baseline initialized", zap.String("feature", fs.Feature))
}

// maybeUpdateBaseline uses a sliding window to keep the baseline fresh.
func (d *DriftDetector) maybeUpdateBaseline(feature string, hist []float64) {
	if d.cfg.WindowSize <= 0 {
		return
	}

	d.mx.Lock()
	defer d.mx.Unlock()

	base := d.baseline[feature]
	if len(base) == 0 {
		d.baseline[feature] = cloneHist(hist)
		return
	}

	// Simple moving average of histograms.
	for i := range base {
		base[i] = ((float64(d.cfg.WindowSize-1) * base[i]) + hist[i]) / float64(d.cfg.WindowSize)
	}
	d.baseline[feature] = base
}

// publishDrift serializes and sends a drift event to the bus.
func (d *DriftDetector) publishDrift(fs FeatureStats, psi float64) error {
	event := DriftEvent{
		ModelVersion:   "latest", // will be enriched by serving layer
		Feature:        fs.Feature,
		PSI:            psi,
		DetectedAt:     d.clock(),
		DetectionStage: "serving",
	}

	payload, err := json.Marshal(event)
	if err != nil {
		return err
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	if err := d.bus.Publish(ctx, d.cfg.Topic, payload); err != nil {
		return err
	}

	driftEventsTotal.WithLabelValues(fs.Feature).Inc()
	d.log.Warn("drift event published",
		zap.String("feature", fs.Feature),
		zap.Float64("psi", psi))
	return nil
}

// populationStabilityIndex calculates PSI between two histograms.
// Assumes buckets are aligned and sum to 1.0 each.
func populationStabilityIndex(expected, actual []float64) float64 {
	var psi float64
	for i := range expected {
		e, a := expected[i], actual[i]

		// Avoid division by zero + log(0). Replace zeros with a very small value.
		const eps = 1e-6
		if e == 0 {
			e = eps
		}
		if a == 0 {
			a = eps
		}

		psi += (a - e) * math.Log(a/e)
	}
	return psi
}

// cloneHist returns a deep copy of a histogram slice.
func cloneHist(src []float64) []float64 {
	out := make([]float64, len(src))
	copy(out, src)
	return out
}

//-----------------------------------------------------------------------------
// Factory Registration (simplified)
//-----------------------------------------------------------------------------

// DetectorFactory builds new DriftDetector instances from config JSON.
// This is a convenience for the platform's dynamic pipeline loader.
type DetectorFactory struct {
	bus EventBus
	log *zap.Logger
}

func NewDetectorFactory(bus EventBus, log *zap.Logger) *DetectorFactory {
	return &DetectorFactory{bus: bus, log: log}
}

// Build constructs a detector from raw bytes containing DriftDetectorConfig in JSON.
func (f *DetectorFactory) Build(cfgJSON []byte) (*DriftDetector, error) {
	var cfg DriftDetectorConfig
	if err := json.Unmarshal(cfgJSON, &cfg); err != nil {
		return nil, err
	}
	return NewDriftDetector(f.bus, &cfg, f.log)
}

//-----------------------------------------------------------------------------
// Compile-time interface assertions
//-----------------------------------------------------------------------------

var (
	_ EventBus = (*mockBus)(nil) // ensure EventBus interface satisfaction
)

//-----------------------------------------------------------------------------
// Internal Mock (used by unit tests; ignored in production builds)
//-----------------------------------------------------------------------------

// mockBus is a minimal in-memory EventBus implementation.
// It is conditionally compiled by using build tags in real code, but kept here
// inline for completeness.
type mockBus struct {
	cb func(topic string, payload []byte)
}

func (m *mockBus) Publish(_ context.Context, topic string, payload []byte) error {
	if m.cb != nil {
		m.cb(topic, payload)
	}
	return nil
}