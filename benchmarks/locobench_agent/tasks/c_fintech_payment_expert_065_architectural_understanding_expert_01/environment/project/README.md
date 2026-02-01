```markdown
# EduPay Ledger Academy  
*A production-grade, clean-architecture fintech platform written in C.*

---

<img src="https://raw.githubusercontent.com/edupay/ledger-academy/main/docs/assets/edupay_logo.svg" alt="EduPay Ledger Academy" width="240" />

EduPay Ledger Academy is a **reference implementation** of enterprise-level payment rails tailored for higher-education.  
Unlike toy examples, the codebase powers real tuition, stipend, and scholarship flows **while doubling as a living textbook** for computer-science curricula.

* Clean Architecture (Robert C. Martin) – every policy is isolated from frameworks.  
* Domain-Driven Design – bounded contexts for Admissions, Bursar, Financial-Aid, and Continuing-Education.  
* Event Sourcing + CQRS – immutable audit trail and low-latency read models.  
* Saga Orchestration – optional chaos-engineering labs for distributed rollbacks.  
* PCI-DSS / FERPA / PSD2 compliance patterns baked-in.

> “We don’t hide complexity from students—we instrument it.”  
> — *Academic Advisory Board, 2024*

---

## Repository Layout

```
EduPayLedgerAcademy/
├─ cmd/                     # CLI entrypoints and service launchers
│  ├─ ep_ledgerd/           # Monolithic daemon (default boot path)
│  └─ ep_saga_simulator/    # Demonstration CLI for saga experiments
├─ core/                    # Enterprise business rules (no I/O!)
│  ├─ admissions/
│  ├─ bursar/
│  ├─ financial_aid/
│  └─ continuing_education/
├─ drivers/                 # Secondary adapters (databases, brokers)
│  ├─ postgres/
│  ├─ rabbitmq/
│  └─ redis_cache/
├─ interfaces/              # Primary adapters (HTTP, GRPC, CLI, UI)
├─ docs/                    # Diagrams, course material, slide decks
└─ tests/                   # End-to-end, property, & fuzz tests
```

The **core** folder contains *pure C* (C17) with zero external dependencies; all I/O is pushed outward to **drivers** to maintain testability and pedagogical clarity.

---

## Quick Start

Prerequisites:

* gcc / clang with C17 support  
* CMake ≥ 3.15  
* GNU Make (optional)  
* PostgreSQL 14, RabbitMQ 3.x (when running full stack)

```bash
git clone https://github.com/edupay/ledger-academy.git
cd ledger-academy
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target all
./build/bin/ep_ledgerd --config etc/ledgerd.sample.toml
```

Docker-compose is available for turnkey experimentation:

```bash
docker compose -f infra/compose.dev.yml up --build
```

---

## Hello, World! Payment

A minimal illustration of **command → domain → event** inside EduPay:

```c
/* src/examples/tuition_payment.c */

#include "admissions/enroll_cmd.h"
#include "bursar/invoice_svc.h"
#include "eventbus/memory_bus.h"

int main(void)
{
    ep_event_bus_t *bus = ep_memory_bus_new();
    ep_invoice_service_t *svc = ep_invoice_service_new(bus);

    const ep_enroll_cmd_t cmd = {
        .student_id = "S12345",
        .program_id = "CS-BS",
        .term = "2024FALL",
        .tuition_fee_cents = 1250000,   /* $12,500.00 */
        .currency = EP_CUR_USD
    };

    if (ep_invoice_service_handle_enroll(svc, &cmd) != EP_OK) {
        fprintf(stderr, "💥  Enrollment rejected: %s\n", ep_last_error());
        return EXIT_FAILURE;
    }

    puts("✅  Invoice emitted; event stored in audit trail.");
    ep_invoice_service_free(svc);
    ep_memory_bus_free(bus);
}
```

```bash
gcc -std=c17 tuition_payment.c -I../include -L../lib -lep_core -o tuition_payment
./tuition_payment
```

Output:

```
✅  Invoice emitted; event stored in audit trail.
```

---

## Pedagogical Hooks

| Module | In-Code Mentoring |
| ------ | ----------------- |
| `core/fraud_detection` | Inline heuristics annotated with links to academic papers. |
| `core/regulatory` | FERPA-aware pseudonymisation examples with unit tests. |
| `tests/fuzz` | AFL++ harnesses for students learning security testing. |
| `cmd/ep_saga_simulator` | Interactive CLI that severs message brokers mid-flight to demonstrate compensating transactions. |

Activate the saga demo:

```bash
./build/bin/ep_saga_simulator --scenario bursar_refund_outage
```

---

## Clean Architecture Overview

```
          ┌────────────────────────────────┐
          │        Interface Layer        │
┌─HTTP────┤  (Controllers, gRPC, CLI)     │
│         └──────────────▲────────────────┘
│                        │
│         ┌──────────────┴────────────────┐
│         │            Use-Case           │
│         │   (Application Services)      │
│         └──────────────▲────────────────┘
│                        │
│         ┌──────────────┴────────────────┐
│         │      Enterprise Business      │
│         │         Rules (Core)          │
│         └──────────────▲────────────────┘
│                        │
│         ┌──────────────┴────────────────┐
└─DB──────┤  Frameworks & Drivers Layer   │
  MQ──────┤  (Postgres, RabbitMQ, Redis)  │
          └───────────────────────────────┘
```

The **dependency rule** is enforced with compiler firewalls and automated CI checks.

---

## Build Matrix

| Target              | CI Profile            | Sanitizers       |
| ------------------- | --------------------- | ---------------- |
| `x86_64-linux-gnu`  | Ubuntu 22.04 (gcc)    | ASan, UBSan      |
| `arm64-darwin`      | macOS 14 (clang)      | —                |
| `rpi-armhf`         | Raspbian (cross-gcc)  | —                |
| `wasm32-wasi`       | WASI-SDK 20           | —                |

---

## Security Posture

EduPay embraces **Security-by-Design**:

* Secrets never live in code—`EP_SECRET_*` env-vars or HashiCorp Vault only.  
* Mandatory static analysis (clang-tidy, cppcheck) + OSS-Fuzz integration.  
* Strict compiler flags: `-fstack-protector-strong -fPIE -pie -D_FORTIFY_SOURCE=3`.  
* Cryptography via [liboqs](https://openquantumsafe.org/) (post-quantum ready).

---

## Testing

```bash
cmake --build build --target check      # unit + integration
ctest --output-on-failure

# Property-based fuzzing
make -C tests/fuzz run
```

Coverage reports (lcov) are uploaded to Codecov on every push.

---

## Course Integration

Professors: see `docs/curriculum/*.md` for semester outlines.  
Assignments map to git tags (`v2024s1-lab1`, `v2024s1-lab2`), enabling *git bisect*-based scavenger hunts.

---

## Contributing

1. Fork the repo and create a feature branch.  
2. Write unit tests + update docs.  
3. Run `make pre-commit` and ensure CI passes.  
4. Submit a PR following the **Conventional Commits** standard.

---

## License

EduPay Ledger Academy is dual-licensed:

* **AGPL-3.0** – free for academic & open-source use.  
* **Commercial license** – required for closed-source deployments. Contact <legal@edupay.com>.

---

## Citation

If you use EduPay Ledger Academy in research, please cite:

```
@software{edupay_2024,
  author       = {Cabrera, Ana and Kai, J.},
  title        = {{EduPay Ledger Academy}: Clean architecture fintech rails in C},
  month        = jan,
  year         = 2024,
  url          = {https://github.com/edupay/ledger-academy}
}
```

Happy hacking, and may your ledgers always balance! 🧮
```