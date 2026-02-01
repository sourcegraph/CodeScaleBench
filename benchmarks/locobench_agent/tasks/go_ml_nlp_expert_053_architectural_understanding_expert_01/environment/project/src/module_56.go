```go
// Code generated for EchoPulse (ml_nlp) — DO NOT EDIT.
// File:     src/module_56.go
// Purpose:  Sliding-window sentiment aggregator with observer fan-out.
// Author:   EchoPulse Core Team

package module56

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"go.uber.org/atomic"
	"go.uber.org/zap"
)

// ----------------------------------------------------------------------------------------------
// Public domain model --------------------------------------------------------------------------
// ----------------------------------------------------------------------------------------------

// SocialEvent represents the canonical unit travelling through EchoPulse.   In the real code-base
// this lives in a shared proto/go module, but we replicate the minimum subset needed here in
// order to keep this file self-contained.
type SocialEvent struct {
	ID        string    // globally unique id
	Timestamp time.Time // ingestion time (monotonic, UTC)
	// Sentiment score in the range [-1, 1], produced by the upstream sentiment classifier.
	Sentiment float64
}

// Aggregate encapsulates the windowed statistics emitted downstream.
type Aggregate struct {
	WindowStart  time.Time
	WindowEnd    time.Time
	Count        int
	Mean         float64
	StdDeviation float64
	// You can extend this later with median, p95, etc.
}

// Handler is the Observer interface for downstream consumers that wish to receive aggregates.
type Handler interface {
	HandleAggregate(ctx context.Context, agg Aggregate) error
}

// ----------------------------------------------------------------------------------------------
// Configuration --------------------------------------------------------------------------------
// ----------------------------------------------------------------------------------------------

// Config holds tunables for the Aggregator.  Use functional options to construct.
type Config struct {
	WindowSize    time.Duration         // absolute width of the moving window (e.g. 5m)
	Step          time.Duration         // how often to flush aggregates (e.g. 10s)
	MaxBuffer     int                   // bounded backlog of events; 0=unbounded
	Logger        *zap.Logger           // optional logger
	Registry      prometheus.Registerer // optional custom Prom registry
	FlushTimeout  time.Duration         // ctx timeout when calling Handler
	StartupLatest bool                  // start window at now() instead of first event
}

var defaultConfig = Config{
	WindowSize:    5 * time.Minute,
	Step:          10 * time.Second,
	MaxBuffer:     0,
	Logger:        zap.NewNop(),
	Registry:      prometheus.DefaultRegisterer,
	FlushTimeout:  2 * time.Second,
	StartupLatest: true,
}

// Option mutates Config.
type Option func(*Config)

// WithWindowSize sets the sliding window width.
func WithWindowSize(d time.Duration) Option { return func(c *Config) { c.WindowSize = d } }

// WithStep sets how often aggregates are emitted.
func WithStep(d time.Duration) Option { return func(c *Config) { c.Step = d } }

// WithMaxBuffer sets maximum number of events retained in memory.
func WithMaxBuffer(n int) Option { return func(c *Config) { c.MaxBuffer = n } }

// WithLogger overrides the logger.
func WithLogger(l *zap.Logger) Option { return func(c *Config) { c.Logger = l } }

// WithRegistry overrides the Prometheus registry.
func WithRegistry(r prometheus.Registerer) Option { return func(c *Config) { c.Registry = r } }

// WithFlushTimeout overrides flush timeout.
func WithFlushTimeout(d time.Duration) Option { return func(c *Config) { c.FlushTimeout = d } }

// ----------------------------------------------------------------------------------------------
// Aggregator implementation --------------------------------------------------------------------
// ----------------------------------------------------------------------------------------------

// Aggregator consumes SocialEvents, maintains a time-based sliding window,
// and broadcasts Aggregate snapshots to registered Handlers.
type Aggregator struct {
	cfg   Config
	inCh  chan SocialEvent
	done  chan struct{}
	wg    sync.WaitGroup
	clock func() time.Time // replaceable for tests

	// window state (protected by mu)
	mu      sync.Mutex
	events  []SocialEvent
	obQueue []Handler

	// metrics
	processed prometheus.Counter
	dropped   prometheus.Counter
	sent      prometheus.Counter
	active    prometheus.Gauge
	errCtr    prometheus.Counter
	failed    atomic.Uint64
}

// New returns a ready-to-run Aggregator.
func New(opts ...Option) (*Aggregator, error) {
	cfg := defaultConfig
	for _, opt := range opts {
		opt(&cfg)
	}
	if cfg.WindowSize <= 0 {
		return nil, errors.New("WindowSize must be > 0")
	}
	if cfg.Step <= 0 {
		return nil, errors.New("Step must be > 0")
	}

	a := &Aggregator{
		cfg:   cfg,
		inCh:  make(chan SocialEvent, 1024),
		done:  make(chan struct{}),
		clock: time.Now,
	}
	a.initMetrics()
	return a, nil
}

func (a *Aggregator) initMetrics() {
	ns := "echopulse"
	sub := "sentiment_agg"

	a.processed = prometheus.NewCounter(prometheus.CounterOpts{
		Namespace: ns, Subsystem: sub, Name: "events_total", Help: "Total ingested events",
	})
	a.dropped = prometheus.NewCounter(prometheus.CounterOpts{
		Namespace: ns, Subsystem: sub, Name: "events_dropped_total", Help: "Events dropped due to buffer limit",
	})
	a.sent = prometheus.NewCounter(prometheus.CounterOpts{
		Namespace: ns, Subsystem: sub, Name: "aggregates_total", Help: "Total aggregates published",
	})
	a.active = prometheus.NewGauge(prometheus.GaugeOpts{
		Namespace: ns, Subsystem: sub, Name: "active_handlers", Help: "Currently registered handlers",
	})
	a.errCtr = prometheus.NewCounter(prometheus.CounterOpts{
		Namespace: ns, Subsystem: sub, Name: "handler_errors_total", Help: "Errors returned from handlers",
	})

	// Register only once (ignore AlreadyRegisteredError)
	for _, c := range []prometheus.Collector{a.processed, a.dropped, a.sent, a.active, a.errCtr} {
		_ = a.cfg.Registry.Register(c)
	}
}

// Start launches background goroutines. Non-blocking.
func (a *Aggregator) Start() {
	a.wg.Add(2)
	go a.ingestLoop()
	go a.tickLoop()
}

// Stop shuts down worker goroutines and waits for them to finish.
func (a *Aggregator) Stop() {
	close(a.done)
	a.wg.Wait()
}

// Ingest pushes a SocialEvent into the aggregator.
//
// Safe for concurrent use; returns error if aggregator is closing.
func (a *Aggregator) Ingest(evt SocialEvent) error {
	select {
	case <-a.done:
		return errors.New("aggregator stopped")
	default:
	}

	a.mu.Lock()
	if a.cfg.MaxBuffer > 0 && len(a.events) >= a.cfg.MaxBuffer {
		// buffer full — drop oldest event to make space (back-pressure could be applied too)
		a.events = a.events[1:]
		a.dropped.Inc()
	}
	a.events = append(a.events, evt)
	a.mu.Unlock()

	// send to internal channel for decoupled processing.
	select {
	case a.inCh <- evt:
		return nil
	case <-a.done:
		return errors.New("aggregator stopped")
	}
}

// Register attaches a new Handler.
func (a *Aggregator) Register(h Handler) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.obQueue = append(a.obQueue, h)
	a.active.Set(float64(len(a.obQueue)))
}

// ingestLoop simply drains the inCh; we already appended to events in Ingest,
// but we keep this loop so we can apply future streaming ops (e.g. feature transforms)
// without blocking Ingest call stack.
func (a *Aggregator) ingestLoop() {
	defer a.wg.Done()
	for {
		select {
		case <-a.done:
			return
		case <-a.inCh:
			a.processed.Inc()
		}
	}
}

// tickLoop wakes up every Step, rotates window, computes stats, invokes handlers.
func (a *Aggregator) tickLoop() {
	defer a.wg.Done()

	// Align first tick to nearest Step boundary to avoid jitter.
	next := a.clock().Truncate(a.cfg.Step).Add(a.cfg.Step)
	if a.cfg.StartupLatest {
		next = a.clock()
	}
	t := time.NewTimer(next.Sub(a.clock()))
	defer t.Stop()

	for {
		select {
		case <-a.done:
			return
		case <-t.C:
			a.flush()
			t.Reset(a.cfg.Step)
		}
	}
}

// flush computes current aggregate and notifies observers.
func (a *Aggregator) flush() {
	now := a.clock()
	start := now.Add(-a.cfg.WindowSize)

	// Snapshot events within window.
	a.mu.Lock()
	var window []SocialEvent
	i := 0
	for ; i < len(a.events); i++ {
		if !a.events[i].Timestamp.Before(start) {
			break
		}
	}
	// i is first index within window
	window = append(window, a.events[i:]...)
	// Remove events outside window to keep buffer bounded.
	a.events = a.events[i:]
	handlers := append([]Handler(nil), a.obQueue...) // copy
	a.mu.Unlock()

	if len(window) == 0 {
		return
	}

	// Compute stats.
	var sum, sumSq float64
	for _, e := range window {
		sum += e.Sentiment
		sumSq += e.Sentiment * e.Sentiment
	}
	n := float64(len(window))
	mean := sum / n
	std := 0.0
	if n > 1 {
		std = sqrt(sumSq/n - mean*mean)
	}

	agg := Aggregate{
		WindowStart:  start,
		WindowEnd:    now,
		Count:        len(window),
		Mean:         mean,
		StdDeviation: std,
	}
	a.sent.Inc()

	// Broadcast with ctx timeout.
	var wg sync.WaitGroup
	for _, h := range handlers {
		wg.Add(1)
		go func(handler Handler) {
			defer wg.Done()
			ctx, cancel := context.WithTimeout(context.Background(), a.cfg.FlushTimeout)
			defer cancel()
			if err := handler.HandleAggregate(ctx, agg); err != nil {
				a.errCtr.Inc()
				a.failed.Inc()
				a.cfg.Logger.Error("handler failed", zap.Error(err))
			}
		}(h)
	}
	wg.Wait()
}

func sqrt(v float64) float64 { // small wrapper avoids importing math for one fn.
	// Basic Newton-Raphson with fixed iterations; acceptable for dev.
	if v <= 0 {
		return 0
	}
	z := v
	for i := 0; i < 6; i++ {
		z -= (z*z - v) / (2 * z)
	}
	return z
}

// ----------------------------------------------------------------------------------------------
// Example concrete Handler implementation ------------------------------------------------------
// ----------------------------------------------------------------------------------------------

// LogHandler writes aggregates to a zap.Logger.  Useful for quick diagnostics.
type LogHandler struct {
	l *zap.Logger
}

// NewLogHandler returns a simple logging handler.
func NewLogHandler(l *zap.Logger) *LogHandler { return &LogHandler{l: l} }

// HandleAggregate implements Handler.
func (h *LogHandler) HandleAggregate(ctx context.Context, agg Aggregate) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
	}
	h.l.Info("aggregate",
		zap.Time("start", agg.WindowStart),
		zap.Time("end", agg.WindowEnd),
		zap.Int("count", agg.Count),
		zap.Float64("mean", agg.Mean),
		zap.Float64("stddev", agg.StdDeviation),
	)
	return nil
}

// ----------------------------------------------------------------------------------------------
// Self-test helper (may be moved to *_test.go) --------------------------------------------------
// ----------------------------------------------------------------------------------------------

// sanityCheck can be called from unit tests to ensure aggregator compiles and runs.
func sanityCheck() error {
	logger, _ := zap.NewDevelopment()
	agg, err := New(
		WithLogger(logger),
		WithWindowSize(1*time.Minute),
		WithStep(2*time.Second),
	)
	if err != nil {
		return err
	}
	agg.Register(NewLogHandler(logger))
	agg.Start()

	// feed some data
	for i := 0; i < 100; i++ {
		evt := SocialEvent{
			ID:        fmt.Sprintf("evt-%d", i),
			Timestamp: time.Now().Add(time.Duration(i) * time.Second * -1),
			Sentiment: float64(i%10)/10 - 0.5, // range [-0.5, 0.4]
		}
		if err := agg.Ingest(evt); err != nil {
			return err
		}
	}
	time.Sleep(3 * time.Second)
	agg.Stop()
	return nil
}
```