```go
// File: src/module_42.go
//
// EchoPulse: Real-Time Social Signal Processing Platform
// ------------------------------------------------------
// TrendSurfer implements a streaming, real-time sentiment–trend detector.
// It consumes canonical SocialEvents, maintains per-community online
// statistics (mean / variance via Welford), and emits TrendAlert events
// when a statistically significant sentiment shift is detected.
//
// Design notes
//  • Completely async / non-blocking (goroutine per TrendSurfer instance)
//  • Very light on dependencies (std-lib only)
//  • Side-effect isolation via EventBus interface for pluggable back-end
//  • Built-in graceful shutdown via context cancellation
//  • Unit-test friendly (pure functions + injectable clock / bus)
//
// Author: EchoPulse ML/NLP Core Team
// SPDX-License-Identifier: Apache-2.0
package processing

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"time"
)

// ---------------------------------------------------------------------
// Domain types
// ---------------------------------------------------------------------

// SocialEvent is the canonical, immutable representation of any social
// artefact ingested by the platform, after upstream enrichment.
type SocialEvent struct {
	CommunityID string            `json:"community_id"`           // logical community / shard
	Topic       string            `json:"topic,omitempty"`        // optional sub-topic
	Timestamp   time.Time         `json:"timestamp"`              // event time (UTC)
	Sentiment   SentimentAnalysis `json:"sentiment"`              // [-1,1] scaled score
	Metadata    map[string]string `json:"metadata,omitempty"`     // opaque extras
}

// SentimentAnalysis stores the output of the sentiment model.
type SentimentAnalysis struct {
	Score float64 `json:"score"` // [-1,1] where 1 == highly positive
}

// TrendAlert is emitted when a statistically significant drift or surge
// in community sentiment is detected.
type TrendAlert struct {
	CommunityID string    `json:"community_id"`
	Topic       string    `json:"topic,omitempty"`
	WindowStart time.Time `json:"window_start"`
	WindowEnd   time.Time `json:"window_end"`
	PValue      float64   `json:"p_value"`   // one-sided Z-test p-value
	AvgScore    float64   `json:"avg_score"` // mean score in window
	BaseMean    float64   `json:"base_mean"` // historical mean
	BaseStdDev  float64   `json:"base_std"`  // historical σ
	AlertType   string    `json:"alert_type"`// e.g. "positive_drift"
}

// ---------------------------------------------------------------------
// EventBus abstraction
// ---------------------------------------------------------------------

// EventBus models the subset of a message bus we need.
type EventBus interface {
	Publish(ctx context.Context, topic string, key string, value []byte) error
}

// ---------------------------------------------------------------------
// TrendSurfer implementation
// ---------------------------------------------------------------------

// Config tunes the behaviour of TrendSurfer.
type Config struct {
	// Sliding aggregation window (e.g. 2m → compute stats every 2 minutes).
	WindowSize time.Duration
	// Frequency of evaluation; typically smaller than WindowSize to ensure
	// overlaps. Must be > 0.
	EvaluationInterval time.Duration
	// Minimum samples required before evaluating a window.
	MinSamples int
	// Z-score threshold above which we emit an alert.
	// Example: 2.5 ~ 99% one-tailed.
	ZScoreThreshold float64
	// Historical decay factor for the baseline, 0<α≤1.  Smaller α gives
	// more memory to earlier data.  α=1 → simple cumulative mean/var.
	EWMAlpha float64
	// Bus topic for outgoing alerts.
	AlertTopic string
}

// Validate performs cheap sanity checks.
func (c Config) Validate() error {
	switch {
	case c.WindowSize <= 0:
		return errors.New("WindowSize must be >0")
	case c.EvaluationInterval <= 0:
		return errors.New("EvaluationInterval must be >0")
	case c.MinSamples <= 0:
		return errors.New("MinSamples must be >0")
	case c.ZScoreThreshold <= 0:
		return errors.New("ZScoreThreshold must be >0")
	case c.EWMAlpha <= 0 || c.EWMAlpha > 1:
		return errors.New("EWMAlpha must be within (0,1]")
	case c.AlertTopic == "":
		return errors.New("AlertTopic required")
	default:
		return nil
	}
}

// TrendSurfer ingests SocialEvents, tracks sentiment evolution, and
// surfaces statistically-significant drifts / surges.
type TrendSurfer struct {
	cfg    Config
	bus    EventBus
	clock  func() time.Time // injectable for tests, default time.Now
	inChan chan SocialEvent

	mu     sync.RWMutex                   // guards perCommunity
	communities map[string]*communityStat // keyed by CommunityID
	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
}

// communityStat holds both the historical baseline and the current window.
type communityStat struct {
	// Sliding window buffer (circular).
	window *ringBuffer
	// Baseline running stats (EWMA).
	baseMean float64
	baseVar  float64
	// Count of observations seen (for initialisation).
	seen int64
}

// NewTrendSurfer constructs and starts a TrendSurfer instance.
func NewTrendSurfer(parent context.Context, bus EventBus, cfg Config) (*TrendSurfer, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	ctx, cancel := context.WithCancel(parent)
	ts := &TrendSurfer{
		cfg:        cfg,
		bus:        bus,
		clock:      time.Now,
		inChan:     make(chan SocialEvent, 4096),
		communities: make(map[string]*communityStat),
		ctx:        ctx,
		cancel:     cancel,
	}

	// Start background consumer / evaluator loops.
	ts.wg.Add(2)
	go ts.consumeLoop()
	go ts.evaluatorLoop()

	return ts, nil
}

// Stop gracefully terminates TrendSurfer.
func (t *TrendSurfer) Stop() {
	t.cancel()
	t.wg.Wait()
}

// OnEvent satisfies the Observer interface; external callers feed data.
func (t *TrendSurfer) OnEvent(evt SocialEvent) {
	select {
	case t.inChan <- evt:
	case <-t.ctx.Done():
	}
}

// ---------------------------------------------------------------------
// Internal loops
// ---------------------------------------------------------------------

func (t *TrendSurfer) consumeLoop() {
	defer t.wg.Done()
	for {
		select {
		case evt := <-t.inChan:
			t.ingest(evt)
		case <-t.ctx.Done():
			return
		}
	}
}

func (t *TrendSurfer) evaluatorLoop() {
	defer t.wg.Done()
	ticker := time.NewTicker(t.cfg.EvaluationInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			t.evaluate()
		case <-t.ctx.Done():
			return
		}
	}
}

// ---------------------------------------------------------------------
// Ingestion & Statistics
// ---------------------------------------------------------------------

func (t *TrendSurfer) ingest(evt SocialEvent) {
	if math.IsNaN(evt.Sentiment.Score) {
		return // skip invalid
	}
	id := evt.CommunityID
	t.mu.RLock()
	cs, ok := t.communities[id]
	t.mu.RUnlock()

	if !ok {
		cs = &communityStat{
			window: newRingBuffer(int(t.cfg.MinSamples * 4)), // heuristic capacity
		}
		t.mu.Lock()
		t.communities[id] = cs
		t.mu.Unlock()
	}

	cs.window.push(evt)

	// Update EWMA baseline.
	alpha := t.cfg.EWMAlpha
	x := evt.Sentiment.Score
	if cs.seen == 0 {
		cs.baseMean = x
		cs.baseVar = 0
	} else {
		delta := x - cs.baseMean
		cs.baseMean += alpha * delta
		cs.baseVar = (1-alpha)*cs.baseVar + alpha*delta*delta
	}
	cs.seen++
}

// evaluate iterates over communities, performs significance test.
func (t *TrendSurfer) evaluate() {
	now := t.clock()
	cutoff := now.Add(-t.cfg.WindowSize)

	t.mu.RLock()
	defer t.mu.RUnlock()
	for id, cs := range t.communities {
		window := cs.window.snapshot(cutoff)
		if len(window) < t.cfg.MinSamples {
			continue
		}
		mean, std := meanStd(window)
		if std == 0 {
			continue // avoid divide by zero
		}
		z := (mean - cs.baseMean) / std
		if math.Abs(z) < t.cfg.ZScoreThreshold {
			continue
		}
		alertType := "positive_drift"
		if z < 0 {
			alertType = "negative_drift"
		}
		pval := 1 - normalCDF(math.Abs(z))
		alert := TrendAlert{
			CommunityID: id,
			WindowStart: cutoff,
			WindowEnd:   now,
			PValue:      pval,
			AvgScore:    mean,
			BaseMean:    cs.baseMean,
			BaseStdDev:  math.Sqrt(cs.baseVar),
			AlertType:   alertType,
		}

		payload, _ := json.Marshal(alert) // guaranteed serialisable
		_ = t.bus.Publish(t.ctx, t.cfg.AlertTopic, id, payload)
	}
}

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

// meanStd computes mean and std.dev for a slice of float64.
func meanStd(xs []float64) (mean, std float64) {
	if len(xs) == 0 {
		return 0, 0
	}
	var m, s float64
	for i, x := range xs {
		delta := x - m
		m += delta / float64(i+1)
		s += delta * (x - m)
	}
	return m, math.Sqrt(s / float64(len(xs)))
}

// normalCDF returns Φ(z) for standard normal.
func normalCDF(z float64) float64 {
	return 0.5 * (1 + math.Erf(z/math.Sqrt2))
}

// ---------------------------------------------------------------------
// Ring buffer for sliding window
// ---------------------------------------------------------------------

type ringBuffer struct {
	mu   sync.RWMutex
	buf  []SocialEvent
	head int
	size int
	cap  int
}

func newRingBuffer(capacity int) *ringBuffer {
	return &ringBuffer{
		buf: make([]SocialEvent, capacity),
		cap: capacity,
	}
}

func (r *ringBuffer) push(evt SocialEvent) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.buf[r.head] = evt
	r.head = (r.head + 1) % r.cap
	if r.size < r.cap {
		r.size++
	}
}

// snapshot returns sentiment scores of events newer than cutoff.
// The copy is detached from the ring to avoid holding locks during
// heavy computations.
func (r *ringBuffer) snapshot(cutoff time.Time) []float64 {
	r.mu.RLock()
	defer r.mu.RUnlock()

	out := make([]float64, 0, r.size)
	idx := r.head // newest → oldest traversal
	for i := 0; i < r.size; i++ {
		idx = (idx - 1 + r.cap) % r.cap
		evt := r.buf[idx]
		if evt.Timestamp.Before(cutoff) {
			break
		}
		out = append(out, evt.Sentiment.Score)
	}
	return out
}
```