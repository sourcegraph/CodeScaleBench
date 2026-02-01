```markdown
# CommerceSphere™ Enterprise Suite  
## Regulatory Compliance Implementation Guide  

**Document Version:** 3.4  
**Last Updated:** 2024-05-28  
**Audience:** Solution Architects, Backend Engineers, Compliance Officers  

---

### 1. Introduction  

CommerceSphere Enterprise Suite ships with first-class support for PCI-DSS, GDPR, and SOX auditability requirements.  
This document provides concrete Java implementation examples, configuration guidelines, and operational checklists for keeping your deployment in continuous compliance.

> IMPORTANT: The examples below are extracted from the production codebase and are designed for immediate use or adaptation.  
> They rely exclusively on JDK 17 (LTS) and Spring Framework 6.0 APIs that are already bundled with the platform.

---

## 2. PCI-DSS

### 2.1 Card-Data Flow

1. Cardholder data is captured client-side and exchanged for a single-use token via the platform’s Tokenization Gateway.  
2. Only the token traverses the internal network and is stored in the `payment_tokens` table.  
3. The real PAN never touches CommerceSphere’s persistence layer.

### 2.2 Encryption & Key Management

CommerceSphere uses AES-256-GCM with a master key stored in an HSM that supports automatic key rotation.  
Encryption material is injected via Spring Cloud Vault at runtime.

```java
package com.commercesphere.payment.crypto;

import com.commercesphere.logging.CorrelationId;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Base64;

/**
 * Production-grade AES-256-GCM cipher utility.
 * All encryption keys are supplied by Vault and never hard-coded.
 */
@Component
public class AesGcmCipher {

    private static final int GCM_TAG_LENGTH = 16;         // 128 bits
    private static final int IV_LENGTH_BYTES = 12;        // 96 bits (recommended for GCM)
    private static final SecureRandom SECURE_RANDOM = new SecureRandom();

    @Value("${security.encryption.master-key}")
    private byte[] masterKey;                             // Vault injects and rotates this value

    public String encrypt(String plainText) {
        try {
            byte[] iv = new byte[IV_LENGTH_BYTES];
            SECURE_RANDOM.nextBytes(iv);

            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            SecretKeySpec keySpec = new SecretKeySpec(masterKey, "AES");
            GCMParameterSpec gcmSpec = new GCMParameterSpec(GCM_TAG_LENGTH * 8, iv);

            cipher.init(Cipher.ENCRYPT_MODE, keySpec, gcmSpec);
            byte[] cipherText = cipher.doFinal(plainText.getBytes());

            byte[] cipherMessage = new byte[IV_LENGTH_BYTES + cipherText.length];
            System.arraycopy(iv, 0, cipherMessage, 0, IV_LENGTH_BYTES);
            System.arraycopy(cipherText, 0, cipherMessage, IV_LENGTH_BYTES, cipherText.length);

            return Base64.getEncoder().encodeToString(cipherMessage);
        } catch (GeneralSecurityException e) {
            throw new CryptoException("Failed to encrypt card data", e, CorrelationId.get());
        }
    }

    public String decrypt(String cipherMessage) {
        try {
            byte[] cipherData = Base64.getDecoder().decode(cipherMessage);

            byte[] iv = new byte[IV_LENGTH_BYTES];
            System.arraycopy(cipherData, 0, iv, 0, IV_LENGTH_BYTES);

            byte[] actualCipherText = new byte[cipherData.length - IV_LENGTH_BYTES];
            System.arraycopy(cipherData, IV_LENGTH_BYTES, actualCipherText, 0, actualCipherText.length);

            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            SecretKeySpec keySpec = new SecretKeySpec(masterKey, "AES");
            GCMParameterSpec gcmSpec = new GCMParameterSpec(GCM_TAG_LENGTH * 8, iv);

            cipher.init(Cipher.DECRYPT_MODE, keySpec, gcmSpec);
            byte[] plainBytes = cipher.doFinal(actualCipherText);

            return new String(plainBytes);
        } catch (GeneralSecurityException e) {
            throw new CryptoException("Failed to decrypt card data", e, CorrelationId.get());
        }
    }
}
```

```java
package com.commercesphere.payment.crypto;

/**
 * Custom runtime exception used for propagating cryptographic errors.
 * Includes a correlationId for full traceability in audit logs.
 */
public class CryptoException extends RuntimeException {
    private final String correlationId;

    public CryptoException(String message, Throwable cause, String correlationId) {
        super(message, cause);
        this.correlationId = correlationId;
    }

    public String getCorrelationId() {
        return correlationId;
    }
}
```

### 2.3 Mandatory Configuration (`application.yaml`)

```yaml
security:
  encryption:
    master-key: ${vault.path.to.master-key} # injected, never committed
```

---

## 3. GDPR

### 3.1 Data-Subject Requests (DSR)

CommerceSphere exposes REST endpoints under `/api/compliance/dsr/**` for:

* Right of access (`GET`)
* Right of rectification (`PATCH`)
* Right to be forgotten (`DELETE`)
* Data portability (`POST /export`)

All calls require `ROLE_COMPLIANCE_OFFICER` or a time-bound JWT with the `dsr` scope.

### 3.2 Scheduled Erasure Job

```java
package com.commercesphere.compliance.gdpr;

import com.commercesphere.logging.AuditLogger;
import com.commercesphere.user.repository.UserRepository;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Scheduled job that permanently purges logically-deleted personal data
 * once the retention period elapses.
 */
