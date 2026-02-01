```markdown
# CardioInsight 360 — Installation Guide  
Unified Healthcare Analytics Engine  

> File: `cardio_insight_360/docs/guides/installation_guide.md`  
> Version: 4.2.1 (compatible with C++17 toolchains)  
> Last Updated: 2024-06-09  

---

## 1. Audience & Scope  
This guide targets clinical-engineering teams, DevOps personnel, and research
IT staff responsible for installing, validating, and maintaining
CardioInsight 360 (CI-360) in production, staging, or research environments.  
The document covers:  

* Supported operating systems & hardware  
* Binary vs. source installation workflows  
* Dependency management & compiler requirements  
* Minimum-security hardening steps (HIPAA & IEC 62304 alignment)  
* Post-install validation suite  
* Upgrade / rollback procedure  

---

## 2. System Requirements  

| Component            | Minimum                               | Recommended                           |
|----------------------|---------------------------------------|---------------------------------------|
| CPU                  | 4 × 64-bit cores (AVX2)               | 16 × 64-bit cores (AVX-512/TBB)        |
| RAM                  | 16 GB                                 | 64 GB                                  |
| Disk                 | 100 GB SSD                            | ≥1 TB NVMe                             |
| OS (x86-64)          | Ubuntu 22.04 LTS / RHEL 9 / Windows 11| Ubuntu 22.04 LTS / RHEL 9              |
| Compiler             | GCC 11+ / Clang 15+ / MSVC 19.35+     | Same, with LTO & PGO enabled           |
| Kafka Cluster        | 3 × brokers @ v3.6+                   | Same                                   |
| CMake                | 3.26+                                 | 3.27+                                  |
| Networking           | 1 GbE                                 | ≥10 GbE                                |
| GPU (optional)       | CUDA-enabled for deep-learning add-ons | NVIDIA A6000                           |

> NOTE - CI-360 requires a CPU that supports AVX2 or higher; execution on
> legacy hardware is blocked at runtime.

---

## 3. Quick Start (Pre-built Binary)  

The CI-360 binary is fully statically linked (except `libc` and kernel
syscalls) to simplify change control. Packages are signed with the hospital’s
internal GPG key.

```bash
# 1. Add the internal repository
$ curl -fsSL https://repo.myhospital.net/ci360/gpg.pub | sudo gpg --dearmor -o /usr/share/keyrings/ci360.gpg
$ echo "deb [arch=amd64 signed-by=/usr/share/keyrings/ci360.gpg] \
  https://repo.myhospital.net/ci360/ubuntu jammy main" | \
  sudo tee /etc/apt/sources.list.d/ci360.list

# 2. Install
$ sudo apt update && sudo apt install cardioinsight360=4.2.1-1

# 3. Minimal configuration
$ sudo cp /opt/ci360/etc/ci360.yaml.sample /etc/ci360.yaml
$ sudo vi /etc/ci360.yaml               # edit as needed

# 4. Start the service (systemd)
$ sudo systemctl enable --now ci360

# 5. Tail the logs
$ journalctl -u ci360 -f
```

---

## 4. Building from Source  

Building is required when:  
* You apply custom patches,  
* Want compiler optimizations (LTO/PGO/OFast),  
* Must statically link to an in-house crypto module, or  
* Are on an unsupported OS/ARCH.

### 4.1. Fetch the Source

```bash
$ git clone https://git.myhospital.net/analytics/ci360.git
$ cd ci360
$ git checkout v4.2.1
```

### 4.2. Install Build Toolchain  

Ubuntu example:

```bash
$ sudo apt install -y build-essential gcc-12 g++-12 cmake ninja-build \
  libssl-dev libprotobuf-dev protobuf-compiler \
  librdkafka-dev libtbb-dev libarrow-dev libparquet-dev libboost-system-dev
```

> Tip – We suggest using [vcpkg](https://github.com/microsoft/vcpkg) for
> cross-platform dependency pinning (`./vcpkg/bootstrap-vcpkg.sh && ./vcpkg/vcpkg install`).

### 4.3. Configure & Build

```bash
$ mkdir -p build && cd build
$ cmake .. -G Ninja \
  -DCMAKE_CXX_COMPILER=g++-12 \
  -DCMAKE_BUILD_TYPE=Release \
  -DENABLE_LTO=ON \
  -DENABLE_PGO=ON \
  -DOPENSSL_ROOT_DIR=/usr/lib/ssl \
  -DKAFKA_ROOT=/usr \
  -DTBB_ROOT=/usr \
  -DArrow_ROOT=/usr \
  -DParquet_ROOT=/usr

$ ninja        # parallel build
$ ninja test   # run unit and integration tests
$ ninja package
```

Artifacts are placed under `build/dist/`:

```
dist/
 ├── cardioinsight360         # main binary
 ├── plugins/                 # strategized transforms (*.so)
 ├── configs/ci360.yaml       # default config
 └── ci360_run.sh             # launch helper
```

### 4.4. Install Locally

```bash
$ sudo ./ci360_run.sh --install /usr/local/ci360
$ sudo ln -s /usr/local/ci360/bin/cardioinsight360 /usr/local/bin/ci360
```

---

## 5. Configuration  

All runtime configuration lives in a single YAML file (`ci360.yaml`) to ease
validation and change-control audits.

```yaml
# /etc/ci360.yaml
system:
  home:           /opt/ci360
  data_lake_root: /data/ci360/lake
  staging_root:   /data/ci360/staging
  tmp_root:       /var/tmp/ci360
  log_level:      info            # debug | info | warn | error | fatal
  max_parallelism: 0              # 0 = auto-detect

