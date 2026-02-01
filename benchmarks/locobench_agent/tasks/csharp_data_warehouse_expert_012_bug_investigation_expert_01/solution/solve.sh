#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
{
  "explanation": "The root cause is a race condition in the `BufferManager` class defined in `src/utils.txt`. The `ParallelEventDispatcher` in `src/module_65.txt` uses `Parallel.ForEach` to serialize multiple events at once. Each parallel thread requests a reusable `MemoryStream` from the `BufferManager`. However, the `BufferManager` uses a standard `System.Collections.Generic.Queue<T>`, which is not thread-safe. During high load, multiple threads dequeue and enqueue streams concurrently, corrupting the internal state of the queue and causing threads to receive streams that are either still in use or have been improperly reset. This results in jumbled or truncated byte arrays being sent to the `DataRecordProcessor` in `src/module_23.txt`, which then correctly throws a `SerializationException`.",
  "file_with_bug": "src/utils.txt",
  "buggy_code": [
    "// Located in src/utils.txt inside the BufferManager class",
    "private static readonly Queue<MemoryStream> _streamPool = new Queue<MemoryStream>();",
    "",
    "public static MemoryStream GetStream() {",
    "    if (_streamPool.Count > 0) {",
    "        MemoryStream stream = _streamPool.Dequeue();",
    "        stream.SetLength(0); // Reset for reuse",
    "        return stream;",
    "    }",
    "    return new MemoryStream();",
    "}",
    "",
    "public static void ReturnStream(MemoryStream stream) {",
    "    _streamPool.Enqueue(stream);",
    "}"
  ],
  "file_to_fix": "src/utils.txt",
  "fixed_code": [
    "// Located in src/utils.txt inside the BufferManager class",
    "// SOLUTION 1: Using a lock for thread safety",
    "private static readonly Queue<MemoryStream> _streamPool = new Queue<MemoryStream>();",
    "private static readonly object _poolLock = new object();",
    "",
    "public static MemoryStream GetStream() {",
    "    lock (_poolLock) {",
    "        if (_streamPool.Count > 0) {",
    "            MemoryStream stream = _streamPool.Dequeue();",
    "            stream.SetLength(0); // Reset for reuse",
    "            return stream;",
    "        }",
    "    }",
    "    return new MemoryStream();",
    "}",
    "",
    "public static void ReturnStream(MemoryStream stream) {",
    "    lock (_poolLock) {",
    "        _streamPool.Enqueue(stream);",
    "    }",
    "}",
    "",
    "// SOLUTION 2 (Alternative/Better): Using a thread-safe collection",
    "// Replace the Queue<T> and lock with a ConcurrentQueue<T>",
    "private static readonly ConcurrentQueue<MemoryStream> _streamPool = new ConcurrentQueue<MemoryStream>();",
    "",
    "public static MemoryStream GetStream() {",
    "    if (_streamPool.TryDequeue(out MemoryStream stream)) {",
    "        stream.SetLength(0); // Reset for reuse",
    "        return stream;",
    "    }",
    "    return new MemoryStream();",
    "}",
    "",
    "public static void ReturnStream(MemoryStream stream) {",
    "    _streamPool.Enqueue(stream);",
    "}"
  ]
}
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
