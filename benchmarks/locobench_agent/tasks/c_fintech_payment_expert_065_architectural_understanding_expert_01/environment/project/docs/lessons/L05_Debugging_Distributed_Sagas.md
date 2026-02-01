```markdown
<!--
│ EduPay Ledger Academy
│ Lesson L05 – Debugging Distributed Sagas
│ --------------------------------------------------------
│ Repository Path : docs/lessons/L05_Debugging_Distributed_Sagas.md
│ Audience        : Advanced C / Systems-Programming students
│ Prerequisites   : Lesson L04 (Implementing the Saga Pattern)
│                   Familiarity with:
│                     • POSIX threads / IPC
│                     • Event Sourcing & CQRS
│                     • Basic GDB workflow
│ Learning Goals  :
│   1. Trace and repair an inconsistent Saga execution
│   2. Correlate events across micro-processes with a
│      shared audit trail
│   3. Use GDB, perf, and strace to pinpoint
│      concurrency and I/O issues in a payment workflow
│ --------------------------------------------------------
-->

# Lesson L05 – Debugging Distributed Sagas

`“Production debugging is a contact sport.”`  
— Every FinTech SRE, ever

In this lab you will **break and then repair** a tuition-payment Saga that spans three separate bounded contexts:

| Context           | Micro-Service Executable | Primary Concern         |
|-------------------|--------------------------|-------------------------|
| Admissions        | `bin/admissions_svc`     | Seat reservation        |
| Bursar            | `bin/bursar_svc`         | Ledger + invoicing      |
| Financial-Aid     | `bin/finaid_svc`         | Grants & scholarships   |

You will attach a debugger to *all three* processes, correlate a single transaction by
`correlation_id`, and uncover an **idempotency bug** that leaves the ledger in an
inconsistent state.

---

## 1. Quick Start: Building the Lab Harness

```bash
$ make saga-lab            # builds admission_svc, bursar_svc, finaid_svc, test_driver
$ ./bin/test_driver        # runs a series of happy-path integration tests
$ ./bin/test_driver --break # injects a failure at saga step #2
```

The `--break` flag forces the Bursar service to crash in the middle of its **credit-memo** step.
Your responsibility is to understand *why* the automatic rollback did not fully compensate
the first step executed in Admissions.

---

## 2. Code Walk-Through

Below is an **abridged version** of the Saga coordinator that ships with EduPay
(`src/saga/saga_coordinator.c`). Pay special attention to the
`dispatch_step()` implementation and the `SAGA_RETRY_MAX` constant.

```c
/*********************************************************************
 *  EduPay Ledger Academy — Saga Coordinator (excerpt)
 *********************************************************************/

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
#include "domain/errors.h"
#include "infra/msg_bus.h"
#include "infra/logger.h"
#include "saga/saga.h"
#include "saga/tracer.h"

#define SAGA_RETRY_MAX 3

