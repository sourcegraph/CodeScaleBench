package utils

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"math/rand"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// NOTE: Every function in this file is intentionally generic and dependency–
// free (beyond the std-lib) so that callers throughout EchoPulse can import
// the utilities without causing heavy build-time graph bloat.
//
// The helpers here focus on three cross-cutting concerns that appear in almost
// every micro-service:
//
//   1. Resiliency (retry / back-off / deadline)
//   2. Environment configuration parsing
//   3. Graceful shutdown orchestration
//
// Any functionality that starts to pull in 3rd-party libraries (e.g. Prometheus
// metrics, OpenTelemetry tracing, Kafka clients) lives in feature-specific
// helper packages elsewhere in the repository.

// -----------------------------------------------------------------------------
// Back-off / Retry Helpers
// -----------------------------------------------------------------------------

// ErrRetryExhausted is returned by Retry when the supplied operation never
// succeeded within the given retry budget.
var ErrRetryExhausted = errors.New("retry budget exhausted")

// Backoff defines the behaviour of a back-off strategy.
type Backoff interface {
	// NextDelay returns the next delay and a boolean that becomes false once the
	// retry budget is exhausted.
	NextDelay() (time.Duration, bool)
	// Reset brings the strategy back to its initial attempt.
	Reset()
}

// ExponentialBackoff implements Backoff with full-jitter, as recommended by
// AWS Architecture blog (and others) to smooth collision of concurrent retries.
type ExponentialBackoff struct {
	Initial     time.Duration // starting delay (e.g. 100 * time.Millisecond)
	Max         time.Duration // maximum delay (e.g. 30 * time.Second)
	Multiplier  float64       // normally 2
	Jitter      float64       // ∈ [0,1] where 0 disables jitter
	MaxAttempts int           // 0 or negative == unlimited

	attempt int
	rng     *rand.Rand
}

// NewExponentialBackoff returns a configured ExponentialBackoff with sane
// defaults if the caller passes zero-values.
func NewExponentialBackoff(init, max time.Duration, mult, jitter float64, maxAttempts int) *ExponentialBackoff {
	if init <= 0 {
		init = 100 * time.Millisecond
	}
	if max <= 0 {
		max = 30 * time.Second
	}
	if mult <= 1 {
		mult = 2
	}
	if jitter < 0 || jitter > 1 {
		jitter = 0.4
	}
	src := rand.NewSource(time.Now().UnixNano())
	return &ExponentialBackoff{
		Initial:     init,
		Max:         max,
		Multiplier:  mult,
		Jitter:      jitter,
		MaxAttempts: maxAttempts,
		rng:         rand.New(src),
	}
}

// NextDelay computes the next back-off delay using FullJitter strategy:
//   sleep = random_between(0, base * multiplier^attempt)
func (b *ExponentialBackoff) NextDelay() (time.Duration, bool) {
	if b.MaxAttempts > 0 && b.attempt >= b.MaxAttempts {
		return 0, false
	}
	exp := float64(b.Initial) * math.Pow(b.Multiplier, float64(b.attempt))
	b.attempt++

	if exp > float64(b.Max) {
		exp = float64(b.Max)
	}
	sleep := time.Duration(exp)
	if b.Jitter > 0 {
		sleep = time.Duration(b.rng.Float64() * b.Jitter * exp)
	}
	return sleep, true
}

// Reset implements Backoff.
func (b *ExponentialBackoff) Reset() { b.attempt = 0 }

// Retry calls fn until it succeeds (returns nil) or the Backoff budget is
// exhausted or ctx is canceled. The final error (fn-error or ctx-error or
// ErrRetryExhausted) is returned.
func Retry(ctx context.Context, b Backoff, fn func() error) error {
	defer b.Reset()

	for {
		err := fn()
		if err == nil {
			return nil
		}

		next, ok := b.NextDelay()
		if !ok {
			return fmt.Errorf("%w: %v", ErrRetryExhausted, err)
		}

		if delayErr := sleepContext(ctx, next); delayErr != nil {
			return delayErr
		}
	}
}

// sleepContext sleeps the given duration or until ctx.Done().
func sleepContext(ctx context.Context, d time.Duration) error {
	timer := time.NewTimer(d)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

// -----------------------------------------------------------------------------
// Environment / Config Helpers
// -----------------------------------------------------------------------------

// GetEnv fetches an environment variable and falls back to defaultVal when unset.
func GetEnv(key, defaultVal string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return defaultVal
}

// MustGetenv behaves like GetEnv but panics when the key is missing.
func MustGetenv(key string) string {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		panic("required environment variable missing: " + key)
	}
	return v
}

