# Kafka SASL Authentication Flow Security Analysis

## Files Examined

### Channel Building & Network Transport
- `clients/src/main/java/org/apache/kafka/common/network/ChannelBuilders.java` — Entry point for creating channel builders based on security protocol, wires up SASL components
- `clients/src/main/java/org/apache/kafka/common/network/SaslChannelBuilder.java` — Constructs SASL-authenticated channels, creates authenticators and callback handlers
- `clients/src/main/java/org/apache/kafka/common/network/KafkaChannel.java` — Container for socket channel and authenticator
- `clients/src/main/java/org/apache/kafka/common/network/NetworkReceive.java` — Reads untrusted bytes from network socket

### Server-Side SASL Authenticator
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java` — State machine for SASL authentication, processes client requests
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslClientAuthenticator.java` — Client-side SASL authenticator (for broker-to-broker connections)

### SASL Mechanism Implementations
- `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainSaslServer.java` — PLAIN mechanism implementation, parses user credentials
- `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainServerCallbackHandler.java` — PLAIN callback handler for credential verification
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java` — SCRAM mechanism implementation (RFC 5802)
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramMessages.java` — SCRAM message parsing with regex validation
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramServerCallbackHandler.java` — SCRAM callback handler

### OAUTHBEARER Mechanism
- `clients/src/main/java/org/apache/kafka/common/security/oauthbearer/internals/OAuthBearerSaslClientCallbackHandler.java` — OAUTHBEARER client handler
- `clients/src/main/java/org/apache/kafka/common/security/oauthbearer/internals/OAuthBearerUnsecuredValidatorCallbackHandler.java` — OAUTHBEARER server validator

### Kerberos (GSSAPI) Mechanism
- `clients/src/main/java/org/apache/kafka/common/security/kerberos/KerberosClientCallbackHandler.java` — Kerberos client handler
- `clients/src/main/java/org/apache/kafka/common/security/kerberos/KerberosShortNamer.java` — Principal name normalization

### Principal Extraction & Authorization
- `clients/src/main/java/org/apache/kafka/common/security/auth/KafkaPrincipal.java` — Authenticated principal representation (type + name)
- `clients/src/main/java/org/apache/kafka/common/security/auth/KafkaPrincipalBuilder.java` — Interface for building principals from authentication context
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/DefaultKafkaPrincipalBuilder.java` — Default principal builder for SASL/SSL
- `clients/src/main/java/org/apache/kafka/server/authorizer/Authorizer.java` — Authorizer interface that uses KafkaPrincipal for ACL decisions

### Authentication Context
- `clients/src/main/java/org/apache/kafka/common/security/auth/AuthenticationContext.java` — Base class for auth context
- `clients/src/main/java/org/apache/kafka/common/security/auth/SaslAuthenticationContext.java` — Carries SaslServer and authentication metadata
- `clients/src/main/java/org/apache/kafka/common/security/auth/PlaintextAuthenticationContext.java` — No auth context

---

## Entry Points

### 1. Network Reception
- **Location**: `NetworkReceive.readFrom(TransportLayer)` in `clients/src/main/java/org/apache/kafka/common/network/NetworkReceive.java`
- **Input Type**: Raw socket bytes from untrusted client connection
- **Limit**: `saslAuthRequestMaxReceiveSize` (default: `DEFAULT_SASL_SERVER_MAX_RECEIVE_SIZE`)
- **Purpose**: Reads size-delimited messages from network socket

### 2. Kafka Request Header Parsing
- **Location**: `SaslServerAuthenticator.handleKafkaRequest()` line 507
- **Input Type**: Client token bytes → `RequestHeader.parse(requestBuffer)`
- **Processing**:
  ```
  byte[] requestBytes → ByteBuffer.wrap() → RequestHeader.parse() → ApiKeys enum lookup
  ```
- **Accepted Requests**: `ApiKeys.API_VERSIONS` or `ApiKeys.SASL_HANDSHAKE` only
- **Untrusted Data**:
  - API key (2 bytes)
  - API version (2 bytes)
  - Correlation ID (4 bytes)
  - Client ID (string)

### 3. SASL Handshake Request
- **Location**: `SaslServerAuthenticator.handleHandshakeRequest()` line 549
- **Input Type**: `SaslHandshakeRequest.data().mechanism()` — client-supplied mechanism string
- **Processing**: String directly from request, matched against `enabledMechanisms` list
- **Vulnerability Window**: Mechanism name extracted from untrusted request before validation

### 4. PLAIN Mechanism Token Processing
- **Location**: `PlainSaslServer.evaluateResponse()` line 71
- **Input Type**: Raw `byte[]` from client
- **Processing**:
  ```
  byte[] responseBytes
  → new String(responseBytes, UTF_8)
  → extractTokens(response)
  → Split by null byte (0x00)
  ```
