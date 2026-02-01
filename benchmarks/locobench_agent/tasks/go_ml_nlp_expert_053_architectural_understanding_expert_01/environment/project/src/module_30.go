```go
// EchoPulse – Real-Time Social Signal Processing Platform
// -------------------------------------------------------
// File:        src/module_30.go
// Module:      drift
// Description: Streaming feature-distribution monitoring, statistical-drift
//              detection and auto-retraining trigger service.
//
// This module demonstrates several architectural patterns used across the
// platform:
//
//   • Observer Pattern   –  Consumes canonical SocialEvents from the event bus.
//   • Strategy Pattern   –  Pluggable drift–detection algorithms.
//   • Factory Pattern    –  Centralised creation of detectors with sane defaults.
//   • Pipeline Pattern   –  Stream-processing pipeline (ingest → aggregate
//                            → detection → notification).
//
// Author: EchoPulse Core Team
// ---------------------------------------------------------------------------

package drift

import (
	"context"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"
)

// --------------- Domain Events ------------------------------------------------

// FeatureEvent represents a numeric feature extracted from a SocialEvent
// and normalised into EchoPulse’s canonical form.
type FeatureEvent struct {
	Timestamp   time.Time // Event time (ingestion time can differ)
	FeatureName string    // e.g. "toxicity_score"
	Value       float64   // Normalised score/value
	ModelID     string    // Which model produced the feature
}

// DriftEvent is used by downstream services (or a model orchestrator) to decide
// whether a model should be retrained due to statistically significant drift.
type DriftEvent struct {
	FeatureName  string
	ModelID      string
	DetectorName string  // Algorithm used
	Score        float64 // Drift metric, e.g. PSI or KL divergence
	Drifted      bool    // True when score > configured threshold
	WindowStart  time.Time
	WindowEnd    time.Time
}

// --------------- Strategy Pattern: Drift Detectors ---------------------------

// DriftDetector defines the behaviour of any statistical-drift detector.
type DriftDetector interface {
	// Add adds a new observation into the detector’s internal buffer.
	Add(v float64)
	// Inspect inspects the current buffer and returns (drift, score, error).
	Inspect() (bool, float64, error)
	// Name is a human-readable identifier, e.g. "psi".
	Name() string
	// Reset clears internal state (called at the end of a window).
	Reset()
}

// psiDetector implements the Population Stability Index algorithm.
// Reference: https://www.listendata.com/2020/05/population-stability-index.html
type psiDetector struct {
	mu        sync.Mutex
	refBins   []int     // Counts in reference distribution
	curBins   []int     // Counts in current  distribution
	threshold float64   // Score at/above which drift is triggered
	binEdges  []float64 // NOTE: len(edges) == len(bins)+1
}

func newPSIDetector(opts Options) (*psiDetector, error) {
	if len(opts.PSIBinEdges) < 2 {
		return nil, errors.New("psi: at least 2 bin edges required")
	}

	binCount := len(opts.PSIBinEdges) - 1
	return &psiDetector{
		refBins:   make([]int, binCount),
		curBins:   make([]int, binCount),
		binEdges:  opts.PSIBinEdges,
		threshold: opts.PSIThreshold,
	}, nil
}

func (p *psiDetector) Name() string { return "psi" }

func (p *psiDetector) Reset() {
	p.mu.Lock()
	defer p.mu.Unlock()
	for i := range p.curBins {
		p.refBins[i] = p.curBins[i]
		p.curBins[i] = 0
	}
}

// Add routes value into the current-window histogram.
func (p *psiDetector) Add(v float64) {
	p.mu.Lock()
	defer p.mu.Unlock()

	idx := p.binIndex(v)
	p.curBins[idx]++
}

// Inspect computes PSI between refBins and curBins.
func (p *psiDetector) Inspect() (bool, float64, error) {
	p.mu.Lock()
	defer p.mu.Unlock()

	totalRef := sumInts(p.refBins)
	totalCur := sumInts(p.curBins)
	if totalRef == 0 || totalCur == 0 {
		return false, 0, errors.New("psi: insufficient observations")
	}

	var psi float64
	for i := 0; i < len(p.refBins); i++ {
		refProp := float64(p.refBins[i]) / float64(totalRef)
		curProp := float64(p.curBins[i]) / float64(totalCur)

		// Avoid log(0)
		if refProp == 0 || curProp == 0 {
			continue
		}
		psi += (curProp - refProp) * math.Log(curProp/refProp)
	}
	return psi >= p.threshold, psi, nil
}

func (p *psiDetector) binIndex(v float64) int {
	edges := p.binEdges
	n := len(edges) - 1
	for i := 0; i < n; i++ {
		if v >= edges[i] && v < edges[i+1] {
			return i
		}
	}
	return n - 1 // Last bin (inclusive of upper bound)
}

// --------------- Detector Factory --------------------------------------------

// Options defines configuration options shared by all detectors.
type Options struct {
	PSIThreshold float64   // Default: 0.25 (industry standby)
	PSIBinEdges  []float64 // e.g. []float64{0, .1, .2, .3, .4, .6, 1}
}

// NewDetector is the Factory entrypoint.
func NewDetector(kind string, opts Options) (DriftDetector, error) {
	switch kind {
	case "psi":
		return newPSIDetector(opts)
	default:
		return nil, fmt.Errorf("drift factory: unknown detector %q", kind)
	}
}

// --------------- Observer: Stream Monitor ------------------------------------

// MonitorConfig holds configuration for Monitor.
type MonitorConfig struct {
	FeatureName  string        // Feature this monitor will watch
	ModelID      string        // Model producing the feature
	DetectorKind string        // e.g. "psi"
	DetectorOpts Options       // Algorithm specific
	Window       time.Duration // Sliding window length
}

// Monitor subscribes to FeatureEvents, aggregates them inside a fixed-duration
// window and emits DriftEvents for downstream pipelines.
type Monitor struct {
	cfg       MonitorConfig
	detector  DriftDetector
	in        <-chan FeatureEvent // Read-only channel for events
	out       chan<- DriftEvent   // Output channel for drift notifications
	cancelCtx context.Context
	cancel    context.CancelFunc
	wg        sync.WaitGroup
}

// NewMonitor creates and starts a new streaming drift monitor.
func NewMonitor(cfg MonitorConfig, in <-chan FeatureEvent, out chan<- DriftEvent) (*Monitor, error) {
	det, err := NewDetector(cfg.DetectorKind, cfg.DetectorOpts)
	if err != nil {
		return nil, err
	}

	ctx, cancel := context.WithCancel(context.Background())
	m := &Monitor{
		cfg:       cfg,
		detector:  det,
		in:        in,
		out:       out,
		cancelCtx: ctx,
		cancel:    cancel,
	}

	m.wg.Add(1)
	go m.loop()

	return m, nil
}

// Close gracefully terminates the monitor and flushes the event loop.
func (m *Monitor) Close() error {
	m.cancel()
	m.wg.Wait()
	return nil
}

// loop is the core pipeline: ingest → detect → emit.
func (m *Monitor) loop() {
	defer m.wg.Done()

	ticker := time.NewTicker(m.cfg.Window)
	defer ticker.Stop()

	windowStart := time.Now()

	for {
		select {
		case <-m.cancelCtx.Done():
			return

		case fe := <-m.in:
			// Filter by feature & model.
			if fe.FeatureName != m.cfg.FeatureName || fe.ModelID != m.cfg.ModelID {
				continue
			}
			if !validFloat(fe.Value) {
				continue
			}
			m.detector.Add(fe.Value)

		case <-ticker.C:
			// Window ended, compute drift score.
			drifted, score, err := m.detector.Inspect()
			if err != nil {
				// Log instead of panic – in real-prod use structured logger.
				fmt.Printf("[drift] %v\n", err)
				// Reset regardless to avoid horror scenarios.
				m.detector.Reset()
				windowStart = time.Now()
				continue
			}

			m.out <- DriftEvent{
				FeatureName:  m.cfg.FeatureName,
				ModelID:      m.cfg.ModelID,
				DetectorName: m.detector.Name(),
				Score:        score,
				Drifted:      drifted,
				WindowStart:  windowStart,
				WindowEnd:    time.Now(),
			}

			// Prepare next window.
			m.detector.Reset()
			windowStart = time.Now()
		}
	}
}

// --------------- Helpers ------------------------------------------------------

func sumInts(xs []int) int {
	var s int
	for _, v := range xs {
		s += v
	}
	return s
}

func validFloat(f float64) bool {
	return !math.IsNaN(f) && !math.IsInf(f, 0)
}

// --------------- Example (stand-alone) ----------------------------------------

// The following code snippet demonstrates how the Monitor can be wired into
// an in-memory pipeline. In production, "in" and "out" would be backed by
// Apache Kafka, NATS JetStream or gRPC streams.

// func example() {
// 	in := make(chan FeatureEvent, 1_000)
// 	out := make(chan DriftEvent, 100)

// 	cfg := MonitorConfig{
// 		FeatureName:  "toxicity_score",
// 		ModelID:      "toxicity_v2",
// 		DetectorKind: "psi",
// 		DetectorOpts: Options{
// 			PSIThreshold: 0.25,
// 			PSIBinEdges:  []float64{0, .05, .1, .2, .3, .4, .5, .6, .8, 1},
// 		},
// 		Window: 5 * time.Minute,
// 	}
// 	monitor, err := NewMonitor(cfg, in, out)
// 	if err != nil {
// 		panic(err)
// 	}
// 	defer monitor.Close()

// 	// Simulate traffic.
// 	go func() {
// 		for {
// 			in <- FeatureEvent{
// 				Timestamp:   time.Now(),
// 				FeatureName: "toxicity_score",
// 				Value:       rand.Float64(),
// 				ModelID:     "toxicity_v2",
// 			}
// 			time.Sleep(20 * time.Millisecond)
// 		}
// 	}()

// 	// Handle drift events.
// 	for ev := range out {
// 		fmt.Printf("[DRIFT] %+v\n", ev)
// 	}
// }
```