package echopulse

// File: src/module_46.go
//
// Overview
// --------
// module_46 implements the real-time TrendSurfer component.  A TrendSurfer
// subscribes to the SocialEvent bus, maintains a sliding time-window of token
// frequencies, and emits “trend” events whenever the set of top-K terms drifts
// significantly.
//
// The component is self-contained and exposes a small API so that callers
// (gRPC handlers, CLI tools, other pipeline stages) can:
//
//   • Start / stop the surfer with context cancelation
//   • Query the current top-K trends in constant time
//   • Register a callback that fires whenever a fresh trend vector is emitted
//
// Internally the TrendSurfer:
//
//   1.  Tokenizes & normalizes user-generated text
//   2.  Buckets term counts into a ring buffer keyed by minute
//   3.  On every bucket-advance, merges the window and re-calculates a min-heap
//   4.  Emits an event if the top-K set has drifted > threshold
//
// Note: Kafka / JetStream wiring is intentionally abstracted behind a simple
//       EventBus interface so that the code can be unit-tested without an
//       external broker.

import (
	"container/heap"
	"context"
	"errors"
	"log"
	"regexp"
	"strings"
	"sync"
	"time"
)

// ---------- Public Domain Model ---------- //

// SocialEvent is the canonical payload broadcast on the platform bus.
// We only care about Body text for trend detection, but we keep the
// whole struct around for context / future feature expansion.
type SocialEvent struct {
	EventID   string            `json:"event_id"`
	Timestamp time.Time         `json:"ts"`
	Body      string            `json:"body"`
	Metadata  map[string]string `json:"meta,omitempty"`
}

// Trend holds the aggregated count for a single token.
type Trend struct {
	Term  string
	Count int
}

// TrendSurferConfig exposes tunables for runtime configuration.
type TrendSurferConfig struct {
	WindowSize       time.Duration // Sliding window length (e.g. 10m)
	BucketInterval   time.Duration // Granularity within the window (e.g. 1m)
	TopK             int           // Number of trends to keep
	DriftThreshold   float64       // % change in overlap required to trigger emit
	MinTokenLength   int           // Filter out very short tokens
	StopWords        map[string]struct{}
	CaseInsensitive  bool
	Logger           *log.Logger
}

// ---------- Event Bus Abstraction ---------- //

// EventBus provides a minimal adapter around the platform message bus.
// Consumers call Subscribe and receive *SocialEvent messages on a channel.
// A real implementation would hide Kafka / NATS connection handling.
//
// For unit tests a simple in-memory mock can be provided.
type EventBus interface {
	Subscribe(ctx context.Context, topic string) (<-chan *SocialEvent, error)
	Publish(ctx context.Context, topic string, value interface{}) error
}

// ---------- TrendSurfer Implementation ---------- //

type TrendSurfer struct {
	cfg TrendSurferConfig
	bus EventBus

	callbackMu sync.RWMutex
	callbacks  []func([]Trend)

	// buckets is a ring buffer of token->count maps keyed by time bucket.
	buckets []map[string]int
	head    int // index of the most-recent bucket

	// aggregate is the merged view across the sliding window.
	aggregate map[string]int

	// prevTopK keeps the last emitted set for drift detection.
	prevTopK map[string]struct{}

	mu sync.RWMutex // protects buckets & aggregate
}

// NewTrendSurfer constructs a ready-to-start TrendSurfer.
func NewTrendSurfer(cfg TrendSurferConfig, bus EventBus) (*TrendSurfer, error) {
	if cfg.WindowSize <= 0 {
		return nil, errors.New("window size must be > 0")
	}
	if cfg.BucketInterval <= 0 {
		return nil, errors.New("bucket interval must be > 0")
	}
	if cfg.WindowSize%cfg.BucketInterval != 0 {
		return nil, errors.New("window size must be divisible by bucket interval")
	}
	if cfg.TopK <= 0 {
		cfg.TopK = 10
	}
	if cfg.MinTokenLength <= 0 {
		cfg.MinTokenLength = 3
	}
	if cfg.DriftThreshold <= 0 {
		cfg.DriftThreshold = 0.3
	}
	if cfg.Logger == nil {
		cfg.Logger = log.Default()
	}

	bucketCount := int(cfg.WindowSize / cfg.BucketInterval)
	buckets := make([]map[string]int, bucketCount)
	for i := range buckets {
		buckets[i] = make(map[string]int)
	}

	return &TrendSurfer{
		cfg:       cfg,
		bus:       bus,
		buckets:   buckets,
		aggregate: make(map[string]int),
		prevTopK:  make(map[string]struct{}),
	}, nil
}

// Start launches the processing loop. The call is non-blocking; callers should
// cancel the context to terminate the surfer.
func (ts *TrendSurfer) Start(ctx context.Context, topic string) error {
	eventCh, err := ts.bus.Subscribe(ctx, topic)
	if err != nil {
		return err
	}

	go ts.run(ctx, eventCh)
	return nil
}

