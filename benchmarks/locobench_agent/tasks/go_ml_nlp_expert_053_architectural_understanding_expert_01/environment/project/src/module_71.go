```go
// Code generated for EchoPulse: Real-Time Social Signal Processing Platform.
// Module: Trending Topic Tracker
//
// The tracker consumes SocialEvents, maintains a sliding-window term
// frequency index, compares it against a baseline window, and publishes
// TrendUpdate messages for topics whose frequency growth exceeds a
// configurable threshold.
//
// Patterns used:
//   – Observer  : subscribes to the canonical SocialEvent stream
//   – Strategy  : pluggable Tokenizer implementation
//   – Pipeline  : streaming, fault-tolerant aggregation
//
// Author: EchoPulse Engineering
// -----------------------------------------------------------------------

package pipeline

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

// SocialEvent is the canonical envelope produced by upstream ingestion.
// In the real project this type lives in a shared protobuf/gRPC module;
// we redefine a minimal subset here to keep the file self-contained.
type SocialEvent struct {
	ID        string    // global unique id
	ChannelID string    // conversation channel (chat room, feed, etc.)
	AuthorID  string    // user id
	Text      string    // UTF-8 body
	Timestamp time.Time // wall-clock timestamp
}

// TrendUpdate is emitted by the TrendingTopicTracker and published to a sink.
type TrendUpdate struct {
	ChannelID string
	WindowEnd time.Time
	Topics    []TopicScore
}

// TopicScore holds topic with computed trend score.
type TopicScore struct {
	Topic string
	Score float64
}

// Sink represents a downstream consumer (e.g. Kafka, gRPC, WebSocket).
// Implementations must be thread-safe.
type Sink interface {
	Publish(ctx context.Context, update TrendUpdate) error
}

// Tokenizer converts raw text into a slice of tokens.
type Tokenizer interface {
	Tokens(s string) []string
}

// Config groups tuning knobs for the TrendingTopicTracker.
type Config struct {
	WindowDuration   time.Duration // fresh activity
	BaselineDuration time.Duration // historical baseline
	FlushInterval    time.Duration // how often to evaluate / emit
	MinCount         int           // ignore terms with < MinCount occurrences
	Threshold        float64       // (win-count / base-count) ratio
	TopK             int           // number of topics per update
	CaseSensitive    bool          // keep / lower-case tokens
}

// DefaultConfig returns production-ready defaults.
func DefaultConfig() Config {
	return Config{
		WindowDuration:   2 * time.Minute,
		BaselineDuration: 10 * time.Minute,
		FlushInterval:    5 * time.Second,
		MinCount:         10,
		Threshold:        2.0,   // ≥ 2x bump vs baseline
		TopK:             10,
		CaseSensitive:    false,
	}
}

// SimpleTokenizer splits on non-letter characters and optionally lower-cases.
type SimpleTokenizer struct {
	caseSensitive bool
	re            *regexp.Regexp
}

// NewSimpleTokenizer creates a default tokenizer.
func NewSimpleTokenizer(caseSensitive bool) *SimpleTokenizer {
	return &SimpleTokenizer{
		caseSensitive: caseSensitive,
		re:            regexp.MustCompile(`[^\p{L}\p{N}]+`),
	}
}

// Tokens implements Tokenizer.
func (t *SimpleTokenizer) Tokens(s string) []string {
	if !t.caseSensitive {
		s = strings.ToLower(s)
	}
	raw := t.re.Split(s, -1)
	out := make([]string, 0, len(raw))
	for _, tok := range raw {
		if len(tok) > 0 {
			out = append(out, tok)
		}
	}
	return out
}

// bucket stores per-topic counts for a time slice.
type bucket struct {
	start  time.Time
	counts map[string]int
}

// TrendingTopicTracker aggregates high-volume events safely with O(1)
// per-event overhead. Internally it uses a time-based circular buffer.
type TrendingTopicTracker struct {
	cfg       Config
	tokenizer Tokenizer
	sink      Sink

	// Buckets ordered oldest→newest as a ring buffer.
	buckets []bucket
	// Index of the newest bucket in buckets slice.
	head int

	// Protects buckets and derived state.
	mu sync.RWMutex

	eventCh <-chan SocialEvent
	ctx     context.Context
	cancel  context.CancelFunc
	wg      sync.WaitGroup
}

// NewTrendingTopicTracker constructs and returns a ready tracker.
// eventCh must be high-throughput buffered channel from the bus.
func NewTrendingTopicTracker(
	parent context.Context,
	eventCh <-chan SocialEvent,
	sink Sink,
	opts ...func(*Config),
) (*TrendingTopicTracker, error) {

	if sink == nil {
		return nil, errors.New("sink cannot be nil")
	}
	if eventCh == nil {
		return nil, errors.New("event channel cannot be nil")
	}

	cfg := DefaultConfig()
	for _, o := range opts {
		o(&cfg)
	}

	ctx, cancel := context.WithCancel(parent)

	totalWindow := cfg.WindowDuration + cfg.BaselineDuration
	// Derive bucket count from minute granularity for memory savings.
	// We use 1-second granularity to support sub-minute windows accurately.
	bucketCount := int(totalWindow.Seconds()) + 1

	ttt := &TrendingTopicTracker{
		cfg:       cfg,
		tokenizer: NewSimpleTokenizer(cfg.CaseSensitive),
		sink:      sink,
		eventCh:   eventCh,
		ctx:       ctx,
		cancel:    cancel,
		buckets:   make([]bucket, bucketCount),
		head:      bucketCount - 1,
	}

	now := time.Now().UTC()
	for i := range ttt.buckets {
		ttt.buckets[i] = bucket{
			start:  now.Add(-time.Duration(bucketCount-i) * time.Second),
			counts: make(map[string]int),
		}
	}
	return ttt, nil
}

// Start launches background goroutines and returns immediately.
func (t *TrendingTopicTracker) Start() {
	t.wg.Add(2)
	go t.consumeEvents()
	go t.flushLoop()
}

// Stop gracefully drains goroutines.
func (t *TrendingTopicTracker) Stop() {
	t.cancel()
	t.wg.Wait()
}

// consumeEvents reads from eventCh and updates the active bucket.
func (t *TrendingTopicTracker) consumeEvents() {
	defer t.wg.Done()
	for {
		select {
		case <-t.ctx.Done():
			return
		case ev, ok := <-t.eventCh:
			if !ok {
				t.cancel()
				return
			}
			t.ingest(ev)
		}
	}
}

// ingest processes one event (hot path, keep lean).
func (t *TrendingTopicTracker) ingest(ev SocialEvent) {
	t.mu.RLock()
	headBucket := &t.buckets[t.head]
	t.mu.RUnlock()

	// Fast path: event belongs to current bucket.
	if ev.Timestamp.After(headBucket.start) {
		t.updateCounts(headBucket.counts, ev.Text)
		return
	}
	// Slow path: event older than current head; walk to correct bucket.
	t.mu.Lock()
	defer t.mu.Unlock()
	insertIdx := t.indexForTimestamp(ev.Timestamp)
	t.updateCounts(t.buckets[insertIdx].counts, ev.Text)
}

// updateCounts tokenizes text and bumps frequency map.
// No locking here; caller must own bucket.
func (t *TrendingTopicTracker) updateCounts(counts map[string]int, text string) {
	for _, tok := range t.tokenizer.Tokens(text) {
		counts[tok]++
	}
}

// flushLoop periodically advances window & publishes trends.
func (t *TrendingTopicTracker) flushLoop() {
	defer t.wg.Done()
	ticker := time.NewTicker(t.cfg.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-t.ctx.Done():
			return
		case now := <-ticker.C:
			t.rotateBuckets(now)
			trends := t.computeTrends()
			if len(trends.Topics) > 0 {
				_ = t.sink.Publish(t.ctx, trends) // errors handled inside sink
			}
		}
	}
}

// rotateBuckets creates new head buckets as time progresses.
func (t *TrendingTopicTracker) rotateBuckets(now time.Time) {
	t.mu.Lock()
	defer t.mu.Unlock()

	curHead := &t.buckets[t.head]
	// If current head already covers 'now', nothing to do.
	if now.Sub(curHead.start) < time.Second {
		return
	}

	// Add as many new buckets as we skipped seconds.
	steps := int(now.Sub(curHead.start).Seconds())
	for i := 0; i < steps; i++ {
		t.head = (t.head + 1) % len(t.buckets)
		nextIdx := t.head
		t.buckets[nextIdx].start = curHead.start.Add(time.Duration(i+1) * time.Second)
		// Reuse map to reduce allocations.
		for k := range t.buckets[nextIdx].counts {
			delete(t.buckets[nextIdx].counts, k)
		}
	}
}

// computeTrends compares window counts vs baseline and returns update.
func (t *TrendingTopicTracker) computeTrends() TrendUpdate {
	windowEnd := time.Now().UTC()

	winCounts := make(map[string]int)
	baseCounts := make(map[string]int)

	winStart := windowEnd.Add(-t.cfg.WindowDuration)
	baseStart := winStart.Add(-t.cfg.BaselineDuration)

	t.mu.RLock()
	defer t.mu.RUnlock()

	// Iterate buckets once, aggregate counts.
	for _, b := range t.buckets {
		if b.start.Before(baseStart) {
			continue // too old
		}
		for tok, cnt := range b.counts {
			switch {
			case b.start.After(winStart):
				winCounts[tok] += cnt
			default:
				baseCounts[tok] += cnt
			}
		}
	}

	// Calculate ratios.
	type kv struct {
		token string
		score float64
	}
	var scored []kv
	for tok, winCnt := range winCounts {
		if winCnt < t.cfg.MinCount {
			continue
		}
		baseCnt := baseCounts[tok]
		if baseCnt == 0 {
			baseCnt = 1 // Laplace smoothing
		}
		ratio := float64(winCnt) / float64(baseCnt)
		if ratio >= t.cfg.Threshold {
			scored = append(scored, kv{tok, ratio})
		}
	}

	sort.Slice(scored, func(i, j int) bool {
		return scored[i].score > scored[j].score
	})

	if len(scored) > t.cfg.TopK {
		scored = scored[:t.cfg.TopK]
	}

	topics := make([]TopicScore, len(scored))
	for i, s := range scored {
		topics[i] = TopicScore{Topic: s.token, Score: s.score}
	}

	return TrendUpdate{
		ChannelID: "global", // TODO: per-channel aggregation
		WindowEnd: windowEnd,
		Topics:    topics,
	}
}

// indexForTimestamp returns bucket index for a timestamp.
//
// PRECONDITION: caller holds write lock.
func (t *TrendingTopicTracker) indexForTimestamp(ts time.Time) int {
	// Align timestamp to second precision
	diffSec := int(time.Since(ts).Seconds())
	if diffSec < 0 || diffSec >= len(t.buckets) {
		// Too new / too old -> assign to head to avoid panic, but flag.
		fmt.Printf("timestamp out of range: %+v\n", ts)
		return t.head
	}
	idx := (t.head - diffSec + len(t.buckets)) % len(t.buckets)
	return idx
}
```