- **Extracted**: `[authorizationId, username, password]`
- **Validation**: Only checks token count (must be 3) and non-empty username/password

### 5. SCRAM Mechanism Token Processing
- **Location**: `ScramSaslServer.evaluateResponse()` line 96
- **Client First Message Parsing**:
  ```
  byte[] response
  → new ClientFirstMessage(response)
  → Regex Pattern matching on UTF-8 decoded string
  ```
- **Regex Pattern** (line 68-74):
  ```
  n,(a=(?<authzid>SASLNAME))?,%sn=(?<saslname>SASLNAME),r=(?<nonce>PRINTABLE)(?<extensions>EXTENSIONS)
  ```
  where `SASLNAME = "(?:[\\x01-\\x7F&&[^=,]]|=2C|=3D)+"` (RFC 5802 percent-encoding)

- **Client Final Message Parsing**:
  ```
  new ClientFinalMessage(response) → Regex parsing
  ```

### 6. OAUTHBEARER Token Processing
- **Location**: `OAuthBearerSaslClientCallbackHandler` / `OAuthBearerUnsecuredValidatorCallbackHandler`
- **Input Type**: JWT token from client (base64url encoded)
- **Processing**: Token passed to validator for JWT signature verification

### 7. GSSAPI/Kerberos Token Processing
- **Location**: `Sasl.createSaslServer()` with GSSAPI mechanism
- **Input Type**: Kerberos AP-REQ message (binary GSS token)
- **Processing**: Delegated to Java GSSAPI implementation and system Kerberos library

---

## Data Flow

### Flow 1: PLAIN Authentication (Complete)
1. **Source**: `NetworkReceive.readFrom()` reads socket bytes
   - **Untrusted Data**: Raw bytes containing Kafka request header + SASL token

2. **Transport Layer**: Bytes buffered in `NetworkReceive.netInBuffer`
   - **No Validation**: Size checked only against `saslAuthRequestMaxReceiveSize`

3. **Parsing Stage 1**: `SaslServerAuthenticator.authenticate()` line 250-304
   - Extracts `clientToken = netInBuffer.payload()` (all bytes)
   - Calls `handleKafkaRequest(clientToken)` for handshake, then `handleSaslToken()` for auth

4. **Parsing Stage 2**: `handleKafkaRequest()` line 507
   - `RequestHeader.parse(requestBuffer)` — extracts API key, version, correlation ID, client ID
   - Validates apiKey is `SASL_HANDSHAKE` or `API_VERSIONS` only
   - Throws `InvalidRequestException` if not valid Kafka format

5. **Mechanism Negotiation**: `handleHandshakeRequest()` line 549
   - `String mechanism = handshakeRequest.data().mechanism()` — **UNTRUSTED MECHANISM NAME**
   - Validates against `enabledMechanisms` list
   - Creates `SaslServer` for mechanism using `Sasl.createSaslServer()`

6. **PLAIN Token Processing**: `PlainSaslServer.evaluateResponse()` line 71
   - Converts bytes to UTF-8 string: `new String(responseBytes, UTF_8)`
   - **Entry point for PLAIN credentials from untrusted client**
   - `extractTokens(response)` splits on null bytes
   - Extracts `[authorizationId, username, password]`
   - Username validated: non-empty check only
   - Password validated: non-empty check only

7. **Callback**: `PlainServerCallbackHandler.handle()` line 101
   - `NameCallback` populated with username
   - `PlainAuthenticateCallback` populated with password
   - Handler validates credentials against configured credential provider

8. **Authorization ID Validation**: `PlainSaslServer.evaluateResponse()` line 107-110
   - If client specifies authorizationId, must match username
   - Throws `SaslAuthenticationException` if mismatch

9. **Principal Extraction**: `SaslServerAuthenticator.principal()` line 307-316
   - `SaslAuthenticationContext` created with `saslServer`
   - `principalBuilder.build(context)` invoked
   - For PLAIN: `DefaultKafkaPrincipalBuilder.build()` line 79-84
   - Returns: `new KafkaPrincipal(USER_TYPE, saslServer.getAuthorizationID())`

10. **Authorization**: `Authorizer.authorize()` (synchronous)
    - Uses `KafkaPrincipal` to match against ACL bindings
    - Checks principal type and name from KafkaPrincipal against ACE principal string
    - Evaluates host IP and operation/resource
    - Returns `ALLOWED` or `DENIED`

### Flow 2: SCRAM-SHA-256 Authentication (Complete)
1. **Source**: `NetworkReceive.readFrom()` reads socket bytes

