```go
// File: src/module_53.go
//
// DriftWatcher — monitors statistical drift in model predictions and
// automatically emits “drift detected” events when the live distribution of
// predictions diverges from a reference baseline beyond a configurable
// threshold.
//
// Copyright
// ---------
// EchoPulse: Real-Time Social Signal Processing Platform
// SPDX-License-Identifier: Apache-2.0

package echopulse

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"

	"github.com/nats-io/nats.go"
)

// ----------------------------------------------------------------------------
// Public event types
// ----------------------------------------------------------------------------

// ClassificationEvent represents the _canonical_ message produced by the
// inference service after a social event has been classified by one of the
// on-line NLP models (toxicity, stance, etc.).
type ClassificationEvent struct {
	EventID        string             `json:"event_id"`
	ModelID        string             `json:"model_id"`
	CreatedAt      time.Time          `json:"created_at"`
	Prediction     string             `json:"prediction"`
	ClassProbs     map[string]float64 `json:"class_probs,omitempty"`
	OriginalSource string             `json:"origin,omitempty"`
}

// DriftAlert is raised when the DriftWatcher concludes that the statistical
// distribution of model predictions has diverged from the reference baseline.
type DriftAlert struct {
	ModelID       string    `json:"model_id"`
	WindowStart   time.Time `json:"window_start"`
	WindowEnd     time.Time `json:"window_end"`
	Divergence    float64   `json:"divergence"`
	Threshold     float64   `json:"threshold"`
	SuspectLabels []string  `json:"suspect_labels"`
}

// ----------------------------------------------------------------------------
// JetStream consumer / publisher implementations
// ----------------------------------------------------------------------------

// JSConsumer wraps a NATS JetStream pull subscription.
type JSConsumer struct {
	js        nats.JetStreamContext
	sub       *nats.Subscription
	batchSize int
}

// NewJSConsumer constructs a pull-based consumer on the given subject / durable.
func NewJSConsumer(js nats.JetStreamContext, subject, durable string, batchSize int) (*JSConsumer, error) {
	sub, err := js.PullSubscribe(subject, durable,
		nats.BindStream("EVENTS"),
		nats.MaxAckPending(10_000))
	if err != nil {
		return nil, fmt.Errorf("pull subscribe: %w", err)
	}
	if batchSize <= 0 {
		batchSize = 100
	}
	return &JSConsumer{js: js, sub: sub, batchSize: batchSize}, nil
}

// Fetch pulls a batch of ClassificationEvent messages (blocking up to maxWait).
func (c *JSConsumer) Fetch(ctx context.Context, maxWait time.Duration) ([]ClassificationEvent, error) {
	msgs, err := c.sub.Fetch(c.batchSize, nats.Context(ctx), nats.MaxWait(maxWait))
	if err != nil && !errors.Is(err, context.DeadlineExceeded) {
		return nil, err
	}

	events := make([]ClassificationEvent, 0, len(msgs))
	for _, m := range msgs {
		var ev ClassificationEvent
		if err := json.Unmarshal(m.Data, &ev); err != nil {
			// Malformed payload; ack + continue
			m.Ack()
			continue
		}
		events = append(events, ev)
		m.Ack()
	}
	return events, nil
}

// JSPublisher publishes alerts onto a JetStream subject.
type JSPublisher struct {
	js      nats.JetStreamContext
	subject string
}

func NewJSPublisher(js nats.JetStreamContext, subject string) *JSPublisher {
	return &JSPublisher{js: js, subject: subject}
}

func (p *JSPublisher) Publish(ctx context.Context, alert DriftAlert) error {
	data, err := json.Marshal(alert)
	if err != nil {
		return err
	}
	_, err = p.js.PublishMsg(&nats.Msg{
		Subject: p.subject,
		Header:  nats.Header{"content-type": []string{"application/json"}},
		Data:    data,
	}, nats.Context(ctx))
	return err
}

// ----------------------------------------------------------------------------
// DriftWatcher implementation
// ----------------------------------------------------------------------------

// DriftConfig holds runtime tuning parameters for a DriftWatcher instance.
type DriftConfig struct {
	ModelID          string
	Window           time.Duration // Sliding window horizon
	SampleThreshold  int           // Min sample count before we test for drift
	KLDivergenceThrs float64       // Alert when KL(p||q) > Thr
}

// DriftWatcher ingests ClassificationEvents, keeps a sliding window of recent
// predictions, and fires DriftAlerts whenever KL-divergence exceeds threshold.
type DriftWatcher struct {
	cfg        DriftConfig
	baseline   map[string]float64 // reference distribution q(label)
	consumer   *JSConsumer
	publisher  *JSPublisher
	bufLock    sync.Mutex
	buffer     []ClassificationEvent
	windowEnds time.Time
}

// NewDriftWatcher wires all collaborators together.
func NewDriftWatcher(
	cfg DriftConfig,
	baseline map[string]float64,
	consumer *JSConsumer,
	publisher *JSPublisher,
) (*DriftWatcher, error) {

	if len(baseline) == 0 {
		return nil, errors.New("baseline distribution must not be empty")
	}
	if cfg.KLDivergenceThrs <= 0 {
		return nil, errors.New("KL threshold must be greater than zero")
	}
	return &DriftWatcher{
		cfg:       cfg,
		baseline:  normalize(baseline),
		consumer:  consumer,
		publisher: publisher,
		buffer:    make([]ClassificationEvent, 0, 4096),
	}, nil
}

// Start spins up the drift detection loop. It is safe to call Start only once.
func (dw *DriftWatcher) Start(ctx context.Context) error {
	ticker := time.NewTicker(dw.cfg.Window / 4) // compute 4× per window
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		// 1. Drain messages from JetStream (non-blocking)
		evs, err := dw.consumer.Fetch(ctx, 250*time.Millisecond)
		if err != nil && !errors.Is(err, context.DeadlineExceeded) {
			return fmt.Errorf("fetch events: %w", err)
		}

		dw.bufLock.Lock()
		for _, ev := range evs {
			dw.buffer = append(dw.buffer, ev)
		}
		dw.bufLock.Unlock()

		select {
		case <-ticker.C:
			if err := dw.evaluateWindow(ctx); err != nil {
				return err
			}
		default:
		}
	}
}

// evaluateWindow trims the sliding window & tests for drift.
func (dw *DriftWatcher) evaluateWindow(ctx context.Context) error {
	cutoff := time.Now().Add(-dw.cfg.Window)

	dw.bufLock.Lock()
	// Trim events outside the window
	var i int
	for i = len(dw.buffer) - 1; i >= 0; i-- {
		if dw.buffer[i].CreatedAt.Before(cutoff) {
			break
		}
	}
	if i >= 0 {
		dw.buffer = dw.buffer[i+1:]
	}
	// Snapshot window copy
	snapshot := make([]ClassificationEvent, len(dw.buffer))
	copy(snapshot, dw.buffer)
	dw.bufLock.Unlock()

	if len(snapshot) < dw.cfg.SampleThreshold {
		return nil
	}

	emp := empiricalDistribution(snapshot)
	div := klDivergence(emp, dw.baseline)

	if div > dw.cfg.KLDivergenceThrs {
		alert := DriftAlert{
			ModelID:       dw.cfg.ModelID,
			WindowStart:   time.Now().Add(-dw.cfg.Window),
			WindowEnd:     time.Now(),
			Divergence:    div,
			Threshold:     dw.cfg.KLDivergenceThrs,
			SuspectLabels: topSuspects(emp, dw.baseline, 3),
		}
		if err := dw.publisher.Publish(ctx, alert); err != nil {
			return fmt.Errorf("publish drift alert: %w", err)
		}
	}
	return nil
}

// ----------------------------------------------------------------------------
// Helper maths
// ----------------------------------------------------------------------------

// empiricalDistribution returns p(label) estimated from the sample slice.
func empiricalDistribution(events []ClassificationEvent) map[string]float64 {
	counts := make(map[string]int)
	for _, e := range events {
		counts[e.Prediction]++
	}
	total := float64(len(events))
	p := make(map[string]float64, len(counts))
	for k, c := range counts {
		p[k] = float64(c) / total
	}
	return p
}

// normalize ensures the probabilities sum to 1 and drops zero-probability bins.
func normalize(dist map[string]float64) map[string]float64 {
	sum := 0.0
	for _, v := range dist {
		sum += v
	}
	norm := make(map[string]float64, len(dist))
	for k, v := range dist {
		if v > 0 {
			norm[k] = v / sum
		}
	}
	return norm
}

// klDivergence calculates KL(p || q) with a small add-epsilon smoothing to
// avoid log(0). Both distributions need not share support; unseen labels in q
// assume epsilon probability mass.
func klDivergence(p, q map[string]float64) float64 {
	const eps = 1e-12
	div := 0.0
	for label, pv := range p {
		qv, ok := q[label]
		if !ok {
			qv = eps
		}
		pv = math.Max(pv, eps)
		div += pv * math.Log(pv/qv)
	}
	return div
}

// topSuspects lists the most deviating labels (largest |p−q|).
func topSuspects(p, q map[string]float64, k int) []string {
	type diff struct {
		Label string
		Delta float64
	}
	var deltas []diff
	for label, pv := range p {
		delta := math.Abs(pv - q[label])
		deltas = append(deltas, diff{label, delta})
	}
	// Simple selection sort for k small
	for i := 0; i < k && i < len(deltas); i++ {
		maxIdx := i
		for j := i + 1; j < len(deltas); j++ {
			if deltas[j].Delta > deltas[maxIdx].Delta {
				maxIdx = j
			}
		}
		deltas[i], deltas[maxIdx] = deltas[maxIdx], deltas[i]
	}
	out := make([]string, 0, k)
	for i := 0; i < k && i < len(deltas); i++ {
		out = append(out, deltas[i].Label)
	}
	return out
}
```