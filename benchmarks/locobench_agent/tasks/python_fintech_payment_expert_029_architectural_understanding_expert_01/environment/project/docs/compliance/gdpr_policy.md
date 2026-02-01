```markdown
<!--
crowdpay_connect/docs/compliance/gdpr_policy.md

CrowdPay Connect — GDPR Privacy Policy
Last Updated: 2024-06-09
Copyright © 2024 CrowdPay Fintech Ltd.  All rights reserved.
-->

# CrowdPay Connect – GDPR Privacy Policy

CrowdPay Fintech Ltd. (“**CrowdPay**”, “**we**”, “**our**” or “**us**”) takes the
privacy of our users seriously.  
This Privacy Policy describes **how we collect, use, store, disclose and
protect Personal Data** when you interact with the CrowdPay Connect platform,
mobile applications, APIs, and related services (collectively, the
“**Services**”).

This Policy is drafted to meet the requirements of:

* Regulation (EU) 2016/679 — General Data Protection Regulation (“**GDPR**”),
* UK GDPR and Data Protection Act 2018,
* Directive (EU) 2015/2366 — PSD2, and
* Applicable Anti-Money Laundering (“AML”) and Know-Your-Customer (“KYC”)
  regulations.

## 1. Scope

This Policy applies to all processing of Personal Data by CrowdPay in its
capacity as a **Data Controller**.  
Where we act solely as a **Data Processor** on behalf of a
CrowdPay Connect customer (e.g., white-label integrations), we comply with the
controller’s documented instructions and enter into Article 28 Data Processing
Agreements (DPAs).

## 2. Definitions

| Term                | Definition (Article 4 GDPR)                                                                 |
|---------------------|---------------------------------------------------------------------------------------------|
| Personal Data       | Any information relating to an identified or identifiable natural person (“Data Subject”). |
| Processing          | Any operation which is performed on Personal Data (collection, storage, etc.).              |
| Controller          | The party that determines the purposes and means of Processing.                             |
| Processor           | The party that processes Personal Data on behalf of the Controller.                         |
| **Special Category**| Data revealing racial/ethnic origin, political opinions, etc. (Article 9)                  |

## 3. What Personal Data We Collect

We collect and Process the following categories of Personal Data:

| Category                    | Examples                                                                                 | Lawful Basis (Art. 6) |
|-----------------------------|------------------------------------------------------------------------------------------|-----------------------|
| **Identification Data**     | Name, postal address, date of birth, government ID, **KYC** selfies.                    | 6 (1)(c), 6 (1)(f)    |
| **Account Credentials**     | Email, hashed passwords, 2FA public keys.                                              | 6 (1)(b)              |
| **Financial Data**          | Bank account numbers, card PAN (tokenised), transaction history, IBAN/BIC.              | 6 (1)(b), 6 (1)(c)    |
| **Usage Data**              | Logins, click-streams, CrowdPod interactions, reputation scores, audit-trail events.    | 6 (1)(f)              |
| **Device & Technical Data** | IP address, browser type, operating system, device identifiers, SDK version.            | 6 (1)(f)              |
| **Geo-Location Data**       | Derived from IP or explicit permission (mobile GPS).                                    | 6 (1)(a), 6 (1)(f)    |
| **Communications**          | Support tickets, chat messages, compliance requests, recorded phone calls.             | 6 (1)(b), 6 (1)(c)    |

We do **not** intentionally collect Special Category Data unless mandated by
law (e.g., facial biometrics for KYC). Where collected, we rely on Article 9 (2)
(b) & (g) or obtain explicit consent per Article 9 (2)(a).

## 4. Lawful Bases for Processing

1. **Contract** – Creating and maintaining your CrowdPay account (Art. 6 (1)(b)).  
2. **Legal Obligation** – AML/KYC, tax reporting, sanctions screening (Art. 6 (1)(c)).  
3. **Legitimate Interests** – Security, fraud prevention, product analytics
   (Art. 6 (1)(f)). A balancing test is performed for each processing activity.  
4. **Consent** – Optional marketing communications, cookies requiring consent
   (Art. 6 (1)(a)). You may withdraw consent at any time.

## 5. Purposes of Processing

* Facilitate payments, currency conversion, and settlement via distributed
  **Saga** orchestration.
* Conduct real-time risk assessment, fraud detection, and reputation scoring
  leveraging **Event Sourcing** & **CQRS**.
* Perform mandatory identity verification and AML checks.
* Provide social features (followers, up-votes, compliance badges).
* Comply with financial regulations and respond to lawful requests.
* Improve, debug, and secure our Services.

We do **not** sell Personal Data to third parties.

## 6. Automated Decision-Making & Profiling

We apply automated algorithms for transaction risk assessment,
reputation scoring, and AML flagging.  
Decisions with legal or similarly significant effects are subject to
human review on request (Art. 22 (3)).

## 7. Data Subject Rights

Under GDPR you have:

* Right of Access (Art. 15) – Obtain a copy of your Personal Data.  
* Right to Rectification (Art. 16) – Correct inaccurate data.  
* Right to Erasure (Art. 17) – “Right to be forgotten”.  
* Right to Restrict Processing (Art. 18).  
* Right to Data Portability (Art. 20) – JSON export or SEPA payment file.  
* Right to Object (Art. 21) – e.g., direct marketing.  
* Rights related to automated decision-making (Art. 22).  

Submit requests by emailing **privacy@crowdpayconnect.com** or via in-app “Privacy Center”.
We respond within **30 days** (Art. 12 (3)). Identity verification is required.

## 8. International Data Transfers

Personal Data may be transferred outside the EEA/UK to:

* AWS EU-West & AWS US-East (encrypted S3 buckets, RDS).  
* Auth0 (EU region) for authentication.  

Transfers rely on:

1. Adequacy Decisions (Art. 45) — e.g., UK to EEA.  
2. Standard Contractual Clauses (“SCCs”) & UK Addendum (Art. 46).  
3. Supplementary encryption, pseudonymisation, and data minimisation.

## 9. Data Retention & Deletion

| Data Category                       | Retention Period                                                                  |
|------------------------------------|-----------------------------------------------------------------------------------|
| Payment & Ledger Records           | 10 years (AML & accounting obligations).                                          |
| KYC Documentation                  | 5 years post account closure (AMLD4/5).                                           |
| Marketing Preferences              | Until consent withdrawn + 30 days grace.                                          |
| Audit Logs & Event Streams         | 6 years, then pseudonymised aggregates.                                           |
| Back-ups (encrypted, off-site)     | 35 days rolling window, immutable snapshots.                                      |

At the end of the retention period, data is **securely deleted or anonymised**
using NIST SP 800-88 purge methods.

## 10. Security Measures

CrowdPay implements **Security-by-Design and by Default**:

* End-to-end TLS 1.3 encryption; field-level AES-256 for sensitive columns.
* Hardware Security Modules (HSMs) for cryptographic keys.
* Zero-trust microservices architecture with mutual mTLS.
* OWASP Top-10 hardened codebase; continuous SAST/DAST.
* Role-Based Access Control (RBAC) & Just-in-Time (JIT) privileged access.
* Event-driven **audit trail** stored immutably (WORM storage).
* Annual SOC 2 Type II & ISO 27001 audits; quarterly penetration tests.
* Data Protection Impact Assessments (**DPIA**) for new high-risk features.

## 11. Data Breach Notification

In the event of a Personal Data Breach, we will:

1. Notify the competent Supervisory Authority within **72 hours** (Art. 33),
   unless the breach is unlikely to pose risks.
2. Communicate to affected Data Subjects **without undue delay** when there is a
   high risk to their rights and freedoms (Art. 34).
3. Record all breach facts and remediation steps in our incident register.

## 12. Processors & Sub-Processors (Article 28)

| Category                   | Provider                | Location | Safeguards           |
|----------------------------|-------------------------|----------|----------------------|
| Cloud Infrastructure       | Amazon Web Services     | EU/US    | SCCs, ISO 27017      |
| Authentication             | Auth0 (Okta)           | EU       | SCCs, ISO 27001      |
| AML/KYC Checks             | ComplyAdvantage         | EU/US    | SCCs                 |
| Payment Acquiring          | Stripe, Adyen           | EU/US    | PCI DSS, SCCs        |
| Analytics (pseudonymised)  | Snowflake              | EU       | ISO 27701, SCCs      |

We maintain an up-to-date list at:
`https://crowdpayconnect.com/legal/subprocessors`.