2. **Parsing Stage 1**: `SaslServerAuthenticator.handleKafkaRequest()` → `handleHandshakeRequest()`
   - Same as PLAIN for mechanism negotiation

3. **SCRAM Server Creation**: `SaslChannelBuilder.createServerCallbackHandlers()` line 328-329
   - For SCRAM mechanisms, creates `ScramServerCallbackHandler(credentialCache, tokenCache)`
   - Callback handler has access to hashed credentials from cache

4. **Client First Message**: `ScramSaslServer.evaluateResponse()` line 96-145
   - `new ClientFirstMessage(response)` — **UNTRUSTED BYTES PARSED HERE**
   - Regex pattern matching on UTF-8 decoded message
   - Extracts:
     - `saslName` — username from client (percent-encoded)
     - `nonce` — client's random nonce
     - `authorizationId` — optional authorization ID
     - `extensions` — optional SCRAM extensions

5. **Username Extraction**: `ScramSaslServer.evaluateResponse()` line 108-109
   - `String username = ScramFormatter.username(saslName)` — percent-decoding applied
   - **Entry point: Username extracted from untrusted regex match**

6. **Credential Lookup**: `ScramServerCallbackHandler.handle()` line 115 or 122
   - `NameCallback` with extracted username
   - `ScramCredentialCallback` queries credential cache for username
   - Returns stored salt, iteration count, and hashed credentials

7. **Authorization ID Validation**: `ScramSaslServer.evaluateResponse()` line 129-131
   - Checks if `authorizationIdFromClient` matches username
   - Throws `SaslAuthenticationException` if mismatch

8. **Server First Message**: Line 135-140
   - Returns salt, iteration count, server nonce to client

9. **Client Final Message**: Line 147-162
   - `new ClientFinalMessage(response)` — **UNTRUSTED FINAL MESSAGE PARSED**
   - Validates nonce matches
   - Calls `verifyClientProof()` — HMAC verification of client proof
   - Client proof is derived from hashed password + client/server messages

10. **Proof Verification**: `ScramSaslServer.verifyClientProof()` line 227-237
    - Computes expected stored key from authenticated challenge
    - Compares with client's proof using `MessageDigest.isEqual()`
    - **Timing-safe comparison prevents username/password enumeration attacks**

11. **Principal Extraction**: Same as PLAIN
    - Returns: `new KafkaPrincipal(USER_TYPE, authorizationId)`

12. **Authorization**: Same as PLAIN

### Flow 3: Authorization using KafkaPrincipal
1. **Request Processing**: Broker processes client request

2. **Principal Passed**: `RequestContext` created with authenticated `KafkaPrincipal`

3. **Authorization Check**: `Authorizer.authorize(requestContext, actions)` invoked
   - For default `StandardAuthorizer`: ACL matching using principal type + name

4. **ACL Matching** (lines 216-291 in `Authorizer.java`):
   - Creates `KafkaPrincipal` from request context
   - Iterates all `AclBinding`s for resource
   - Matches:
     - Principal: compares `binding.entry().principal()` to request `KafkaPrincipal`
     - Host: compares `binding.entry().host()` to client IP
     - Operation: compares `binding.entry().operation()` to requested operation
     - Permission: checks ALLOW vs DENY

5. **Decision**: Returns `AuthorizationResult.ALLOWED` or `DENIED`

---

## Dependency Chain (Entry to Sink)

### PLAIN Attack Chain
1. Untrusted Data Entry
   - `NetworkReceive.readFrom()`
   - `SaslServerAuthenticator.authenticate()` → `netInBuffer.payload()`

2. Request Parsing
   - `RequestHeader.parse(ByteBuffer)` — validates Kafka frame format
   - `RequestContext.parseRequest(ByteBuffer)` — validates request schema

3. Mechanism Selection (Validated)
   - `handleHandshakeRequest()` → mechanism name from request
   - Cross-check against `enabledMechanisms` list
   - `createSaslServer(mechanism)` — instantiates correct SaslServer

4. PLAIN Credential Extraction (Untrusted Input)
   - `PlainSaslServer.evaluateResponse(byte[])`
   - UTF-8 decoding: `new String(responseBytes, UTF_8)`
   - Token extraction: `extractTokens(response)` — null byte split
   - Username/password obtained: lines 87-89

5. Credential Verification (Validated)
   - `PlainServerCallbackHandler.handle(Callback[])`
   - Callback handler invokes configured authenticator
   - Credentials checked against credential store

6. Principal Extraction (Validated)
   - `SaslServerAuthenticator.principal()`
   - `DefaultKafkaPrincipalBuilder.build(SaslAuthenticationContext)`
   - Returns `new KafkaPrincipal(USER_TYPE, username)`

