```go
// File: src/module_8.go
// Description: DriftWatcher service. Continuously monitors online model
//              predictions flowing over the event-bus, performs a streaming
//              Kolmogorov–Smirnov test against the training baseline, and
//              publishes a DriftAlert event when statistically significant
//              drift is detected.
//              The code demonstrates the Strategy, Observer, Pipeline and
//              Factory patterns used throughout EchoPulse.
//
// NOTE: This file is self-contained to keep the demo concise.  In production
//       the bus implementation, model registry client, and proto generated
//       types would live in their own packages.

package echopulse

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"math"
	"sort"
	"sync"
	"time"
)

// ============================== Event Bus Layer =============================

// EventBus abstracts the underlying messaging system (Kafka, JetStream, …).
// Only the subset used by DriftWatcher is declared here.
type EventBus interface {
	Subscribe(ctx context.Context, topic, group string) (<-chan []byte, error)
	Publish(ctx context.Context, topic string, msg []byte) error
	Close() error
}

// busFactory is a runtime switch enabling EchoPulse to choose between
// Kafka / NATS / mock for unit tests.
type busFactory func() (EventBus, error)

// registerBusFactory allows module initialization code to inject
// the concrete factory.  (Factory pattern)
var (
	muBusFactory sync.RWMutex
	makeBus      busFactory
)

// RegisterBusFactory must be called at process startup (main) *once*.
func RegisterBusFactory(f busFactory) {
	muBusFactory.Lock()
	defer muBusFactory.Unlock()
	makeBus = f
}

// newBus uses the chosen runtime factory to construct an EventBus.
func newBus() (EventBus, error) {
	muBusFactory.RLock()
	defer muBusFactory.RUnlock()
	if makeBus == nil {
		return nil, errors.New("no event-bus factory registered")
	}
	return makeBus()
}

// ============================= Domain Event Types ===========================

// predictionEvent is pushed by online inference workers.
type predictionEvent struct {
	Timestamp    time.Time `json:"ts"`
	Model        string    `json:"model"`
	InputHash    string    `json:"input_hash"`
	Probability  float64   `json:"prob"` // e.g. positive sentiment probability
	Label        *int      `json:"lbl"`  // may be nil if ground-truth unknown
	FeatureSlice string    `json:"-"`
}

// driftAlertEvent notifies downstream systems that the statistical properties
// of the incoming stream no longer match the training set.
type driftAlertEvent struct {
	Timestamp   time.Time `json:"ts"`
	Model       string    `json:"model"`
	Metric      string    `json:"metric"`
	Statistic   float64   `json:"statistic"`
	PValue      float64   `json:"p_value"`
	WindowSecs  int       `json:"window_secs"`
	Description string    `json:"description"`
}

// =========================== Drift Detection Logic ==========================

// DriftDetector is the Strategy interface.
type DriftDetector interface {
	Add(prob float64)
	// Drift returns (driftDetected, statistic, pValue)
	Drift() (bool, float64, float64)
	Reset()
}

// ksDetector implements a streaming Kolmogorov-Smirnov test.  A baseline of
// empirical CDF values is captured during training and passed at build time
// (omitted in this demo – we approximate using a synthetic normal dist).
type ksDetector struct {
	// parameters
	windowSize int
	alpha      float64 // significance level

	// runtime state
	samples []float64
}

// newKSDetector returns a *ksDetector with user supplied config.
func newKSDetector(window int, alpha float64) DriftDetector {
	return &ksDetector{
		windowSize: window,
		alpha:      alpha,
		samples:    make([]float64, 0, window),
	}
}

func (k *ksDetector) Add(prob float64) {
	if len(k.samples) == k.windowSize {
		k.samples = k.samples[1:]
	}
	k.samples = append(k.samples, prob)
}

func (k *ksDetector) Drift() (bool, float64, float64) {
	if len(k.samples) < k.windowSize {
		return false, 0, 1
	}
	// Baseline CDF approximated by Uniform[0,1] for demo purposes.
	stat := ksStatistic(k.samples)
	// Kolmogorov distribution critical value approximation
	n := float64(len(k.samples))
	c := 1.36 // for alpha≈0.05
	crit := c / math.Sqrt(n)
	drift := stat > crit
	p := ksPValue(stat, n) // slow but OK for window<=1k
	return drift, stat, p
}

func (k *ksDetector) Reset() {
	k.samples = k.samples[:0]
}

// ----------------------------- KS utilities --------------------------------

// ksStatistic computes D_n = sup |F_n(x) - F(x)| where F(x) for baseline
// is assumed to be Uniform[0,1].
func ksStatistic(sample []float64) float64 {
	n := len(sample)
	cp := append([]float64(nil), sample...)
	sort.Float64s(cp)

	var d float64
	for i, v := range cp {
		fn := float64(i+1) / float64(n)
		d = math.Max(d, math.Max(math.Abs(fn-v), math.Abs(v-float64(i)/float64(n))))
	}
	return d
}

// ksPValue returns the Kolmogorov distribution complementary CDF
// (Smirnov approximation). n is sample size.
func ksPValue(d float64, n float64) float64 {
	if d <= 0 {
		return 1
	}
	sqrtN := math.Sqrt(n)
	lam := (sqrtN + 0.12 + 0.11/sqrtN) * d
	// Use the asymptotic formula
	// P(D_n > d) ≈ 2 Σ (-1)^{k-1} e^{-2 k^2 λ^2}
	sum := 0.0
	for k := 1; k < 100; k++ {
		add := math.Exp(-2 * math.Pow(float64(k), 2) * lam * lam)
		if k%2 == 1 {
			sum += add
		} else {
			sum -= add
		}
		if add < 1e-6 {
			break
		}
	}
	return 2 * sum
}

// ============================== DriftWatcher ===============================

// DriftWatcher subscribes to <predictions> and publishes <model.drift> events.
type DriftWatcher struct {
	detector DriftDetector
	bus      EventBus

	modelName string
	groupID   string

	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
}

// DriftWatcherConfig groups ctor arguments.
type DriftWatcherConfig struct {
	ModelName       string
	WindowSize      int
	Alpha           float64
	ConsumerGroupID string
}

// NewDriftWatcher wires everything together (Factory pattern).
func NewDriftWatcher(cfg DriftWatcherConfig) (*DriftWatcher, error) {
	bus, err := newBus()
	if err != nil {
		return nil, err
	}

	det := newKSDetector(cfg.WindowSize, cfg.Alpha)

	ctx, cancel := context.WithCancel(context.Background())

	return &DriftWatcher{
		detector: det,
		bus:      bus,

		modelName: cfg.ModelName,
		groupID:   cfg.ConsumerGroupID,

		ctx:    ctx,
		cancel: cancel,
	}, nil
}

// Start launches background processing goroutines (Observer pattern).
func (d *DriftWatcher) Start() error {
	stream, err := d.bus.Subscribe(d.ctx, "predictions."+d.modelName, d.groupID)
	if err != nil {
		return err
	}

	d.wg.Add(1)
	go func() {
		defer d.wg.Done()
		for {
			select {
			case <-d.ctx.Done():
				return
			case raw, ok := <-stream:
				if !ok {
					return
				}
				d.handleMessage(raw)
			}
		}
	}()

	return nil
}

// Stop cancels all background work and waits for completion.
func (d *DriftWatcher) Stop() {
	d.cancel()
	d.wg.Wait()
	_ = d.bus.Close()
}

func (d *DriftWatcher) handleMessage(raw []byte) {
	var ev predictionEvent
	if err := json.Unmarshal(raw, &ev); err != nil {
		log.Printf("[DriftWatcher] unable to parse event: %v", err)
		return
	}
	// Only track the configured model.
	if ev.Model != d.modelName {
		return
	}

	d.detector.Add(ev.Probability)
	drift, stat, p := d.detector.Drift()
	if drift {
		d.publishAlert(stat, p)
		d.detector.Reset()
	}
}

func (d *DriftWatcher) publishAlert(stat, p float64) {
	alert := driftAlertEvent{
		Timestamp:   time.Now().UTC(),
		Model:       d.modelName,
		Metric:      "KS",
		Statistic:   stat,
		PValue:      p,
		WindowSecs:  0, // unknown ‑ could derive from sample diff timestamps
		Description: "Kolmogorov–Smirnov drift detected",
	}

	payload, _ := json.Marshal(alert) // safe: fields all serializable
	if err := d.bus.Publish(d.ctx, "model.drift", payload); err != nil {
		log.Printf("[DriftWatcher] unable to publish drift alert: %v", err)
	}
}

// ============================= Example Mock Bus =============================
// The following section enables `go run module_8.go` to execute without
// external dependencies.  In production, register a Kafka or JetStream
// implementation via RegisterBusFactory(kafka.NewBus).

// init registers a mock bus when running under `go run` or `go test` – production
// binaries are expected to override this in main().
func init() {
	RegisterBusFactory(func() (EventBus, error) { return newMockBus(), nil })
}

// mockBus is an in-memory, fan-out pub/sub good enough for unit tests.
type mockBus struct {
	mtx      sync.RWMutex
	topics   map[string][]chan []byte
	shutdown bool
}

func newMockBus() *mockBus {
	return &mockBus{
		topics: make(map[string][]chan []byte),
	}
}

func (m *mockBus) Subscribe(ctx context.Context, topic, _ string) (<-chan []byte, error) {
	m.mtx.Lock()
	defer m.mtx.Unlock()

	if m.shutdown {
		return nil, errors.New("bus is closed")
	}

	ch := make(chan []byte, 128)
	m.topics[topic] = append(m.topics[topic], ch)

	// Handle context cancellation.
	go func() {
		<-ctx.Done()
		m.unsubscribe(topic, ch)
	}()

	return ch, nil
}

func (m *mockBus) unsubscribe(topic string, ch chan []byte) {
	m.mtx.Lock()
	defer m.mtx.Unlock()

	subs := m.topics[topic]
	for i, c := range subs {
		if c == ch {
			m.topics[topic] = append(subs[:i], subs[i+1:]...)
			close(c)
			break
		}
	}
}

func (m *mockBus) Publish(_ context.Context, topic string, msg []byte) error {
	m.mtx.RLock()
	defer m.mtx.RUnlock()

	if m.shutdown {
		return errors.New("bus is closed")
	}

	for _, sub := range m.topics[topic] {
		// non-blocking send
		select {
		case sub <- append([]byte(nil), msg...): // copy to avoid mutation
		default:
		}
	}
	return nil
}

func (m *mockBus) Close() error {
	m.mtx.Lock()
	defer m.mtx.Unlock()
	if m.shutdown {
		return nil
	}
	for t, subs := range m.topics {
		for _, ch := range subs {
			close(ch)
		}
		delete(m.topics, t)
	}
	m.shutdown = true
	return nil
}

// ============================== Demonstration ===============================
//
// Run `go run src/module_8.go` to watch the DriftWatcher raise an alert every
// ~2 seconds as the mock inference worker feeds random numbers into the stream.
//
func main() {
	cfg := DriftWatcherConfig{
		ModelName:       "sentiment_v42",
		WindowSize:      200,
		Alpha:           0.05,
		ConsumerGroupID: "drift-watcher",
	}

	watcher, err := NewDriftWatcher(cfg)
	if err != nil {
		log.Fatal(err)
	}

	if err := watcher.Start(); err != nil {
		log.Fatal(err)
	}

	// Simulate an inference worker publishing predictions.
	go func() {
		ctx := context.Background()
		bus, _ := newBus()
		defer bus.Close()

		ticker := time.NewTicker(10 * time.Millisecond)
		defer ticker.Stop()

		for range ticker.C {
			// Synthetic probability distribution: abruptly shift mean after 3 seconds.
			shift := time.Now().Unix()%6 >= 3
			mean := 0.5
			if shift {
				mean = 0.8 // introduce drift
			}
			msg := predictionEvent{
				Timestamp:   time.Now().UTC(),
				Model:       "sentiment_v42",
				Probability: clamp(normal(mean, 0.05), 0, 1),
			}
			payload, _ := json.Marshal(msg)
			_ = bus.Publish(ctx, "predictions.sentiment_v42", payload)
		}
	}()

	// Run watcher for 10 seconds
	time.Sleep(10 * time.Second)
	watcher.Stop()
}

// =========================== Helpers for demo ===============================

func normal(mean, std float64) float64 {
	// Box-Muller transform
	u1 := randFloat64()
	u2 := randFloat64()
	z := math.Sqrt(-2*math.Log(u1)) * math.Cos(2*math.Pi*u2)
	return mean + std*z
}

func randFloat64() float64 {
	return float64(time.Now().UnixNano()%1e9) / 1e9
}

func clamp(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
```