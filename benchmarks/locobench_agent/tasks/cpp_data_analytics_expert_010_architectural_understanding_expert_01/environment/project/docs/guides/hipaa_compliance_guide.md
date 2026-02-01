```markdown
<!--
  CardioInsight360 – Unified Healthcare Analytics Engine
  File: docs/guides/hipaa_compliance_guide.md
  -------------------------------------------------------------------------------
  Copyright (c) MedTech Dynamics.
  Licensed under the Business Source License 1.1 (see LICENSE for details).
  -------------------------------------------------------------------------------
  This document is part of the permanent documentation set and is subject to
  the same change-control and validation procedures as the code itself.
-->

# CardioInsight360 HIPAA Compliance Guide  
*Version: 2.1.0 • Last updated: 2024-05-21*

---

## 1. Audience

This guide is intended for:

* Compliance Officers and Privacy Officers evaluating CardioInsight360 for clinical deployment.  
* DevOps and Security Engineers responsible for the secure installation and day-to-day operation of the platform.  
* Clinical Engineering teams overseeing validation, certification, and on-premise change-control processes.  

---

## 2. Executive Summary

CardioInsight360 is designed **from the ground up** to operate in a HIPAA-regulated environment.  
The platform provides end-to-end safeguards—administrative, physical, and technical—that map to the Security Rule (45 CFR Parts 160, 162, and 164).  

> **Key Takeaway**  
> CardioInsight360 ships as a *single, hard-enforced* binary that encapsulates encryption, audit logging, and RBAC, thereby reducing the attack surface and simplifying compliance validation.

---

## 3. Regulatory Scope

| HIPAA Rule                    | Applicability to CardioInsight360 |
| ----------------------------- | ---------------------------------- |
| Privacy Rule                  | ✅ Handles ePHI; supports data-minimization & de-identification. |
| Security Rule                 | ✅ Provides administrative, physical, and technical safeguards. |
| Breach Notification Rule      | ✅ Ships with notification hooks (SMTP, FHIR Subscription). |
| Enforcement Rule              | ✅ Produces audit evidence for OCR investigations. |

---

## 4. Administrative Safeguards

### 4.1 Risk Analysis & Management

* A formal **Threat Model** (STRIDE) is updated every release.  
* Automated **Static Application Security Testing (SAST)** runs in CI.  
* A **Software Bill of Materials (SBOM)** is published in SPDX 2.3 format.

### 4.2 Workforce Training

* The installation bundle includes **Just-in-Time (JIT) onboarding** videos.  
* A *GxP-aligned* training checklist is provided for clinical staff.

### 4.3 Contingency Planning

* Built-in **Incremental Backup Service** leverages immutable storage (WORM).  
* Restoration procedures are validated every quarter via Disaster-Recovery drills.

---

## 5. Physical Safeguards

Although CardioInsight360 is software, it enforces policy controls on:

* **Removable Media** – Data export is cryptographically signed and access-logged.  
* **Device & Media Controls** – Secure wipe (`NIST 800-88 Rev1`) routines are embedded.

---

## 6. Technical Safeguards

| Technical Requirement        | CardioInsight360 Implementation |
| ---------------------------- | -------------------------------- |
| Access Control               | Fine-grained RBAC, OIDC SSO, MFA enforcement. |
| Audit Controls               | Write-once append-only logs, SHA-512 digests, Syslog over TCP/TLS. |
| Integrity Controls           | End-to-End hashing (BLAKE3) on HL7/FHIR messages. |
| Transmission Security        | TLS 1.3, AES-256-GCM with PFS; Mutual TLS for peer nodes. |
| Encryption at Rest           | AES-256-XTS full-disk, plus field-level envelope encryption. |

### 6.1 Source-of-Truth: Master Key Management

CardioInsight360 integrates with HSMs and cloud KMS (AWS KMS, Azure Key Vault).

```cpp
// src/security/Keyring.cpp (excerpt)
// Demonstrates envelope encryption using AWS KMS
#include "security/Keyring.hpp"
#include <aws/kms/KMSClient.h>
#include <aws/kms/model/GenerateDataKeyRequest.h>
#include <aws/kms/model/GenerateDataKeyOutcome.h>