7. Authorization Decision (Validated)
   - `Authorizer.authorize(AuthorizableRequestContext, List<Action>)`
   - ACL matching using principal type and name
   - Host IP and operation checks

### SCRAM Attack Chain
Same as PLAIN for steps 1-3, then:

4. SCRAM Message Parsing (Untrusted Input)
   - `ScramSaslServer.evaluateResponse(byte[])`
   - `new ClientFirstMessage(response)` — regex parsing on UTF-8 bytes
   - Regex extraction of username, nonce, extensions

5. Username Extraction (Untrusted Input)
   - `ScramFormatter.username(saslName)` — percent-decoding
   - NameCallback populated with decoded username

6. Credential Lookup (Validated)
   - `ScramServerCallbackHandler` queries credential cache
   - Returns stored salt and hashed password for username

7. Challenge-Response Verification (Validated)
   - `ClientFinalMessage` parsing and validation
   - Nonce verification
   - `verifyClientProof()` — HMAC-based proof verification
   - Timing-safe comparison

8-9. Principal Extraction & Authorization (Same as PLAIN)

---

## Analysis

### SASL Mechanism Architecture

Kafka supports four SASL mechanisms via Java's `javax.security.sasl.SaslServer` interface:

1. **PLAIN (RFC 4616)**: Simple username/password exchange
   - Server receives credentials in clear text over TLS/encrypted channel
   - No mutual authentication
   - Suitable for constrained environments

2. **SCRAM-SHA-256/SHA-512 (RFC 5802)**: Salted Challenge Response
   - Passwords never transmitted in clear
   - Challenge-response with HMAC proof
   - Iterations configured per credential (future-proofing against hash speed improvements)
   - Mutual authentication possible

3. **OAUTHBEARER (RFC 7628)**: JWT-based tokens
   - Bearer tokens from OAuth2 authorization servers
   - JWT signature validation (pluggable validator)
   - Suitable for cloud/multi-tenant environments

4. **GSSAPI (RFC 2743/2744)**: Kerberos-based
   - Mutual authentication via AP-REQ/AP-REP exchange
   - Delegates to system Kerberos library (krb5)
   - Suitable for enterprise environments

### Critical Entry Points & Threat Model

#### Entry Point 1: Network Bytes → Request Header
**Risk Level**: MEDIUM
- **Vulnerability Class**: Potential DoS via malformed requests
- **Data Input**: Untrusted socket bytes
- **Processing**:
  - Size check: `InvalidReceiveException` if exceeds `saslAuthRequestMaxReceiveSize`
  - Format check: `RequestHeader.parse()` validates Kafka wire format
  - API Key check: Only `API_VERSIONS` or `SASL_HANDSHAKE` allowed at this stage
- **Mitigation**:
  - ✓ Size limits enforced
  - ✓ Schema validation in `RequestHeader.parse()`
  - ✓ API key whitelist
- **Gap**: No per-field validation of header contents (correlation ID, client ID) — but these are low-risk
- **Attack Scenario**:
  - Malformed request header could trigger parsing exception
  - Caught and reported as invalid request

#### Entry Point 2: SASL Handshake → Mechanism Selection
**Risk Level**: LOW
- **Vulnerability Class**: Potential auth bypass via mechanism confusion
- **Data Input**: `SaslHandshakeRequest.data().mechanism()` — client-supplied string
- **Processing**:
  - String compared against `enabledMechanisms` list
  - Throws `UnsupportedSaslMechanismException` if not enabled
  - Prevents mechanism downgrade attacks
- **Mitigation**:
  - ✓ Mechanism name must match exactly enabled mechanisms
  - ✓ If client requests unknown mechanism, connection fails
- **Gap**: No validation that mechanism string matches RFC specs, but comparison is exact
- **Attack Scenario**:
  - Client requests "PLAIN" when only "SCRAM-SHA-256" enabled → denied
  - Potential for typosquatting only if broker misconfigured

#### Entry Point 3: PLAIN Credentials → UTF-8 Decoding
**Risk Level**: MEDIUM (Information Disclosure)
- **Vulnerability Class**: Potential username/password enumeration via timing differences
- **Data Input**: Raw `byte[]` from client → `String(responseBytes, UTF_8)`
- **Processing**:
  - No validation of UTF-8 validity (invalid UTF-8 results in replacement characters)
  - Token splitting on null byte (0x00)
  - Username/password extracted without sanitization
- **Mitigation**:
  - ✓ `extractTokens()` validates token count (must be 3)
  - ✓ Username/password non-empty checks
  - ✓ Credential verification delegated to callback handler
- **Gap**:
  - No explicit UTF-8 validation — could cause garbled usernames
  - No length limits on username/password fields (only implicit in receive size)