static saga_status_t dispatch_step(const saga_t       *saga,
                                   const saga_step_t  *step,
                                   saga_ctx_t         *ctx)
{
    tracer_begin(step->name, ctx->correlation_id);

    for (uint8_t attempt = 0; attempt < SAGA_RETRY_MAX; ++attempt) {
        saga_status_t rc = step->action(ctx);

        if (rc == SAGA_OK) {
            tracer_success(step->name, ctx->correlation_id);
            return SAGA_OK;
        }

        LOG_WARN("[saga] step='%s' attempt=%u rc=%s", 
                 step->name, attempt, saga_status_str(rc));

        if (rc == SAGA_TRANSIENT && attempt + 1 < SAGA_RETRY_MAX) {
            /* Exponential backoff */
            usleep( (1 << attempt) * 1000 );
            continue;
        }

        tracer_failure(step->name, ctx->correlation_id, rc);
        return rc;           /* <- Payload: let caller start compensation */
    }

    tracer_failure(step->name, ctx->correlation_id, SAGA_ERR_MAX_RETRY);
    return SAGA_ERR_MAX_RETRY;
}
```

### 2.1 Hidden Bug

Look again at the `tracer_failure()` call:  
Notice that **no error code** is propagated to the tracer when we bail out due
to `SAGA_ERR_MAX_RETRY`. This will make root-cause analysis painful because the
audit trail will have `null` for `error_code` on the last attempt.  
We will fix this as part of the exercise.

---

## 3. Reproduce the Failure

Run the broken transaction inside `tmux` panes so you can attach GDB to each
service:

```bash
$ tmux new-session -d -s saga-debug './bin/admissions_svc'
$ tmux split-window -v './bin/bursar_svc --simulate-crash'
$ tmux split-window -v './bin/finaid_svc'
$ tmux split-window -v './bin/test_driver --break'
$ tmux attach-session -t saga-debug
```

`bin/test_driver` will block waiting for a *42-character* correlation ID
(ASCII‐encoded ULID). Copy that value; you’ll need it for queries later.

---

## 4. Multi-Process Debugging with GDB

1. From a new terminal, locate each PID:

   ```bash
   $ pgrep -f admissions_svc
   14673
   $ pgrep -f bursar_svc
   14692
   ```

2. Attach:

   ```bash
   $ gdb -p 14673
   (gdb) break saga_coordinator.c:dispatch_step if ctx->correlation_id == 0x4224...
   (gdb) c
   ```

3. When Bursar crashes you should see GDB drop into the **compensation flow**
   of Admissions:

   ```gdb
   (gdb) bt
   #0  dispatch_step (...)
   #1  execute_rollback (...)
   #2  run_saga        (...)
   ```

4. Inspect the **compensation ledger**:

   ```gdb
   (gdb) print ctx->compensation_stack
   ```

You will notice that step #1 shows `COMP_SUCCESS=false`, even though Admissions
reported `"Seat released"` in its logs. The delta between the in-memory stack
and the audit projection is exactly the bug we’re hunting.

---

## 5. Exercise — Fix the Root Cause

The issue is two-fold:

1. `tracer_failure()` is called without an error code during a *max-retry* exit.  
2. Admissions’ compensation callback returns a non-zero error but the
   coordinator ignores the return value when unwinding the stack.

### 5.1 Patch #1 — Proper Error Propagation

Edit `dispatch_step()`:

```diff
-    tracer_failure(step->name, ctx->correlation_id, SAGA_ERR_MAX_RETRY);
+    tracer_failure(step->name, ctx->correlation_id, rc);
```

### 5.2 Patch #2 — Handle Compensation Failures

`execute_rollback()` currently short-circuits on the *first* compensation
failure but does **not log** it. Add a tracer call and bubble up the failure:

```c
static saga_status_t execute_rollback(saga_ctx_t *ctx)
{
    while (!stack_is_empty(&ctx->compensation_stack)) {
        saga_step_t *step = stack_pop(&ctx->compensation_stack);
        saga_status_t rc  = step->compensate(ctx);

        if (rc != SAGA_OK) {
            tracer_comp_failure(step->name, ctx->correlation_id, rc);
            return rc;          /* escalate! */
        }
    }
    return SAGA_OK;
}
```

### 5.3 Re-Run Tests

```bash
$ make clean && make saga-lab
$ ./bin/test_driver --break
```

All three services should now report **“COMPENSATION COMPLETE”** and the audit
projection (`port 8088 /_dashboards?tx_id=<id>`) will show a consistent ledger.

---

## 6. Performance “Side Quest”

While you are in GDB, try `perf top` and `strace -ff -p <pid>` on the Bursar
process. Why is `fsync()` dominating syscall time?  
Hint: The ledger writes **every** compensation event synchronously.  
Explore `FADVISE_DONTNEED` or batch writes with *O_RDONLY|O_DIRECT*.

---

## 7. Deliverables

1. A Git branch named **`fix/lesson05-saga-compensation`**
2. A merge request that…
   • Links to this lesson  
   • Includes unit-tests in `tests/test_saga_compensation.c`  
   • Tags at least one reviewer from your T.A. group

Happy hunting! 🐛💸

---

## Appendix A — Minimal Repro Snippet

Use the following single-file example if you want a
self-contained repro without spinning up the full stack:

```c
/*********************************************************************
 *  compile:  gcc -pthread -O2 saga_repro.c -o saga_repro
 *********************************************************************/

#include <stdio.h>
#include <unistd.h>
#include "saga.h"

static saga_status_t ok(saga_ctx_t *ctx) {
    (void)ctx;
    puts("ok!");
    return SAGA_OK;
}

static saga_status_t intermittent(saga_ctx_t *ctx) {
    static int counter = 0;
    (void)ctx;
    return (++counter % 2) ? SAGA_TRANSIENT : SAGA_OK;
}

static saga_status_t fail_comp(saga_ctx_t *ctx) {
    (void)ctx;
    puts("rollback failed!");
    return SAGA_ERR_COMPENSATION;
}

int main(void)
{
    saga_step_t steps[] = {
        {"step-1", intermittent, fail_comp},
        {"step-2", ok,           ok},
    };

    saga_t saga = {
        .name  = "demo-saga",
        .steps = steps,
        .num_steps = sizeof(steps)/sizeof(steps[0])
    };

    saga_ctx_t ctx = {
        .correlation_id = 0xdeadbeef
    };

    saga_status_t rc = run_saga(&saga, &ctx);
    printf("saga finished with rc=%s\n", saga_status_str(rc));
    return (rc == SAGA_OK) ? 0 : 1;
}
```

Compile, run under GDB, set a breakpoint at `execute_rollback()`, and watch the
compensation failure bubble up.

---

## Appendix B — GDB Cheatsheet

| Command                      | Purpose                                   |
|------------------------------|-------------------------------------------|
| `set follow-fork-mode child` | Attach to forked micro-service processes  |
| `info sharedlibrary`         | Ensure symbols from `libsaga.so` are loaded |
| `catch syscall ioctl`        | Break on suspicious `ioctl` calls         |
| `thread apply all bt`        | Get backtrace for every running thread    |
| `dir src/`                   | Add source path when debugging unit tests |

End of Lesson L05
```