```go
// File: src/module_63.go
//
// Package healthscore implements an in-memory, real-time community-health
// scoring pipeline.  The pipeline listens to a stream of SocialEvent messages
// that already carry sentiment, stance, and toxicity annotations coming from
// upstream ML micro-services.  A sliding-window EWMA is maintained for every
// community (e.g. chat room, hashtag, voice channel) and periodically flushed
// downstream so that dashboards and alerting rules can react with low
// latency.
//
// This module is intentionally self-contained and only relies on the standard
// library plus a single external, ubiquitous dependency (uuid).  Production
// deployments wire concrete implementations of EventSource / EventSink that
// connect to Kafka, JetStream, or gRPC streams, while unit-tests can inject
// lightweight mocks without touching this file.
package healthscore

import (
	"context"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"

	"github.com/google/uuid"
)

/********************************************************************
 * Domain Models & Contracts
 ********************************************************************/

// SocialEvent is the canonical payload emitted by the EchoPulse ingestion
// layer.  Only the subset of fields needed for health scoring is modeled
// here.  The struct purposefully includes protobuf-style tags so that it
// can be serialized with minimal boilerplate if required.
type SocialEvent struct {
	// EventID is globally unique and set at ingestion time.
	EventID uuid.UUID `json:"event_id"`
	// CommunityID identifies the logical discussion space this event belongs to.
	CommunityID string `json:"community_id"`
	// Unix epoch millis for when the user action occurred.
	Timestamp int64 `json:"ts"`
	// Pre-calculated sentiment in range [-1,1] where ‑1 is very negative,
	// +1 very positive, and 0 is neutral.
	Sentiment float32 `json:"sentiment"`
	// Toxicity probability in range [0,1].
	Toxicity float32 `json:"toxicity"`
}

// EventSource is a pull-based abstraction over any message bus or HTTP long-poll.
type EventSource interface {
	// Recv blocks until the next SocialEvent arrives or the context is cancelled.
	Recv(ctx context.Context) (SocialEvent, error)
}

// EventSink consumes aggregated health scores and pushes them further downstream.
//
// NOTE: The sink interface supports back-pressure via ctx.Done().  Implementations
//       must either respect the cancellation or buffer internally.
type EventSink interface {
	Publish(ctx context.Context, score CommunityHealthScore) error
}

// CommunityHealthScore is the EWMA/aggregate emitted for every community.
type CommunityHealthScore struct {
	CommunityID string    `json:"community_id"`
	WindowSize  time.Duration
	Score       float32   // Bounded [0, 100]  —  0 = toxic, 100 = healthy.
	AsOf        time.Time `json:"as_of"`
}

/********************************************************************
 * Configuration
 ********************************************************************/

// Config drives HealthPipeline behavior.  All fields are required; use the
// With* helpers for ergonomic construction if desired.
type Config struct {
	WindowSize     time.Duration // Sliding window length (look-back horizon).
	EWMADecay      float64       // 0 < decay <= 1; higher = faster reaction.
	ToxicityWeight float64       // Scaling factor when penalizing toxicity.
	TickInterval   time.Duration // How often to flush downstream.
	Source         EventSource
	Sink           EventSink
}

// Validate sanity-checks the configuration.
func (c Config) Validate() error {
	if c.WindowSize <= 0 {
		return errors.New("WindowSize must be > 0")
	}
	if c.EWMADecay <= 0 || c.EWMADecay > 1 {
		return errors.New("EWMADecay must be in (0,1]")
	}
	if c.ToxicityWeight < 0 {
		return errors.New("ToxicityWeight must be >= 0")
	}
	if c.TickInterval <= 0 {
		return errors.New("TickInterval must be > 0")
	}
	if c.Source == nil || c.Sink == nil {
		return errors.New("Source and Sink must be provided")
	}
	return nil
}

/********************************************************************
 * Pipeline Implementation
 ********************************************************************/

// HealthPipeline wires together the scoring logic and manages lifecycles.
//
//     ctx ---> Start()  -----------.
//                 ^                 |
//                 |                 | events
//                 |           +-------------+
//                 |           |  ingestion  |
//                 |           +-------------+
//                 |                  |
//                 |  scores          v
//                 |          +---------------+
//                 |          | aggregation   |
//                 |          +---------------+
//                 |                  |
//                 `------- Stop() <--'
type HealthPipeline struct {
	cfg      Config
	mux      sync.RWMutex // protects scores
	scores   map[string]*emaScore
	startOnce sync.Once
	stopOnce  sync.Once
	cancel    context.CancelFunc
	wg        sync.WaitGroup
}

// emaScore holds the state for a single EWMA.
type emaScore struct {
	mu    sync.Mutex
	value float64
}

// NewHealthPipeline validates cfg and returns a ready-to-start instance.
func NewHealthPipeline(cfg Config) (*HealthPipeline, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	return &HealthPipeline{
		cfg:    cfg,
		scores: make(map[string]*emaScore),
	}, nil
}