- **Attack Scenario**:
  - Client sends non-UTF-8 bytes → replacement characters used as username
  - Potential false positive/negative in credential lookup if handler not strict
  - Information Disclosure: `SaslAuthenticationException` message includes "Invalid username or password" — does not leak which field failed in PLAIN (line 106)

#### Entry Point 4: SCRAM Messages → Regex Parsing
**Risk Level**: HIGH (ReDoS Vulnerability Potential)
- **Vulnerability Class**: Regular Expression Denial of Service (ReDoS)
- **Data Input**: UTF-8 decoded client message → Regex matching
- **Processing** (line 68-74 in ScramMessages.java):
  ```
  n,(a=(?<authzid>SASLNAME))?,%sn=(?<saslname>SASLNAME),r=(?<nonce>PRINTABLE)(?<extensions>EXTENSIONS)

  SASLNAME = "(?:[\\x01-\\x7F&&[^=,]]|=2C|=3D)+"  (ONE OR MORE of allowed chars)
  PRINTABLE = "[\\x21-\\x7E&&[^,]]+"            (ONE OR MORE of allowed chars)
  EXTENSIONS = "(,%s=%s)*"                      (ZERO OR MORE extensions)
  ```
- **ReDoS Risk Analysis**:
  - `SASLNAME` has `+` quantifier on alternation `(?:...|...)+`
  - `PRINTABLE` has `+` quantifier
  - Overlapping character classes could cause backtracking
  - Example attack: username with many equal signs (`=2C`) could trigger exponential backtracking

- **Mitigation**:
  - ✓ Message size limited by `saslAuthRequestMaxReceiveSize`
  - ✓ Single regex call per message (not nested loops)
  - ? No explicit regex complexity analysis in comments

- **Gap**:
  - Regex patterns not analyzed for ReDoS vulnerability
  - No regex timeout enforcement (reliant on JVM regex engine)

- **Attack Scenario**:
  - Client sends SCRAM ClientFirstMessage: `n,,n=A=2C=2C=2C...=2C,r=nonce` (many percent-encoded equals)
  - Regex matcher backtracks excessively
  - CPU spike, potential denial of service
  - **Mitigation effectiveness**: Limited by message size only (~1MB default)

#### Entry Point 5: SCRAM Client First Message → Username Extraction
**Risk Level**: MEDIUM (Injection Vulnerability)
- **Vulnerability Class**: Percent-encoding bypass / SASLNAME parsing
- **Data Input**: `clientFirstMessage.saslName()` — regex-extracted string
- **Processing**:
  ```
  saslName = "(?:[\\x01-\\x7F&&[^=,]]|=2C|=3D)+"
  ```
  - Allowed: any character except `=`, `,`, and those < 0x01 or > 0x7F
  - Encoding: `=2C` for `,` and `=3D` for `=`
  - `ScramFormatter.username(saslName)` decodes percent-encoding

- **Mitigation**:
  - ✓ Percent-decoding implemented correctly (standard RFC 5802)
  - ✓ No shell metacharacters allowed (charset strictly limited)

- **Gap**:
  - No validation that decoded username is non-empty
  - Credential cache lookup could fail silently if username contains unexpected characters

- **Attack Scenario**:
  - Client sends `n,,n==2C,r=nonce` → decoded username is `,`
  - Credential lookup for `,` might fail or return wrong user
  - Unlikely to cause auth bypass if credential handler strict

#### Entry Point 6: SCRAM Challenge-Response → Proof Verification
**Risk Level**: LOW (Well-Mitigated)
- **Vulnerability Class**: Authentication bypass via weak proof verification
- **Data Input**: `ClientFinalMessage.proof()` — base64-decoded client proof
- **Processing** (lines 227-237 in ScramSaslServer.java):
  - Computes `expectedStoredKey` from SCRAM credential
  - Computes `clientSignature` from client first/final messages + stored key
  - Derives `computedStoredKey = HMAC(clientSignature XOR proof)`
  - Comparison: `MessageDigest.isEqual(computedStoredKey, expectedStoredKey)` — **timing-safe**

- **Mitigation**:
  - ✓ Timing-safe comparison prevents timing attacks
  - ✓ Proof is HMAC-based, cryptographically sound
  - ✓ Salt and iteration count checked (line 133-134)

- **Gap**: None identified in proof verification logic

- **Attack Scenario**:
  - Attacker cannot forge proof without password
  - Brute-force mitigated by iteration count (default 4096+)

