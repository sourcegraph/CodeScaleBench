package echopulse

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"sync"
	"time"

	"go.uber.org/zap"
)

// -----------------------------------------------------------------------
// Event bus abstraction – allows us to stay decoupled from Kafka / NATS.
// -----------------------------------------------------------------------

type EventBus interface {
	Publish(topic string, msg interface{}) error
	Subscribe(ctx context.Context, topic string) (<-chan []byte, error)
}

// -----------------------------------------------------------------------
// Drift detector Strategy + Factory
// -----------------------------------------------------------------------

// DriftDetector encapsulates an algorithm that determines whether the
// distribution of the incoming feature batch has diverged from a
// reference window.
type DriftDetector interface {
	// Name returns the unique identifier of the detector implementation.
	Name() string
	// Detect returns (drifted?, score, error)
	Detect(reference, current []float64) (bool, float64, error)
}

// DetectorFactory is a functional factory for DriftDetectors.
type DetectorFactory func(cfg json.RawMessage) (DriftDetector, error)

var (
	factoryMu          sync.RWMutex
	detectorFactories  = make(map[string]DetectorFactory)
	ErrUnknownDetector = errors.New("echopulse: unknown drift detector")
)

// RegisterDriftDetector registers a detector factory by name. Called from init().
func RegisterDriftDetector(name string, f DetectorFactory) {
	factoryMu.Lock()
	defer factoryMu.Unlock()
	detectorFactories[name] = f
}

// NewDriftDetector instantiates a detector by name + config blob.
func NewDriftDetector(name string, cfg json.RawMessage) (DriftDetector, error) {
	factoryMu.RLock()
	defer factoryMu.RUnlock()
	f, ok := detectorFactories[name]
	if !ok {
		return nil, fmt.Errorf("%w %q", ErrUnknownDetector, name)
	}
	return f(cfg)
}

// -----------------------------------------------------------------------
// KS-Test based detector implementation
// -----------------------------------------------------------------------

type ksConfig struct {
	Threshold float64 `json:"threshold"` // threshold for the KS statistic
}

type ksTestDetector struct {
	threshold float64
}

func (k *ksTestDetector) Name() string { return "kstest" }

func (k *ksTestDetector) Detect(reference, current []float64) (bool, float64, error) {
	if len(reference) == 0 || len(current) == 0 {
		return false, 0, errors.New("kstest: empty sample")
	}

	d := ksStatistic(reference, current)
	drifted := d > k.threshold
	return drifted, d, nil
}

func init() {
	RegisterDriftDetector("kstest", func(cfg json.RawMessage) (DriftDetector, error) {
		c := ksConfig{Threshold: 0.12} // sensible default
		if len(cfg) > 0 {
			if err := json.Unmarshal(cfg, &c); err != nil {
				return nil, err
			}
		}
		return &ksTestDetector{threshold: c.Threshold}, nil
	})
}

// ksStatistic calculates the two-sample Kolmogorov–Smirnov statistic.
func ksStatistic(x, y []float64) float64 {
	xs := append([]float64(nil), x...)
	ys := append([]float64(nil), y...)
	sort.Float64s(xs)
	sort.Float64s(ys)

	n1, n2 := float64(len(xs)), float64(len(ys))
	i1, i2 := 0, 0
	var cdf1, cdf2, d float64

	for i1 < len(xs) && i2 < len(ys) {
		if xs[i1] <= ys[i2] {
			i1++
			cdf1 = float64(i1) / n1
		} else {
			i2++
			cdf2 = float64(i2) / n2
		}
		d = math.Max(d, math.Abs(cdf1-cdf2))
	}

	// Flush remaining steps.
	for i1 < len(xs) {
		i1++
		cdf1 = float64(i1) / n1
		d = math.Max(d, math.Abs(cdf1-cdf2))
	}
	for i2 < len(ys) {
		i2++
		cdf2 = float64(i2) / n2
		d = math.Max(d, math.Abs(cdf1-cdf2))
	}
	return d
}

// -----------------------------------------------------------------------
// Event payloads
// -----------------------------------------------------------------------

// FeatureWindowEvent is emitted by upstream feature-windowing service.
type FeatureWindowEvent struct {
	Feature        string    `json:"feature"`
	ReferenceUUID  string    `json:"reference_uuid"`
	CurrentUUID    string    `json:"current_uuid"`
	ReferenceBatch []float64 `json:"reference"`
	CurrentBatch   []float64 `json:"current"`
	Timestamp      time.Time `json:"ts"`
}

// DriftEvent is published by the DriftMonitor whenever drift is detected.
type DriftEvent struct {
	Feature       string    `json:"feature"`
	Detector      string    `json:"detector"`
	Score         float64   `json:"score"`
	ReferenceUUID string    `json:"reference_uuid"`
	CurrentUUID   string    `json:"current_uuid"`
	Timestamp     time.Time `json:"ts"`
}

// -----------------------------------------------------------------------
// DriftMonitor – Observer pattern implementation
// -----------------------------------------------------------------------