## 13. Children’s Privacy

Our Services are **not intended for individuals under 18**.  
We do not knowingly collect data from minors. If you believe we have done so,
contact privacy@crowdpayconnect.com and we will delete such data promptly.

## 14. Cookies & Tracking Technologies

We use:

* **Strictly Necessary** cookies for session management (legal basis: Art. 6 (1)(b)).
* **Analytics** cookies (e.g., Matomo) with IP truncation (legitimate interest).
* **Marketing** cookies only where **opt-in consent** is obtained via the
  Consent Management Platform (CMP).

For a detailed cookie table, see `cookies_policy.md`.

## 15. Changes to This Policy

We may update this Policy to reflect legal, technical, or business changes.
Material changes will be notified via email and in-app notifications **30 days
before** they take effect.

## 16. Contact Us

Data Controller:    
CrowdPay Fintech Ltd.  
70 Gracechurch Street, London EC3V 0HR, United Kingdom

Email: **privacy@crowdpayconnect.com**  
Data Protection Officer (DPO): **Ms. Ana Fernandes**

If you believe we have not resolved your concern, you have the right to lodge a
complaint with your local Supervisory Authority. In the UK, this is the
Information Commissioner’s Office (ICO).

---

_This document is version 1.0.0, generated automatically from the Governance,
Risk & Compliance (“GRC”) knowledge base. Sign-off: Legal & Compliance Board,
Ref #GRC-POL-GDPR-001._
```