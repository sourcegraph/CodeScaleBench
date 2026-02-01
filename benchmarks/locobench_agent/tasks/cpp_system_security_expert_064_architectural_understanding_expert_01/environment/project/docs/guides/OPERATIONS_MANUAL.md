```markdown
<!--
  FortiLedger360 Enterprise Security Suite
  Operations Manual
  File: docs/guides/OPERATIONS_MANUAL.md
  NOTE:
    • This manual is version-controlled, peer-reviewed, and must pass our CI‐lint
      (markdown-lint + spell-check) pipeline before merging to `main`.
    • All shell snippets assume a Bourne-compatible shell (`bash >= 5.2`).
    • All infrastructure commands are idempotent—operators may re-run them
      safely if a previous attempt was interrupted.
    • Internal code listings (C++, YAML, protobuf) are production extracts and
      compile/run in the reference repository.
-->

# FortiLedger360 – Operations Manual
Author: Site Reliability Engineering (SRE)  
Audience: Platform & SRE teams responsible for day-0, day-1, and day-2 operations.

---

## 1. Quick-Start Checklist

| Stage | Task | Script/Command | Runtime |
|-------|------|----------------|---------|
| Day-0 | Provision Mesh CA & cluster certs | `tools/cert-forge.sh --issue mesh` | 30 s |
| Day-0 | Terraform core infra (VPC, LB, SQL) | `make tf-apply` | 3–5 min |
| Day-1 | Bootstrap control-plane | `make deploy-control-plane` | 90 s |
| Day-1 | Deploy service mesh sidecars | `make deploy-mesh` | ≈2 min |
| Day-1 | On-board first tenant | `flctl tenant create --file examples/new-tenant.yaml` | <1 s |
| Day-2 | Upsize backup nodes | `flctl cluster scale backup +2 --tenant acme-corp` | 20 s |
| Day-2 | Rotate gRPC mTLS certs | `flctl cert rotate --all` | 45 s |

`flctl` is the canonical CLI. Install via:

```bash
curl -fsSL https://releases.fortiledger360.com/install.sh | bash
sudo mv flctl /usr/local/bin/
flctl version    # Should match your Git tag
```

---

## 2. Architectural Recap for Operators

FortiLedger360 is arranged in five logical layers.

```
┌─────────────────────┐
│ Presentation & API  │  <— Ingress (REST, gRPC, WebSocket)
├─────────────────────┤
│ Orchestration       │  <— Command/Strategy engines
├─────────────────────┤
│ Domain              │  <— Multi-tenant business logic
├─────────────────────┤
│ Infrastructure      │  <— Mesh services (Scanner, BackupNode…)
├─────────────────────┤
│ Platform            │  <— Kubernetes, Istio, PostgreSQL, object-store
└─────────────────────┘
```

Each micro-service is stateless; persistent state is stored in an HA
PostgreSQL cluster and versioned object-storage.

---

## 3. Deployment Prerequisites

1. **Kubernetes ≥ 1.27** with ContainerD.
2. **Istio ≥ 1.18** (sidecar injection enabled).
3. **PostgreSQL 14 (with pgcrypto)**, configured for synchronous replication.
4. **MinIO cluster**, S3-compatible, 3-way replication.
5. Company-wide mTLS root CA (PEM) or the bundled dev-CA.

> Recommendation: Use our curated Helm charts (`charts/fortiledger360/`) that
> automatically validate your cluster for missing CRDs, PSPs, or network
> policies.

---

## 4. Day-0 Procedures

### 4.1 Generating Certificates

The script below issues a mesh root CA and leaf certificates for each mesh
service. Certificates are stored in Vault and projected into pods via CSI
volume.

```bash
# tools/cert-forge.sh
set -euo pipefail

readonly MESH_NS="fledger-mesh"
readonly VAULT_PATH="secret/pki"

function forge_ca() {
  openssl req -x509 -newkey rsa:4096 -sha256 -days 365 \
    -subj "/CN=FortiLedger360 Mesh Root" \
    -keyout root.key -out root.crt -nodes
  vault kv put "${VAULT_PATH}/root" crt=@root.crt key=@root.key
}

function issue_leaf() {
  local svc="$1"
  openssl genrsa -out "${svc}.key" 4096
  openssl req -new -key "${svc}.key" -out "${svc}.csr" \
    -subj "/CN=${svc}.${MESH_NS}.svc.cluster.local"
  openssl x509 -req -in "${svc}.csr" -CA root.crt -CAkey root.key \
    -CAcreateserial -out "${svc}.crt" -days 180 -sha256
  vault kv put "${VAULT_PATH}/${svc}" crt=@"${svc}.crt" key=@"${svc}.key"
}

forge_ca
for svc in scanner orchestrator metrics backup-node config-mgr alert-broker; do
  issue_leaf "${svc}"
done
echo "✅ All mesh certs issued & stored in Vault"
```

### 4.2 Terraform Infrastructure

```bash
export TF_VAR_region=us-east-1
cd infra/terraform
terraform init
terraform apply -auto-approve
```

Outputs are exported to `infra/terraform/terraform.tfstate` and consumed by
Helm as `.Values.infra`. Never edit manually.

---

## 5. Day-1 Operations

### 5.1 Installing FortiLedger360

```bash
helm repo add fortiledger360 https://charts.fortiledger360.com
helm upgrade --install fortiledger360 fortiledger360/enterprise \
  --namespace forti-system --create-namespace \
  -f env/prod/values.yaml
