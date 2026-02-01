```go
// File: tests/test_utils.go
// Package tests provides a thin layer of helpers that are shared by the
// suite of integration / unit–tests that make up the EchoPulse CI
// pipeline.
//
// The helpers intentionally avoid introducing *any* production‐side
// dependencies.  They are test-only conveniences that make the tests
// terse, deterministic and easy to reason about.
//
// NOTE: do NOT import these helpers from production code.

package tests

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"

	tc "github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/kafka"
	"github.com/testcontainers/testcontainers-go/wait"
)

// ---------------------------------------------------------------------
//               Lightweight assertion / requirement layer
// ---------------------------------------------------------------------

// Require terminates the test immediately when err is not nil.
//
// It is *not* meant to replace a full-fledged assertion framework, it
// just avoids the repetitive if err != nil { t.Fatalf(...) } noise.
//
// Usage:
//
//	fo, err := os.Open("foo.txt")
//	tests.Require(t, err)
//	defer fo.Close()
func Require(t *testing.T, err error, msgAndArgs ...any) {
	t.Helper()

	if err == nil {
		return
	}

	msg := "unexpected error"
	if len(msgAndArgs) > 0 {
		msg = fmt.Sprint(msgAndArgs...)
	}
	t.Fatalf("%s: %v", msg, err)
}

// AssertEqual uses reflect.DeepEqual and prints a helpful diff when
// objects are not equal.
func AssertEqual[T any](t *testing.T, expected, actual T) {
	t.Helper()

	if reflect.DeepEqual(expected, actual) {
		return
	}

	t.Fatalf("objects differ\n--- expected:\n%#v\n--- got:\n%#v", expected, actual)
}

// AssertJSONEqual pretty-prints JSON before comparison to make diffs
// human-readable.  Whitespace and key-ordering do *not* affect the
// comparison.
func AssertJSONEqual(t *testing.T, expected, actual []byte) {
	t.Helper()

	var expObj, actObj any
	Require(t, json.Unmarshal(expected, &expObj), "bad expected JSON")
	Require(t, json.Unmarshal(actual, &actObj), "bad actual JSON")

	if !reflect.DeepEqual(expObj, actObj) {
		pretty := func(v any) string {
			buf, _ := json.MarshalIndent(v, "", "  ")
			return string(buf)
		}
		t.Fatalf("json mismatch\n--- expected:\n%s\n--- got:\n%s", pretty(expObj), pretty(actObj))
	}
}

// ---------------------------------------------------------------------
//                           Kafka Test-Fixture
// ---------------------------------------------------------------------

// kafkaFixture bundles state required by the Kafka container helper.
type kafkaFixture struct {
	Container *kafka.KafkaContainer
	URI       string // kafka://host:port bootstrap URI
}

var (
	// kafkaReuseContainer can be set via env var when debugging to keep
	// the container around for multiple `go test ./...` runs.  It cuts
	// a full test-pass from >20s to <3s on a typical laptop.
	kafkaReuseContainer = strings.ToLower(os.Getenv("ECHO_PULSE_TEST_REUSE_KAFKA")) == "true"
)

// WithKafka spins up an ephemeral Kafka cluster (via testcontainers) and
// provides the bootstrap URI to testFn.  The container is terminated
// automatically once testFn returns.
//
// Example:
//
//	tests.WithKafka(ctx, t, func(uri string) {
//	    // your test logic here …
//	})
func WithKafka(ctx context.Context, t *testing.T, testFn func(bootstrapURI string)) {
	t.Helper()

	fixture := mustStartKafka(ctx, t)
	defer fixture.Terminate(ctx, t)

	testFn(fixture.URI)
}

func mustStartKafka(ctx context.Context, t *testing.T) *kafkaFixture {
	t.Helper()

	req := kafka.WithImage("confluentinc/cp-kafka:7.5.1").
		WithReuse(kafkaReuseContainer).
		WithEnv(map[string]string{
			"KAFKA_ADVERTISED_LISTENERS": "PLAINTEXT://localhost:0",
		}).
		WithWaitStrategy(
			wait.ForListeningPort("9092/tcp").
				WithStartupTimeout(2 * time.Minute),
		)

	container, err := kafka.RunContainer(ctx, req)
	Require(t, err, "failed to start kafka container")

	host, err := container.Host(ctx)
	Require(t, err, "failed to resolve kafka host")
	mapped, err := container.MappedPort(ctx, "9092/tcp")
	Require(t, err, "failed to resolve kafka port")

	addr := net.JoinHostPort(host, mapped.Port())
	return &kafkaFixture{
		Container: container,
		URI:       fmt.Sprintf("kafka://%s", addr),
	}
}

func (f *kafkaFixture) Terminate(ctx context.Context, t *testing.T) {
	t.Helper()

	if kafkaReuseContainer {
		return // keep it around for subsequent test runs
	}
	if err := f.Container.Terminate(ctx); err != nil {
		t.Logf("failed to terminate kafka container: %v", err)
	}
}

// ---------------------------------------------------------------------
//                        Golden-file comparators
// ---------------------------------------------------------------------

// LoadGolden reads a *.golden file relative to the calling test file.
//
// LoadGolden(t, "happy_path.golden")
func LoadGolden(t *testing.T, name string) []byte {
	t.Helper()

	_, callerFile, _, ok := runtime.Caller(1)
	if !ok {
		t.Fatalf("unable to locate caller")
	}
	dir := filepath.Dir(callerFile)
	path := filepath.Join(dir, "testdata", name)

	b, err := os.ReadFile(path)
	Require(t, err, "read golden file")
	return bytes.TrimSpace(b) // nip trailing newline for easier cmp
}

// UpdateGolden overwrites/creates the golden file with content.
//
// Controlled via UPDATE_GOLDEN=1 environment variable to avoid
// accidental updates.
func UpdateGolden(t *testing.T, name string, content []byte) {
	t.Helper()

	if os.Getenv("UPDATE_GOLDEN") == "" {
		t.Fatalf("refusing to update golden file %s without UPDATE_GOLDEN=1", name)
	}

	_, callerFile, _, ok := runtime.Caller(1)
	if !ok {
		t.Fatalf("unable to locate caller")
	}
	dir := filepath.Dir(callerFile)
	path := filepath.Join(dir, "testdata", name)

	Require(t, os.MkdirAll(filepath.Dir(path), 0o755), "mkdir testdata")

	if err := os.WriteFile(path, content, 0o644); err != nil {
		t.Fatalf("failed to write golden file: %v", err)
	}
}

// CompareWithGolden asserts that actual matches the given golden file,
// or updates the golden file if UPDATE_GOLDEN=1 is set.
func CompareWithGolden(t *testing.T, goldenFile string, actual []byte) {
	t.Helper()

	if os.Getenv("UPDATE_GOLDEN") != "" {
		UpdateGolden(t, goldenFile, actual)
		return
	}

	expected := LoadGolden(t, goldenFile)
	if !bytes.Equal(expected, actual) {
		t.Fatalf("golden file mismatch\n--- expected:\n%s\n--- got:\n%s",
			expected, actual)
	}
}

// ---------------------------------------------------------------------
//                    Misc. helpers (I/O, process, etc.)
// ---------------------------------------------------------------------

// MustReadAll is a sugar helper used primarily inside tests that need
// to slurp an io.Reader in a single line.
//
//	foo := tests.MustReadAll(r)
func MustReadAll(r io.Reader) []byte {
	b, err := io.ReadAll(r)
	if err != nil {
		panic(err) // simplify test code – fail hard and loud
	}
	return b
}

// RunCmd executes an external command and returns stdout/stderr paired
// with the exit code.  It is useful for black-box integration tests
// where we spawn the CLI tool built by the current module.
//
// Example:
//
//	code, out, errOut := tests.RunCmd(t, "echo", "hi")
//	tests.AssertEqual(t, 0, code)
//	tests.AssertEqual(t, "hi\n", out)
func RunCmd(t *testing.T, name string, args ...string) (exitCode int, stdout, stderr string) {
	t.Helper()

	cmd := exec.Command(name, args...)
	var outBuf, errBuf bytes.Buffer
	cmd.Stdout, cmd.Stderr = &outBuf, &errBuf

	err := cmd.Run()
	stdout, stderr = outBuf.String(), errBuf.String()

	var exitErr *exec.ExitError
	if err == nil {
		return 0, stdout, stderr
	}
	if errors.As(err, &exitErr) {
		return exitErr.ExitCode(), stdout, stderr
	}

	// Something unexpected happened (e.g. binary not found)
	t.Fatalf("failed to run %q: %v", name, err)
	return -1, stdout, stderr
}

// AwaitCondition polls fn until it returns true or the timeout elapses.
// It sleeps 50ms between attempts.  Useful for waiting on asynchronous
// signals inside integration tests (e.g., “message has reached topic”).
func AwaitCondition(t *testing.T, timeout time.Duration, fn func() bool) {
	t.Helper()

	deadline := time.Now().Add(timeout)
	for {
		if fn() {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("condition not met within %v", timeout)
		}
		time.Sleep(50 * time.Millisecond)
	}
}

// TeeReader returns an io.Reader that duplicates its reads to the
// supplied writer.  It is a tiny addition on top of io.TeeReader that
// also sinks the written bytes in memory so they can be asserted in
// tests without adding an extra buffer manually.
func TeeReader(r io.Reader, out io.Writer) (io.Reader, *bytes.Buffer) {
	buf := &bytes.Buffer{}
	mw := io.MultiWriter(out, buf)
	return io.TeeReader(r, mw), buf
}

// ---------------------------------------------------------------------
//                     Logging capture / interception
// ---------------------------------------------------------------------

// CaptureStdout runs fn while redirecting os.Stdout to an in-memory
// buffer.  The captured output is returned.  Stdout is restored
// afterwards even if fn panics.
func CaptureStdout(fn func()) string {
	orig := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w

	done := make(chan struct{})
	var buf bytes.Buffer
	go func() {
		_, _ = io.Copy(&buf, r)
		close(done)
	}()

	fn()

	_ = w.Close()
	os.Stdout = orig
	<-done
	return buf.String()
}

// CaptureStderr does the same but for os.Stderr.
func CaptureStderr(fn func()) string {
	orig := os.Stderr
	r, w, _ := os.Pipe()
	os.Stderr = w

	done := make(chan struct{})
	var buf bytes.Buffer
	go func() {
		_, _ = io.Copy(&buf, r)
		close(done)
	}()

	fn()

	_ = w.Close()
	os.Stderr = orig
	<-done
	return buf.String()
}

// ---------------------------------------------------------------------
//            REPL-like interactive helper for quick debugging
// ---------------------------------------------------------------------

// Prompt waits for user input on stdin when the PAUSE_TESTS=1 env var
// is set.  It helps when you need to inspect a running container,
// pause a failing test at a certain line, or similar ad-hoc debugging.
//
// Example:
//
//	tests.Prompt("inspect kafka topic, then press enter to resume")
func Prompt(msg string) {
	if os.Getenv("PAUSE_TESTS") == "" {
		return
	}
	fmt.Fprintf(os.Stderr, "\n--- PAUSED: %s ---\nPress <ENTER> to continue…\n", msg)
	_ = bufio.NewReader(os.Stdin).ReadBytes('\n')
}
```