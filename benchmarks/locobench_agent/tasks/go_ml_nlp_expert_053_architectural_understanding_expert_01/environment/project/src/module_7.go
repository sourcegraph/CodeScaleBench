```go
// File: src/module_7.go
//
// Drift monitoring module for EchoPulse.
// Implements a JetStream–backed observer that continuously assesses statistical
// drift between a model’s reference distribution and the live production stream.
// When significant drift is detected it (1) publishes a guidance event back to
// the bus and (2) notifies the Training-Orchestrator gRPC service so an
// automated re-training job can be queued.

package drift

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"sync"
	"time"

	"github.com/nats-io/nats.go"
	"google.golang.org/grpc"
)

// ----------------------------- //
// Configuration & Dependencies  //
// ----------------------------- //

// Config holds runtime configuration for a DriftDetector instance.
type Config struct {
	// NATS / JetStream connection details
	NATSUrl         string
	NATSSubjectProd string // Subject carrying production inference scores
	NATSSubjectCtrl string // Subject to publish drift alerts

	// Model / reference dataset
	ModelID              string
	ReferenceDistribution []float64 // baseline distribution

	// Drift threshold & windows
	Metric           string        // "ks" or "psi"
	CheckInterval    time.Duration // how often to evaluate drift
	MinSamples       int           // minimum samples required before evaluating
	DriftThreshold   float64       // metric-specific threshold

	// gRPC training service
	TrainingEndpoint string // host:port for Training-Orchestrator
}

// Validate sanity-checks config values.
func (c *Config) Validate() error {
	switch {
	case c.NATSUrl == "":
		return errors.New("NATSUrl required")
	case c.NATSSubjectProd == "":
		return errors.New("NATSSubjectProd required")
	case c.NATSSubjectCtrl == "":
		return errors.New("NATSSubjectCtrl required")
	case len(c.ReferenceDistribution) == 0:
		return errors.New("ReferenceDistribution must not be empty")
	case c.TrainingEndpoint == "":
		return errors.New("TrainingEndpoint required")
	case c.CheckInterval <= 0:
		c.CheckInterval = 1 * time.Minute
	case c.MinSamples <= 0:
		c.MinSamples = 500
	case c.DriftThreshold <= 0:
		c.DriftThreshold = 0.1
	}
	return nil
}

// -------------------- //
// Event Representation //
// -------------------- //

// InferenceEvent is the canonical payload published by model‐serving workers.
type InferenceEvent struct {
	ModelID string  `json:"model_id"`
	Score   float64 `json:"score"` // probability, logit, sentiment, etc.
	// ... other fields stripped for brevity
}

// DriftAlertEvent is issued by this module when significant drift is observed.
type DriftAlertEvent struct {
	ModelID     string    `json:"model_id"`
	Metric      string    `json:"metric"`
	Value       float64   `json:"value"`
	Threshold   float64   `json:"threshold"`
	EventTime   time.Time `json:"event_time"`
	SampleCount int       `json:"sample_count"`
}

// --------------------- //
// Strategy Pattern      //
// --------------------- //

// DriftMetricStrategy defines a pluggable algorithm for drift detection.
type DriftMetricStrategy interface {
	// Compute returns metric score and whether the score indicates drift.
	Compute(reference, production []float64, threshold float64) (score float64, drift bool, err error)
	Name() string
}

// ksMetric implements the Kolmogorov–Smirnov two-sample test.
type ksMetric struct{}

func (k ksMetric) Name() string { return "ks" }

func (k ksMetric) Compute(ref, prod []float64, threshold float64) (float64, bool, error) {
	if len(ref) == 0 || len(prod) == 0 {
		return 0, false, errors.New("empty distribution for ks metric")
	}
	// Sort copies so we don't mutate inputs.
	r := append([]float64(nil), ref...)
	p := append([]float64(nil), prod...)
	sort.Float64s(r)
	sort.Float64s(p)

	n1, n2 := len(r), len(p)
	var d, dp, dq float64
	i, j := 0, 0
	for i < n1 && j < n2 {
		if r[i] < p[j] {
			i++
		} else if r[i] > p[j] {
			j++
		} else {
			i++
			j++
		}
		dp = float64(i) / float64(n1)
		dq = float64(j) / float64(n2)
		d = math.Max(d, math.Abs(dp-dq))
	}
	// Reject H0 if D > threshold. Typical KS critical value ~ 0.1 for 95% conf.
	return d, d > threshold, nil
}

// psiMetric implements Population Stability Index.
type psiMetric struct {
	Buckets int
}

func (p psiMetric) Name() string { return "psi" }

func (p psiMetric) Compute(ref, prod []float64, threshold float64) (float64, bool, error) {
	if len(ref) == 0 || len(prod) == 0 {
		return 0, false, errors.New("empty distribution for psi metric")
	}
	buckets := p.Buckets
	if buckets <= 0 {
		buckets = 10
	}

	// Determine bucket edges from reference distribution.
	edges := make([]float64, buckets+1)
	sorted := append([]float64(nil), ref...)
	sort.Float64s(sorted)
	for i := 0; i <= buckets; i++ {
		edgeIdx := int(float64(i) / float64(buckets) * float64(len(sorted)-1))
		edges[i] = sorted[edgeIdx]
	}
	edges[buckets] = sorted[len(sorted)-1] + 1e-6 // ensure max inclusive

	countsRef := make([]int, buckets)
	countsProd := make([]int, buckets)

	// Bin counts.
	for _, v := range ref {
		for i := 0; i < buckets; i++ {
			if v >= edges[i] && v < edges[i+1] {
				countsRef[i]++
				break
			}
		}
	}
	for _, v := range prod {
		for i := 0; i < buckets; i++ {
			if v >= edges[i] && v < edges[i+1] {
				countsProd[i]++
				break
			}
		}
	}

	psi := 0.0
	for i := 0; i < buckets; i++ {
		pr := float64(countsRef[i]) / float64(len(ref))
		pp := float64(countsProd[i]) / float64(len(prod))
		// Avoid divide-by-zero & log(0)
		if pr == 0 {
			pr = 1e-6
		}
		if pp == 0 {
			pp = 1e-6
		}
		psi += (pr - pp) * math.Log(pr/pp)
	}
	return psi, psi > threshold, nil
}

// metricFactory returns a DriftMetricStrategy according to name.
func metricFactory(name string) (DriftMetricStrategy, error) {
	switch name {
	case "", "ks":
		return ksMetric{}, nil
	case "psi":
		return psiMetric{Buckets: 10}, nil
	default:
		return nil, fmt.Errorf("unknown drift metric: %s", name)
	}
}

// -------------- //
// gRPC Transport //
// -------------- //

// TrainingServiceClient is a minimal interface for queuing re-training.
type TrainingServiceClient interface {
	TriggerRetrain(ctx context.Context, in *TriggerRetrainRequest, opts ...grpc.CallOption) (*TriggerRetrainResponse, error)
}

// TriggerRetrainRequest is a stripped-down gRPC request payload.
type TriggerRetrainRequest struct {
	ModelID string `json:"model_id"`
	Reason  string `json:"reason"`
	Metric  string `json:"metric"`
	Value   float64 `json:"value"`
}

// TriggerRetrainResponse placeholder.
type TriggerRetrainResponse struct {
	Queued bool `json:"queued"`
}

// ------------- //
// DriftDetector //
// ------------- //

// DriftDetector is an observer that monitors inference events for drift.
type DriftDetector struct {
	cfg          Config
	metric       DriftMetricStrategy
	js           nats.JetStreamContext
	conn         *nats.Conn
	subscription *nats.Subscription

	productionBuf []float64
	bufMu         sync.Mutex

	grpcConn *grpc.ClientConn
	trainSvc TrainingServiceClient

	ctx        context.Context
	cancelFunc context.CancelFunc
	wg         sync.WaitGroup
}

// NewDriftDetector constructs and prepares (not yet started).
func NewDriftDetector(cfg Config) (*DriftDetector, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	strategy, err := metricFactory(cfg.Metric)
	if err != nil {
		return nil, err
	}

	// Connect to NATS
	nc, err := nats.Connect(cfg.NATSUrl, nats.Name("EchoPulse.DriftDetector"))
	if err != nil {
		return nil, fmt.Errorf("connect nats: %w", err)
	}

	js, err := nc.JetStream()
	if err != nil {
		return nil, fmt.Errorf("jetstream context: %w", err)
	}

	// gRPC connection
	gConn, err := grpc.Dial(cfg.TrainingEndpoint, grpc.WithInsecure(), grpc.WithBlock())
	if err != nil {
		_ = nc.Drain()
		return nil, fmt.Errorf("dial training service: %w", err)
	}

	detector := &DriftDetector{
		cfg:    cfg,
		metric: strategy,
		js:     js,
		conn:   nc,

		grpcConn: gConn,
		trainSvc: NewTrainingServiceClientStub(gConn),

		productionBuf: make([]float64, 0, cfg.MinSamples*2),
	}
	detector.ctx, detector.cancelFunc = context.WithCancel(context.Background())
	return detector, nil
}

// Start begins consuming inference stream and evaluating drift.
func (d *DriftDetector) Start() error {
	if d.subscription != nil {
		return errors.New("drift detector already started")
	}

	sub, err := d.js.Subscribe(d.cfg.NATSSubjectProd, d.handleMsg, nats.Durable(fmt.Sprintf("drift-%s", d.cfg.ModelID)))
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	d.subscription = sub

	// Periodic drift evaluator
	d.wg.Add(1)
	go func() {
		defer d.wg.Done()
		ticker := time.NewTicker(d.cfg.CheckInterval)
		defer ticker.Stop()

		for {
			select {
			case <-ticker.C:
				d.evaluate()
			case <-d.ctx.Done():
				return
			}
		}
	}()

	return nil
}

// Stop drains subscriptions and shuts down.
func (d *DriftDetector) Stop(ctx context.Context) error {
	d.cancelFunc()
	// Stop NATS subscription.
	if d.subscription != nil {
		_ = d.subscription.Drain()
	}
	// Wait for goroutines.
	done := make(chan struct{})
	go func() {
		d.wg.Wait()
		close(done)
	}()
	select {
	case <-done:
	case <-ctx.Done():
		return ctx.Err()
	}

	_ = d.conn.Drain()
	_ = d.grpcConn.Close()
	return nil
}

// handleMsg processes a single inference event from JetStream.
func (d *DriftDetector) handleMsg(m *nats.Msg) {
	var ev InferenceEvent
	if err := json.Unmarshal(m.Data, &ev); err != nil {
		_ = m.InProgress() // keep message
		fmt.Printf("json unmarshal inference event: %v\n", err)
		return
	}

	if ev.ModelID != d.cfg.ModelID {
		_ = m.Ack() // not our model
		return
	}

	d.bufMu.Lock()
	d.productionBuf = append(d.productionBuf, ev.Score)
	// Prevent unbounded growth.
	if len(d.productionBuf) > 10*d.cfg.MinSamples {
		d.productionBuf = d.productionBuf[len(d.productionBuf)-10*d.cfg.MinSamples:]
	}
	d.bufMu.Unlock()
	_ = m.Ack()
}

// evaluate computes drift on buffered production scores.
func (d *DriftDetector) evaluate() {
	d.bufMu.Lock()
	prodCopy := append([]float64(nil), d.productionBuf...)
	d.bufMu.Unlock()

	if len(prodCopy) < d.cfg.MinSamples {
		// Not enough samples yet.
		return
	}

	score, drift, err := d.metric.Compute(d.cfg.ReferenceDistribution, prodCopy, d.cfg.DriftThreshold)
	if err != nil {
		fmt.Printf("drift compute: %v\n", err)
		return
	}

	if !drift {
		return
	}

	fmt.Printf("Model %s drift detected by %s metric = %.4f\n", d.cfg.ModelID, d.metric.Name(), score)

	// 1. Publish drift alert event.
	alert := DriftAlertEvent{
		ModelID:     d.cfg.ModelID,
		Metric:      d.metric.Name(),
		Value:       score,
		Threshold:   d.cfg.DriftThreshold,
		EventTime:   time.Now().UTC(),
		SampleCount: len(prodCopy),
	}
	payload, _ := json.Marshal(alert)
	if _, err := d.js.Publish(d.cfg.NATSSubjectCtrl, payload); err != nil {
		fmt.Printf("publish drift alert: %v\n", err)
	}

	// 2. Notify training orchestrator.
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, err = d.trainSvc.TriggerRetrain(ctx, &TriggerRetrainRequest{
		ModelID: d.cfg.ModelID,
		Reason:  "statistical_drift",
		Metric:  d.metric.Name(),
		Value:   score,
	})
	if err != nil {
		fmt.Printf("training service TriggerRetrain error: %v\n", err)
	}
}

// ---------------------------- //
// TrainingServiceClient STUB   //
// ---------------------------- //
//
// In real deployment this interface would be generated from protobuf.
// For the sake of a self-contained example we provide a minimal stub.

type trainingServiceClientStub struct {
	conn *grpc.ClientConn
}

func NewTrainingServiceClientStub(conn *grpc.ClientConn) TrainingServiceClient {
	return &trainingServiceClientStub{conn: conn}
}

func (t *trainingServiceClientStub) TriggerRetrain(ctx context.Context, in *TriggerRetrainRequest, opts ...grpc.CallOption) (*TriggerRetrainResponse, error) {
	// Simulate RPC round-trip delay.
	select {
	case <-time.After(300 * time.Millisecond):
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	fmt.Printf("RPC TriggerRetrain queued for model=%s metric=%s value=%.4f\n", in.ModelID, in.Metric, in.Value)
	return &TriggerRetrainResponse{Queued: true}, nil
}
```