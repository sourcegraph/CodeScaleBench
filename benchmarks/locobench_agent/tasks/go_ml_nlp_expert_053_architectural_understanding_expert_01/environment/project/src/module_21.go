```go
// Code generated for EchoPulse: Real-Time Social Signal Processing Platform.
// File: src/module_21.go
// Description: Implements a pluggable, observable NLP processing pipeline with
//              strategy-based toxicity classification. This component can be
//              wired into a Kafka / JetStream consumer or any other event source.

package echopulse

import (
	"context"
	"errors"
	"log"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"
)

// -----------------------------------------------------------------------------
// Domain Types
// -----------------------------------------------------------------------------

// SocialEvent is the canonical representation of an incoming user artifact.
type SocialEvent struct {
	ID             string            // globally unique event id
	Timestamp      time.Time         // event creation/ingestion time
	AuthorID       string            // user that created the event
	RawText        string            // as provided by upstream source
	NormalizedText string            // output of text-normalization stage
	ToxicityScore  float64           // output of toxicity classifier
	Metadata       map[string]string // extensible kv pairs
}

// Clone performs a deep copy to avoid mutating the same object across pipelines.
func (se *SocialEvent) Clone() *SocialEvent {
	clone := *se
	if se.Metadata != nil {
		clone.Metadata = make(map[string]string, len(se.Metadata))
		for k, v := range se.Metadata {
			clone.Metadata[k] = v
		}
	}
	return &clone
}

// -----------------------------------------------------------------------------
// Pipeline & Observer
// -----------------------------------------------------------------------------

// Processor is the contract every pipeline stage must satisfy.
type Processor interface {
	Name() string
	Process(ctx context.Context, evt *SocialEvent) error
}

// EventObserver receives callbacks after every stage execution.
type EventObserver interface {
	OnStageCompleted(stage string, evt *SocialEvent, dur time.Duration, err error)
}

// Pipeline coordinates execution of a series of ordered Processors.
type Pipeline struct {
	stages    []Processor
	observers []EventObserver
}

// NewPipeline constructs a pipeline with the provided processors.
func NewPipeline(stages ...Processor) *Pipeline {
	return &Pipeline{stages: stages}
}

// AddObserver registers observers for stage completion notifications.
func (p *Pipeline) AddObserver(obs ...EventObserver) {
	p.observers = append(p.observers, obs...)
}

// Process executes all processors in order. It short-circuits on error.
func (p *Pipeline) Process(ctx context.Context, evt *SocialEvent) error {
	for _, stage := range p.stages {
		start := time.Now()
		err := stage.Process(ctx, evt)
		dur := time.Since(start)

		for _, o := range p.observers {
			o.OnStageCompleted(stage.Name(), evt, dur, err)
		}
		if err != nil {
			return err
		}
	}
	return nil
}

// -----------------------------------------------------------------------------
// Sample Processors
// -----------------------------------------------------------------------------

// TextNormalizer converts raw text into a canonical normalized representation.
type TextNormalizer struct{}

// Name returns the processor name.
func (t *TextNormalizer) Name() string { return "text_normalizer" }

// Process applies normalization rules.
func (t *TextNormalizer) Process(_ context.Context, evt *SocialEvent) error {
	if evt.RawText == "" {
		return errors.New("empty raw text")
	}

	// Lowercase & collapse multiple spaces.
	s := strings.ToLower(evt.RawText)
	s = squishSpaces(s)

	// Remove control characters.
	s = stripControlChars(s)

	evt.NormalizedText = s
	return nil
}

// ToxicityClassifier uses a configurable Strategy implementation to assign scores.
type ToxicityClassifier struct {
	strategy ToxicityStrategy
}

// NewToxicityClassifier is a factory helper.
func NewToxicityClassifier(name string) (*ToxicityClassifier, error) {
	strat, err := BuildToxicityStrategy(name)
	if err != nil {
		return nil, err
	}
	return &ToxicityClassifier{strategy: strat}, nil
}

func (t *ToxicityClassifier) Name() string { return "toxicity_classifier" }

func (t *ToxicityClassifier) Process(ctx context.Context, evt *SocialEvent) error {
	score, err := t.strategy.Evaluate(ctx, evt.NormalizedText)
	if err != nil {
		return err
	}
	evt.ToxicityScore = score
	return nil
}

// -----------------------------------------------------------------------------
// Strategy Pattern ‑ Toxicity
// -----------------------------------------------------------------------------

// ToxicityStrategy defines how toxicity is measured.
type ToxicityStrategy interface {
	Evaluate(ctx context.Context, text string) (float64, error)
}

// BuildToxicityStrategy is a factory that returns a concrete strategy.
func BuildToxicityStrategy(name string) (ToxicityStrategy, error) {
	switch strings.ToLower(name) {
	case "", "keyword":
		return DefaultKeywordStrategy{}, nil
	case "ml_model":
		return MLModelStrategy{}, nil
	default:
		return nil, errors.New("unknown toxicity strategy: " + name)
	}
}

// DefaultKeywordStrategy is a naive strategy based on a keyword blacklist.
type DefaultKeywordStrategy struct{}

func (DefaultKeywordStrategy) Evaluate(_ context.Context, text string) (float64, error) {
	if text == "" {
		return 0.0, nil
	}
	badWords := []string{"hate", "kill", "stupid"}
	score := 0.0
	for _, w := range badWords {
		if strings.Contains(text, w) {
			score += 0.4
		}
	}
	if score > 1.0 {
		score = 1.0
	}
	return score, nil
}

// MLModelStrategy simulates a call to a heavy ML model (could be served via gRPC).
type MLModelStrategy struct{}

func (MLModelStrategy) Evaluate(_ context.Context, text string) (float64, error) {
	// NOTE: This is a stub. In production this could:
	//  * call model inference service
	//  * fallback to on-device model
	//  * batch requests for efficiency
	// We'll mimic latency to ensure callers handle timeouts.
	time.Sleep(35 * time.Millisecond)

	// Dummy heuristic: longer messages slightly more toxic (for demo only).
	l := float64(len(text))
	score := (l / 280.0) * 0.5 // cap at ~0.5
	if score > 1.0 {
		score = 1.0
	}
	return score, nil
}

// -----------------------------------------------------------------------------
// Stream Processor Coordinator (Observer Pattern)
// -----------------------------------------------------------------------------

// StreamProcessor consumes events from an input channel, applies the pipeline
// with concurrency, and forwards the enriched events to an output channel.
type StreamProcessor struct {
	pipeline *Pipeline
	in       <-chan *SocialEvent
	out      chan<- *SocialEvent
	errs     chan<- error
	workers  int

	wg     sync.WaitGroup
	cancel context.CancelFunc
}

// NewStreamProcessor constructs a stream processor.
func NewStreamProcessor(p *Pipeline, in <-chan *SocialEvent, out chan<- *SocialEvent, errs chan<- error, workers int) *StreamProcessor {
	if workers <= 0 {
		workers = 4 // sane default
	}
	return &StreamProcessor{
		pipeline: p,
		in:       in,
		out:      out,
		errs:     errs,
		workers:  workers,
	}
}

// Start runs worker goroutines until context cancellation or channel closure.
func (sp *StreamProcessor) Start(parent context.Context) {
	ctx, cancel := context.WithCancel(parent)
	sp.cancel = cancel
	sp.wg.Add(sp.workers)

	for i := 0; i < sp.workers; i++ {
		go func() {
			defer sp.wg.Done()
			for {
				select {
				case <-ctx.Done():
					return
				case evt, ok := <-sp.in:
					if !ok {
						return
					}
					processed := evt.Clone()
					if err := sp.pipeline.Process(ctx, processed); err != nil {
						select {
						case sp.errs <- err:
						default:
							log.Printf("unhandled pipeline error: %v", err)
						}
						continue
					}
					select {
					case sp.out <- processed:
					case <-ctx.Done():
						return
					}
				}
			}
		}()
	}
}

// Stop gracefully stops all workers.
func (sp *StreamProcessor) Stop() {
	if sp.cancel != nil {
		sp.cancel()
	}
	sp.wg.Wait()
}

// -----------------------------------------------------------------------------
// Observability Helpers
// -----------------------------------------------------------------------------

// LoggerObserver logs stage execution time and errors.
type LoggerObserver struct{}

func (LoggerObserver) OnStageCompleted(stage string, evt *SocialEvent, dur time.Duration, err error) {
	if err != nil {
		log.Printf("[stage=%s] failed for event=%s err=%v", stage, evt.ID, err)
		return
	}
	log.Printf("[stage=%s] event=%s processed in %s", stage, evt.ID, dur)
}

// -----------------------------------------------------------------------------
// Utility functions
// -----------------------------------------------------------------------------

// squishSpaces collapses runs of space characters.
func squishSpaces(s string) string {
	return strings.Join(strings.Fields(s), " ")
}

// stripControlChars removes non-graphic runes.
func stripControlChars(s string) string {
	var b strings.Builder
	for len(s) > 0 {
		r, size := utf8.DecodeRuneInString(s)
		if r == utf8.RuneError && size == 1 {
			// invalid utf8, skip
			s = s[size:]
			continue
		}
		if !unicode.IsControl(r) {
			b.WriteRune(r)
		}
		s = s[size:]
	}
	return b.String()
}
```