@Component
public class PersonalDataPurgeJob {

    private final UserRepository userRepository;
    private final AuditLogger auditLogger;

    public PersonalDataPurgeJob(UserRepository userRepository, AuditLogger auditLogger) {
        this.userRepository = userRepository;
        this.auditLogger = auditLogger;
    }

    @Scheduled(cron = "0 0 3 * * ?") // 3 AM UTC daily
    public void purgeExpiredPersonalData() {
        userRepository
            .findCandidatesForPermanentDeletion()
            .forEach(user -> {
                userRepository.deletePermanently(user);
                auditLogger.recordErasure(user.getId(),
                        "GDPR_PURGE_JOB",
                        "Personal data permanently removed after retention window.");
            });
    }
}
```

### 3.3 Consent Management Filter

```java
package com.commercesphere.compliance.gdpr;

import jakarta.servlet.*;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Component;
import java.io.IOException;

@Component
public class ConsentFilter implements Filter {

    public static final String CONSENT_COOKIE = "cs_consent";

    @Override
    public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain)
            throws IOException, ServletException {

        HttpServletRequest request = (HttpServletRequest) req;
        boolean consentGiven = hasConsent(request);

        if (!consentGiven && isPersonalDataEndpoint(request)) {
            throw new MissingConsentException("User consent required for " + request.getRequestURI());
        }
        chain.doFilter(req, res);
    }

    private boolean hasConsent(HttpServletRequest request) {
        if (request.getCookies() == null) return false;
        for (Cookie cookie : request.getCookies()) {
            if (CONSENT_COOKIE.equals(cookie.getName()) && "true".equals(cookie.getValue())) {
                return true;
            }
        }
        return false;
    }

    private boolean isPersonalDataEndpoint(HttpServletRequest request) {
        String uri = request.getRequestURI();
        return uri.startsWith("/api/user") || uri.startsWith("/api/address");
    }
}
```

---

## 4. SOX-Grade Audit Logging

CommerceSphere captures an immutable, append-only log of every critical business operation.

```java
package com.commercesphere.logging;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import java.time.Instant;
import java.util.UUID;

@Component
public class AuditLogger {

    private static final Logger LOG = LoggerFactory.getLogger("AUDIT");

    public void recordErasure(UUID userId, String source, String reason) {
        log("USER_ERASURE", userId, source, reason);
    }

    public void recordPayment(UUID paymentId, String source, String action) {
        log("PAYMENT", paymentId, source, action);
    }

    private void log(String type, UUID entityId, String source, String message) {
        LOG.info("type={} entityId={} source={} message=\"{}\" ts={}",
                type, entityId, source, message, Instant.now().toString());
    }
}
```

### 4.1 Correlation IDs

Every HTTP request automatically receives a `X-Correlation-Id` if absent.  
The following interceptor propagates the ID to SLF4J’s MDC:

```java
package com.commercesphere.logging;

import jakarta.servlet.*;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import java.io.IOException;
import java.util.UUID;

@Component
public class CorrelationIdFilter implements Filter {

    public static final String HEADER = "X-Correlation-Id";

    @Override
    public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain)
            throws IOException, ServletException {

        String correlationId = getOrCreateCorrelationId((HttpServletRequest) req);
        MDC.put("correlationId", correlationId);
        try {
            chain.doFilter(req, res);
        } finally {
            MDC.remove("correlationId");
        }
    }

    private String getOrCreateCorrelationId(HttpServletRequest request) {
        String cid = request.getHeader(HEADER);
        if (cid == null || cid.isEmpty()) {
            cid = UUID.randomUUID().toString();
        }
        return cid;
    }
}
```

---

## 5. Compliance Checklist (CI/CD)  

| Stage | Validation | Tool | Blocking |
|-------|------------|------|----------|
| Build | OWASP dependency scan | OWASP Dependency-Check Maven Plugin | ✔ |
| Test  | Static code analysis (PCI, GDPR rulesets) | SonarQube | ✔ |
| Deploy| Infra configuration drift | Terraform Sentinel | ✔ |
| Run   | Continuous vulnerability scan | AWS Inspector / Qualys | ⚠️ |

---

## 6. Operational Runbooks

* **Key Rotation:** Run the Vault `rotate-aes` automation workflow (`scripts/ops/rotate-aes.sh`) every 90 days.  
* **DSR SLA:** EU GDPR requires fulfillment within 30 days. Monitor `/metrics/dsr.pending` to ensure backlog < 5.  
* **Alerting:** Forward `AUDIT` log group to your SIEM (Splunk, Elastic, etc.) with a retention of ≥ 1 year.

---

## 7. Additional Resources

* PCI Security Standards Council – [PCI-DSS v4.0](https://www.pcisecuritystandards.org)  
* European Commission – [GDPR Portal](https://gdpr.eu)  
* U.S. SOX Act – [Full Text](https://www.govinfo.gov/content/pkg/PLAW-107publ204/pdf/PLAW-107publ204.pdf)  

---

© 2024 CommerceSphere Inc.  All rights reserved.
```