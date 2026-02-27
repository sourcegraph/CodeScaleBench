# Kafka SASL Authentication Flow Security Analysis

## Files Examined

### Channel Builders & Network Layer
- `clients/src/main/java/org/apache/kafka/common/network/ChannelBuilders.java` — Factory for creating SASL channel builders based on security protocol
- `clients/src/main/java/org/apache/kafka/common/network/SaslChannelBuilder.java` — Creates SASL authenticators, manages callback handlers per mechanism
- `clients/src/main/java/org/apache/kafka/common/network/Authenticator.java` — Base interface for channel authenticators
- `clients/src/main/java/org/apache/kafka/common/network/NetworkReceive.java` — Size-delimited buffer for receiving untrusted client data

### SASL Authenticators
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java` — Server-side SASL state machine, receives and parses client requests
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslClientAuthenticator.java` — Client-side SASL implementation

### SASL Mechanism Implementations
- `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainSaslServer.java` — SASL/PLAIN mechanism, parses UTF8NUL-delimited credentials
- `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainServerCallbackHandler.java` — Validates PLAIN credentials against JAAS config
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java` — SASL/SCRAM mechanism, implements RFC 5802 challenge-response
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramServerCallbackHandler.java` — Retrieves SCRAM credentials from credential cache
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramMessages.java` — SCRAM message parsing and validation
- `clients/src/main/java/org/apache/kafka/common/security/oauthbearer/internals/OAuthBearerSaslServer.java` — OAuth Bearer token validation
- `clients/src/main/java/org/apache/kafka/common/security/oauthbearer/internals/unsecured/OAuthBearerUnsecuredValidatorCallbackHandler.java` — Unsecured JWT validation
- `clients/src/main/java/org/apache/kafka/common/security/kerberos/KerberosClientCallbackHandler.java` — GSSAPI/Kerberos implementation

### Principal Extraction
- `clients/src/main/java/org/apache/kafka/common/security/auth/KafkaPrincipal.java` — Authenticated principal representation
- `clients/src/main/java/org/apache/kafka/common/security/auth/KafkaPrincipalBuilder.java` — Interface for deriving principals from authentication context
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/DefaultKafkaPrincipalBuilder.java` — Default principal builder, applies GSSAPI short naming rules
- `clients/src/main/java/org/apache/kafka/common/security/auth/SaslAuthenticationContext.java` — Context passed to principal builder containing SaslServer

### Authorization
- `clients/src/main/java/org/apache/kafka/server/authorizer/Authorizer.java` — Interface for ACL enforcement
- `clients/src/main/java/org/apache/kafka/server/authorizer/Action.java` — Resource and operation for authorization check
- `clients/src/main/java/org/apache/kafka/server/authorizer/AuthorizableRequestContext.java` — Request context with authenticated principal

### Supporting Infrastructure
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/CredentialCache.java` — Thread-safe credential storage
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/LoginManager.java` — JAAS login lifecycle management
- `clients/src/main/java/org/apache/kafka/common/security/JaasContext.java` — JAAS configuration loader

---

## Entry Points

### 1. **Network Data Reception** (SaslServerAuthenticator:264)
- **File**: `SaslServerAuthenticator.java:264`
- **Method**: `authenticate()`
- **Accepts**: Untrusted client network data via `TransportLayer.readFrom()`
- **Type**: Opaque byte array of up to `saslAuthRequestMaxReceiveSize` (default 1MB)
- **Untrusted Content**: Complete protocol messages from potentially malicious clients

### 2. **Request Header Parsing** (SaslServerAuthenticator:510)
- **File**: `SaslServerAuthenticator.java:510`
- **Method**: `handleKafkaRequest()`
- **Accepts**: Client-provided `RequestHeader` containing API key and version
- **Type**: Client explicitly selects which Kafka API to invoke (ApiVersions or SaslHandshake)
- **Vulnerability**: No SASL handshake integrity; mechanism selection is unprotected

### 3. **SASL Mechanism Selection** (SaslServerAuthenticator:550)
- **File**: `SaslServerAuthenticator.java:550`
- **Method**: `handleHandshakeRequest()`
- **Accepts**: Client-specified SASL mechanism name from `SaslHandshakeRequest.mechanism()`
- **Type**: String matching one of enabled mechanisms (PLAIN, SCRAM-SHA-256, OAUTHBEARER, GSSAPI)
- **Vulnerability**: Mechanism is client-chosen; server enforces match against enabled list but no binding to connection identity

