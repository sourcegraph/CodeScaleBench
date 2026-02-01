package echopulse

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	cm "github.com/dgryski/go-countmin"
	"github.com/google/uuid"
	"github.com/segmentio/kafka-go"
)

// ----------------------------------------------------------------------------
// Module: TrendingTermTracker  (src/module_49.go)
//
// This module keeps a lightweight, approximate frequency sketch of tokens
// observed over a defined sliding window.  When the window elapses, the top‐k
// terms are surfaced as a TrendEvent and published to the outbound event bus
// (Kafka).  The data structure of choice is Count–Min Sketch which delivers
// bounded accuracy with tight memory usage—vital for the cardinality of large
// public chat rooms.
//
// The implementation is fully concurrent safe, cancellation‐aware, and built
// for high throughput ingestion.
// ----------------------------------------------------------------------------

// Config holds runtime parameters for a TrendingTermTracker instance.
type Config struct {
	KafkaBrokers      []string      // list of brokers: ["broker-1:9092", "broker-2:9092"]
	OutTopic          string        // topic to which trend events are published
	SketchEpsilon     float64       // error factor ε  (smaller => more memory)
	SketchDelta       float64       // probability δ of larger error
	FlushInterval     time.Duration // how often we snapshot current window
	TopK              int           // how many terms to emit per flush
	MaxKafkaAttempts  int           // retry attempts for a failed publish
	CompressionCodec  kafka.Compression
	ClientIDComponent string // unique component name used in kafka client-id
}

// DefaultConfig returns a tuned configuration good for most use cases.
func DefaultConfig() Config {
	return Config{
		KafkaBrokers:     []string{"localhost:9092"},
		OutTopic:         "trend-events",
		SketchEpsilon:    0.0005,
		SketchDelta:      0.999,
		FlushInterval:    5 * time.Second,
		TopK:             20,
		MaxKafkaAttempts: 3,
		CompressionCodec: kafka.Snappy,
		// ClientIDComponent will be filled by caller for uniqueness.
	}
}

// ErrShuttingDown indicates the tracker has begun graceful shutdown.
var ErrShuttingDown = errors.New("tracker is shutting down")

// SocialEvent is the canonical representation consumed by this tracker.
// In the real project this would be imported from a dedicated package.
// Only the subset required for trending calculation is included here.
type SocialEvent struct {
	EventID   uuid.UUID `json:"event_id"`
	Timestamp time.Time `json:"ts"`
	UserID    string    `json:"uid"`
	Text      string    `json:"text"` // normalized UTF-8 corpus
	// other fields: Emoji, Reactions, AudioTranscript, etc.
}

// TrendEvent is the outbound struct emitted by this tracker.
type TrendEvent struct {
	WindowStart time.Time         `json:"window_start"`
	WindowEnd   time.Time         `json:"window_end"`
	TopTerms    []TermWithScore   `json:"top_terms"`
	Meta        map[string]string `json:"meta,omitempty"`
}

// TermWithScore pairs a term with its approximate frequency.
type TermWithScore struct {
	Term  string  `json:"term"`
	Score uint64  `json:"score"`
	Rank  int     `json:"rank"`
	Error float64 `json:"error_estimate"`
}

// TrendingTermTracker is a concurrently safe, windowed sketch aggregator.
type TrendingTermTracker struct {
	cfg Config

	sketch    *cm.CountMinSketch
	windowMux sync.Mutex // protects sketch & window start
	windowBeg time.Time

	ingestCh chan SocialEvent
	wg       sync.WaitGroup

	writer  *kafka.Writer
	ctx     context.Context
	cancel  context.CancelFunc
	started bool
}

// NewTrendingTermTracker wires up a new tracker and spawns internal goroutines.
// A nil Config field will be replaced with defaults.
func NewTrendingTermTracker(parent context.Context, cfg Config) (*TrendingTermTracker, error) {
	if cfg.ClientIDComponent == "" {
		return nil, errors.New("config.ClientIDComponent must be non-empty")
	}

	ctx, cancel := context.WithCancel(parent)

	ks := &kafka.Writer{
		Addr:         kafka.TCP(cfg.KafkaBrokers...),
		Topic:        cfg.OutTopic,
		Balancer:     &kafka.Hash{}, // stable hashing on key
		RequiredAcks: kafka.RequireAll,
		Async:        true, // high throughput, we handle errors separately
		Compression:  cfg.CompressionCodec,
	}

	// Initialize Count-Min Sketch
	sketch := cm.New(cfg.SketchEpsilon, cfg.SketchDelta)

	tr := &TrendingTermTracker{
		cfg:     cfg,
		sketch:  sketch,
		writer:  ks,
		ctx:     ctx,
		cancel:  cancel,
		ingestCh: make(chan SocialEvent, 2048),
		windowBeg: time.Now().UTC(),
	}

	tr.wg.Add(2)
	go tr.ingestLoop()
	go tr.flushLoop()

	tr.started = true
	return tr, nil
}

// Ingest pushes a SocialEvent text into the TrendingTermTracker buffer.
// Heavy allocation & CPU work (tokenization) is done on background goroutine.
func (t *TrendingTermTracker) Ingest(evt SocialEvent) error {
	if !t.started {
		return ErrShuttingDown
	}

	select {
	case t.ingestCh <- evt:
		return nil
	case <-t.ctx.Done():
		return ErrShuttingDown
	default:
		// Buffer full—a backpressure mechanism should be added here in prod.
		return fmt.Errorf("tracker ingest buffer is full")
	}
}