// EnvDuration parses key as time.Duration. When unset or malformed it returns
// defaultVal.
func EnvDuration(key string, defaultVal time.Duration) time.Duration {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return defaultVal
	}
	d, err := time.ParseDuration(raw)
	if err != nil {
		return defaultVal
	}
	return d
}

// EnvBool parses key as bool. Accepts 1/t/T/true/TRUE/True and 0/f/false...
func EnvBool(key string, defaultVal bool) bool {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return defaultVal
	}
	v, err := strconv.ParseBool(raw)
	if err != nil {
		return defaultVal
	}
	return v
}

// EnvInt parses key as integer, returning defaultVal if missing or invalid.
func EnvInt(key string, defaultVal int) int {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return defaultVal
	}
	v, err := strconv.Atoi(raw)
	if err != nil {
		return defaultVal
	}
	return v
}

// JSONPretty renders v as pretty-printed JSON for debug logging. If marshalling
// fails, the returned string contains the error message.
func JSONPretty(v any) string {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return fmt.Sprintf("json-marshal-error: %v", err)
	}
	return string(data)
}

// KafkaTopic composes a canonical topic name using convention:
//
//   <env>.<team>.<domain>.<name>[.v<version>]
//
// The helpers centralise topic naming to keep dashboards / ACL-rules aligned.
func KafkaTopic(env, team, domain, name string, version int) string {
	segments := []string{
		sanitiseTopicToken(env),
		sanitiseTopicToken(team),
		sanitiseTopicToken(domain),
		sanitiseTopicToken(name),
	}
	if version > 0 {
		segments = append(segments, fmt.Sprintf("v%d", version))
	}
	return strings.Join(segments, ".")
}

func sanitiseTopicToken(t string) string {
	return strings.ToLower(strings.ReplaceAll(strings.TrimSpace(t), ".", "_"))
}

// -----------------------------------------------------------------------------
// Graceful Shutdown Helpers
// -----------------------------------------------------------------------------

// TrapSignals returns a context that is cancelled when the process receives any
// of the provided signals (defaults to SIGINT & SIGTERM when none passed).
//
// Typical usage:
//
//	ctx, stop := utils.TrapSignals(context.Background())
//	defer stop() // ensure resources are freed when main() exits
func TrapSignals(parent context.Context, sigs ...os.Signal) (ctx context.Context, stop context.CancelFunc) {
	if len(sigs) == 0 {
		sigs = []os.Signal{syscall.SIGINT, syscall.SIGTERM}
	}

	ctx, cancel := context.WithCancel(parent)
	ch := make(chan os.Signal, 1)
	signal.Notify(ch, sigs...)

	go func() {
		select {
		case <-ctx.Done():
			// parent cancelled; cleanup.
		case <-ch:
			cancel()
		}
		signal.Stop(ch)
		close(ch)
	}()

	return ctx, cancel
}

// WaitForShutdown wraps <-ctx.Done() with an optional onShutdown callback and
// a timeout force kill. It blocks until shutdown is complete.
func WaitForShutdown(ctx context.Context, onShutdown func(), timeout time.Duration) {
	<-ctx.Done()

	if onShutdown != nil {
		onShutdown()
	}

	// If caller supplied a timeout, create a watchdog goroutine that will exit
	// the process if we hang for too long during shutdown.
	if timeout > 0 {
		go func() {
			select {
			case <-time.After(timeout):
				_, _ = fmt.Fprintln(os.Stderr, "graceful shutdown timed out, forcing exit")
				os.Exit(1)
			case <-ctx.Done():
				// context already done; nothing to do
			}
		}()
	}
}

// -----------------------------------------------------------------------------
// Misc Helpers
// -----------------------------------------------------------------------------

// TimeoutContext returns a new context with the given timeout unless the parent
// already has a sooner deadline. This prevents accidentally extending the
// parent deadline.
func TimeoutContext(parent context.Context, d time.Duration) (context.Context, context.CancelFunc) {
	if dl, ok := parent.Deadline(); ok {
		// if parent deadline is sooner, honour that rather than extending
		if time.Until(dl) < d {
			return context.WithCancel(parent)
		}
	}
	return context.WithTimeout(parent, d)
}

// NowUTC is a convenience wrapper for time.Now().UTC().
func NowUTC() time.Time {
	return time.Now().UTC()
}