### 4. **PLAIN Credential Parsing** (PlainSaslServer:85)
- **File**: `PlainSaslServer.java:85`
- **Method**: `evaluateResponse()`
- **Accepts**: Raw bytes from client, interpreted as UTF-8 string with NUL delimiters
- **Type**: Client SASL response token containing `[authzid]\0authcid\0passwd`
- **Vulnerability**: Parses untrusted UTF-8 string; no size limits on individual tokens

### 5. **SCRAM Message Parsing** (ScramSaslServer:100)
- **File**: `ScramSaslServer.java:100`
- **Method**: `evaluateResponse()`
- **Accepts**: Client SCRAM message bytes (ClientFirstMessage, ClientFinalMessage)
- **Type**: Structured SCRAM protocol messages with embedded username and proof
- **Vulnerability**: Complex SCRAM message parsing including base64 decoding, nonce handling

### 6. **Credential Lookup** (PlainServerCallbackHandler:65, ScramServerCallbackHandler:67)
- **Files**:
  - `PlainServerCallbackHandler.java:65`
  - `ScramServerCallbackHandler.java:67`
- **Methods**: `authenticate()`, `handle()`
- **Accepts**: Username extracted from client SASL message
- **Type**: String used as JAAS config key prefix (PLAIN) or credential cache lookup key (SCRAM)
- **Vulnerability**: Arbitrary strings from client used for configuration/cache lookups

---

## Data Flow

### Flow 1: PLAIN Authentication
```
1. Source: SaslServerAuthenticator.authenticate():264
   - networkReceive.readFrom(transportLayer) reads client bytes

2. Parse: SaslServerAuthenticator.handleKafkaRequest():510
   - RequestHeader.parse() extracts API key (must be SASL_HANDSHAKE)
   - SaslHandshakeRequest parsed to extract mechanism string

3. Mechanism Selection: SaslServerAuthenticator.createSaslServer():201
   - Client-provided mechanism checked against enabledMechanisms list
   - Callback handler retrieved from map keyed by mechanism
   - JAAS Subject retrieved from map keyed by mechanism
   - Sasl.createSaslServer() invoked with PlainServerCallbackHandler

4. Token Exchange: SaslServerAuthenticator.handleSaslToken():421
   - Client sends SASL response token containing PLAIN credentials
   - PlainSaslServer.evaluateResponse():85 called with token bytes
   - String decoded from UTF-8, split on NUL delimiters

5. Credential Verification: PlainServerCallbackHandler.authenticate():61
   - Username extracted from token used to lookup JAAS config entry
   - JAAS key = "user_" + username (from untrusted client)
   - Expected password retrieved from JAAS configuration
   - Constant-time comparison with client-provided password

6. Principal Extraction: SaslServerAuthenticator.principal():312
   - DefaultKafkaPrincipalBuilder.build() called with SaslAuthenticationContext
   - SaslServer.getAuthorizationID() returns username from PLAIN server
   - KafkaPrincipal created with type="User", name=username

7. Sink: Authorizer.authorize() - sensitive operation
   - Principal used to enforce ACLs on subsequent requests
```

**Dependency Chain**:
1. `SaslServerAuthenticator.authenticate()` — entry point
2. `TransportLayer.readFrom()` — receives untrusted bytes
3. `SaslServerAuthenticator.handleKafkaRequest()` — parses request header
4. `RequestHeader.parse()` — parses RequestHeader
5. `SaslHandshakeRequest` parsing — extracts mechanism
6. `Sasl.createSaslServer()` — creates SASL server with callback handler
7. `PlainSaslServer.evaluateResponse()` — parses PLAIN token
8. `PlainServerCallbackHandler.authenticate()` — verifies credentials
9. `SaslServerAuthenticator.principal()` — extracts principal
10. `DefaultKafkaPrincipalBuilder.build()` — builds KafkaPrincipal
11. `Authorizer.authorize()` — enforces ACLs based on principal

---

