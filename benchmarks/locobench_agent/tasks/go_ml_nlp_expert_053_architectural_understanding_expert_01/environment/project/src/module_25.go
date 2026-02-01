```go
// File: src/module_25.go
//
// Package services contains long–running daemons that attach
// to the EchoPulse event-bus and orchestrate higher-level
// workflows (auto-retraining, model promotion, etc.).
//
package services

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
	"github.com/sirupsen/logrus"
)

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

// DriftMonitor consumes feature-drift metrics emitted by the online
// model-monitoring component and triggers automated re-training
// pipelines when predefined thresholds are breached.
type DriftMonitor struct {
	cfg       Config
	reader    *kafka.Reader
	handler   DriftHandler
	wg        sync.WaitGroup
	ctx       context.Context
	cancel    context.CancelFunc
	startOnce sync.Once
	stopOnce  sync.Once
}

// Config models the configuration required to bootstrap the monitor.
type Config struct {
	Brokers          []string      // Kafka bootstrap brokers
	Topic            string        // Topic that carries drift metrics
	GroupID          string        // Kafka consumer group
	MinBytes         int           // Reader min-fetch
	MaxBytes         int           // Reader max-fetch
	MaxWait          time.Duration // Reader max-wait
	PSIThreshold     float64       // Drift threshold
	AggregationWindow time.Duration // Sliding window for aggregation
}

// DriftMetric is the canonical payload pushed onto the bus by the
// model-monitoring service (one metric per <model, feature> tuple).
type DriftMetric struct {
	Timestamp   time.Time `json:"ts"`
	ModelID     string    `json:"model_id"`
	Feature     string    `json:"feature"`
	Population1 string    `json:"pop1"` // e.g. training hash / baseline label
	Population2 string    `json:"pop2"` // e.g. live traffic tag
	PSI         float64   `json:"psi"`  // population-stability-index
}

// DriftEvent represents a drift condition that calls for an automated
// reaction (e.g. re-training, escalation to human-in-the-loop, …).
type DriftEvent struct {
	ModelID string
	Feature string
	PSI     float64
	Time    time.Time
}

// DriftHandler is the pluggable strategy that defines how the monitor
// reacts to drift events.
type DriftHandler interface {
	OnDrift(ctx context.Context, ev DriftEvent) error
}

// ---------------------------------------------------------------------------
// Construction helpers
// ---------------------------------------------------------------------------

// NewDriftMonitor instantiates a fully-wired monitor with sane defaults.
// The caller must invoke Start() to begin processing.
func NewDriftMonitor(parentCtx context.Context, cfg Config, handler DriftHandler) (*DriftMonitor, error) {
	if len(cfg.Brokers) == 0 {
		return nil, errors.New("driftmonitor: empty broker list")
	}
	if cfg.Topic == "" {
		return nil, errors.New("driftmonitor: empty topic")
	}
	if handler == nil {
		return nil, errors.New("driftmonitor: nil handler")
	}
	r := kafka.NewReader(kafka.ReaderConfig{
		Brokers:   cfg.Brokers,
		Topic:     cfg.Topic,
		GroupID:   cfg.GroupID,
		MinBytes:  cfg.MinBytes,
		MaxBytes:  cfg.MaxBytes,
		MaxWait:   cfg.MaxWait,
		Partition: 0,
	})
	ctx, cancel := context.WithCancel(parentCtx)

	return &DriftMonitor{
		cfg:    cfg,
		reader: r,
		handler: handler,
		ctx:    ctx,
		cancel: cancel,
	}, nil
}

// Start begins consumption on a dedicated goroutine.
func (m *DriftMonitor) Start() {
	m.startOnce.Do(func() {
		logrus.Infof("driftmonitor: starting (topic=%s group=%s)", m.cfg.Topic, m.cfg.GroupID)
		m.wg.Add(1)
		go m.loop()
	})
}

// Stop gracefully shuts down the monitor and waits for inflight
// processing to finish (bounded by Context deadline/cancel).
func (m *DriftMonitor) Stop() {
	m.stopOnce.Do(func() {
		logrus.Info("driftmonitor: stopping")
		m.cancel()
		m.wg.Wait()
		_ = m.reader.Close()
	})
}

// ---------------------------------------------------------------------------
// Event loop
// ---------------------------------------------------------------------------

func (m *DriftMonitor) loop() {
	defer m.wg.Done()

	for {
		msg, err := m.reader.ReadMessage(m.ctx)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return // normal shutdown
			}
			logrus.WithError(err).Warn("driftmonitor: read error")
			continue
		}

		var metric DriftMetric
		if err = json.Unmarshal(msg.Value, &metric); err != nil {
			logrus.WithError(err).Warn("driftmonitor: invalid json payload")
			continue
		}

		// Sanity guard
		if metric.ModelID == "" || metric.Feature == "" {
			logrus.Warn("driftmonitor: missing model/feature identifier")
			continue
		}

		// Evaluate drift
		if metric.PSI >= m.cfg.PSIThreshold {
			ev := DriftEvent{
				ModelID: metric.ModelID,
				Feature: metric.Feature,
				PSI:     metric.PSI,
				Time:    metric.Timestamp,
			}
			logrus.WithFields(logrus.Fields{
				"model":   ev.ModelID,
				"feature": ev.Feature,
				"psi":     fmt.Sprintf("%.4f", ev.PSI),
			}).Warn("driftmonitor: drift detected")

			// Forward to downstream handler
			if err := m.handler.OnDrift(m.ctx, ev); err != nil {
				logrus.WithError(err).Error("driftmonitor: handler error")
			}
		}
	}
}

// ---------------------------------------------------------------------------
// Default Handler — HTTP trainer client
// ---------------------------------------------------------------------------

// TrainerClient is a minimal REST client that wraps the model-trainer
// service. In production this might be gRPC, but HTTP keeps the sample
// self-contained.
type TrainerClient interface {
	// TriggerRetrain requests an immediate (ad-hoc) training job and
	// returns the job identifier on success.
	TriggerRetrain(ctx context.Context, modelID, reason string) (string, error)
}

// HTTPTrainerClient is a best-effort implementation backed by Go's
// stdlib HTTP stack.
type HTTPTrainerClient struct {
	Endpoint   string            // e.g. http://trainer.svc.cluster.local:8080
	HTTPClient *http.Client      // injected for testability
	Headers    map[string]string // optional static headers (auth, trace, …)
}

// TriggerRetrain fires a POST /v1/train endpoint with a JSON body.
func (c *HTTPTrainerClient) TriggerRetrain(ctx context.Context, modelID, reason string) (string, error) {
	if c.Endpoint == "" {
		return "", errors.New("trainerclient: empty endpoint")
	}
	body := map[string]string{
		"model_id": modelID,
		"reason":   reason,
	}
	buf, _ := json.Marshal(body) // cannot fail
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.Endpoint+"/v1/train", strings.NewReader(string(buf)))
	if err != nil {
		return "", err
	}
	req.Header.Set("content-type", "application/json")
	for k, v := range c.Headers {
		req.Header.Set(k, v)
	}
	client := c.HTTPClient
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return "", fmt.Errorf("trainerclient: unexpected HTTP %d", resp.StatusCode)
	}
	var out struct {
		JobID string `json:"job_id"`
	}
	if err = json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", err
	}
	if out.JobID == "" {
		return "", errors.New("trainerclient: empty job_id")
	}
	return out.JobID, nil
}

// ---------------------------------------------------------------------------
// Concrete DriftHandler implementation
// ---------------------------------------------------------------------------

// RetrainHandler is a DriftHandler that directly calls the trainer
// service when drift occurs.
type RetrainHandler struct {
	client TrainerClient
}

// NewRetrainHandler builds a handler with the supplied client.
func NewRetrainHandler(client TrainerClient) *RetrainHandler {
	return &RetrainHandler{client: client}
}

// OnDrift implements the DriftHandler interface.
func (h *RetrainHandler) OnDrift(ctx context.Context, ev DriftEvent) error {
	reason := fmt.Sprintf("psi=%.4f feature=%s at %s", ev.PSI, ev.Feature, ev.Time.Format(time.RFC3339))
	jobID, err := h.client.TriggerRetrain(ctx, ev.ModelID, reason)
	if err != nil {
		return err
	}
	logrus.WithFields(logrus.Fields{
		"model":  ev.ModelID,
		"job_id": jobID,
	}).Info("driftmonitor: auto-retraining kicked off")
	return nil
}

// ---------------------------------------------------------------------------
// Bootstrap helper for CLI or tests
// ---------------------------------------------------------------------------

// RunDriftMonitorFromEnv is a convenience entry-point that wires the
// monitor using environment variables. It is suitable for docker-ised
// sidecars or local dev.
//
//   ECHOPULSE_BROKERS=broker1:9092,broker2:9092
//   ECHOPULSE_MONITOR_TOPIC=feature_drift
//   ECHOPULSE_GROUP_ID=ml_drift_monitor
//   ECHOPULSE_PSI_THRESHOLD=0.2
//
// A Ctrl-C (SIGINT) will trigger graceful shutdown.
func RunDriftMonitorFromEnv() error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle Ctrl-C.
	go func() {
		sig := make(chan os.Signal, 1)
		signal.Notify(sig, os.Interrupt)
		<-sig
		cancel()
	}()

	brokers := strings.Split(os.Getenv("ECHOPULSE_BROKERS"), ",")
	topic := getenvDefault("ECHOPULSE_MONITOR_TOPIC", "feature_drift")
	group := getenvDefault("ECHOPULSE_GROUP_ID", "ml_drift_monitor")

	psiThreshold, _ := strconv.ParseFloat(getenvDefault("ECHOPULSE_PSI_THRESHOLD", "0.2"), 64)

	cfg := Config{
		Brokers:      brokers,
		Topic:        topic,
		GroupID:      group,
		MinBytes:     1e4,           // 10KiB
		MaxBytes:     5e6,           // 5MiB
		MaxWait:      200 * time.Millisecond,
		PSIThreshold: psiThreshold,
	}

	handler := NewRetrainHandler(&HTTPTrainerClient{
		Endpoint: getenvDefault("ECHOPULSE_TRAINER_ENDPOINT", "http://trainer:8080"),
		Headers:  map[string]string{"X-Requested-By": "echopulse-drift-monitor"},
	})

	monitor, err := NewDriftMonitor(ctx, cfg, handler)
	if err != nil {
		return err
	}
	monitor.Start()
	<-ctx.Done()
	monitor.Stop()
	return nil
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

func getenvDefault(key, def string) string {
	val := os.Getenv(key)
	if val == "" {
		return def
	}
	return val
}

// signal is imported lazily via side-effect for Unix platforms.
var signal struct {
	Notify func(chan<- os.Signal, ...os.Signal)
}

// init resolves the platform-specific signal package (stubbed for
// Windows where syscall.SIGINT isn't defined).
func init() {
	var (
		once sync.Once
		err  error
	)
	once.Do(func() {
		signal.Notify, err = loadSignalNotify()
		if err != nil {
			// If signal.Notify cannot be loaded the monitor still works,
			// but won't respond to Ctrl-C. Log and continue.
			logrus.WithError(err).Warn("driftmonitor: signal Notify unavailable")
		}
	})
}

// loadSignalNotify attempts to obtain the os/signal.Notify symbol
// via reflection so the code compiles on all platforms without a
// direct import (which would break on JS/WASM).
func loadSignalNotify() (func(chan<- os.Signal, ...os.Signal), error) {
	pkg, err := importPkg("os/signal")
	if err != nil {
		return nil, err
	}
	sym, ok := pkg.Lookup("Notify")
	if !ok {
		return nil, errors.New("symbol Notify not found")
	}
	fn, ok := sym.Interface().(func(chan<- os.Signal, ...os.Signal))
	if !ok {
		return nil, errors.New("Notify has unexpected type")
	}
	return fn, nil
}

// importPkg loads a package by path at runtime. It relies on the
// plugin mechanism which is unavailable on Windows/JS, but the code
// remains safe thanks to graceful degradation.
func importPkg(path string) (*plugin.Plugin, error) {
	return nil, errors.New("dynamic import not supported in this build")
}

// ---------------------------------------------------------------------------
// Mock helpers (used in unit-tests)
// ---------------------------------------------------------------------------

// NewTestHandler returns a no-op DriftHandler that records received
// events into the supplied slice for assertions in tests.
func NewTestHandler(out *[]DriftEvent) DriftHandler {
	var mu sync.Mutex
	return DriftHandlerFunc(func(_ context.Context, ev DriftEvent) error {
		mu.Lock()
		defer mu.Unlock()
		*out = append(*out, ev)
		return nil
	})
}

// DriftHandlerFunc is a functional adapter to build handlers inline.
type DriftHandlerFunc func(ctx context.Context, ev DriftEvent) error

// OnDrift implements the DriftHandler interface.
func (f DriftHandlerFunc) OnDrift(ctx context.Context, ev DriftEvent) error { return f(ctx, ev) }
```