```

The Helm chart

1. Deploys CRDs (`Tenant`, `SubscriptionPlan`).
2. Registers a validating admission webhook (Chain-of-Responsibility).
3. Enables HPA with the recommended vCPU/memory minima.

`helm test fortiledger360` runs synthetic transactions and validates:

* Config-manager connectivity to Postgres.
* Scanner reaching the vulnerability feed endpoints.
* Backup-nodes cloning a test volume.

### 5.2 On-Boarding a Tenant

```yaml
# examples/new-tenant.yaml
apiVersion: fleet.fledger360.io/v1alpha1
kind: Tenant
metadata:
  name: acme-corp
spec:
  plan: gold
  contact:
    email: ops@acme.example
    phone: "+1-555-0100"
  preferences:
    scanning: continuous
    backupWindow: "01:00-03:00"
```

Apply and verify:

```bash
kubectl apply -f examples/new-tenant.yaml
flctl tenant ls
flctl tenant health acme-corp
```

---

## 6. Day-2 Operations

### 6.1 Scaling Service Mesh Nodes

Scale Backup-Nodes from 3 to 5 replicas:

```bash
flctl cluster scale backup +2 --tenant acme-corp
# under the hood: PATCH /tenants/acme-corp/spec/capacity
```

Alternatively via `kubectl`:

```bash
kubectl -n forti-system scale deploy backup-node --replicas=5
```

### 6.2 Certificate Rotation

1. Issue fresh leaf certs using `tools/cert-forge.sh`.
2. Trigger rolling restart:

```bash
flctl cert rotate --all
```

Pods detect the updated certificate secret version and restart gracefully (0 s
downtime due to Envoy hot-restart feature).

### 6.3 Patching a Release

Patch version `v3.8.2` → `v3.8.3`:

```bash
helm upgrade fortiledger360 fortiledger360/enterprise \
  --namespace forti-system \
  --version 3.8.3 \
  --reuse-values
```

Post-upgrade smoke test:

```bash
flctl smoke all
kubectl get pods -n forti-system | grep -v Running
```

---

## 7. Disaster Recovery (DR)

| Component | RPO | Mechanism |
|-----------|-----|-----------|
| PostgreSQL | 15 s | Synchronous replica, WAL-shipping to a cold region |
| Object-store | 0 s | Erasure-coded triple replication |
| gRPC mesh | 60 s | DNS fail-over + warm standby |
| Control-plane | 2 min | GitOps redeploy |

1. In a primary-region outage, run the DR plan:

```bash
drctl failover \
  --from us-east-1 \
  --to eu-central-1 \
  --promote postgres \
  --verify
```

2. Confirm health:

```bash
drctl status --region eu-central-1
```

---

## 8. Observability

FortiLedger360 exposes Prometheus & OpenTelemetry endpoints. Example Grafana
dashboard panels:

* *Mesh mTLS Handshake Duration p95*
* *Scanner Queue Depth*
* *Backup Success Ratio (last 24 h)*
* *Config Drift Change Rate*

To import:

```bash
flctl observability import-dashboard grafana/mesh_overview.json
```

---

## 9. Troubleshooting Run-Book

| Symptom | Check | Fix |
|---------|-------|-----|
| `TENANT_POLICY_DENIED` error | `flctl tenant policy-explain <id>` | Adjust plan limits or exemption |
| Scanner pods CrashLoop | `kubectl logs scanner -c app` | Verify CVE feed URL reachability |
| Backup lag > 5 min | `kubectl top pod backup-node` | Increase CPU/memory; scale replicas |

### 9.1 Deep-Dive: gRPC Connectivity

Use the built-in `"grpc-doctor"` job:

```bash
flctl net grpc-diagnose --tenant acme-corp
```

Output sample:

```
[OK] scanner:443 — TLS v1.3, SAN validated
[OK] backup-node:443 — TLS v1.3, SAN validated
[FAIL] alert-broker:443 — connection refused
```

Redeploy Alert-Broker:

```bash
kubectl -n forti-system rollout restart deploy alert-broker
```

---

## 10. Appendix

### A.1 CLI Cheat-Sheet

```
flctl tenant ls                            # List tenants
flctl tenant purge <name>                  # Delete tenant (irreversible!)
flctl plan promote silver gold             # Upgrade plan
flctl cert rotate --service scanner        # Rotate a single cert
flctl cluster scale <svc> <delta> [...]    # Scale nodes
flctl observability port-forward grafana   # Local Grafana access
```

### A.2 Minimal C++ Health Probe

Operators often embed a custom health probe in legacy integration scripts.
Here’s a vetted C++17 example referencing the official SDK:

```cpp
// File: samples/healthcheck/main.cpp
#include <fl360/sdk/client.hpp>
#include <chrono>
#include <cstdlib>
#include <iostream>

int main(int argc, char** argv) try {
    using namespace fl360::sdk;
    ClientOptions opts;
    opts.grpc_target = "scanner.forti-system.svc.cluster.local:443";
    opts.tls_root_ca = "/var/run/secrets/mesh/root.pem";
    Client client{opts};

    auto deadline = std::chrono::system_clock::now() + std::chrono::seconds(3);
    HealthResponse resp = client.healthProbe(deadline);

    if (resp.ok && resp.status == HealthStatus::SERVING) {
        std::cout << "SERVING\n";
        return EXIT_SUCCESS;
    }
    std::cerr << "UNHEALTHY: " << resp.message << '\n';
    return EXIT_FAILURE;
} catch (const std::exception& ex) {
    std::cerr << "Probe failed: " << ex.what() << '\n';
    return EXIT_FAILURE;
}
```

Compile:

```bash
g++ -std=c++17 -I/usr/include/fl360 -lfl360_grpc \
    samples/healthcheck/main.cpp -o healthcheck
```

---

*Last reviewed:* 2024-06-14  
*Next review due:* 2024-09-14  
PRs welcome! 🛡️
```