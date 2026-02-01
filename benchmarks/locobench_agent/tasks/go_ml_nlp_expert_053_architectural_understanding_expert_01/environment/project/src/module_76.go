```go
// Code generated for EchoPulse (ml_nlp) — DO NOT EDIT.
//
// Module:       src/module_76.go
// Description:  Rolling-window statistical drift detector that watches the
//               live feature stream and emits DriftEvent messages when a
//               significant change in distribution is observed.
//
//               The detector keeps two rolling windows per feature—baseline
//               and current—and runs a two-sample z-test on the mean after
//               every tick.  Significant drift is forwarded to the event
//               bus so that the automated retraining pipeline can kick in.
//
// Pattern:      Observer + Pipeline + Strategy (detector strategy)
//
// Author:       EchoPulse Engineering
// License:      Apache-2.0
package monitoring

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
	"go.uber.org/zap"
)

// --------------------------- Public Domain Types -----------------------------

// DriftEvent represents a light-weight JSON serialisable message describing
// statistically significant drift on a single feature.
type DriftEvent struct {
	Feature    string    `json:"feature"`
	PValue     float64   `json:"p_value"`
	WindowID   string    `json:"window_id"`
	Timestamp  time.Time `json:"ts_utc"`
	BaselineN  int       `json:"baseline_n"`
	CurrentN   int       `json:"current_n"`
	BaselineMu float64   `json:"baseline_mu"`
	CurrentMu  float64   `json:"current_mu"`
}

// DetectorConfig defines configurable knobs for the drift detector.
type DetectorConfig struct {
	FeatureNames        []string      // subset of features to monitor (empty==all)
	BaselineWindowSize  int           // number of samples in baseline window
	CurrentWindowSize   int           // number of samples in current window
	PValueThreshold     float64       // significance level (e.g. 0.01)
	KafkaBrokers        []string      // brokers for writing DriftEvents
	KafkaTopic          string        // topic to write DriftEvents to
	KafkaRequiredAcks   kafka.RequiredAcks
	KafkaCompression    kafka.Compression
	FlushInterval       time.Duration // how often to flush kafka writer
	Logger              *zap.Logger   // optional external logger
	EventBufferCapacity int           // internal buffer for DriftEvents
}

// NewDefaultDetectorConfig returns a sensible default config for small/medium
// deployments.
func NewDefaultDetectorConfig() DetectorConfig {
	return DetectorConfig{
		BaselineWindowSize:  2_000,
		CurrentWindowSize:   2_000,
		PValueThreshold:     0.01,
		KafkaBrokers:        []string{"localhost:9092"},
		KafkaTopic:          "drift_events",
		KafkaRequiredAcks:   kafka.RequireAll,
		KafkaCompression:    kafka.Snappy,
		FlushInterval:       500 * time.Millisecond,
		EventBufferCapacity: 4_096,
	}
}

// DriftDetector is the behaviour expected from every drift-detection strategy.
type DriftDetector interface {
	// Process-ingests the latest numeric feature vector.
	Process(ctx context.Context, featureVector map[string]float64) error
	// Close releases internal resources (kafka writer, goroutines, etc.).
	Close() error
}

// --------------------------- Rolling Window Impl -----------------------------

// moment keeps Welford's online algorithm statistics.
type moment struct {
	n  int
	μ  float64 // mean
	M2 float64 // sum of squares of diffs
}

func (m *moment) update(x float64) {
	m.n++
	delta := x - m.μ
	m.μ += delta / float64(m.n)
	m.M2 += delta * (x - m.μ)
}

func (m *moment) variance() float64 {
	if m.n < 2 {
		return 0
	}
	return m.M2 / float64(m.n-1)
}

// rollingWindow holds a FIFO circular buffer of samples and Welford stats.
type rollingWindow struct {
	cap   int
	buf   []float64
	head  int
	count int
	stat  moment
}

func newRollingWindow(size int) *rollingWindow {
	return &rollingWindow{
		cap: size,
		buf: make([]float64, size),
	}
}

func (rw *rollingWindow) push(x float64) {
	if rw.count < rw.cap {
		rw.buf[rw.head] = x
		rw.head = (rw.head + 1) % rw.cap
		rw.count++
		rw.stat.update(x)
		return
	}

	// window full — replace oldest sample
	oldestIdx := rw.head
	old := rw.buf[oldestIdx]

	// rewind Welford stats (approximate) by removing oldest sample
	// NOTE: exact removal is expensive; we trade accuracy for speed by
	// reinitialising when drift is checked. This is acceptable for large N.
	rw.buf[oldestIdx] = x
	rw.head = (rw.head + 1) % rw.cap
	rw.recomputeStats()
}

func (rw *rollingWindow) recomputeStats() {
	var s moment
	for i := 0; i < rw.count; i++ {
		s.update(rw.buf[i])
	}
	rw.stat = s
}

// ----------------------- RollingWindowDriftDetector --------------------------

type rollingWindowDriftDetector struct {
	cfg        DetectorConfig
	log        *zap.Logger
	windowsMu  sync.RWMutex
	baseline   map[string]*rollingWindow
	current    map[string]*rollingWindow
	producer   *kafka.Writer
	events     chan DriftEvent
	publishWg  sync.WaitGroup
	closedOnce sync.Once
}

// NewRollingWindowDriftDetector sets up the detector and starts background
// publishing goroutines.
func NewRollingWindowDriftDetector(cfg DetectorConfig) (DriftDetector, error) {
	if cfg.BaselineWindowSize <= 0 || cfg.CurrentWindowSize <= 0 {
		return nil, errors.New("window sizes must be positive")
	}
	if cfg.PValueThreshold <= 0 || cfg.PValueThreshold >= 1 {
		return nil, errors.New("p-value threshold must be between (0,1)")
	}
	log := cfg.Logger
	if log == nil {
		l, _ := zap.NewProduction()
		log = l
	}

	// initialise kafka writer
	writer := &kafka.Writer{
		Addr:         kafka.TCP(cfg.KafkaBrokers...),
		Topic:        cfg.KafkaTopic,
		RequiredAcks: cfg.KafkaRequiredAcks,
		Compression:  cfg.KafkaCompression,
		BatchTimeout: cfg.FlushInterval,
		Async:        true,
	}

	d := &rollingWindowDriftDetector{
		cfg:      cfg,
		log:      log,
		baseline: make(map[string]*rollingWindow),
		current:  make(map[string]*rollingWindow),
		producer: writer,
		events:   make(chan DriftEvent, cfg.EventBufferCapacity),
	}

	// Kick off publisher.
	d.publishWg.Add(1)
	go d.publishLoop()

	log.Info("RollingWindowDriftDetector started",
		zap.Int("baseline_size", cfg.BaselineWindowSize),
		zap.Int("current_size", cfg.CurrentWindowSize),
		zap.Float64("p_th", cfg.PValueThreshold),
		zap.String("kafka_topic", cfg.KafkaTopic))

	return d, nil
}

func (d *rollingWindowDriftDetector) publishLoop() {
	defer d.publishWg.Done()

	for ev := range d.events {
		msgBytes, err := json.Marshal(ev)
		if err != nil {
			d.log.Error("Failed to marshal DriftEvent", zap.Error(err))
			continue
		}
		err = d.producer.WriteMessages(context.Background(),
			kafka.Message{
				Key:   []byte(ev.Feature),
				Time:  ev.Timestamp,
				Value: msgBytes,
			})
		if err != nil {
			d.log.Error("Failed to write DriftEvent to kafka", zap.Error(err))
		}
	}
}

func (d *rollingWindowDriftDetector) Process(ctx context.Context, vec map[string]float64) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
	}

	d.windowsMu.Lock()
	defer d.windowsMu.Unlock()

	for fname, val := range vec {
		bw, ok := d.baseline[fname]
		if !ok {
			bw = newRollingWindow(d.cfg.BaselineWindowSize)
			d.baseline[fname] = bw
		}
		cw, ok := d.current[fname]
		if !ok {
			cw = newRollingWindow(d.cfg.CurrentWindowSize)
			d.current[fname] = cw
		}

		// rotate windows once current is full
		if cw.count >= cw.cap {
			// After drift check, promote current to baseline, reset current
			d.checkAndEmit(fname, bw, cw)
			d.baseline[fname] = cw
			d.current[fname] = newRollingWindow(d.cfg.CurrentWindowSize)
			bw = d.baseline[fname]
			cw = d.current[fname]
		}

		cw.push(val)
	}
	return nil
}

// checkAndEmit performs a two-sample z-test for the mean of the two windows.
func (d *rollingWindowDriftDetector) checkAndEmit(feature string, baseline, current *rollingWindow) {
	// Guard against insufficient data
	if baseline.count < 30 || current.count < 30 {
		return
	}

	μ0 := baseline.stat.μ
	μ1 := current.stat.μ
	var0 := baseline.stat.variance()
	var1 := current.stat.variance()

	// pooled standard error
	se := math.Sqrt(var0/float64(baseline.count) + var1/float64(current.count))
	if se == 0 {
		return
	}

	z := math.Abs(μ1-μ0) / se
	p := 2 * (1 - 0.5*math.Erfc(z/math.Sqrt2)) // two-tailed p-value

	if p < d.cfg.PValueThreshold {
		ev := DriftEvent{
			Feature:    feature,
			PValue:     p,
			WindowID:   fmt.Sprintf("%d_%d", time.Now().UnixNano(), z*1000),
			Timestamp:  time.Now().UTC(),
			BaselineN:  baseline.count,
			CurrentN:   current.count,
			BaselineMu: μ0,
			CurrentMu:  μ1,
		}

		select {
		case d.events <- ev:
		default:
			d.log.Warn("DriftEvent buffer full, dropping event", zap.String("feature", feature))
		}
	}
}

// Close signals shutdown and waits for internal routines to finish.
func (d *rollingWindowDriftDetector) Close() error {
	var err error
	d.closedOnce.Do(func() {
		close(d.events)
		d.publishWg.Wait()
		err = d.producer.Close()
		d.log.Info("RollingWindowDriftDetector stopped")
	})
	return err
}
```