#### Entry Point 7: Principal Extraction → Authorization
**Risk Level**: MEDIUM (Principal Confusion)
- **Vulnerability Class**: Principal type confusion / ACL bypass
- **Data Input**: `saslServer.getAuthorizationID()` → `KafkaPrincipal` constructor
- **Processing**:
  ```java
  new KafkaPrincipal(KafkaPrincipal.USER_TYPE, authorizationId)  // line 84 in DefaultKafkaPrincipalBuilder
  ```
  - Principal type hardcoded as `"User"`
  - Name taken directly from SASL mechanism's authorizationId

- **Mitigation**:
  - ✓ Pluggable `KafkaPrincipalBuilder` interface allows customization
  - ✓ Default builder safe for PLAIN/SCRAM/OAUTHBEARER (all return username)

- **Gap**:
  - Custom principal builders could return incorrect types
  - No validation that principal name matches authenticated identity

- **Attack Scenario**:
  - Custom principal builder could map PLAIN user "alice" to principal type "Admin"
  - ACL system trusts principal type from builder
  - Privilege escalation if ACL grants "Admin:*" permissions
  - **Mitigation**: Custom builders must be vetted by administrators

#### Entry Point 8: ACL Authorization → Principal Matching
**Risk Level**: MEDIUM (ACL Bypass)
- **Vulnerability Class**: ACL matching logic errors
- **Data Input**: `KafkaPrincipal` from authentication
- **Processing** (lines 216-291 in Authorizer.java):
  ```
  KafkaPrincipal principal = new KafkaPrincipal(
      requestContext.principal().getPrincipalType(),
      requestContext.principal().getName());
  String hostAddr = requestContext.clientAddress().getHostAddress();

  for (AclBinding binding : acls(aclFilter)) {
      if (!binding.entry().host().equals(hostAddr) && !binding.entry().host().equals("*"))
          continue;  // Host mismatch

      if (!SecurityUtils.parseKafkaPrincipal(binding.entry().principal()).equals(principal)
              && !binding.entry().principal().equals("User:*"))
          continue;  // Principal mismatch

      if (binding.entry().operation() != op
              && binding.entry().operation() != AclOperation.ALL)
          continue;  // Operation mismatch

      // Permission check: DENY > ALLOW
  }
  ```

- **Mitigation**:
  - ✓ Host IP check (literal or wildcard `*`)
  - ✓ Principal check (literal or wildcard `User:*`)
  - ✓ Operation check (literal or `ALL`)
  - ✓ DENY permission type wins over ALLOW

- **Gap**:
  - Host matching uses `InetAddress.getHostAddress()` — could be IPv6, may not match DNS
  - Principal wildcard `User:*` grants to all users (design choice, not bug)
  - No validation that principal name is non-empty

- **Attack Scenario**:
  - ACL specifies host `192.168.1.1/24` but API receives IP in different notation → mismatch
  - Denied access when should be allowed
  - **Mitigation**: Use CIDR matching in ACL system (out of scope for authenticator)

### Specific Mechanism Analysis

#### PLAIN Mechanism
- **Strengths**:
  - Simple, low overhead
  - Works with cleartext credentials in config

- **Weaknesses**:
  - Credentials sent in plaintext over wire (mitigated by requiring TLS)
  - No mutual authentication
  - No forward secrecy

- **Security Assumptions**:
  - TLS/SSL encryption of wire traffic (SASL_SSL or SASL_PLAINTEXT + network-level encryption)
  - Credential handler prevents brute-force (rate limiting, lockout)

- **Known Issues**:
  - Information disclosure: SASL mechanisms must be careful with error messages
  - Current implementation: `SaslAuthenticationException("Authentication failed: Invalid username or password")` — does not leak which field failed ✓

#### SCRAM Mechanism (SHA-256/SHA-512)
- **Strengths**:
  - Passwords never transmitted in plaintext
  - Challenge-response prevents replay attacks
  - Iteration count future-proofs against hash speed improvements
  - Mutual authentication possible (server proof included)
  - HMAC-based proof verification

- **Weaknesses**:
  - Requires storing salted+hashed passwords (no cleartext)
  - Vulnerability to offline dictionary attacks if credential store compromised

- **Security Assumptions**:
  - Credential store (ZooKeeper, etc.) is adequately protected
  - Hash function (SHA-256/512) remains cryptographically secure
  - Salt is random and unique per credential

- **SCRAM Implementation Issues**:
  - Regex parsing vulnerability (ReDoS potential) — mitigated by message size limit
  - Percent-encoding handling — correct per RFC 5802
  - Proof verification uses timing-safe comparison ✓

#### OAUTHBEARER Mechanism
- **Strengths**:
  - Integrates with OAuth2 ecosystem
  - Short-lived tokens reduce compromise risk
  - Delegation to external identity provider

- **Weaknesses**:
  - JWT signature validation is critical — misconfiguration could bypass auth
  - Token refresh mechanism required for long-lived sessions
  - External dependency on OAuth provider availability

