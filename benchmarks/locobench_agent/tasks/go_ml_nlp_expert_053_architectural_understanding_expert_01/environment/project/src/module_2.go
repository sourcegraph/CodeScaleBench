package echopulse

import (
	"context"
	"errors"
	"fmt"
	"log"
	"runtime"
	"sync"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
)

// ------------------------------------------------------------------
// module_2.go
//
// Realtime Processing Pipeline & Processor Factory
//
// This module provides:
//   1. A Processor interface implemented by any real-time analytics
//      component (sentiment, toxicity, stance, topic surfacing, …).
//   2. A Factory that instantiates processors from runtime config.
//   3. A highly Concurrent Pipeline that fans-out SocialEvents to a
//      configurable worker pool, traces latency with OpenTelemetry,
//      and fans-in the resulting Actions.
//
// The code is self-contained and can be wired into the broader
// EchoPulse graph by importing this package and passing a channel of
// SocialEvent instances into Pipeline.Run().
// ------------------------------------------------------------------

// SocialEvent is the canonical message flowing through EchoPulse.
// In real deployment it is produced by the ingestion tier and pushed
// on the event bus.  Here we only need a subset of the full schema.
type SocialEvent struct {
	ID        string            // Globally unique event id
	UserID    string            // Source user
	Timestamp time.Time         // Wall-clock creation time
	Channel   string            // Chat room / micro-blog / etc.
	Payload   string            // Raw text or transcript
	Meta      map[string]string // Additional, domain-specific metadata
}

// Action is emitted by analytic processors to notify down-stream
// systems (e.g. moderation, UI highlight boosts, alerts).
type Action struct {
	OriginProcessor string            // Name() of originating processor
	EventID         string            // The SocialEvent.ID being acted on
	Kind            string            // e.g. "TOXICITY_ALERT", "HIGHLIGHT"
	Score           float64           // Confidence or magnitude
	Labels          map[string]string // Extra info for consumers
	CreatedAt       time.Time
}

// Processor defines a component able to analyze a single SocialEvent.
// Implementations should be stateless (or internally synchronize) so
// that they can be safely used by multiple goroutines.
type Processor interface {
	Name() string
	Process(ctx context.Context, ev SocialEvent) ([]Action, error)
	Close() error // Free heavy resources (GPU, file handles, …)
}

// ------------------------------------------------------------------
// Processor Factory
// ------------------------------------------------------------------

// Config is a generic configuration blob understood by a Processor.
// The concrete processors inspect their own keys.
type Config map[string]any

// ErrUnknownProcessorType is returned when the factory cannot resolve
// a name to a concrete implementation.
var ErrUnknownProcessorType = errors.New("unknown processor type")

// ProcessorFactory creates Processor instances from a config spec.
type ProcessorFactory struct {
	registry map[string]func(Config) (Processor, error)
	mu       sync.RWMutex
}

// NewProcessorFactory returns an empty registry capable of producing
// built-in processors.  Additional processors can be plugged at
// runtime via Register().
func NewProcessorFactory() *ProcessorFactory {
	f := &ProcessorFactory{
		registry: make(map[string]func(Config) (Processor, error)),
	}
	// Register built-in processors
	f.registry["sentiment"] = newSentimentProcessor
	f.registry["toxicity"] = newToxicityProcessor
	return f
}

// Register adds a factory function for a new processor type.  If name
// is already present it is overwritten.
func (f *ProcessorFactory) Register(name string, fn func(Config) (Processor, error)) {
	f.mu.Lock()
	f.registry[name] = fn
	f.mu.Unlock()
}

// Create instantiates the requested processor or returns an error.
func (f *ProcessorFactory) Create(name string, cfg Config) (Processor, error) {
	f.mu.RLock()
	fn, ok := f.registry[name]
	f.mu.RUnlock()
	if !ok {
		return nil, fmt.Errorf("%w: %s", ErrUnknownProcessorType, name)
	}
	return fn(cfg)
}

// ------------------------------------------------------------------
// Example Processor Implementations
// ------------------------------------------------------------------

// SentimentProcessor is a lightweight runtime sentiment estimator.
// In production, a model would live behind an RPC server or on-device
// accelerated runtime.  Here we emulate latency & scoring behavior.
type SentimentProcessor struct {
	threshold float64
}

func newSentimentProcessor(cfg Config) (Processor, error) {
	t := 0.0 // default threshold
	if v, ok := cfg["threshold"].(float64); ok {
		t = v
	}
	return &SentimentProcessor{threshold: t}, nil
}

func (sp *SentimentProcessor) Name() string { return "sentiment" }

func (sp *SentimentProcessor) Process(ctx context.Context, ev SocialEvent) ([]Action, error) {
	// Fake inference latency
	time.Sleep(4 * time.Millisecond)
	score := mockHashScore(ev.Payload)
	if score < sp.threshold {
		return nil, nil
	}
	act := Action{
		OriginProcessor: sp.Name(),
		EventID:         ev.ID,
		Kind:            "SENTIMENT_HIGH",
		Score:           score,
		Labels: map[string]string{
			"polarity": "positive",
		},
		CreatedAt: time.Now(),
	}
	return []Action{act}, nil
}

func (sp *SentimentProcessor) Close() error { return nil }

// ToxicityProcessor performs a toy toxicity classification.
type ToxicityProcessor struct {
	version string
}