namespace ci360::security {

DataKey Keyring::generate_data_key() {
    Aws::KMS::KMSClient kms{_config.aws_credentials()};
    Aws::KMS::Model::GenerateDataKeyRequest req;
    req.SetKeyId(_config.kms_key_id());
    req.SetKeySpec(Aws::KMS::Model::DataKeySpec::aes_256);
    auto outcome = kms.GenerateDataKey(req);
    if (!outcome.IsSuccess()) {
        throw std::runtime_error(
            "KMS::GenerateDataKey failed: " +
            outcome.GetError().GetMessage());
    }
    return {
        .ciphertext = base64::encode(outcome.GetResult().GetCiphertextBlob()),
        .plaintext  = outcome.GetResult().GetPlaintext()
    };
}

} // namespace ci360::security
```

---

## 7. Data Lifecycle & Retention

1. **Ingestion** – HL7/FHIR messages are validated, hashed, and timestamped.  
2. **Transformation** – Business logic runs inside a *temporal sandbox* (time-boxed TBB tasks).  
3. **Storage** – Raw and curated Parquet files reside under `/ci360/datalake/YYYY/MM/DD/`.  
4. **Archival** – After **N = 6 years** (configurable), ePHI is migrated to cold storage.  
5. **Purge / De-Identification** – Supports HIPAA Expert Determination (§ 164.514(b)(1)).

---

## 8. Audit Logging & Monitoring

* All CRUD operations emit **RFC 5424** Syslog messages enriched with:
  * `patient_id` (hashed), `session_id`, `device_uuid`, and `ip_geo`.  
* The **Observer Pattern** streams metrics to Prometheus & Grafana.  
* Log tampering is mitigated via **LedgerChain™**—a Merkle tree that notarizes events.

```cpp
// src/audit/LedgerChain.cpp (excerpt)
void LedgerChain::append(const AuditEvent& ev) {
    std::lock_guard lk(_mutex);
    const auto prev_hash = _entries.empty() ? kGenesisHash : _entries.back().hash;
    _entries.emplace_back(ev, prev_hash);
    write_to_immutable_log(_entries.back());
}
```

---

## 9. Minimum Necessary & Access Control

* Role-based data scoping restricts API payloads to the *minimum necessary* PHI.  
* UI dashboards auto-redact patient identifiers for **Research-Only Accounts**.  

---

## 10. Incident Response & Breach Notification

| Stage                  | SLA  | Automation |
| ---------------------- | ---- | ---------- |
| Detection              | < 15 min | Prometheus alerts + On-call rotation via PagerDuty |
| Containment            | < 60 min | Automatic circuit-breaker for compromised ingest sources |
| Notification to OCR    | < 60 days | Pre-filled PDF/JSON report generator (`make breach-report`) |

---

## 11. Business Associate Agreement (BAA)

A signed **BAA** is mandatory before production deployment.  
Templates and negotiation guidelines are located under `/legal/baa/`.

---

## 12. Compliance Checklist

| ID | HIPAA Ref.            | Verification Method              | Status |
|----|-----------------------|----------------------------------|--------|
| AC-1 | § 164.312(a)         | Unit tests: `test_RBAC.cpp`      | ✅ |
| AU-2 | § 164.312(b)         | Audit log hashing E2E test       | ✅ |
| TR-1 | § 164.312(e)         | TLS 1.3 integration test         | ✅ |
| CP-3 | § 164.308(a)(7)(ii) | Quarterly DR runbook             | 🟡 _(scheduled)_ |

---

## 13. Shared Responsibility Model

| Responsibility                    | CardioInsight360 | Customer |
| --------------------------------- | :--------------: | :------: |
| Application-level encryption      | ✅               |          |
| Network perimeter firewalls       |                  | ✅       |
| Physical server security          |                  | ✅       |
| User provisioning & off-boarding  |                  | ✅       |
| Software updates & patches        | ✅               |          |

---

## 14. Operational Hardening Guide

1. **Enable FIPS Mode**  
   `export CI360_FIPS_MODE=1`

2. **Lock Down Configurations**  
   *Store `ci360.yaml` in a Git repo with signed commits.*

3. **Use SELinux/AppArmor**  
   Profiles are provided under `/ops/selinux/ci360.te`.

4. **Rotate Secrets**  
   Use the built-in `secret-rotate` sub-command:

   ```bash
   ./ci360 admin secret-rotate --scope=database --kms=aws
   ```

---

## 15. Validation & Verification

A full **Validation Protocol (VP)** is included in `/docs/validation/`.  
Run the automated suite:

```bash
./ci360 validate --profile=hipaa --output=vp_results.json
```

> **Expected Result** – All 183 HIPAA-mapped controls must PASS.  
> Attach `vp_results.json` to your change-control ticket.

---

## 16. Appendix

### 16.1 Compile-Time Flags

| Flag                         | Purpose                                  |
| ---------------------------- | ---------------------------------------- |
| `-D CI360_FIPS_COMPAT`       | Compile OpenSSL in FIPS-validated mode. |
| `-D CI360_DISABLE_EXPORT`    | Disable CSV export module (for air-gaps). |

### 16.2 Environment Variables

| Variable              | Default | Description |
| --------------------- | ------- | ----------- |
| `CI360_DATA_DIR`      | `/var/lib/ci360` | Root of the Data-Lake. |
| `CI360_AUDIT_ENDPOINT`| `syslog+tls://127.0.0.1:6514` | Syslog target. |
| `CI360_MTLS_REQUIRED` | `true`  | Enforce Mutual TLS for all endpoints. |

---

## 17. Contact & Support

*Email*: compliance@medtech-dynamics.com  
*PGP Key*: `0x8E32A7BDB23F9F1C` (FIPS 140-2 Level 2 HSM-backed)

> **Disclaimer**  
> This document does not constitute legal advice. Consult qualified counsel to
> confirm that your deployment meets all federal, state, and local regulations
> governing ePHI.
```