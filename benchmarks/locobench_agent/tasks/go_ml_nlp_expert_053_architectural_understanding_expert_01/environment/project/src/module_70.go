```go
// Code generated for EchoPulse (ml_nlp) — DO NOT EDIT.
//
// module_70.go
//
// Package monitoring implements on-line statistical drift detection for
// continuously-emitted SocialEvents.  It subscribes to the high-throughput
// event bus, keeps sliding-window estimates of the feature distribution, and
// raises DriftEvents whenever the empirical Jensen-Shannon divergence between
// the live window and a (slowly updated) reference window exceeds a configured
// threshold.
//
package monitoring

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"time"
)

// ---------------------------------------------------------------------------
// Domain Models
// ---------------------------------------------------------------------------

// SocialEvent is the canonical representation of user-generated artifacts
// after they have been enriched by upstream services.  Only the fields needed
// for drift detection are included here.
type SocialEvent struct {
	Timestamp time.Time   `json:"ts"`
	Features  []float64   `json:"fv"` // Dense, normalized feature vector
	UserID    string      `json:"uid"`
	Meta      interface{} `json:"meta,omitempty"`
}

// DriftEvent is published when the detector observes statistically significant
// divergence between the live (fast) window and the reference (slow) window.
type DriftEvent struct {
	DetectedAt   time.Time `json:"detected_at"`
	PValue       float64   `json:"p_value"`
	JSScore      float64   `json:"js_score"`
	WindowSize   int       `json:"window_size"`
	ReferenceAge time.Duration `json:"reference_age"`
}

// ---------------------------------------------------------------------------
// Bus Abstractions (lightweight to keep this module standalone)
// ---------------------------------------------------------------------------

// EventPublisher is the minimal abstraction required to push events back onto
// the platform event bus.  A concrete implementation will be provided at
// wiring time (Kafka producer, NATS JetStream, etc.).
type EventPublisher interface {
	Publish(ctx context.Context, topic string, msg []byte) error
}

// EventConsumer is a minimal abstraction for high-throughput subscription to
// SocialEvent streams.
type EventConsumer interface {
	Subscribe(ctx context.Context, topic string) (<-chan []byte, error)
}

// ---------------------------------------------------------------------------
// DriftMonitor
// ---------------------------------------------------------------------------

// DriftMonitorConfig tunes the statistical and runtime behaviour of the
// detector.
type DriftMonitorConfig struct {
	FastWindowSize  int           // Number of samples in the “current” window
	SlowWindowSize  int           // Number of samples in the reference window
	MaxFeatureDim   int           // Sanity limit on incoming feature vectors
	MinSamples      int           // Minimum samples before testing
	Threshold       float64       // JS divergence required to flag drift
	Cooldown        time.Duration // Min duration between successive alarms
	ConsumeTopic    string        // Bus topic for SocialEvents
	PublishTopic    string        // Bus topic for DriftEvents
}

// DriftMonitor implements a concurrent, self-contained drift detector.
type DriftMonitor struct {
	cfg        DriftMonitorConfig
	consumer   EventConsumer
	publisher  EventPublisher
	log        Logger // Simple slf4j-style façade to decouple from concrete logger

	// Internal state protected by mu
	mu            sync.RWMutex
	fastWindow    *ringBuffer
	slowWindow    *ringBuffer
	lastAlarmTime time.Time
}

// Logger is a tiny façade allowing pluggable logging libraries.
type Logger interface {
	Infof(format string, args ...any)
	Warnf(format string, args ...any)
	Errorf(format string, args ...any)
}

// NewDriftMonitor wires together a DriftMonitor instance.
func NewDriftMonitor(cfg DriftMonitorConfig, c EventConsumer, p EventPublisher, l Logger) (*DriftMonitor, error) {
	if cfg.FastWindowSize <= 0 || cfg.SlowWindowSize <= 0 {
		return nil, errors.New("window sizes must be positive")
	}
	if cfg.FastWindowSize > cfg.SlowWindowSize {
		return nil, errors.New("fast window must be <= slow window")
	}
	if cfg.MinSamples <= 0 {
		cfg.MinSamples = cfg.FastWindowSize
	}
	if cfg.MaxFeatureDim <= 0 {
		cfg.MaxFeatureDim = 2048
	}
	return &DriftMonitor{
		cfg:         cfg,
		consumer:    c,
		publisher:   p,
		log:         l,
		fastWindow:  newRingBuffer(cfg.FastWindowSize),
		slowWindow:  newRingBuffer(cfg.SlowWindowSize),
	}, nil
}

// Start spawns the consumption loop and blocks until ctx is cancelled or an
// unrecoverable error occurs.
func (m *DriftMonitor) Start(ctx context.Context) error {
	ch, err := m.consumer.Subscribe(ctx, m.cfg.ConsumeTopic)
	if err != nil {
		return err
	}

	m.log.Infof("[drift] monitor started; threshold=%.4f, fast=%d, slow=%d",
		m.cfg.Threshold, m.cfg.FastWindowSize, m.cfg.SlowWindowSize)

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case raw := <-ch:
			var ev SocialEvent
			if err := json.Unmarshal(raw, &ev); err != nil {
				m.log.Errorf("[drift] failed to decode SocialEvent: %v", err)
				continue
			}
			if len(ev.Features) == 0 || len(ev.Features) > m.cfg.MaxFeatureDim {
				m.log.Warnf("[drift] invalid feature vector len=%d", len(ev.Features))
				continue
			}
			m.ingest(ev)
			if m.shouldTest() {
				m.testAndMaybePublish(ctx)
			}
		}
	}
}

// ingest pushes the feature vector into both fast and slow windows, with the
// slow window acting like a decaying reservoir (slowly drifting reference).
func (m *DriftMonitor) ingest(ev SocialEvent) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.fastWindow.push(ev.Features)
	m.slowWindow.push(ev.Features)
}

// shouldTest tells whether we have accumulated enough samples to run the
// divergence test and whether the cooldown period has passed.
func (m *DriftMonitor) shouldTest() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if m.fastWindow.len() < m.cfg.MinSamples {
		return false
	}
	if time.Since(m.lastAlarmTime) < m.cfg.Cooldown {
		return false
	}
	return true
}

// testAndMaybePublish runs a Jensen-Shannon divergence test between the fast
// and slow windows.  If the score exceeds m.cfg.Threshold, a DriftEvent is
// emitted.
func (m *DriftMonitor) testAndMaybePublish(ctx context.Context) {
	m.mu.RLock()
	fast := m.fastWindow.snapshot()
	slow := m.slowWindow.snapshot()
	m.mu.RUnlock()

	js := averageJensenShannon(fast, slow)
	if js < m.cfg.Threshold {
		return
	}

	event := DriftEvent{
		DetectedAt:   time.Now().UTC(),
		PValue:       0.0, // Placeholder: future work to integrate permutation test
		JSScore:      js,
		WindowSize:   len(fast),
		ReferenceAge: time.Since(m.slowWindow.oldest()),
	}

	payload, err := json.Marshal(event)
	if err != nil {
		m.log.Errorf("[drift] failed to marshal DriftEvent: %v", err)
		return
	}

	if err := m.publisher.Publish(ctx, m.cfg.PublishTopic, payload); err != nil {
		m.log.Errorf("[drift] failed to publish drift event: %v", err)
		return
	}

	m.log.Warnf("[drift] divergence detected! js=%.4f win=%d", js, len(fast))

	m.mu.Lock()
	m.lastAlarmTime = time.Now()
	m.fastWindow.reset() // Flush fast window so next detection waits for fresh data
	m.mu.Unlock()
}

// ---------------------------------------------------------------------------
// Statistics helpers
// ---------------------------------------------------------------------------

// averageJensenShannon computes the mean JS divergence over aligned feature
// dimensions.  Vectors are expected to be ℓ₂-normalized upstream, therefore
// each dimension already resembles a probability mass attribution.
func averageJensenShannon(a, b [][]float64) float64 {
	if len(a) == 0 || len(b) == 0 {
		return 0
	}

	dim := len(a[0])
	pa := make([]float64, dim)
	pb := make([]float64, dim)

	// Aggregate per-feature means of both windows
	for _, v := range a {
		for i, x := range v {
			pa[i] += x
		}
	}
	for _, v := range b {
		for i, x := range v {
			pb[i] += x
		}
	}
	nA := float64(len(a))
	nB := float64(len(b))
	for i := 0; i < dim; i++ {
		pa[i] /= nA
		pb[i] /= nB
	}

	return jensenShannon(pa, pb)
}

// jensenShannon is a symmetric, smoothed variant of KL divergence.
// Inputs must be valid probability distributions that sum to 1; if they don't,
// we renormalize rather than fail hard, for robustness in production.
func jensenShannon(p, q []float64) float64 {
	if len(p) != len(q) {
		return 0
	}
	normalize := func(x []float64) {
		sum := 0.0
		for _, v := range x {
			sum += v
		}
		if math.Abs(sum-1.0) > 1e-6 && sum > 0 {
			for i := range x {
				x[i] /= sum
			}
		}
	}
	normalize(p)
	normalize(q)

	m := make([]float64, len(p))
	for i := range p {
		m[i] = (p[i] + q[i]) / 2
	}
	return (kl(p, m) + kl(q, m)) / 2
}

// kl calculates the Kullback-Leibler divergence KL(p || q).  A tiny epsilon is
// added to protect against log(0).
func kl(p, q []float64) float64 {
	const eps = 1e-12
	d := 0.0
	for i := range p {
		if p[i] == 0 {
			continue
		}
		d += p[i] * math.Log((p[i]+eps)/(q[i]+eps))
	}
	return d / math.Ln2 // Use bits as the divergence unit
}

// ---------------------------------------------------------------------------
// ringBuffer – lock-free single-producer single-consumer ring for []float64
// ---------------------------------------------------------------------------

type ringBuffer struct {
	data   [][]float64
	size   int
	cursor int
	full   bool
	ts     []time.Time // per-entry timestamps to approximate window age
}

func newRingBuffer(size int) *ringBuffer {
	return &ringBuffer{
		data: make([][]float64, size),
		ts:   make([]time.Time, size),
		size: size,
	}
}

func (r *ringBuffer) push(v []float64) {
	cp := make([]float64, len(v))
	copy(cp, v)
	r.data[r.cursor] = cp
	r.ts[r.cursor] = time.Now()
	r.cursor = (r.cursor + 1) % r.size
	if r.cursor == 0 {
		r.full = true
	}
}

func (r *ringBuffer) len() int {
	if r.full {
		return r.size
	}
	return r.cursor
}

func (r *ringBuffer) snapshot() [][]float64 {
	var out [][]float64
	if !r.full {
		out = make([][]float64, r.cursor)
		copy(out, r.data[:r.cursor])
		return out
	}

	out = make([][]float64, r.size)
	n := copy(out, r.data[r.cursor:])
	copy(out[n:], r.data[:r.cursor])
	return out
}

func (r *ringBuffer) reset() {
	r.cursor = 0
	r.full = false
}

func (r *ringBuffer) oldest() time.Time {
	if !r.full && r.cursor == 0 {
		return time.Now()
	}
	if r.full {
		return r.ts[r.cursor] // cursor points to oldest element
	}
	return r.ts[0]
}
```