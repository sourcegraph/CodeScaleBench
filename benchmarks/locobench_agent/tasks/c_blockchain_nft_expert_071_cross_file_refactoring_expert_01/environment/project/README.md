```markdown
# HoloCanvas  
_A Micro-Gallery Blockchain for Generative Artifacts_

``The distributed atelier where every micro-service is a brush-stroke.``  

---

## ➊ Project Synopsis
HoloCanvas is an expert-grade, C-centric blockchain–NFT stack enabling **live, collaborative generation of audiovisual artifacts**.  
Unlike traditional NFT platforms that merely tokenize static media, HoloCanvas **stores immutable creative _recipes_** on a Layer-2 roll-up while allowing the rendered output to evolve in response to on-chain / off-chain stimuli (bids, governance, sensor feeds, etc).

* **Language**: ISO C17 with optional C++20 extensions for tests  
* **Runtime**: `musl` / `glibc` + `posix_threads`  
* **Message-Bus**: Apache Kafka ↔  gRPC  
* **Persistence**: RocksDB (micro-ledgers) + PostgreSQL (metadata)  
* **Cryptography**: libsodium, secp256k1, BLAKE3, Ed25519, XChaCha20-Poly1305  
* **Smart-Contracts**: eWASM shards (compiled from C)  
* **CI/CD**: GitHub Actions → Containers → K8s (Helm)  

---

## ➋ Service Topology

```
                                       ┌───────────────┐
    Sensors/Oracles  ─────►   Muse     │ Oracle-Bridge │── external feeds
                                       └───────────────┘
                                                ▲
                                                │ gRPC
                                                ▼
  ┌──────────────┐    Kafka     ┌───────────────┐
  │ Mint-Factory │◄────────────►│ Gallery-Gate  │─► REST / WebSocket
  └──────────────┘              └───────────────┘
         ▲                                │
         │ gRPC                           │ gRPC
         ▼                                ▼
  ┌──────────────┐              ┌────────────────┐
  │ Ledger-Core  │◄────────────►│ Governance-Hall│
  └──────────────┘    Events    └────────────────┘
         ▲
         │ gRPC
         ▼
  ┌──────────────┐
  │ DeFi-Garden  │
  └──────────────┘
```

*Each micro-service is delivered as a standalone container embedding a minimalistic C runtime, reducing attack surface while enabling predictable real-time performance.*

---

## ➌ Quick-Start (Dev Cluster)

Prerequisites  
```
gcc ≥ 11.2     (or clang ≥ 13)  
cmake ≥ 3.20  
python ≥ 3.8   # code-gen, glue scripts  
docker ≥ 24.0  # local micro-cluster
```

Clone & build everything (debug profile):
```bash
git clone --recurse-submodules https://github.com/<you>/HoloCanvas.git
cd HoloCanvas
./scripts/bootstrap.sh   # installs git hooks & pre-commit linters
cmake -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build -j$(nproc)
docker compose -f docker/docker-compose.dev.yml up --build
```

Minimal CLI sanity-check:
```bash
./build/bin/hc-wallet-cli keygen --output test.key
./build/bin/hc-mint-cli  mint \
   --shader examples/shaders/mandelbulb.hlsli \
   --audio  examples/audio/vaus_theme.flac \
   --author test.key
```

---

## ➍ Code Samples

### 4.1 Submit a Shader Fragment (Client Library)

```c
/**
 * Example: streaming a GLSL fragment to the Mint-Factory service.
 * This snippet intentionally omits detailed error logging for brevity.
 */
#include <hc/client.h>

static void publish_shader(const char *path)
{
    hc_client_ctx_t *ctx = hc_client_init("127.0.0.1:7050", /*timeout_ms=*/3000);
    if (!ctx) {
        fprintf(stderr, "ctx init failed\n");
        return;
    }

    hc_shader_spec_t spec  = {0};
    hc_file_t       *file  = hc_file_map(path, HC_FILE_RDONLY);
    if (!file) {
        fprintf(stderr, "map %s failed: %s\n", path, strerror(errno));
        goto cleanup;
    }

    spec.source      = hc_file_data(file);
    spec.length      = hc_file_size(file);
    spec.shader_lang = HC_SHADER_GLSL;
    spec.license     = "CC-BY-SA-4.0";
    spec.author_key  = hc_wallet_load_priv("test.key");

    hc_tx_receipt_t receipt = {0};
    if (hc_client_publish_shader(ctx, &spec, &receipt) != 0) {
        fprintf(stderr, "publish failed: %s\n", hc_strerror(errno));
    } else {
        printf("✓ Shader committed @ block %llu (tx %s)\n",
               (unsigned long long)receipt.block_height,
               receipt.tx_hash_hex);
    }

cleanup:
    hc_file_close(file);
    hc_client_free(ctx);
}
```

### 4.2 Implement a Custom “Muse” Plugin (Strategy Pattern)

```c
/**
 * Compile as a shared object; loaded at runtime by Muse-Daemon.
 *
 * Triggers an NFT color-palette evolution whenever the ETH price
 * crosses ±2 % in a 5-minute window (data from Oracle-Bridge).
 */
#include <hc/plugin.h>
#include <math.h>

typedef struct {
    double last_price;
} ctx_t;

static void *on_init(void)
{
    ctx_t *c = calloc(1, sizeof(ctx_t));
    c->last_price = NAN;
    return c;
}

static void  on_price_tick(void *user, double price, uint64_t ts_ms)
{
    ctx_t *c = (ctx_t *)user;
    if (isnan(c->last_price)) {
        c->last_price = price;
        return;
    }

    double delta = fabs(price - c->last_price) / c->last_price;
    if (delta >= 0.02) {
        hc_event_t ev = {
            .type               = HC_EVT_ART_MUTATE,
            .mutate.random_seed = ts_ms,
            .mutate.payload     = NULL
        };
        hc_emit(&ev);
        c->last_price = price;
    }
}

static void  on_cleanup(void *user) { free(user); }

HC_PLUGIN_EXPORT(hc_plugin_desc_t) HoloCanvas_Plugin = {
    .api_version  = HC_PLUGIN_API_VER,
    .name         = "eth-price-palette-twister",
    .on_init      = on_init,
    .on_price     = on_price_tick,
    .on_cleanup   = on_cleanup
};
```

---

## ➎ Repository Layout

```
HoloCanvas/
 ├─ cmake/                # cross-platform tool-chain files
 ├─ src/
 │   ├─ ledger/           # consensus & tx validation
 │   ├─ mint/             # factory pattern micro-service
 │   ├─ client/           # libholocanvas (SDK)
 │   └─ plugins/          # dynamic Muse strategies
 ├─ include/
 │   └─ hc/               # public headers
 ├─ docker/
 │   └─ *.yml             # dev & prod stacks
 ├─ schemas/              # protobuf, avro messages
 ├─ tests/                # criterion + gtest suites
 └─ examples/             # shaders, audio, recipes
```

---

## ➏ Contributing

1. Fork + feature branch (`feat/<issue>-<short-slug>`)  
2. `pre-commit run --all-files` (clang-format, cppcheck, SPDX headers)  
3. Add Criterion unit tests and, if relevant, integration tests (`docker-compose.test.yml`).  
4. Squash into logical commits, open PR.  

Security issues? E-mail `security@holocanvas.io` (PGP key in `/SECURITY.md`).

---

## ➐ License
HoloCanvas is dual-licensed under **GPL-3.0-or-later** ♥ **Commercial**.  
See [`/LICENSE.md`](LICENSE.md) for terms.

> _“Code is a paint-stroke; commit history is the canvas.”_
```