### Flow 2: SCRAM Authentication
```
1. Source: SaslServerAuthenticator.authenticate():264
   - networkReceive.readFrom(transportLayer) reads client bytes

2. Parse: SaslServerAuthenticator.handleKafkaRequest():510
   - Same as PLAIN: mechanism selection via SaslHandshakeRequest

3. SCRAM Server Creation: SaslServerAuthenticator.createSaslServer():201
   - Sasl.createSaslServer() invoked with ScramServerCallbackHandler

4. ClientFirstMessage: ScramSaslServer.evaluateResponse():96
   - Client SCRAM message parsed by ClientFirstMessage class
   - Username extracted: clientFirstMessage.clientFirstMessageBareWithoutProof()
   - Nonce, channel binding, extensions parsed from client data

5. Credential Lookup: ScramServerCallbackHandler.handle():53
   - NameCallback.getDefaultName() returns username from client message
   - credentialCache.get(username) retrieves ScramCredential
   - Cache lookup with untrusted username string

6. Challenge Response: ScramSaslServer state machine
   - Server issues challenge with random salt and iteration count
   - Client responds with ClientFinalMessage containing proof
   - Server verifies HMAC proof using cached credential
   - ScramFormatter applies password algorithm (SCRAM-SHA-256)

7. Principal Extraction: Same as PLAIN
   - SaslServer.getAuthorizationID() returns username
   - DefaultKafkaPrincipalBuilder creates KafkaPrincipal

8. Sink: Authorizer.authorize()
```

**Dependency Chain**:
1. `SaslServerAuthenticator.authenticate()` — entry point
2. `TransportLayer.readFrom()` — receives untrusted bytes
3. `SaslServerAuthenticator.handleKafkaRequest()` — parses request
4. `SaslHandshakeRequest` parsing — extracts mechanism
5. `Sasl.createSaslServer()` — creates SCRAM server
6. `ScramSaslServer.evaluateResponse()` — parses SCRAM message
7. `ClientFirstMessage` constructor — parses client data
8. `ScramServerCallbackHandler.handle()` — retrieves credential
9. `CredentialCache.get()` — looks up credential by username
10. `HMAC verification` — verifies client proof
11. `SaslServerAuthenticator.principal()` — extracts principal
12. `Authorizer.authorize()` — enforces ACLs

---

### Flow 3: GSSAPI (Kerberos) Authentication
```
1. Source: Network receive (same as PLAIN/SCRAM)

2. Mechanism Selection: Same handshake process
   - Client requests GSSAPI mechanism

3. GSSAPI Server Creation: SaslServerAuthenticator.createSaslKerberosServer():219
   - Service principal parsed from server's Kerberos subject
   - KerberosName.parse() applied to principal
   - Sasl.createSaslServer() invoked with default SaslServerCallbackHandler

4. GSS Token Exchange: (delegated to JDK implementation)
   - GSSContext.acceptSecurityContext() processes client tokens
   - Kerberos KDC validation via system credentials

5. Principal Extraction: DefaultKafkaPrincipalBuilder.build():81
   - SaslServer.getAuthorizationID() returns Kerberos principal
   - KerberosName.parse() applied to principal string
   - KerberosShortNamer.shortName() applies configured rewrite rules
   - Vulnerable: Short naming rules can be misconfigured

6. Sink: Authorizer.authorize()
```

---

## Analysis

### Vulnerability Class: **Authentication Data Injection & Principal Spoofing**

#### 1. **Username-Based Cache Poisoning (SCRAM/Delegation Token)**
- **Location**: ScramServerCallbackHandler:67, CredentialCache.get()
- **Issue**: Arbitrary usernames from client SCRAM message used to lookup credentials
- **Impact**:
  - If credential cache is improperly populated (e.g., offline mode without validation)
  - Attacker can request specific usernames to trigger credential lookups
  - Could reveal timing information about user existence via cache hits/misses
- **Mitigation**: Cache is populated from trusted Zookeeper/KRaft controller; untrusted clients cannot add entries
- **Gap**: No per-request quota on credential lookups; DoS via high-cardinality usernames

#### 2. **PLAIN Credential Parsing - Format Injection**
- **Location**: PlainSaslServer:85, extractTokens():116
- **Issue**: Client provides UTF-8 encoded string with NUL delimiters; parser tolerates malformed input
  - Extra tokens beyond 3 ignored: `extractTokens()` breaks on first 4 NULs
  - Empty authzid allowed (line 87: empty check only on authzid != username case)
  - UTF-8 decoding could fail or produce unexpected characters
- **Impact**:
  - Username containing control characters may bypass JAAS config lookup
  - Misconfiguration: if JAAS allows special usernames, attacker could authenticate as unintended user
- **Mitigation**: Constant-time comparison prevents password guessing; JAAS config is trusted
- **Gap**: No validation on username/password format; misconfigured brokers could allow injection