- **Security Assumptions**:
  - JWT validator implementation is correct (pluggable, high risk)
  - Token issuer public keys are authentic
  - Token expiration is enforced

- **Current Implementation Issues**:
  - Unsecured validator callback handler available for testing — **CRITICAL for production disablement**
  - Custom validator implementations must validate expiration and issuer

#### GSSAPI/Kerberos Mechanism
- **Strengths**:
  - Mutual authentication via AP-REQ/AP-REP
  - Session key establishment for message protection
  - Delegated to system Kerberos library (well-tested)
  - Enterprise integration

- **Weaknesses**:
  - Complex setup (requires KDC, principal, keytab)
  - Time synchronization critical (skew tolerance configurable)
  - Delegation to native library — potential for JNI vulnerabilities

- **Security Assumptions**:
  - KDC is trustworthy and secure
  - Keytabs are protected (OS file permissions)
  - Native GSS library implementation is secure

- **Current Implementation Issues**:
  - None critical identified in Kafka codebase (delegated to Java/native libs)

### SASL Token Validation Strategy

**Issue**: SASL tokens arrive as untrusted bytes and must be parsed. Kafka uses:

1. **Size-based DoS prevention**:
   - `saslAuthRequestMaxReceiveSize` default: 102400 (100KB)
   - Prevents extremely large tokens
   - Attack: 100KB malicious SCRAM message with ReDoS pattern

2. **Format validation**:
   - UTF-8 decoding (PLAIN, SCRAM)
   - Regex parsing (SCRAM)
   - Kerberos ASN.1 parsing (delegated to GSS library)

3. **Content validation**:
   - PLAIN: Token count, username/password non-empty
   - SCRAM: Regex match, nonce format, proof HMAC verification
   - OAUTHBEARER: JWT signature and expiration
   - GSSAPI: Delegated to Kerberos library

### Principal Builder Security

**Critical Code Path**: `DefaultKafkaPrincipalBuilder.build(AuthenticationContext)` (lines 69-87)

```java
if (context instanceof SaslAuthenticationContext) {
    SaslServer saslServer = ((SaslAuthenticationContext) context).server();
    if (SaslConfigs.GSSAPI_MECHANISM.equals(saslServer.getMechanismName()))
        return applyKerberosShortNamer(saslServer.getAuthorizationID());
    else
        return new KafkaPrincipal(KafkaPrincipal.USER_TYPE, saslServer.getAuthorizationID());
}
```

**Trust Model**:
- `saslServer.getAuthorizationID()` is trusted (returned from SASL mechanism)
- PLAIN: Returns authenticated username (trusted by credential verification)
- SCRAM: Returns authenticated username (trusted by proof verification + credential lookup)
- OAUTHBEARER: Returns claim from JWT (trusted if validator is correct)
- GSSAPI: Returns Kerberos principal (trusted by KDC)

**Vulnerability**: Custom `KafkaPrincipalBuilder` implementations could:
- Return incorrect principal type
- Map usernames to unintended principals
- Fail to apply transformations (e.g., Kerberos short names)

**Mitigation**: Builders must be audited and configured by trusted administrators.

### Authorization Flow

**Data Flow**:
```
KafkaPrincipal (from auth)
  → AuthorizableRequestContext
  → Authorizer.authorize()
  → ACL matching
  → AuthorizationResult.ALLOWED or DENIED
```

**Key Decision Point**: ACL binding matching (lines 221-265 in `Authorizer.java`)

```
For each AclBinding:
  1. Host match: binding.entry().host() == clientIP or "*"
  2. Principal match: binding.entry().principal() == KafkaPrincipal or "User:*"
  3. Operation match: binding.entry().operation() == requestOp or ALL
  4. Permission type: DENY > ALLOW
```

**Security Properties**:
- ✓ DENY permission type cannot be overridden by ALLOW (correct precedence)
- ✓ Wildcard principal `User:*` grants to all authenticated users (by design)
- ✓ Wildcard host `*` grants to all IPs (by design)
- ? Host matching assumes `InetAddress.getHostAddress()` format matches ACL (potential mismatch for IPv6)

**Missing Validation**: No check that principal name is alphanumeric or conforms to expected format

---

## Existing Mitigations Summary

### Network & Protocol Layer
- ✓ Message size limits (`saslAuthRequestMaxReceiveSize`)
- ✓ Kafka request header validation (API key whitelist)
- ✓ TLS/SSL support (SASL_SSL, SASL_PLAINTEXT modes)

### Authentication Mechanisms
- ✓ PLAIN: Credential verification via callback handler
- ✓ SCRAM: Timing-safe HMAC proof verification
- ✓ OAUTHBEARER: JWT signature validation (if properly configured)
- ✓ GSSAPI: Delegated to secure Kerberos library