type DriftMonitor struct {
	bus           EventBus
	detector      DriftDetector
	inTopic       string
	outTopic      string
	logger        *zap.Logger
	ctx           context.Context
	cancel        context.CancelFunc
	startStopLock sync.Mutex
	running       bool
}

// DriftMonitorConfig is typically unmarshalled from HCL / YAML / JSON.
type DriftMonitorConfig struct {
	InTopic        string          `json:"in_topic"`
	OutTopic       string          `json:"out_topic"`
	Detector       string          `json:"detector"`
	DetectorConfig json.RawMessage `json:"detector_config"`
}

func NewDriftMonitor(bus EventBus, cfg DriftMonitorConfig, l *zap.Logger) (*DriftMonitor, error) {
	if cfg.InTopic == "" || cfg.OutTopic == "" {
		return nil, errors.New("drift monitor: topics must be provided")
	}

	detector, err := NewDriftDetector(cfg.Detector, cfg.DetectorConfig)
	if err != nil {
		return nil, err
	}

	ctx, cancel := context.WithCancel(context.Background())

	return &DriftMonitor{
		bus:      bus,
		detector: detector,
		inTopic:  cfg.InTopic,
		outTopic: cfg.OutTopic,
		logger:   l.Named("drift_monitor"),
		ctx:      ctx,
		cancel:   cancel,
	}, nil
}

// Start begins consuming feature-window events and performing drift checks.
func (m *DriftMonitor) Start() error {
	m.startStopLock.Lock()
	defer m.startStopLock.Unlock()
	if m.running {
		return errors.New("drift monitor already running")
	}

	ch, err := m.bus.Subscribe(m.ctx, m.inTopic)
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}

	m.running = true
	go m.consume(ch)
	m.logger.Info("drift monitor started",
		zap.String("detector", m.detector.Name()),
		zap.String("inTopic", m.inTopic),
		zap.String("outTopic", m.outTopic),
	)
	return nil
}

// Stop gracefully halts event processing.
func (m *DriftMonitor) Stop() {
	m.startStopLock.Lock()
	defer m.startStopLock.Unlock()
	if !m.running {
		return
	}
	m.cancel()
	m.running = false
	m.logger.Info("drift monitor stopped")
}

func (m *DriftMonitor) consume(ch <-chan []byte) {
	for {
		select {
		case <-m.ctx.Done():
			return
		case raw, ok := <-ch:
			if !ok {
				m.logger.Warn("input channel closed unexpectedly")
				return
			}
			var evt FeatureWindowEvent
			if err := json.Unmarshal(raw, &evt); err != nil {
				m.logger.Error("unmarshal feature window event", zap.Error(err))
				continue
			}

			go m.handle(evt)
		}
	}
}

func (m *DriftMonitor) handle(evt FeatureWindowEvent) {
	start := time.Now()
	didDrift, score, err := m.detector.Detect(evt.ReferenceBatch, evt.CurrentBatch)
	if err != nil {
		m.logger.Error("detect drift", zap.Error(err), zap.String("feature", evt.Feature))
		return
	}

	m.logger.Debug("drift detection completed",
		zap.String("feature", evt.Feature),
		zap.Bool("drift", didDrift),
		zap.Float64("score", score),
		zap.Duration("took", time.Since(start)),
	)

	if !didDrift {
		return
	}

	payload := DriftEvent{
		Feature:       evt.Feature,
		Detector:      m.detector.Name(),
		Score:         score,
		ReferenceUUID: evt.ReferenceUUID,
		CurrentUUID:   evt.CurrentUUID,
		Timestamp:     time.Now().UTC(),
	}

	if err := m.bus.Publish(m.outTopic, payload); err != nil {
		m.logger.Error("publish drift event", zap.Error(err))
	}
}

// -----------------------------------------------------------------------
// Compile-time assertions
// -----------------------------------------------------------------------

var _ DriftDetector = (*ksTestDetector)(nil)
var _ EventBus = (*noopBus)(nil) // dev helper
var _ = ksStatistic              // keep linter happy

// -----------------------------------------------------------------------
// noopBus – developer utility fallback bus implementation.
// -----------------------------------------------------------------------

type noopBus struct {
	subs map[string][]chan []byte
	mu   sync.RWMutex
}

func NewNoopBus() *noopBus { return &noopBus{subs: make(map[string][]chan []byte)} }

func (b *noopBus) Publish(topic string, msg interface{}) error {
	b.mu.RLock()
	defer b.mu.RUnlock()
	payload, err := json.Marshal(msg)
	if err != nil {
		return err
	}
	for _, ch := range b.subs[topic] {
		select {
		case ch <- payload:
		default:
			// drop message when subscriber is slow; mimic real broker behaviour
		}
	}
	return nil
}

func (b *noopBus) Subscribe(ctx context.Context, topic string) (<-chan []byte, error) {
	b.mu.Lock()
	defer b.mu.Unlock()

	ch := make(chan []byte, 64)
	b.subs[topic] = append(b.subs[topic], ch)

	go func() {
		<-ctx.Done()
		b.mu.Lock()
		defer b.mu.Unlock()
		close(ch)
	}()

	return ch, nil
}