security:
  tls:
    enable: true
    cert: /etc/ssl/certs/ci360.crt
    key:  /etc/ssl/private/ci360.key
    ca:   /etc/ssl/certs/ca_bundle.crt
  encryption_at_rest:
    enable: true
    master_key_path: /etc/ci360/.master_key

streaming:
  kafka:
    brokers: ["kafka-1:9092","kafka-2:9092","kafka-3:9092"]
    topics:
      ingestion_raw:         vh_incoming_hl7
      ingestion_parsed:      vh_incoming_parsed
      alerts_realtime:       vh_alerts
  producer_batch_size: 1048576
  consumer_group_id:   ci360_pipeline

etl:
  batch_window_seconds: 600
  retention_days:
    raw:    7
    staged: 30
    curate: 180
dashboards:
  enable: true
  bind_address: 0.0.0.0
  bind_port:    8443
```

> After **any** change, run `ci360 --validate-config /etc/ci360.yaml`.

---

## 6. Initial Data-Lake Bootstrap  

```bash
$ sudo -u ci360 mkdir -p /data/ci360/{lake,staging,archive}
$ sudo -u ci360 chmod 700 /data/ci360
$ ci360 --bootstrap \
        --config /etc/ci360.yaml \
        --force-new-master-key
```

The command:

1. Generates an AES-256 master key (if missing).  
2. Creates hierarchical Parquet directories:  
   `/YYYY/MM/DD/{raw,staged,curated}/`  
3. Registers dataset schemas with Arrow’s schema registry file.  

---

## 7. Post-install Validation  

Run the validation harness to simulate HL7 traffic and ensure that:

* Librdkafka connectivity works (metadata fetch).  
* Transformation strategies load (.so presence & ABI).  
* Parquet files are created with correct schema & compression (Snappy).  
* Observer metrics are exposed on `:9100/metrics`.

```bash
$ ci360 --run-validation --config /etc/ci360.yaml
...
[ OK ] HL7 ingest loopback
[ OK ] Strategy registry (8 transforms loaded)
[ OK ] Parquet write/read cycle
[ OK ] Metrics endpoint (http://localhost:9100/metrics)
Validation summary: SUCCESS
```

---

## 8. Service Management  

### 8.1. Linux systemd Unit  

File: `/etc/systemd/system/ci360.service`

```ini
[Unit]
Description=CardioInsight 360 Analytics Engine
After=network.target kafka.target

[Service]
User=ci360
Group=ci360
ExecStart=/opt/ci360/bin/cardioinsight360 --config /etc/ci360.yaml
LimitNOFILE=1048576
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=on-failure
RestartSec=5s
Environment="CI360_HOME=/opt/ci360"

[Install]
WantedBy=multi-user.target
```

Control commands:

```bash
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now ci360
$ sudo systemctl status ci360
```

### 8.2. Windows Service  

```powershell
PS> sc.exe create CI360 binPath= "C:\ci360\cardioinsight360.exe --config C:\ci360\ci360.yaml"
PS> sc.exe start  CI360
```

---

## 9. Upgrading  

1. Backup current data-lake & config:  
   `ci360 --backup --output /backups/ci360_$(date +%Y%m%d).tgz`  
2. Validate new package in staging:  
   `apt-get install cardioinsight360=4.3.0-rc1 --download-only`  
3. Run schema-migration dry-run:  
   `ci360 --migrate --dry-run`  
4. Stop, upgrade, start, verify.

Rollback by re-installing the previous `.deb` and restoring the backup:

```bash
$ sudo apt install ./cardioinsight360_4.2.1-1_amd64.deb
$ ci360 --restore /backups/ci360_20240609.tgz
```

---

## 10. Uninstall  

```bash
$ sudo systemctl stop ci360
$ sudo apt purge cardioinsight360
$ sudo rm -rf /data/ci360 /etc/ci360.yaml /etc/systemd/system/ci360.service
```

---

## 11. Troubleshooting Checklist  

| Symptom                            | Possible Cause / Fix                                           |
|------------------------------------|----------------------------------------------------------------|
| `ci360: symbol lookup error`       | ABI mismatch — rebuild plugins with identical compiler flags.  |
| Kafka offsets stall                | Zookeeper ACLs missing — add `sasl.scram` credentials.         |
| Dashboard 504 Gateway Timeout      | Reverse proxy idle-timeout too low; set `proxy_read_timeout`.  |
| High resident memory (>90 %)       | Arrow memory pool set to default (unbounded), tune to 2 GB.    |
| TLS handshake fails (code 42)      | Incorrent key pair; regenerate with correct SAN & EKU.         |

---

## 12. Compliance Notes  

CI-360 ships with a built-in IEC 62304 Class B safety case, but final
responsibility for **validation in the target clinical environment** rests on
the deploying organization. Always:

1. Verify the chain of custody for build artifacts.  
2. Run the full IQ/OQ/PQ scripts located in `scripts/compliance/`.  
3. Document any deviation or local patch.  

---

## 13. Support  

* Slack (Internal Channel): `#ci360-support`  
* Email: `ci360@myhospital.net`  
* Knowledge Base: <https://kb.myhospital.net/ci360>  

---

© 2024 MyHospital Health Tech. All rights reserved.  
CardioInsight 360 is a registered trademark of MyHospital Health Tech.
```