#### 3. **Mechanism Negotiation Without Binding**
- **Location**: SaslServerAuthenticator:550, handleHandshakeRequest()
- **Issue**: Client selects SASL mechanism; server accepts any enabled mechanism for the connection
- **Impact**:
  - **Downgrade Attack**: Broker could support SCRAM-SHA-512 and PLAIN; attacker connects with PLAIN if server hasn't disabled it
  - **Mechanism Confusion**: If broker enables both SCRAM and delegation tokens, confusion about token type
  - **No Channel Binding**: Mechanism choice not bound to TLS channel; MITM on PLAINTEXT connection could inject fake mechanism
- **Mitigation**:
  - Brokers can disable PLAIN in production (`sasl.enabled.mechanisms`)
  - SASL_SSL protocol provides channel binding via TLS
- **Gap**:
  - PLAINTEXT mode has no protection against MITM mechanism injection
  - RFC 5802 (SCRAM) recommends channel binding; Kafka uses optional binding
  - No per-connection mechanism lock; re-auth could use different mechanism (mitigated: re-auth enforces same mechanism, line 656)

#### 4. **Request Header Parsing Before SASL State Validation**
- **Location**: SaslServerAuthenticator:507, handleKafkaRequest()
- **Issue**: Client provides RequestHeader with API key; server parses before full SASL state validation
  - First request must be ApiVersions or SaslHandshake (line 515)
  - RequestHeader parsing uses RequestContext which normalizes request structure
- **Impact**:
  - Malformed RequestHeader could cause parsing exceptions
  - Error messages may leak information about broker capabilities
- **Mitigation**: Invalid API key throws InvalidRequestException with generic message (line 542-543)
- **Gap**: Error messages for old clients mention "KIP-43 support" which leaks protocol version info

#### 5. **Credential Lifetime Token Authority**
- **Location**: ScramSaslServer:671, ScramServerCallbackHandler:62
- **Issue**: SCRAM server can set `CREDENTIAL_LIFETIME_MS_SASL_NEGOTIATED_PROPERTY_KEY` from credential
  - Returned to client as `sessionLifetimeMs` (SaslServerAuthenticator:468)
  - Client decides when to reauthenticate based on server's lifetime
- **Impact**:
  - If credential contains attacker-controlled lifetime (via credential injection), client reauthentication can be delayed
  - Mitigated by broker-side `connections.max.reauth.ms` config (line 674)
- **Mitigation**: Broker enforces minimum reauthentication via `connections.max.reauth.ms`
- **Gap**: No validation that credential lifetime is within acceptable range; depends on credential cache integrity

#### 6. **Principal Builder Pluggability Without Integrity Check**
- **Location**: SaslServerAuthenticator:193, ChannelBuilders:225
- **Issue**: `KafkaPrincipalBuilder` is pluggable via `principal.builder.class` config
- **Impact**:
  - Custom principal builder could extract wrong principal from SaslServer
  - DefaultKafkaPrincipalBuilder relies on SaslServer.getAuthorizationID() which is mechanism-specific
  - GSSAPI short naming (line 93) applies user-configured regex rules
- **Mitigation**:
  - Default implementation uses SaslServer.getAuthorizationID() directly
  - GSSAPI applies configurable KerberosShortNamer rules
- **Gap**:
  - If GSSAPI short naming rules are misconfigured (e.g., overly broad pattern), attacker Kerberos principal could match unintended short name
  - Custom principal builder has no validation; could return ANONYMOUS or arbitrary principals

#### 7. **Callback Handler Resource Exhaustion**
- **Location**: SaslChannelBuilder:145, createServerCallbackHandlers()
- **Issue**: Per-mechanism callback handlers are created at broker startup
  - CredentialCache shared across all connections for given mechanism
  - Each client connection creates a new SaslServer (line 208)
- **Impact**:
  - Attacker with many connections could cause memory exhaustion
  - Per-client SaslServer state (clientFirstMessage, scramCredential) not bounded by client quota
- **Mitigation**:
  - `sasl.server.max.receive.size` limits individual token size (default 1MB)
  - No per-connection quota implemented
- **Gap**:
  - Large number of concurrent SCRAM authentications could exhaust credential cache memory
  - No timeout on authentication exchange; client could stall handshake indefinitely