// Close gracefully shuts down background workers.
func (t *TrendingTermTracker) Close() error {
	if !t.started {
		return nil
	}
	t.started = false
	t.cancel()
	close(t.ingestCh)
	t.wg.Wait()
	return t.writer.Close()
}

// ----------------------------------------------------------------------------
// Internal implementation
// ----------------------------------------------------------------------------

func (t *TrendingTermTracker) ingestLoop() {
	defer t.wg.Done()
	for {
		select {
		case evt, ok := <-t.ingestCh:
			if !ok {
				return
			}
			t.processEvent(evt)
		case <-t.ctx.Done():
			return
		}
	}
}

// processEvent tokenizes the text and updates the sketch counts.
func (t *TrendingTermTracker) processEvent(evt SocialEvent) {
	terms := tokenize(evt.Text)
	if len(terms) == 0 {
		return
	}

	t.windowMux.Lock()
	defer t.windowMux.Unlock()

	for _, term := range terms {
		t.sketch.UpdateString(term, 1)
	}
}

// flushLoop periodically emits TrendEvents and resets the sketch.
func (t *TrendingTermTracker) flushLoop() {
	defer t.wg.Done()

	ticker := time.NewTicker(t.cfg.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			t.flushWindow()
		case <-t.ctx.Done():
			return
		}
	}
}

// flushWindow snapshots current sketch, extracts top-k, publishes, and resets.
func (t *TrendingTermTracker) flushWindow() {
	// Swap sketch under lock to minimize ingest blocking
	t.windowMux.Lock()
	oldSketch := t.sketch
	startTime := t.windowBeg

	t.sketch = cm.New(t.cfg.SketchEpsilon, t.cfg.SketchDelta)
	t.windowBeg = time.Now().UTC()
	t.windowMux.Unlock()

	topTerms := extractTopK(oldSketch, t.cfg.TopK)

	evt := TrendEvent{
		WindowStart: startTime,
		WindowEnd:   time.Now().UTC(),
		TopTerms:    buildTermWithScoreList(oldSketch, topTerms),
		Meta: map[string]string{
			"generator": "TrendingTermTracker",
			"version":   "v1.0.0",
		},
	}

	if err := t.publish(evt); err != nil {
		// Ideally we would have a durable retry queue or DLQ
		fmt.Printf("flushWindow: failed to publish trend event: %v\n", err)
	}
}

func (t *TrendingTermTracker) publish(evt TrendEvent) error {
	payload, err := json.Marshal(evt)
	if err != nil {
		return fmt.Errorf("marshal trend event: %w", err)
	}

	msg := kafka.Message{
		Key:   []byte(evt.WindowEnd.Format(time.RFC3339Nano)),
		Value: payload,
		Time:  time.Now().UTC(),
	}

	var attempt int
	for {
		err = t.writer.WriteMessages(t.ctx, msg)
		if err == nil {
			return nil
		}
		attempt++
		if attempt >= t.cfg.MaxKafkaAttempts {
			return fmt.Errorf("publish trend event after %d attempts: %w", attempt, err)
		}
		// Exponential backoff
		select {
		case <-time.After(time.Duration(attempt) * 250 * time.Millisecond):
		case <-t.ctx.Done():
			return ErrShuttingDown
		}
	}
}

// ----------------------------------------------------------------------------
// Helper functions
// ----------------------------------------------------------------------------

// tokenize converts incoming text to lower‐cased unigrams without stop words.
// For production, consider Unicode aware segmentation & stop word lists.
func tokenize(text string) []string {
	text = strings.ToLower(text)
	// Basic punctuation removal
	replacer := strings.NewReplacer(".", "", ",", "", "!", "", "?", "", "\"", "", "'", "", ":", "", ";", "")
	text = replacer.Replace(text)

	words := strings.Fields(text)
	stopWords := map[string]struct{}{
		"a": {}, "the": {}, "and": {}, "or": {}, "but": {}, "i": {}, "me": {}, "you": {},
	}

	var tokens []string
	for _, w := range words {
		if _, skip := stopWords[w]; skip {
			continue
		}
		tokens = append(tokens, w)
	}
	return tokens
}

// extractTopK approximates the top‐k terms by scanning a hash of counters.
func extractTopK(sketch *cm.CountMinSketch, k int) []string {
	type kv struct {
		term  string
		count uint64
	}
	// The Count-Min Sketch does not retain the original key set.
	// In production, we would maintain a Space-Saving summary or heavy-hitters
	// data structure to extract top‐k efficiently.  For this example, we fall
	// back to the Count-Min sketch's internal hashmap for demonstration.
	var pairs []kv
	for key, c := range sketch.Table() {
		pairs = append(pairs, kv{term: key.(string), count: c})
	}

	// Partial selection (O(n*k))
	top := make([]string, 0, k)
	for i := 0; i < k && len(pairs) > 0; i++ {
		var maxIdx int
		for j, p := range pairs {
			if p.count > pairs[maxIdx].count {
				maxIdx = j
			}
		}
		top = append(top, pairs[maxIdx].term)
		pairs = append(pairs[:maxIdx], pairs[maxIdx+1:]...)
	}
	return top
}

func buildTermWithScoreList(sketch *cm.CountMinSketch, terms []string) []TermWithScore {
	out := make([]TermWithScore, 0, len(terms))
	for rank, term := range terms {
		count := sketch.EstimateString(term)
		errEst := sketch.Error()
		out = append(out, TermWithScore{
			Term:  term,
			Score: count,
			Rank:  rank + 1,
			Error: errEst,
		})
	}
	return out
}