// Start spawns worker goroutines and begins processing.  It is safe to call
// only once; subsequent calls are no-ops.
func (p *HealthPipeline) Start(parent context.Context) {
	p.startOnce.Do(func() {
		var ctx context.Context
		ctx, p.cancel = context.WithCancel(parent)

		// Consume events
		p.wg.Add(1)
		go func() {
			defer p.wg.Done()
			p.ingestLoop(ctx)
		}()

		// Periodic flush
		p.wg.Add(1)
		go func() {
			defer p.wg.Done()
			p.flushLoop(ctx)
		}()
	})
}

// Stop gracefully terminates the pipeline.
func (p *HealthPipeline) Stop() {
	p.stopOnce.Do(func() {
		if p.cancel != nil {
			p.cancel()
		}
		p.wg.Wait()
	})
}

// ingestLoop reads SocialEvents and updates EWMA state.
func (p *HealthPipeline) ingestLoop(ctx context.Context) {
	for {
		event, err := p.cfg.Source.Recv(ctx)
		if err != nil {
			// Treat context cancellation as graceful exit.
			if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
				return
			}
			// Non-fatal read error; log and continue.
			fmt.Printf("[healthscore] source error: %v\n", err)
			continue
		}

		p.updateScore(event)
	}
}

// updateScore calculates the instantaneous contribution and updates EWMA.
func (p *HealthPipeline) updateScore(ev SocialEvent) {
	// Health contribution is a composite metric:
	//   sentiment ∈ [-1,1]      → linear map to [0,100]
	//   toxicity  ∈ [0,1]       → penalty (higher toxicity lowers health)
	//
	//   healthRaw = ((sentiment+1)/2)*100 - toxicityWeight*toxicity*100
	//
	// After calculation clamp to [0,100].
	raw := ((float64(ev.Sentiment)+1.0)/2.0)*100.0 -
		p.cfg.ToxicityWeight*float64(ev.Toxicity)*100.0
	health := math.Max(0, math.Min(100, raw))

	es := p.getOrCreateEMA(ev.CommunityID)
	es.mu.Lock()
	defer es.mu.Unlock()

	if es.value == 0 {
		// first observation initializes EMA directly
		es.value = health
	} else {
		es.value = p.cfg.EWMADecay*health + (1-p.cfg.EWMADecay)*es.value
	}
}

// getOrCreateEMA returns the emaScore pointer for a community.
func (p *HealthPipeline) getOrCreateEMA(commID string) *emaScore {
	p.mux.RLock()
	es, ok := p.scores[commID]
	p.mux.RUnlock()
	if ok {
		return es
	}

	// Lazily allocate
	p.mux.Lock()
	defer p.mux.Unlock()
	// Re-check after acquiring write lock to avoid double allocation.
	if es, ok = p.scores[commID]; ok {
		return es
	}
	es = &emaScore{}
	p.scores[commID] = es
	return es
}

// flushLoop ticks on cfg.TickInterval and publishes latest scores.
func (p *HealthPipeline) flushLoop(ctx context.Context) {
	ticker := time.NewTicker(p.cfg.TickInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case t := <-ticker.C:
			p.flushOnce(ctx, t)
		}
	}
}

// flushOnce snapshots all community scores and pushes them to the sink.
func (p *HealthPipeline) flushOnce(ctx context.Context, asOf time.Time) {
	p.mux.RLock()
	defer p.mux.RUnlock()

	var wg sync.WaitGroup
	for commID, es := range p.scores {
		wg.Add(1)
		go func(id string, scorePtr *emaScore) {
			defer wg.Done()
			scorePtr.mu.Lock()
			val := scorePtr.value
			scorePtr.mu.Unlock()

			chScore := CommunityHealthScore{
				CommunityID: id,
				WindowSize:  p.cfg.WindowSize,
				Score:       float32(val),
				AsOf:        asOf,
			}
			if err := p.cfg.Sink.Publish(ctx, chScore); err != nil {
				fmt.Printf("[healthscore] sink publish error: %v\n", err)
			}
		}(commID, es)
	}
	wg.Wait()
}

/********************************************************************
 * Lightweight In-Memory Mocks (for dev / tests)
 ********************************************************************/

// MemorySource is a simple channel-backed EventSource useful in tests.
type MemorySource struct {
	C <-chan SocialEvent
}

// Recv implements EventSource.
func (m MemorySource) Recv(ctx context.Context) (SocialEvent, error) {
	select {
	case <-ctx.Done():
		return SocialEvent{}, ctx.Err()
	case ev, ok := <-m.C:
		if !ok {
			return SocialEvent{}, errors.New("memory source closed")
		}
		return ev, nil
	}
}

// MemorySink accumulates scores and makes them accessible to callers.
type MemorySink struct {
	mu     sync.Mutex
	Scores []CommunityHealthScore
}

// Publish implements EventSink.
func (m *MemorySink) Publish(ctx context.Context, s CommunityHealthScore) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
		m.mu.Lock()
		defer m.mu.Unlock()
		m.Scores = append(m.Scores, s)
		return nil
	}
}

// Snapshot returns a thread-safe copy of accumulated scores.
func (m *MemorySink) Snapshot() []CommunityHealthScore {
	m.mu.Lock()
	defer m.mu.Unlock()
	cp := make([]CommunityHealthScore, len(m.Scores))
	copy(cp, m.Scores)
	return cp
}
```