```go
// File: src/module_60.go
// Package monitoring provides a real-time statistical-drift sentinel that listens
// to live model predictions, compares the label distribution against a reference
// baseline, and emits a RetrainEvent to the event bus when drift exceeds a
// configurable threshold.  This module demonstrates how EchoPulse keeps models
// fresh and healthy in production.
//
// NOTE: The concrete Kafka/NATS implementations are hidden behind thin
// interfaces so that the core algorithm can be covered by unit tests without
// spinning up external infrastructure.

package monitoring

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

// ----------------------------- Public Contracts -----------------------------

// MessageReader represents the read-side of a streaming broker.  Kafka/NATS
// concrete implementations live in another package.
type MessageReader interface {
	// Read pulls the next message off the stream or blocks until ctx is done.
	Read(ctx context.Context) ([]byte, error)
	Close() error
}

// MessageWriter represents the write-side of a streaming broker.
type MessageWriter interface {
	Write(ctx context.Context, key string, payload []byte) error
	Close() error
}

// RetrainEvent is the governance command emitted when drift is detected.
type RetrainEvent struct {
	Timestamp  time.Time `json:"timestamp"`
	ModelName  string    `json:"model_name"`
	Metric     string    `json:"metric"`
	Score      float64   `json:"score"`
	WindowSize int       `json:"window_size"`
}

// Prediction is the canonical payload produced by the inference service.
type Prediction struct {
	Timestamp time.Time `json:"timestamp"`
	ModelName string    `json:"model_name"`
	Label     string    `json:"label"`
	Prob      float64   `json:"probability"`
}

// ------------------------------ Drift Monitor -------------------------------

// Config controls runtime behaviour of the DriftMonitor.
type Config struct {
	WindowSize      int           // sliding window (N predictions)
	MinWindow       int           // minimum count before evaluation
	Threshold       float64       // chi-square statistic threshold
	CheckInterval   time.Duration // how often to evaluate drift
	ReferencePeriod time.Duration // how often to refresh baseline
}

// DriftMonitor watches a stream and fires events on statistical drift.
type DriftMonitor struct {
	cfg      Config
	reader   MessageReader
	writer   MessageWriter
	baseline BaselineStore

	mu       sync.Mutex
	counts   map[string]int // label => count within sliding window
	total    int
	window   []string // ring buffer of last cfg.WindowSize labels
	idx      int
	lastPull time.Time

	// telemetry
	chiSquareGauge prometheus.Gauge
	driftCounter   prometheus.Counter
}

// BaselineStore abstracts persistence for baseline distributions so that
// governance can update them independently.
type BaselineStore interface {
	Load(model string) (map[string]float64, error) // label => probability
}

// New returns a fully-wired DriftMonitor.  Caller is responsible for closing
// reader and writer.
func New(cfg Config, r MessageReader, w MessageWriter, bs BaselineStore) (*DriftMonitor, error) {
	if cfg.WindowSize <= 0 {
		return nil, errors.New("window size must be >0")
	}
	dm := &DriftMonitor{
		cfg:      cfg,
		reader:   r,
		writer:   w,
		baseline: bs,
		counts:   make(map[string]int),
		window:   make([]string, cfg.WindowSize),
		chiSquareGauge: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: "echopulse",
			Subsystem: "drift_monitor",
			Name:      "chi_square_statistic",
			Help:      "Chi-square statistic for the current sliding window.",
		}),
		driftCounter: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: "echopulse",
			Subsystem: "drift_monitor",
			Name:      "drift_event_total",
			Help:      "Number of detected drift events.",
		}),
	}

	// Register metrics – duplicate registration protection happens upstream.
	prometheus.DefaultRegisterer.MustRegister(dm.chiSquareGauge, dm.driftCounter)

	return dm, nil
}

// Run is a blocking call; it terminates when ctx is cancelled or an unrecoverable
// error occurs during Read.
func (d *DriftMonitor) Run(ctx context.Context) error {
	ticker := time.NewTicker(d.cfg.CheckInterval)
	defer ticker.Stop()

	refTicker := time.NewTicker(d.cfg.ReferencePeriod)
	defer refTicker.Stop()

	// Pre-warm baseline cache
	baselineCache := make(map[string]map[string]float64)

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		// 1. Pull next prediction (non-blocking)
		if err := d.pull(ctx); err != nil {
			if errors.Is(err, context.Canceled) {
				return ctx.Err()
			}
			// Non-fatal: log and continue.  In this scaffold we simply propagate.
			return err
		}

		// 2. Evaluate drift periodically
		select {
		case <-ticker.C:
			d.mu.Lock()
			countSnapshot := cloneCounts(d.counts)
			windowSize := d.total
			d.mu.Unlock()

			// Not enough samples yet
			if windowSize < d.cfg.MinWindow {
				continue
			}

			latestModel := d.latestModel()
			if latestModel == "" {
				continue
			}

			ref, ok := baselineCache[latestModel]
			if !ok {
				var err error
				ref, err = d.baseline.Load(latestModel)
				if err != nil {
					// skip evaluation without baseline
					continue
				}
				baselineCache[latestModel] = ref
			}

			stat := chiSquare(countSnapshot, ref, windowSize)
			d.chiSquareGauge.Set(stat)

			if stat >= d.cfg.Threshold {
				// DRIFT!
				d.driftCounter.Inc()
				if err := d.emitRetrain(ctx, latestModel, stat, windowSize); err != nil {
					// best effort; we still continue
				}
				// reset counts to avoid duplicate alerts
				d.reset()
			}

		default:
		}

		// 3. Refresh baselines at configured cadence
		select {
		case <-refTicker.C:
			// Clear cache; next eval will re-load
			baselineCache = make(map[string]map[string]float64)
		default:
		}
	}
}

// pull ingests one message off the stream and updates the sliding window.
func (d *DriftMonitor) pull(ctx context.Context) error {
	msg, err := d.reader.Read(ctx)
	if err != nil {
		return err
	}
	var p Prediction
	if err := json.Unmarshal(msg, &p); err != nil {
		// Invalid payload – ignore but don't crash.
		return nil
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	// Remove oldest if window is full
	if d.total == d.cfg.WindowSize {
		old := d.window[d.idx]
		d.counts[old]--
		if d.counts[old] == 0 {
			delete(d.counts, old)
		}
	} else {
		d.total++
	}

	d.window[d.idx] = p.Label
	d.counts[p.Label]++
	d.idx = (d.idx + 1) % d.cfg.WindowSize
	d.lastPull = time.Now()

	return nil
}

// emitRetrain pushes a RetrainEvent to the event bus.
func (d *DriftMonitor) emitRetrain(ctx context.Context, model string, stat float64, window int) error {
	re := RetrainEvent{
		Timestamp:  time.Now().UTC(),
		ModelName:  model,
		Metric:     "chi_square",
		Score:      stat,
		WindowSize: window,
	}
	payload, err := json.Marshal(re)
	if err != nil {
		return err
	}
	return d.writer.Write(ctx, model, payload)
}

// latestModel returns the most recently seen model name.
func (d *DriftMonitor) latestModel() string {
	// Not stored per-prediction to reduce overhead; instead rely on FIFO queue.
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.total == 0 {
		return ""
	}
	// window[d.idx-1] is latest label but does not encode model. For simplicity,
	// assume single model per stream. In multi-model streams you'd carry model
	// names in a parallel ring buffer.
	return "sentiment_v2"
}

// reset clears the sliding window after drift to prevent duplicate alerts.
func (d *DriftMonitor) reset() {
	d.counts = make(map[string]int)
	d.total = 0
	d.idx = 0
}

// ---------------------------- Helper Functions ------------------------------

func cloneCounts(src map[string]int) map[string]int {
	dst := make(map[string]int, len(src))
	for k, v := range src {
		dst[k] = v
	}
	return dst
}

// chiSquare computes the Pearson chi-square statistic between observed counts
// and expected probabilities.
//
//   χ² = Σ ( (Oᵢ − Eᵢ)² / Eᵢ )
//
// Where Eᵢ = Pᵢ * N.
func chiSquare(observed map[string]int, expected map[string]float64, N int) float64 {
	var total float64
	for label, expProb := range expected {
		E := expProb * float64(N)
		O := float64(observed[label])
		if E == 0 {
			// skip to avoid div/0 — treat as heavy drift.
			total += 1e9
			continue
		}
		total += math.Pow(O-E, 2) / E
	}

	// Account for unseen labels in the baseline.
	for label, count := range observed {
		if _, ok := expected[label]; !ok {
			// baseline unaware of this label → big penalty
			total += math.Pow(float64(count), 2) / 1e-9
		}
	}
	return total
}
```