#### 8. **Information Disclosure in Error Messages**
- **Location**: SaslServerAuthenticator:488, PlainSaslServer:92-108
- **Issue**: Error messages may leak authentication state to unauthenticated clients
  - Line 106: "Invalid username or password" (doesn't distinguish between user existence and wrong password)
  - Line 108: Leaks that authorization ID differs from username
  - Line 489: "invalid credentials with SASL mechanism" generic message (mitigation)
- **Impact**:
  - Attackers can perform user enumeration via precise error messages
  - SCRAM and GSSAPI errors may leak more information than PLAIN
- **Mitigation**:
  - Generic error messages used in production (lines 489-495)
  - SASL spec recommends generic errors
- **Gap**:
  - Some paths still return mechanism-specific errors
  - SCRAM ClientFirstMessage parsing could leak username existence (line 100)

#### 9. **Delegation Token Lifecycle Not Bound to Client Connection**
- **Location**: ScramServerCallbackHandler:58, DelegationTokenCredentialCallback:62
- **Issue**: Delegation token retrieved from cache but not validated against connection identity
- **Impact**:
  - Token could be shared across connections
  - No binding to source IP or other connection metadata
- **Mitigation**:
  - Tokens have global expiration time (line 64: `tokenExpiryTimestamp`)
  - But no per-token revocation or connection binding
- **Gap**:
  - Compromised token on one broker could be used on another
  - No token refresh mechanism during connection lifetime

---

## Existing Mitigations & Gaps

### Strong Mitigations
1. **Constant-Time Password Comparison** (PlainServerCallbackHandler:68)
   - Uses `Utils.isEqualConstantTime()` preventing timing attacks

2. **Per-Mechanism Callback Handlers** (SaslChannelBuilder:145)
   - Each mechanism has dedicated handler; failures in one don't affect others

3. **JAAS Configuration Integrity**
   - JAAS config loaded at broker startup, not from untrusted clients
   - SCRAM credentials from Zookeeper/KRaft controller (trusted source)

4. **Maximum Token Size** (SaslServerAuthenticator:195)
   - `sasl.server.max.receive.size` limits memory consumption per token

5. **Mechanism Validation** (SaslServerAuthenticator:554)
   - Client mechanism must be in enabled list; unsupported mechanisms rejected

### Insufficient Mitigations
1. **No Channel Binding for PLAINTEXT**
   - Mechanism selection not cryptographically bound to connection
   - PLAINTEXT connections vulnerable to MITM mechanism downgrade

2. **Per-Mechanism State Not Bounded**
   - No quota on concurrent authentication attempts per mechanism
   - Resource exhaustion possible via connection storm

3. **Short Naming Rules Not Validated** (DefaultKafkaPrincipalBuilder:93)
   - Kerberos short naming patterns applied without validation
   - Misconfigured regex could match unintended principals

4. **Principal Builder Pluggability Unsupervised**
   - Custom builders have no contract enforcement
   - Could return incorrect/spoofed principals

5. **Credential Lookup Latency Information**
   - Timing of credential cache lookups could reveal user existence
   - No constant-time lookup path

6. **Error Message Sanitization Incomplete**
   - Some authentication errors still leak mechanism-specific details
   - SCRAM ClientFirstMessage parsing error handling not consistent

---

## Attack Scenarios

### Scenario 1: Downgrade to PLAIN Authentication (PLAINTEXT Listener)
```
Prerequisites:
- Broker enables both SCRAM-SHA-256 and PLAIN mechanisms
- Attacker has network access to PLAINTEXT listener

Attack:
1. Attacker connects to broker's PLAINTEXT listener
2. Sends SASL Handshake request with mechanism=PLAIN
3. Broker accepts if PLAIN is enabled
4. Attacker guesses weak passwords on known usernames
5. Constant-time comparison mitigates password timing attacks, but offline brute force still possible

Impact: Authentication bypass if weak passwords used

Mitigation: Disable PLAIN in production, only allow SCRAM/GSSAPI/OAUTHBEARER
```

### Scenario 2: Credential Cache User Enumeration (SCRAM)
```
Prerequisites:
- Broker uses SCRAM authentication
- Credential cache memory usage is not monitored

Attack:
1. Attacker discovers valid username via social engineering or external source
2. Initiates SCRAM ClientFirstMessage with target username
3. Measures response latency from credential cache lookup
4. Repeats with invalid usernames
5. Cache hits on valid usernames are slightly faster (hypothetically)
6. Attacker builds map of valid usernames

Impact: User enumeration, useful for targeted attacks

Mitigation:
- Constant-time credential lookup not implemented
- Generic error messages prevent explicit user existence leaks
- Timing attacks require fine-grained network latency measurement
- Impractical against geographically distant brokers
```

### Scenario 3: Authorization ID Confusion Attack (PLAIN)
```
Prerequisites:
- PLAIN mechanism enabled
- Attackers compromises one user's password
- Kafka ACLs not properly configured

Attack:
1. Attacker obtains password for user "bob"
2. Constructs PLAIN token: alice\0bob\0bob_password
3. Sends token where authzid (alice) != authcid (bob)
4. PlainSaslServer:107 throws error (mitigates this)
5. BUT: If misconfigured to skip authzid check:
   - alice principal could be extracted
   - alice could authorize requests meant for bob

Impact: Principal spoofing if authorization ID validation bypassed

Mitigation:
- Line 107-108: Authorization ID must match username
- No configuration option to disable this check
```

### Scenario 4: Kerberos Short Name Injection (GSSAPI)
```
Prerequisites:
- GSSAPI/Kerberos enabled
- Short naming rules misconfigured (e.g., overly broad regex)

Attack:
1. Attacker obtains Kerberos principal "admin/service.kafka@REALM"
2. Broker's short naming rule: /.*/ -> admin (matches everything)
3. Short naming rule: service.kafka@REALM -> "admin"
4. Attacker's principal maps to "admin" principal
5. Attacker can authenticate and act as "admin"

Impact: Principal spoofing via regex misconfig

Mitigation:
- KerberosShortNamer validates rules at startup (line 93)
- Brokers should test short naming rules in dev environment
- No runtime validation of rule correctness
```

### Scenario 5: Delegation Token Refresh During Re-authentication
```
Prerequisites:
- SCRAM with delegation token support enabled
- Token lifetime < connection lifetime

Attack:
1. Client authenticates with delegation token, lifetime 1 hour
2. After 30 minutes, client initiates re-authentication (line 343)
3. During re-auth, token expiry checked (line 64)
4. If token expired, re-auth fails
5. BUT: New token not issued; connection closed

Impact: Denial of service on long-lived connections with delegated tokens

Mitigation:
- Token refresh expected at application layer (client library)
- Broker enforces `connections.max.reauth.ms` independently (line 674)
- No mechanism to issue new token during re-auth handshake
```

---

## Summary

The Kafka SASL authentication flow implements a well-structured state machine that processes untrusted client data through mechanism-specific handlers with appropriate credential verification.

**Key Security Properties**:
- **Credential Verification**: Constant-time password comparison prevents timing attacks (PLAIN); HMAC verification prevents SCRAM spoofing
- **Mechanism Isolation**: Each SASL mechanism has dedicated handler; failures don't cascade
- **Trusted Credential Source**: SCRAM credentials from Zookeeper/KRaft, not client-provided
- **Principal Extraction**: Derived from SaslServer state, mechanism-specific but consistent

**Primary Vulnerabilities**:
1. **Mechanism Downgrade** (PLAINTEXT only): No cryptographic binding between mechanism choice and connection identity
2. **Short Naming Misconfiguration** (GSSAPI): Regex rules applied without validation; overly broad patterns enable spoofing
3. **Resource Exhaustion**: No per-connection quota on concurrent authentications or token sizes
4. **Pluggable Principal Builder**: Custom builders have no contract enforcement; could return spoofed principals
5. **Timing Information Leakage**: Credential cache lookup latency not constant-time

**Recommended Remediations**:
1. Implement channel binding (RFC 5802) for SCRAM with PLAINTEXT connections
2. Add validation and unit tests for Kerberos short naming rules at broker startup
3. Implement per-connection quota on concurrent authentications and max token accumulation
4. Add interface contract validation for pluggable principal builders (audit-log principal changes)
5. Implement constant-time credential lookup path with fixed delays for cache misses
6. Add connection-level session binding (nonce) to prevent token reuse across connections
7. Enhance error message sanitization: ensure all authentication error paths return identical generic messages
8. Add delegation token refresh mechanism during re-authentication handshake

**Attack Surface Summary**:
- Untrusted entry points: Client SASL tokens, mechanism selection, username strings, credential lookups
- Sensitive operations: Principal extraction, authorization decision, credential cache updates
- Trust boundaries: Network → SASL subsystem → Authorization → ACL enforcement
- Most dangerous path: Mechanism downgrade → PLAIN auth with weak password → principal spoofing via short naming misconfiguration
