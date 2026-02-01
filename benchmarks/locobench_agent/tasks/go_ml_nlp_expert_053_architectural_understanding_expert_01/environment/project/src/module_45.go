```go
package echopulse // Module name follows project root (replace with actual module path)

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/sirupsen/logrus"
)

// -----------------------------------------------------------------------------
// Event Bus (minimal abstraction)
// -----------------------------------------------------------------------------

// Event represents a canonical payload exchanged across the EchoPulse backbone.
type Event struct {
	// StreamTopic is a logical channel (Kafka topic / NATS subject).
	StreamTopic string          `json:"stream_topic"`
	Key         string          `json:"key"` // Partition / routing key.
	Timestamp   time.Time       `json:"ts"`
	Payload     json.RawMessage `json:"payload"`
}

// EventBus is an internal abstraction over Kafka/NATS JetStream,
// easing testing and allowing hot-swaps.
type EventBus interface {
	Publish(ctx context.Context, evt Event) error
	Subscribe(ctx context.Context, topic string) (<-chan Event, error)
	Close() error
}

// -----------------------------------------------------------------------------
// Model/Drift Domain Types
// -----------------------------------------------------------------------------

// ModelMeta carries identifying information for a trained model.
type ModelMeta struct {
	RegistryName string    `json:"registry_name"`
	Version      string    `json:"version"`
	TrainedAt    time.Time `json:"trained_at"`
}

// MetricSample is a single inference metric reported from online serving.
// Example: latency, accuracy, confidence, or distributional properties.
type MetricSample struct {
	Model   ModelMeta `json:"model"`
	Name    string    `json:"name"` // e.g. "confidence"
	Value   float64   `json:"value"`
	Created time.Time `json:"created"`
}

// DriftAlarm is emitted when statistical drift is detected.
type DriftAlarm struct {
	ID         uuid.UUID `json:"id"`
	Model      ModelMeta `json:"model"`
	MetricName string    `json:"metric_name"`
	// TestStatistic is the value that caused the alarm (e.g., PH statistic).
	TestStatistic float64   `json:"test_statistic"`
	Threshold     float64   `json:"threshold"`
	DetectedAt    time.Time `json:"detected_at"`
}

// encode helper – panic-free.
func encode[T any](v T) json.RawMessage {
	b, _ := json.Marshal(v)
	return b
}

// -----------------------------------------------------------------------------
// Drift Detection Strategy Pattern
// -----------------------------------------------------------------------------

// DriftDetector receives a stream of metric values and decides when to alarm.
type DriftDetector interface {
	// Observe adds a new numeric sample; returns true when drift occurred.
	Observe(sample float64) (drift bool, statistic float64)
	// Reset clears internal state (after model update for instance).
	Reset()
}

// PageHinkleyDetector implements the cumulative average shift detection.
// https://link.springer.com/article/10.1007/s10115-004-0152-x
type PageHinkleyDetector struct {
	mu sync.Mutex

	lambda        float64 // threshold
	delta         float64 // tolerance for minor changes
	cumSum        float64
	minCumSum     float64
	updateCount   int
	initialised   bool
	lastStatistic float64
}

// NewPageHinkley returns Page-Hinkley detector with user thresholds.
func NewPageHinkley(lambda, delta float64) *PageHinkleyDetector {
	if lambda <= 0 {
		panic("lambda must be positive")
	}
	return &PageHinkleyDetector{
		lambda: lambda,
		delta:  delta,
	}
}

func (p *PageHinkleyDetector) Observe(x float64) (bool, float64) {
	p.mu.Lock()
	defer p.mu.Unlock()

	// Initialisation with first sample
	if !p.initialised {
		p.cumSum = 0
		p.minCumSum = 0
		p.updateCount = 1
		p.initialised = true
		return false, 0
	}

	// Update cumulative sum with the deviation (x - mean - delta)
	mean := p.cumSum / float64(p.updateCount)
	p.cumSum += x - mean - p.delta
	p.updateCount++

	if p.cumSum < p.minCumSum {
		p.minCumSum = p.cumSum
	}

	statistic := p.cumSum - p.minCumSum
	p.lastStatistic = statistic

	if statistic > p.lambda {
		// Drift detected
		return true, statistic
	}
	return false, statistic
}

func (p *PageHinkleyDetector) Reset() {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.cumSum = 0
	p.minCumSum = 0
	p.updateCount = 0
	p.initialised = false
	p.lastStatistic = 0
}

// -----------------------------------------------------------------------------
// Detector Factory
// -----------------------------------------------------------------------------

// DetectorConfig is constructor input for the factory.
type DetectorConfig struct {
	Algorithm string
	Lambda    float64
	Delta     float64
}

// NewDetector returns a strategy matching input config.
func NewDetector(cfg DetectorConfig) (DriftDetector, error) {
	switch cfg.Algorithm {
	case "page_hinkley":
		return NewPageHinkley(lambdaOrDefault(cfg.Lambda), cfg.Delta), nil
	default:
		return nil, errors.New("unsupported drift detection algorithm: " + cfg.Algorithm)
	}
}

func lambdaOrDefault(v float64) float64 {
	if v <= 0 {
		return 50 // sane default
	}
	return v
}

// -----------------------------------------------------------------------------
// DriftWatcher Service (Observer Pattern)
// -----------------------------------------------------------------------------

// DriftWatcher observes MetricSample events, detects drift,
// and publishes DriftAlarm events.
type DriftWatcher struct {
	bus           EventBus
	subTopic      string
	pubTopic      string
	buildDetector func() DriftDetector
	log           *logrus.Entry
}

// DriftWatcherConfig bundles constructor params.
type DriftWatcherConfig struct {
	Bus             EventBus
	MetricTopic     string
	AlarmTopic      string
	DetectorBuilder func() DriftDetector
	Logger          *logrus.Logger
}

// NewDriftWatcher validates cfg and returns runnable instance.
func NewDriftWatcher(cfg DriftWatcherConfig) (*DriftWatcher, error) {
	if cfg.Bus == nil {
		return nil, errors.New("bus is required")
	}
	if cfg.MetricTopic == "" || cfg.AlarmTopic == "" {
		return nil, errors.New("metric / alarm topics are required")
	}
	if cfg.DetectorBuilder == nil {
		return nil, errors.New("detector builder is required")
	}
	if cfg.Logger == nil {
		cfg.Logger = logrus.StandardLogger()
	}

	return &DriftWatcher{
		bus:           cfg.Bus,
		subTopic:      cfg.MetricTopic,
		pubTopic:      cfg.AlarmTopic,
		buildDetector: cfg.DetectorBuilder,
		log:           cfg.Logger.WithField("component", "DriftWatcher"),
	}, nil
}

// Run blocks until ctx is cancelled or subscription errors.
func (w *DriftWatcher) Run(ctx context.Context) error {
	subCh, err := w.bus.Subscribe(ctx, w.subTopic)
	if err != nil {
		return err
	}

	// Map each model & metric to its own detector instance.
	detectors := make(map[string]DriftDetector)

	w.log.Infof("DriftWatcher started (sub: %s, pub: %s)", w.subTopic, w.pubTopic)

	for {
		select {
		case <-ctx.Done():
			w.log.Info("DriftWatcher shutting down: context cancelled")
			return nil

		case evt, ok := <-subCh:
			if !ok {
				return errors.New("subscription channel closed")
			}

			var sample MetricSample
			if err := json.Unmarshal(evt.Payload, &sample); err != nil {
				w.log.WithError(err).Warn("discarding malformed MetricSample")
				continue
			}

			// Compose key: one detector per (model, metric)
			key := detectorKey(sample.Model, sample.Name)
			det, ok := detectors[key]
			if !ok {
				det = w.buildDetector()
				detectors[key] = det
				w.log.WithFields(logrus.Fields{
					"key":    key,
					"lambda": getLambda(det),
				}).Debug("Initialized new detector")
			}

			drift, stat := det.Observe(sample.Value)
			if drift {
				alarm := DriftAlarm{
					ID:            uuid.New(),
					Model:         sample.Model,
					MetricName:    sample.Name,
					TestStatistic: stat,
					Threshold:     getLambda(det),
					DetectedAt:    time.Now().UTC(),
				}

				if err := w.bus.Publish(ctx, Event{
					StreamTopic: w.pubTopic,
					Key:         key,
					Timestamp:   alarm.DetectedAt,
					Payload:     encode(alarm),
				}); err != nil {
					w.log.WithError(err).Error("failed to publish DriftAlarm")
					// Do not return; keep processing
				} else {
					w.log.WithFields(logrus.Fields{
						"key":        key,
						"statistic":  stat,
						"threshold":  alarm.Threshold,
						"alarm_id":   alarm.ID,
						"model_ver":  sample.Model.Version,
						"metric":     sample.Name,
						"detectedAt": alarm.DetectedAt,
					}).Info("Drift detected")
				}

				// Optional: reset detector after alarm.
				det.Reset()
			}
		}
	}
}

func detectorKey(model ModelMeta, metric string) string {
	return model.RegistryName + ":" + model.Version + ":" + metric
}

func getLambda(d DriftDetector) float64 {
	if ph, ok := d.(*PageHinkleyDetector); ok {
		return ph.lambda
	}
	return math.NaN()
}

// -----------------------------------------------------------------------------
// Graceful Shutdown helper
// -----------------------------------------------------------------------------

// RunDriftWatcher is a convenience wrapper that starts DriftWatcher in its own
// goroutine and handles lifecycle, useful for dependency injection in main().
//
//    ctx, cancel := context.WithCancel(context.Background())
//    defer cancel()
//    if err := RunDriftWatcher(ctx, cfg); err != nil { ... }
//
func RunDriftWatcher(parent context.Context, cfg DriftWatcherConfig) error {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()

	watcher, err := NewDriftWatcher(cfg)
	if err != nil {
		return err
	}

	wg := sync.WaitGroup{}
	wg.Add(1)

	var runErr error
	go func() {
		defer wg.Done()
		runErr = watcher.Run(ctx)
	}()

	// Block until parent ctx done.
	<-parent.Done()
	cancel()
	wg.Wait()
	return runErr
}
```