```go
// Code generated for EchoPulse (Real-Time Social Signal Processing Platform)
// File: src/module_50.go
// Purpose: Online feature-drift monitor that watches streaming, numeric features,
//          detects statistically significant distribution shifts in real-time,
//          and emits alert events back onto the event bus.
//
// The component is implemented as a Strategy-Pipeline node.  It consumes the
// canonical FeatureEvent stream, maintains rolling statistics per feature using
// numerically stable Welford updates, periodically compares the “live” window
// against the historical baseline, and publishes DriftAlert events when the
// deviation exceeds a configurable threshold.
//
// NOTE: The concrete message bus implementation (Kafka, JetStream, etc.) is
//       injected via the EventBus interface, allowing this module to be reused
//       across environments and to be unit-tested with the in-memory bus below.

package echopulse

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"math"
	"sync"
	"time"
)

// ===============================
// Canonical event models
// ===============================

// FeatureEvent is produced by upstream preprocessing pipelines after they have
// extracted numeric features from raw SocialEvents (text, emoji, audio, etc.).
type FeatureEvent struct {
	Feature   string    `json:"feature"`             // canonical feature name
	Value     float64   `json:"value"`               // numeric representation
	Timestamp time.Time `json:"timestamp,omitempty"` // event creation time
}

// DriftAlert is emitted by this module when a statistically significant shift
// in the distribution of a numeric feature is detected.
type DriftAlert struct {
	Feature        string    `json:"feature"`
	DriftScore     float64   `json:"drift_score"`      // test statistic (e.g., z-score)
	BaselineMean   float64   `json:"baseline_mean"`    // long-term average
	WindowMean     float64   `json:"window_mean"`      // recent window average
	WindowCount    int64     `json:"window_count"`     // sample size in window
	GeneratedAt    time.Time `json:"generated_at"`     // alert creation time
	RecommendedAct string    `json:"recommended_act"` // optional guidance
}

// ===============================
// Event bus contract
// ===============================

// EventBus abstracts the underlying pub/sub fabric (Kafka, NATS JetStream, …).
type EventBus interface {
	Publish(ctx context.Context, topic string, msg []byte) error
	Subscribe(ctx context.Context, topic string, handler func(context.Context, []byte) error) error
}

// ===============================
// Online statistics helpers
// ===============================

type onlineStats struct {
	// Welford’s algorithm state
	mean  float64
	m2    float64
	count int64
}

func (s *onlineStats) update(x float64) {
	s.count++
	delta := x - s.mean
	s.mean += delta / float64(s.count)
	s.m2 += delta * (x - s.mean)
}

func (s *onlineStats) variance() float64 {
	if s.count < 2 {
		return 0
	}
	return s.m2 / float64(s.count-1)
}

func (s *onlineStats) reset() {
	s.mean, s.m2, s.count = 0, 0, 0
}

// ===============================
// FeatureDriftMonitor
// ===============================

// FeatureDriftMonitor maintains rolling statistics for each feature and
// periodically checks for distribution drift between the short-term window and
// long-term baseline.
type FeatureDriftMonitor struct {
	bus             EventBus
	windowDuration  time.Duration // rolling window for "live" stats
	alertTopic      string        // topic to publish DriftAlert events
	thresholdZScore float64       // alert threshold (|z| > threshold)

	// state
	mu           sync.RWMutex
	baseline     map[string]*onlineStats // long-term baseline
	window       map[string]*onlineStats // per-window stats
	cancelWorker context.CancelFunc
}

// NewFeatureDriftMonitor builds a new monitor instance.  The caller must invoke
// Start() to begin consuming events.
func NewFeatureDriftMonitor(bus EventBus, windowDuration time.Duration, thresholdZScore float64, alertTopic string) *FeatureDriftMonitor {
	return &FeatureDriftMonitor{
		bus:             bus,
		windowDuration:  windowDuration,
		alertTopic:      alertTopic,
		thresholdZScore: thresholdZScore,
		baseline:        make(map[string]*onlineStats),
		window:          make(map[string]*onlineStats),
	}
}

// Start subscribes to the "feature.stream" topic and spawns the analysis
// goroutine.  A cancellation of ctx will gracefully shut everything down.
func (m *FeatureDriftMonitor) Start(ctx context.Context, featureStreamTopic string) error {
	if m.bus == nil {
		return errors.New("FeatureDriftMonitor: nil EventBus")
	}
	ctx, cancel := context.WithCancel(ctx)
	m.cancelWorker = cancel

	// subscribe to incoming feature events
	if err := m.bus.Subscribe(ctx, featureStreamTopic, m.processRaw); err != nil {
		return err
	}

	// periodic tick to evaluate window stats
	go m.windowEvaluator(ctx)
	log.Printf("[drift-monitor] started (window=%s threshold=%.2f topic=%s)",
		m.windowDuration, m.thresholdZScore, featureStreamTopic)
	return nil
}

// Stop terminates background workers.
func (m *FeatureDriftMonitor) Stop() {
	if m.cancelWorker != nil {
		m.cancelWorker()
	}
}

// processRaw is the subscription handler; it unpacks the message and updates
// window statistics under a feature-level lock.
func (m *FeatureDriftMonitor) processRaw(ctx context.Context, msg []byte) error {
	var fe FeatureEvent
	if err := json.Unmarshal(msg, &fe); err != nil {
		return err
	}

	if fe.Feature == "" {
		return errors.New("empty feature name")
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	// update window stats
	ws := m.window[fe.Feature]
	if ws == nil {
		ws = &onlineStats{}
		m.window[fe.Feature] = ws
	}
	ws.update(fe.Value)

	// update baseline incrementally (EMA-ish) to keep memory bounded
	bs := m.baseline[fe.Feature]
	if bs == nil {
		bs = &onlineStats{}
		m.baseline[fe.Feature] = bs
	}
	bs.update(fe.Value)

	return nil
}

// windowEvaluator periodically examines the collected window statistics,
// compares them against the baseline, publishes alerts when the deviation is
// significant, and finally resets the window statistics.
func (m *FeatureDriftMonitor) windowEvaluator(ctx context.Context) {
	ticker := time.NewTicker(m.windowDuration)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Println("[drift-monitor] shutting down")
			return
		case <-ticker.C:
			m.evaluateAndFlush(ctx)
		}
	}
}

// evaluateAndFlush holds the central logic for drift detection.
func (m *FeatureDriftMonitor) evaluateAndFlush(ctx context.Context) {
	m.mu.Lock()
	defer m.mu.Unlock()

	now := time.Now()
	for feat, wStats := range m.window {
		bStats := m.baseline[feat]
		if bStats == nil || wStats.count == 0 {
			continue // not enough information
		}

		// compute pooled std error and z-score
		bVar := bStats.variance()
		if bVar == 0 {
			continue // variance too low; skip noisy alert
		}
		pooledStdErr := math.Sqrt(bVar / float64(wStats.count))
		if pooledStdErr == 0 {
			continue
		}
		z := math.Abs(wStats.mean-bStats.mean) / pooledStdErr
		if z >= m.thresholdZScore {
			// drift detected; publish alert
			alert := DriftAlert{
				Feature:        feat,
				DriftScore:     z,
				BaselineMean:   bStats.mean,
				WindowMean:     wStats.mean,
				WindowCount:    wStats.count,
				GeneratedAt:    now,
				RecommendedAct: "retrain_model", // default suggestion
			}
			serialized, err := json.Marshal(alert)
			if err != nil {
				log.Printf("[drift-monitor] alert marshal error: %v", err)
				continue
			}
			if err := m.bus.Publish(ctx, m.alertTopic, serialized); err != nil {
				log.Printf("[drift-monitor] alert publish error: %v", err)
			} else {
				log.Printf("[drift-monitor] drift alert published: feature=%s z=%.2f", feat, z)
			}
		}

		// reset window stats for next interval
		wStats.reset()
	}
}

// ===============================
// An in-memory bus implementation
// (useful for unit tests & local dev)
// ===============================

type inMemoryBus struct {
	mu      sync.RWMutex
	handlers map[string][]func(context.Context, []byte) error
}

func NewInMemoryBus() *inMemoryBus {
	return &inMemoryBus{
		handlers: make(map[string][]func(context.Context, []byte) error),
	}
}

func (b *inMemoryBus) Publish(ctx context.Context, topic string, msg []byte) error {
	b.mu.RLock()
	hList := b.handlers[topic]
	b.mu.RUnlock()

	if len(hList) == 0 {
		return nil // nobody listening; not an error
	}

	// fan-out to all subscribers asynchronously
	for _, h := range hList {
		hCopy := h
		go func() {
			if err := hCopy(ctx, msg); err != nil {
				log.Printf("[in-mem-bus] handler error on topic %s: %v", topic, err)
			}
		}()
	}
	return nil
}

func (b *inMemoryBus) Subscribe(ctx context.Context, topic string, handler func(context.Context, []byte) error) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.handlers[topic] = append(b.handlers[topic], handler)
	return nil
}

// ===============================
// Example usage (can be placed in a _test.go file)
// ===============================

/*
func Example() {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	bus := NewInMemoryBus()
	monitor := NewFeatureDriftMonitor(bus, 10*time.Second, 3.0, "drift.alerts")
	if err := monitor.Start(ctx, "feature.stream"); err != nil {
		log.Fatal(err)
	}

	// Simulate streaming feature events
	go func() {
		ticker := time.NewTicker(200 * time.Millisecond)
		defer ticker.Stop()

		for i := 0; i < 500; i++ {
			v := rand.NormFloat64()*1.0 + 0 // baseline N(0,1)
			fe := FeatureEvent{
				Feature: "sentiment_score",
				Value:   v,
			}
			b, _ := json.Marshal(fe)
			_ = bus.Publish(ctx, "feature.stream", b)
			<-ticker.C
		}
	}()

	// Wait long enough for at least one evaluation cycle
	time.Sleep(30 * time.Second)
	monitor.Stop()
}
*/
```