### Principal Extraction
- ✓ Pluggable principal builder interface
- ✓ Default builder maps to authenticated identity

### Authorization
- ✓ ACL-based enforcement
- ✓ DENY permission takes precedence
- ✓ Wildcard matching supported (*, User:*)

### Error Handling
- ✓ Generic error messages (avoid leaking credential details)
- ✓ Detailed errors logged server-side, generic sent to client

---

## Critical Gaps & Recommendations

### 1. SCRAM Regex ReDoS Vulnerability
**Severity**: MEDIUM (requires large message + crafted content)
**Recommendation**: Add regex timeout or input length validation per field
```
Option 1: Use pattern.setTimeoutMs() or Pattern.compile() with timeout
Option 2: Validate field lengths before regex (max 256 chars for username, nonce, etc.)
```

### 2. UTF-8 Validation in PLAIN Mechanism
**Severity**: LOW (unlikely to cause real-world issues)
**Recommendation**: Explicitly validate UTF-8 before string conversion
```
CharsetDecoder decoder = StandardCharsets.UTF_8.newDecoder();
decoder.onMalformedInput(CodingErrorAction.REPORT);
decoder.decode(ByteBuffer.wrap(responseBytes));
```

### 3. Principal Name Validation
**Severity**: MEDIUM (depends on custom builders)
**Recommendation**: Add optional principal name validation in DefaultKafkaPrincipalBuilder
```
if (name == null || name.isEmpty()) {
    throw new IllegalArgumentException("Principal name cannot be empty");
}
```

### 4. ReDoS Protection in SCRAM
**Severity**: MEDIUM
**Recommendation**:
- Document ReDoS risk in SCRAM implementation
- Consider field-level length limits (username < 256, nonce < 512)
- Add regex execution time monitoring

### 5. Host Matching in ACL Enforcement
**Severity**: LOW (IPv6 notation mismatch)
**Recommendation**:
- Normalize IPv6 addresses before ACL matching
- Consider CIDR matching for future versions
- Document IPv6 handling in authorizer

### 6. Credential Store Security (Configuration)
**Severity**: HIGH (out of scope but critical)
**Recommendation**:
- For SCRAM: Protect ZooKeeper/credential store with strong ACLs
- For PLAIN: Use cleartext credentials in secure config management
- For OAUTHBEARER: Validate JWT issuer certificates
- Recommendation: Never store plaintext passwords in broker configs

---

## Summary

Kafka's SASL authentication flow implements a multi-layer security model:

1. **Network Entry**: Untrusted bytes received from socket, size-limited and validated as Kafka requests
2. **Mechanism Selection**: Client-supplied mechanism validated against enabled mechanisms list
3. **Token Processing**: Mechanism-specific parsers (PLAIN UTF-8, SCRAM regex, OAUTHBEARER JWT, GSSAPI ASN.1)
4. **Credential Verification**: Challenge-response (SCRAM) or callback-based (PLAIN) verification against credential store
5. **Principal Extraction**: Authenticated identity mapped to KafkaPrincipal via pluggable builder
6. **Authorization**: ACL-based enforcement using principal type, name, host IP, and operation

**Strengths**:
- Pluggable architecture (mechanisms, callbacks, principal builders, authorizers)
- Timing-safe comparisons for sensitive operations
- Multiple mechanism options for different threat models
- Size and format validation at network layer

**Weaknesses**:
- SCRAM regex parsing vulnerable to ReDoS (mitigated by message size)
- Principal builder trust model relies on administrator configuration
- Limited validation of principal names and fields
- Host matching assumes specific IP format (potential IPv6 issues)

**Attack Surface**:
- Untrusted client data enters at NetworkReceive, validated through request header and mechanism selection
- Mechanism-specific parsers are critical: UTF-8 decoding (PLAIN), regex (SCRAM), JWT validation (OAUTHBEARER)
- Credential verification is mechanism-specific: callback handlers (PLAIN/SCRAM), validators (OAUTHBEARER), KDC (GSSAPI)
- Principal extraction trusts SASL mechanism output (validated by authentication)
- Authorization relies on ACL matching logic (validates host, principal, operation)

**Recommendation**: Organizations should:
1. Use SCRAM-SHA-256+ in production (not PLAIN unless over TLS with strong credential management)
2. Implement strong credential store protection (especially for SCRAM salted hashes)
3. Monitor and audit authentication failures
4. Keep Kerberos libraries updated (GSSAPI) and JWT validators current (OAUTHBEARER)
5. Apply principle of least privilege to ACLs (explicit allow rather than wildcard User:*)