func newToxicityProcessor(cfg Config) (Processor, error) {
	v := "v1"
	if s, ok := cfg["model_version"].(string); ok {
		v = s
	}
	return &ToxicityProcessor{version: v}, nil
}

func (tp *ToxicityProcessor) Name() string { return "toxicity" }

func (tp *ToxicityProcessor) Process(ctx context.Context, ev SocialEvent) ([]Action, error) {
	time.Sleep(6 * time.Millisecond)
	score := 1 - mockHashScore(ev.Payload) // pretend low hash==high toxicity
	if score < 0.75 {
		return nil, nil
	}
	act := Action{
		OriginProcessor: tp.Name(),
		EventID:         ev.ID,
		Kind:            "TOXICITY_ALERT",
		Score:           score,
		Labels: map[string]string{
			"model_version": tp.version,
		},
		CreatedAt: time.Now(),
	}
	return []Action{act}, nil
}

func (tp *ToxicityProcessor) Close() error { return nil }

// mockHashScore returns a deterministic pseudo-random score (0–1) from
// the input string.  For demo purposes only.
func mockHashScore(s string) float64 {
	h := 0
	for i := 0; i < len(s); i++ {
		h = (h*31 + int(s[i])) & 0x7fffffff
	}
	return float64(h%1000) / 1000.0
}

// ------------------------------------------------------------------
// Processing Pipeline
// ------------------------------------------------------------------

// Pipeline orchestrates multi-stage, concurrent processing of
// SocialEvents.  An internal fan-out dispatches events to N workers
// that run the configured processor chain sequentially (Stage1 →
// Stage2 → …). Results are batched onto an output channel.
type Pipeline struct {
	processors []Processor
	workers    int
}

// NewPipeline assembles a new Pipeline.  If workers == 0 it defaults
// to the number of logical CPUs.
func NewPipeline(workers int, processors ...Processor) *Pipeline {
	if workers <= 0 {
		workers = runtime.NumCPU()
	}
	return &Pipeline{
		processors: processors,
		workers:    workers,
	}
}

// Run starts the workers and returns two read-only channels:
//   actions: produced by processors
//   errs:    fatal errors that cause worker exit
// Callers must cancel ctx to stop the pipeline and read until both
// channels are closed.
func (p *Pipeline) Run(ctx context.Context, in <-chan SocialEvent) (actions <-chan Action, errs <-chan error) {
	outActions := make(chan Action, 1024)
	outErrs := make(chan error, p.workers)

	wg := sync.WaitGroup{}
	tracer := otel.Tracer("echopulse.realtime.pipeline")

	worker := func() {
		defer wg.Done()
		for {
			select {
			case <-ctx.Done():
				return
			case ev, ok := <-in:
				if !ok {
					return
				}
				// Trace per event
				ctx2, span := tracer.Start(ctx, "ProcessEvent")
				span.SetAttributes(attribute.String("event.id", ev.ID))
				err := p.handleEvent(ctx2, ev, outActions)
				if err != nil {
					select {
					case outErrs <- err:
					default:
						log.Printf("[WARN] error channel full: %v", err)
					}
				}
				span.End()
			}
		}
	}

	wg.Add(p.workers)
	for i := 0; i < p.workers; i++ {
		go worker()
	}

	// Close out channels when all workers exit
	go func() {
		wg.Wait()
		close(outActions)
		close(outErrs)
	}()

	return outActions, outErrs
}

// handleEvent runs the processor chain on a single event.
func (p *Pipeline) handleEvent(ctx context.Context, ev SocialEvent, out chan<- Action) error {
	for _, pr := range p.processors {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		acts, err := pr.Process(ctx, ev)
		if err != nil {
			return fmt.Errorf("processor %s: %w", pr.Name(), err)
		}
		for _, a := range acts {
			select {
			case out <- a:
			case <-ctx.Done():
				return ctx.Err()
			}
		}
	}
	return nil
}

// Close shuts down all processors gracefully.
func (p *Pipeline) Close() error {
	var allErr error
	for _, pr := range p.processors {
		if err := pr.Close(); err != nil {
			allErr = errors.Join(allErr, err)
		}
	}
	return allErr
}

// ------------------------------------------------------------------
// Example Usage (can be removed in production)
// ------------------------------------------------------------------

// This example demonstrates how a service could wire the pipeline.
// An init() block is used to avoid polluting the package namespace.
func init() {
	go func() {
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()

		// Build processors
		factory := NewProcessorFactory()
		sentiment, _ := factory.Create("sentiment", Config{"threshold": 0.6})
		toxicity, _ := factory.Create("toxicity", Config{"model_version": "v2"})

		pipe := NewPipeline(0, sentiment, toxicity)

		events := make(chan SocialEvent, 100)
		actions, errs := pipe.Run(ctx, events)

		// Feed some dummy events
		go func() {
			for i := 0; i < 10; i++ {
				events <- SocialEvent{
					ID:        fmt.Sprintf("ev-%d", i),
					UserID:    fmt.Sprintf("user-%d", i%3),
					Timestamp: time.Now(),
					Payload:   fmt.Sprintf("Hello world %d", i),
				}
			}
			close(events)
		}()

		// Consume results
		go func() {
			for a := range actions {
				log.Printf("[ACTION] %#v", a)
			}
		}()

		// Handle errors
		go func() {
			for e := range errs {
				log.Printf("[ERR] %v", e)
			}
		}()
	}()
}