// RegisterCallback allows clients to be notified when new trends surface.
func (ts *TrendSurfer) RegisterCallback(fn func([]Trend)) {
	ts.callbackMu.Lock()
	defer ts.callbackMu.Unlock()
	ts.callbacks = append(ts.callbacks, fn)
}

// CurrentTrends returns the latest top-K snapshot.
func (ts *TrendSurfer) CurrentTrends() []Trend {
	ts.mu.RLock()
	defer ts.mu.RUnlock()

	return computeTopK(ts.aggregate, ts.cfg.TopK)
}

// ---------- Private Methods ---------- //

func (ts *TrendSurfer) run(ctx context.Context, events <-chan *SocialEvent) {
	ticker := time.NewTicker(ts.cfg.BucketInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			ts.cfg.Logger.Println("TrendSurfer terminating:", ctx.Err())
			return
		case ev := <-events:
			if ev != nil {
				ts.processEvent(ev)
			}
		case <-ticker.C:
			ts.advanceBucket()
		}
	}
}

func (ts *TrendSurfer) processEvent(ev *SocialEvent) {
	tokens := tokenize(ev.Body, ts.cfg)

	ts.mu.Lock()
	defer ts.mu.Unlock()

	curBucket := ts.buckets[ts.head]
	for _, tok := range tokens {
		curBucket[tok]++
		ts.aggregate[tok]++
	}
}

func (ts *TrendSurfer) advanceBucket() {
	ts.mu.Lock()
	defer ts.mu.Unlock()

	// Zero out the tail bucket that drops off the window.
	tail := (ts.head + 1) % len(ts.buckets)
	for term, count := range ts.buckets[tail] {
		ts.aggregate[term] -= count
		if ts.aggregate[term] <= 0 {
			delete(ts.aggregate, term)
		}
	}
	// Reset the bucket map for reuse.
	ts.buckets[tail] = make(map[string]int)

	// Move the head pointer.
	ts.head = tail

	// Evaluate new trends.
	top := computeTopK(ts.aggregate, ts.cfg.TopK)
	if ts.hasDrifted(top) {
		ts.emit(top)
	}
}

func (ts *TrendSurfer) hasDrifted(top []Trend) bool {
	curSet := make(map[string]struct{}, len(top))
	for _, t := range top {
		curSet[t.Term] = struct{}{}
	}

	overlap := 0
	for term := range curSet {
		if _, ok := ts.prevTopK[term]; ok {
			overlap++
		}
	}
	sharedRatio := float64(overlap) / float64(len(curSet))
	drifted := sharedRatio < (1.0 - ts.cfg.DriftThreshold)

	if drifted {
		ts.prevTopK = curSet
	}
	return drifted
}

func (ts *TrendSurfer) emit(top []Trend) {
	ts.cfg.Logger.Printf("New trend set detected (top-%d): %+v\n", ts.cfg.TopK, top)

	ts.callbackMu.RLock()
	defer ts.callbackMu.RUnlock()
	for _, fn := range ts.callbacks {
		// Fire callbacks asynchronously to avoid blocking.
		go func(f func([]Trend)) {
			defer func() {
				if r := recover(); r != nil {
					ts.cfg.Logger.Printf("trend callback panic: %v", r)
				}
			}()
			f(top)
		}(fn)
	}
}

// ---------- Helpers ---------- //

// Simple tokenizer based on regexp split.
// Production systems might use a proper NLP package but this keeps the module
// self-contained.
var nonAlpha = regexp.MustCompile(`[^\p{L}]+`)

func tokenize(text string, cfg TrendSurferConfig) []string {
	if cfg.CaseInsensitive {
		text = strings.ToLower(text)
	}

	parts := nonAlpha.Split(text, -1)
	out := make([]string, 0, len(parts))

	for _, p := range parts {
		if p == "" || len(p) < cfg.MinTokenLength {
			continue
		}
		if _, stop := cfg.StopWords[p]; stop {
			continue
		}
		out = append(out, p)
	}
	return out
}

// ---------- Top-K Heap ---------- //

type kv struct {
	key   string
	value int
}

type minHeap []kv

func (h minHeap) Len() int            { return len(h) }
func (h minHeap) Less(i, j int) bool  { return h[i].value < h[j].value }
func (h minHeap) Swap(i, j int)       { h[i], h[j] = h[j], h[i] }
func (h *minHeap) Push(x interface{}) { *h = append(*h, x.(kv)) }
func (h *minHeap) Pop() interface{} {
	old := *h
	n := len(old)
	item := old[n-1]
	*h = old[:n-1]
	return item
}

// computeTopK returns the K largest counts in O(n log k).
func computeTopK(m map[string]int, k int) []Trend {
	h := &minHeap{}
	heap.Init(h)

	for term, count := range m {
		if h.Len() < k {
			heap.Push(h, kv{term, count})
		} else if count > (*h)[0].value {
			heap.Pop(h)
			heap.Push(h, kv{term, count})
		}
	}

	// Extract in reverse order (largest first).
	res := make([]Trend, h.Len())
	for i := len(res) - 1; i >= 0; i-- {
		item := heap.Pop(h).(kv)
		res[i] = Trend{Term: item.key, Count: item.value}
	}
	return res
}