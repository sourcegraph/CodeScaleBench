# Apache Kafka SASL Authentication Flow Security Analysis

## Files Examined

### Network/Channel Layer
- `clients/src/main/java/org/apache/kafka/common/network/ChannelBuilders.java` — Factory for creating channel builders (entry point for server-side setup)
- `clients/src/main/java/org/apache/kafka/common/network/ChannelBuilder.java` — Interface for channel building
- `clients/src/main/java/org/apache/kafka/common/network/SaslChannelBuilder.java` — Creates SaslServerAuthenticator and manages callback handlers
- `clients/src/main/java/org/apache/kafka/common/network/KafkaChannel.java` — Wraps authenticator and transport layer, invokes authenticate()
- `clients/src/main/java/org/apache/kafka/common/network/NetworkReceive.java` — Reads size-delimited network data with max size validation
- `clients/src/main/java/org/apache/kafka/common/network/Authenticator.java` — Interface for authentication logic

### SASL Server Authenticator
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java` — Orchestrates SASL handshake and challenge-response, parses untrusted Kafka request headers
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslClientAuthenticator.java` — Client-side SASL authenticator

### PLAIN Mechanism
- `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainSaslServer.java` — PLAIN RFC4616 implementation, parses UTF-8 tokens separated by null bytes
- `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainServerCallbackHandler.java` — Looks up passwords in JAAS config, uses constant-time comparison

### SCRAM Mechanism
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java` — SCRAM-SHA-256/512 RFC5802 implementation, parses client messages and verifies HMAC proofs
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramServerCallbackHandler.java` — Retrieves credentials from CredentialCache or delegation token cache
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramFormatter.java` — SCRAM message formatting and parsing
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramMechanism.java` — Mechanism metadata (SCRAM-SHA-256, SCRAM-SHA-512)

### GSSAPI Mechanism
- Integrated with Java's `javax.security.auth.kerberos` and `org.ietf.jgss`
- `clients/src/main/java/org/apache/kafka/common/security/kerberos/KerberosShortNamer.java` — Applies name rewrite rules to Kerberos principals

### Principal & Authorization
- `clients/src/main/java/org/apache/kafka/common/security/auth/KafkaPrincipal.java` — Represents authenticated user (type + name)
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/DefaultKafkaPrincipalBuilder.java` — Builds KafkaPrincipal from SaslServer's authorization ID
- `clients/src/main/java/org/apache/kafka/common/security/auth/SaslAuthenticationContext.java` — Context passed to principal builder (contains SaslServer, SSL session, client address)
- `clients/src/main/java/org/apache/kafka/server/authorizer/Authorizer.java` — Interface for ACL-based authorization
- `clients/src/main/java/org/apache/kafka/server/authorizer/AuthorizableRequestContext.java` — Context for authorization (principal, request type, listener, client IP)

### Configuration & Credentials
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/CredentialCache.java` — In-memory cache of SCRAM credentials
- `clients/src/main/java/org/apache/kafka/common/security/JaasContext.java` — Loads JAAS configuration for PLAIN

---

## Entry Points

1. **ChannelBuilders.serverChannelBuilder()** — Accepts [listener name, security protocol, config, credential cache, token cache]
   - Creates SaslChannelBuilder with JAAS contexts, one per mechanism (PLAIN, SCRAM, GSSAPI, OAUTHBEARER)
   - Location: `clients/src/main/java/org/apache/kafka/common/network/ChannelBuilders.java:96-108`

2. **SaslChannelBuilder.buildChannel()** — Accepts [channel ID, socket selection key, max receive size, memory pool, metadata registry]
   - Creates KafkaChannel with SaslServerAuthenticator as authenticator supplier
   - Location: `clients/src/main/java/org/apache/kafka/common/network/SaslChannelBuilder.java:215-250`

3. **KafkaChannel.prepare()** — Calls `authenticator.authenticate()`
   - Location: `clients/src/main/java/org/apache/kafka/common/network/KafkaChannel.java:174-198`

4. **SaslServerAuthenticator.authenticate()** — Primary entry point for SASL protocol
   - Accepts untrusted bytes from `NetworkReceive.readFrom()` via socket
   - Location: `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java:250-304`

5. **NetworkReceive.readFrom()** — Reads from socket channel
   - Reads 4-byte network-ordered size, validates against maxSize
   - Then reads up to size bytes of payload
   - Location: `clients/src/main/java/org/apache/kafka/common/network/NetworkReceive.java:82-115`

6. **SaslServerAuthenticator.handleKafkaRequest()** — Parses initial request
   - Accepts untrusted byte array from NetworkReceive payload
   - Parses RequestHeader and dispatches to handleApiVersionsRequest() or handleHandshakeRequest()
   - Location: `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java:507-547`

7. **SaslServerAuthenticator.handleSaslToken()** — Processes SASL tokens
   - Accepts untrusted SASL token bytes
   - For non-Kafka-header mode: passes directly to SaslServer.evaluateResponse()
   - For Kafka-header mode: parses SaslAuthenticateRequest and extracts authBytes
   - Location: `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java:421-500`

8. **PlainSaslServer.evaluateResponse()** — Processes PLAIN authentication
   - Accepts untrusted byte array (client's PLAIN response)
   - Parses as UTF-8 string, extracts 3 null-separated tokens
   - Location: `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainSaslServer.java:71-114`

9. **ScramSaslServer.evaluateResponse()** — Processes SCRAM authentication
   - Accepts untrusted byte array (client's SCRAM message)
   - Parses ClientFirstMessage, extracts username and nonce
   - Location: `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java:96-180`

10. **PlainServerCallbackHandler.authenticate()** — Verifies PLAIN credentials
    - Accepts untrusted username string
    - Looks up in JAAS config using `JaasContext.configEntryOption()`
    - Compares password with constant-time comparison
    - Location: `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainServerCallbackHandler.java:61-70`

---

## Data Flow

### Flow 1: SASL Channel Creation → SASL Handshake → PLAIN Authentication

1. **Source**: Socket connection from untrusted client
   - Untrusted input: Raw bytes from network socket
   - Entry: `NetworkReceive.readFrom(socket channel)` reads 4-byte size + payload

2. **Transport**: NetworkReceive validates and buffers untrusted data
   - File: `clients/src/main/java/org/apache/kafka/common/network/NetworkReceive.java:82-115`
   - **Validation**: Size must be >= 0 and <= maxSize (BrokerSecurityConfigs.SASL_SERVER_MAX_RECEIVE_SIZE_CONFIG, default 256KB)
   - **Action**: Allocates buffer from memoryPool, reads payload

3. **Transform**: SaslServerAuthenticator receives raw bytes
   - File: `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java:250-304`
   - Line 261: `netInBuffer = new NetworkReceive(saslAuthRequestMaxReceiveSize, connectionId)`
   - Line 264: `netInBuffer.readFrom(transportLayer)`
   - Line 270: `netInBuffer.payload().rewind()`
   - Line 272-274: Extracts bytes into `clientToken`

4. **Parse Initial Request**: RequestHeader parsing
   - File: `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java:507-547`
   - Line 509: `ByteBuffer requestBuffer = ByteBuffer.wrap(requestBytes)`
   - Line 510: `RequestHeader header = RequestHeader.parse(requestBuffer)`
   - **Untrusted data**: API key, API version, correlation ID, client ID are all read from untrusted bytes
   - **Validation**: Line 515 checks if apiKey is ApiKeys.API_VERSIONS or ApiKeys.SASL_HANDSHAKE
   - **Risk**: RequestHeader.parse() could throw if malformed

5. **Mechanism Negotiation**: SaslHandshakeRequest parsing
   - File: `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java:549-565`
   - Line 550: `String clientMechanism = handshakeRequest.data().mechanism()`
   - **Untrusted data**: SASL mechanism name from client
   - **Validation**: Line 554 checks if mechanism is in enabledMechanisms list
   - **Action**: If valid, creates SaslServer via createSaslServer() at line 533

6. **Create SASL Server**: Callback handler instantiation
   - File: `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java:200-217`
   - For PLAIN: Line 209: `Sasl.createSaslServer(saslMechanism, "kafka", serverAddress().getHostName(), configs, callbackHandler)`
   - Returns PlainSaslServer with PlainServerCallbackHandler

7. **SASL Token Exchange**: PlainSaslServer.evaluateResponse()
   - File: `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainSaslServer.java:71-114`
   - **Untrusted input**: Raw PLAIN response bytes (format: [authzid]\0authcid\0passwd)
   - Line 85: `String response = new String(responseBytes, StandardCharsets.UTF_8)`
   - **No bounds check on UTF-8 decoding** — entire payload is decoded
   - Line 86: `List<String> tokens = extractTokens(response)`
   - Line 116-134: Splits on null bytes (U+0000), expects exactly 3 tokens
   - **Validation**: Lines 91-96 check that username and password are non-empty

8. **Credential Verification**: PlainServerCallbackHandler.authenticate()
   - File: `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainServerCallbackHandler.java:61-70`
   - Line 65-67: Looks up user via `JaasContext.configEntryOption(jaasConfigEntries, "user_" + username, ...)`
   - **Untrusted data**: Username used directly as dictionary key (with "user_" prefix)
   - **Validation**: Constant-time comparison at line 68: `Utils.isEqualConstantTime(password, expectedPassword.toCharArray())`
   - **Action**: Sets authenticateCallback.authenticated(true/false)

9. **Principal Extraction**: DefaultKafkaPrincipalBuilder.build()
   - File: `clients/src/main/java/org/apache/kafka/common/security/authenticator/DefaultKafkaPrincipalBuilder.java:69-88`
   - Line 80: `SaslServer saslServer = ((SaslAuthenticationContext) context).server()`
   - Line 84: `return new KafkaPrincipal(KafkaPrincipal.USER_TYPE, saslServer.getAuthorizationID())`
   - **Untrusted data**: Authorization ID from PlainSaslServer.authorizationId (set from username at line 110 in PlainSaslServer)
   - **No additional validation** — whatever PlainSaslServer set becomes the principal

10. **Sink**: KafkaChannel.principal() and Authorizer.authorize()
    - File: `clients/src/main/java/org/apache/kafka/common/network/KafkaChannel.java:161-163`
    - Line 162: `return authenticator.principal()`
    - File: `clients/src/main/java/org/apache/kafka/server/authorizer/Authorizer.java:107`
    - `List<AuthorizationResult> authorize(AuthorizableRequestContext requestContext, List<Action> actions)`
    - **Sensitive operation**: ACL-based authorization decision using principal name

### Flow 2: SASL Channel Creation → SASL Handshake → SCRAM-SHA-256 Authentication

1. **Source**: Same as Flow 1 — socket bytes via NetworkReceive

2. **Transport**: Same as Flow 1 — size validation and buffering

3. **Transform**: Same as Flow 1 — SaslServerAuthenticator.authenticate()

4. **Parse Initial Request**: Same as Flow 1 — RequestHeader parsing

5. **Mechanism Negotiation**: Same as Flow 1 — SaslHandshakeRequest parsing with SCRAM mechanism selected

6. **Create SASL Server**: ScramSaslServer instantiation
   - File: `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java:207-216`
   - Line 208: `Sasl.createSaslServer(saslMechanism, "kafka", serverAddress().getHostName(), configs, callbackHandler)`
   - Returns ScramSaslServer with ScramServerCallbackHandler

7. **SCRAM Token Exchange - ClientFirstMessage**: ScramSaslServer.evaluateResponse()
   - File: `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java:99-145`
   - **Untrusted input**: Raw SCRAM ClientFirstMessage bytes
   - Line 100: `this.clientFirstMessage = new ClientFirstMessage(response)`
   - **Message structure** (from RFC 5802): `[reserved-mext ','] [authzid ','] [cbind-input ','] username ',' nonce [',' extensions]`

8. **Parse ClientFirstMessage**: ScramMessages.ClientFirstMessage constructor
   - File: `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramMessages.java`
   - **Untrusted data**: Username, nonce, extensions parsed from message
   - Line 108: `String saslName = clientFirstMessage.saslName()`
   - Line 109: `String username = ScramFormatter.username(saslName)`
   - **No bounds validation** on username length during parsing

9. **Credential Lookup**: ScramServerCallbackHandler.handle()
   - File: `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramServerCallbackHandler.java:52-71`
   - Line 67: `sc.scramCredential(credentialCache.get(username))`
   - **Untrusted data**: Username used as cache key
   - **Validation**: CredentialCache returns null if user not found
   - Line 127-128 in ScramSaslServer: Throws "Invalid user credentials" if null

10. **Credential Verification**: HMAC-based proof verification
    - File: `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java:147-180`
    - Line 149: `ClientFinalMessage clientFinalMessage = new ClientFinalMessage(response)`
    - Line 150: Nonce validation: `!clientFinalMessage.nonce().equals(serverFirstMessage.nonce())`
    - Proof is computed as `ClientProof = ClientKey XOR ClientSignature`
    - **Cryptographic verification**: HMAC-SHA-256/512 prevents tampering
    - Server recomputes expected proof and compares

11. **Principal Extraction**: Same as Flow 1
    - DefaultKafkaPrincipalBuilder.build() extracts username from SaslServer

12. **Sink**: Same as Flow 1 — KafkaChannel.principal() and Authorizer.authorize()

### Flow 3: Re-authentication with mechanism switch attempt

1. **Source**: Existing authenticated connection receives SaslHandshakeRequest for re-auth

2. **Transport**: Same — NetworkReceive buffering

3. **Transform**: SaslServerAuthenticator.reauthenticate()
   - File: `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java:343-357`
   - Line 343-351: Validates saslHandshakeReceive, extracts previous mechanism, principal
   - Line 355: Sets state to REAUTH_PROCESS_HANDSHAKE

4. **Mechanism Validation**: handleHandshakeRequest() during re-auth
   - File: `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java:549-565`
   - Line 532: `if (!reauthInfo.reauthenticating() || reauthInfo.saslMechanismUnchanged(clientMechanism))`
   - **Mitigation**: If mechanism changes, sets REAUTH_BAD_MECHANISM state at line 535
   - **Exception thrown**: SaslAuthenticationException at line 284

5. **Sink**: Authentication fails, connection closed

---

## Dependency Chain

### PLAIN Authentication Chain
1. `SaslChannelBuilder.buildChannel()` creates KafkaChannel
2. `KafkaChannel.prepare()` calls `SaslServerAuthenticator.authenticate()`
3. `SaslServerAuthenticator.authenticate()` reads from `NetworkReceive`
4. `NetworkReceive.readFrom()` reads 4-byte size + payload from socket, validates max size
5. `SaslServerAuthenticator.handleKafkaRequest()` parses RequestHeader (untrusted)
6. `RequestHeader.parse()` reads API key, version, correlation ID
7. `SaslServerAuthenticator.handleHandshakeRequest()` extracts mechanism name (untrusted)
8. `SaslServerAuthenticator.createSaslServer()` instantiates PlainSaslServer
9. `PlainSaslServer.evaluateResponse()` parses UTF-8 string (untrusted)
10. `PlainSaslServer.extractTokens()` splits on null bytes (untrusted)
11. `PlainServerCallbackHandler.handle()` receives username + password callbacks
12. `PlainServerCallbackHandler.authenticate()` looks up in JAAS config (trusted)
13. `Utils.isEqualConstantTime()` compares passwords (safe)
14. `DefaultKafkaPrincipalBuilder.build()` extracts SaslServer.getAuthorizationID() (trusted from server)
15. `KafkaChannel.principal()` returns KafkaPrincipal
16. `Authorizer.authorize()` makes ACL decision using principal

### SCRAM Authentication Chain
1. Steps 1-7 same as PLAIN
2. `SaslServerAuthenticator.createSaslServer()` instantiates ScramSaslServer
3. `ScramSaslServer.evaluateResponse()` processes ClientFirstMessage (untrusted)
4. `ClientFirstMessage` constructor parses SCRAM protocol message
5. `ScramFormatter.username()` extracts username from saslName
6. `ScramServerCallbackHandler.handle()` looks up credentials by username in CredentialCache
7. `CredentialCache.get()` retrieves ScramCredential for username (trusted store)
8. `ScramSaslServer.evaluateResponse()` processes ClientFinalMessage (untrusted)
9. HMAC-SHA-256/512 proof verification (cryptographically secure)
10. `DefaultKafkaPrincipalBuilder.build()` extracts principal
11. Steps 15-16 same as PLAIN

---

## Analysis

### Entry Point Security Properties

#### 1. Network Reception (NetworkReceive)
- **Vulnerability class**: Denial of Service (memory exhaustion)
- **Untrusted input**: 4-byte size field read from socket
- **Existing mitigation**:
  - Size validated at line 92-95: must be >= 0 and <= maxSize
  - maxSize configured via `BrokerSecurityConfigs.SASL_SERVER_MAX_RECEIVE_SIZE_CONFIG` (default 256KB)
  - Memory allocated from memoryPool, which can be exhausted
- **Gaps**:
  - No rate limiting on invalid size attempts
  - No per-connection size tracking (client can keep sending max-size buffers)
  - Memory pressure could cause broker unresponsiveness

#### 2. RequestHeader Parsing (Initial SASL Request)
- **Vulnerability class**: Protocol confusion, invalid API key handling
- **Untrusted input**: Kafka RequestHeader (API key, version, correlation ID, client ID)
- **Existing mitigation**:
  - Line 515: Validates API key is only API_VERSIONS or SASL_HANDSHAKE during handshake
  - InvalidRequestException thrown for unexpected API keys
- **Gaps**:
  - No validation of correlation ID format (could be used for request confusion if proxy in path)
  - Client ID is untrusted string, stored in logs/metrics (could contain injection payloads for log analysis)
  - RequestHeader parsing assumes well-formed Kafka protocol (could throw ParseException)

#### 3. SASL Mechanism Negotiation (SaslHandshakeRequest)
- **Vulnerability class**: Authentication bypass (if custom handlers improperly implement interface)
- **Untrusted input**: SASL mechanism name from client
- **Existing mitigation**:
  - Line 554: Validates mechanism is in enabledMechanisms list
  - Mechanism set in broker config, not client-controlled
  - Default mechanisms: PLAIN, SCRAM-SHA-256, SCRAM-SHA-512, GSSAPI, OAUTHBEARER
- **Gaps**:
  - If custom AuthenticateCallbackHandler implementation is provided, could have validation bugs
  - No audit logging of mechanism selection attempt (would help detect attacks)

#### 4. PLAIN Authentication Mechanism
- **Vulnerability class**: Plaintext credential handling, username enumeration
- **Untrusted input**: UTF-8 encoded string with null separators
- **Parsing vulnerability**:
  - Line 85: `new String(responseBytes, StandardCharsets.UTF_8)` — can decode arbitrary UTF-8
  - No length validation before UTF-8 decoding (could process very long strings)
  - No validation that null separators appear in expected positions
- **Credential lookup vulnerability**:
  - Line 65-67: Username used directly as JAAS config key ("user_" + username)
  - No length limits on username (could be millions of characters)
  - JAAS config lookup is O(n) or dictionary access O(1) depending on implementation
  - **Username enumeration**: If credential lookup raises different exception for missing vs wrong password, attacker learns valid usernames
    - Mitigation at line 103: Catches all Throwable and throws generic "credentials for user could not be verified"
    - Mitigation at line 105-106: Throws generic "Invalid username or password" (no distinction)
  - **Constant-time comparison**: Line 68 uses `Utils.isEqualConstantTime()` — good
- **Gaps**:
  - No rate limiting on failed authentication attempts
  - No account lockout mechanism
  - No audit logging of PLAIN authentication attempts
  - UTF-8 decoding exception not caught — could reveal information

#### 5. SCRAM Authentication Mechanism
- **Vulnerability class**: Partial hash disclosure, nonce guessing
- **Untrusted input**: SCRAM messages (RFC 5802 format)
- **ClientFirstMessage parsing**:
  - Line 100: `new ClientFirstMessage(response)` — parses untrusted bytes
  - Username extracted without bounds checking
  - **No nonce validation**: Line 106 generates nonce but doesn't validate client's nonce format/entropy
  - Client's nonce passed through to ServerFirstMessage
  - Attacker could send predictable/repeating nonces (doesn't break protocol but could leak timing info)
- **Credential verification**:
  - Line 126: Credential is null-checked and raises generic exception
  - No username enumeration (same null exception for missing user and missing credential)
- **Cryptographic verification**:
  - Line 150-180: Proof verification uses HMAC comparison
  - **No constant-time HMAC comparison visible** — need to verify Utils class
  - Iterations validated at line 133-134: must be >= mechanism.minIterations()
  - Salt is base64-decoded from credential (trusted source)
- **Gaps**:
  - No rate limiting on failed authentication attempts
  - No protection against dictionary attacks (iterations count is critical)
  - Nonce could theoretically be exhausted in repeated authentication attempts (2^64 possible)

#### 6. Principal Extraction
- **Vulnerability class**: Authorization bypass (if principal builder has bugs)
- **Untrusted source**: SaslServer.getAuthorizationID() (set by mechanism)
- **PLAIN principal extraction**:
  - Line 84 (DefaultKafkaPrincipalBuilder): `return new KafkaPrincipal(KafkaPrincipal.USER_TYPE, saslServer.getAuthorizationID())`
  - Username from PLAIN response becomes principal name directly
  - **No validation** of principal name format/length
  - Could contain special characters used by authorization system (e.g., wildcards, spaces)
- **SCRAM principal extraction**:
  - Same as PLAIN — username from SCRAM message becomes principal name
  - **Risk**: If authorization system uses `String.contains()` or regex without anchoring, could have injection
- **GSSAPI principal extraction**:
  - Line 82: Applies KerberosShortNamer if GSSAPI
  - KerberosShortNamer could have regex injection vulnerabilities (depends on rules)
- **Gaps**:
  - No validation that principal name matches allowed character set
  - Custom PrincipalBuilder implementations could bypass all validation
  - No serialization validation before storing principal in credential cache

#### 7. Authorization
- **Vulnerability class**: Principal spoofing, privilege escalation
- **Untrusted principal**: Passed to Authorizer.authorize()
- **Existing mitigation**:
  - Principal comes from completed SASL authentication
  - Cannot be set by client directly (would fail SASL)
- **Gaps**:
  - Authorization is only as strong as the Authorizer implementation
  - ACLs are broker-side stored, but principal name is untrusted in format/content
  - If Authorizer uses principal name in security decisions without escaping, could have injection

---

### Authentication Security Properties

#### PLAIN Authentication
- **Security level**: Weak (credentials transmitted in plaintext over SASL_PLAINTEXT)
- **Assumed transport security**: SASL_SSL (TLS encryption) or SASL_PLAINTEXT with network isolation
- **Vulnerability without SSL**:
  - Credentials captured on network by passive observer
  - No authentication of server to client (man-in-the-middle possible)
  - No perfect forward secrecy
- **Replay protection**: None (tokens can be replayed if network is not secure)
- **Mitigation dependency**: Must use SASL_SSL (PLAIN + TLS), not SASL_PLAINTEXT
- **Key derivation**: No key derivation (plaintext comparison)
- **Constant-time comparison**: Yes, `Utils.isEqualConstantTime()`

#### SCRAM Authentication
- **Security level**: Stronger than PLAIN (hash-based, no plaintext credentials on wire)
- **Protocol compliance**: RFC 5802 SCRAM-SHA-256 / SCRAM-SHA-512
- **Credential derivation**:
  - Server stores salted, iterated HMAC-SHA-256/512 of password
  - Client proves knowledge of password without revealing it
- **Replay protection**: Nonce included in each exchange, server-side nonce prevents replay
- **Mitigation dependency**: Still uses TLS (SASL_SSL) for confidentiality and server authentication
- **Iterations**: Configurable (default likely 4096+), increases security against offline attacks
- **Key derivation**: PBKDF2-like with configurable iterations
- **Constant-time comparison**: Should be used but not verified in visible code

#### GSSAPI/Kerberos
- **Security level**: Strongest (mutual authentication, keying material, ticket-based)
- **Protocol compliance**: RFC 1964 (GSS-API), Kerberos v5
- **Ticket authentication**: Client possesses TGT from KDC, proves identity
- **Server authentication**: Client verifies server's ticket with KDC
- **Forward secrecy**: Session key derived per connection
- **Mitigation dependency**: Requires KDC (Kerberos infrastructure), not suitable for all deployments
- **Principal name transformation**: KerberosShortNamer could have regex bugs
- **GSSCredential injection**: maybeAddNativeGssapiCredentials() at line 374-402 in SaslChannelBuilder

#### OAUTHBEARER
- **Security level**: Depends on token issuer and validation implementation
- **Credential bearer**: OAuth 2.0 bearer token (JWT or opaque)
- **Token validation**: OAuthBearerUnsecuredValidatorCallbackHandler (name suggests "unsecured")
- **Mitigation dependency**: Token issuer security (offline or online validation)

---

### Data Validation Vulnerabilities

#### Length-based DoS
1. **PLAIN username length**:
   - Line 85 in PlainSaslServer: UTF-8 string decoded entirely
   - No length check before lookup
   - JAAS config lookup could be slow for very long keys
   - **Mitigation**: None visible
   - **Attack**: Send 1MB username string → broker spends CPU on string operations and config lookup

2. **SCRAM username length**:
   - Similar to PLAIN
   - **Additional**: ClientFirstMessage parsing could fail on malformed SCRAM
   - **Mitigation**: Exceptions caught and treated as auth failure

3. **SASL token size**:
   - NetworkReceive limits overall size (256KB default)
   - **Mitigation**: Adequate

#### UTF-8 Decoding
- **PLAIN mechanism**: Line 85 calls `new String(responseBytes, StandardCharsets.UTF_8)`
- **Risk**: Malformed UTF-8 could throw exception, but exception is handled generically
- **No risk**: Java's UTF-8 decoder is well-tested, won't cause code execution

#### Nonce Handling
- **SCRAM server nonce**: Generated at line 106 with `formatter.secureRandomString()`
- **Client nonce**: Accepted as-is from untrusted source
- **Risk**: If RNG is weak, nonces could be guessable
- **Mitigation**: Java's SecureRandom is cryptographically secure

---

### Configuration Security

#### JAAS Configuration
- **PLAIN passwords stored in**: JAAS config entries (in-memory)
- **Loaded from**: Files or dynamic configuration
- **Plaintext storage**: Passwords visible in config (no encryption at rest)
- **Mitigation**: File permissions, OS-level access control
- **Gap**: No encrypted password support for PLAIN

#### Credential Cache
- **SCRAM credentials stored in**: CredentialCache (in-memory HashMap)
- **Loaded from**: Zookeeper or other metadata store
- **Plaintext storage**: Salted hashes visible in memory
- **Risk**: If JVM is compromised, all credentials accessible
- **Mitigation**: JVM memory protection, secure erasure of cleared credentials

#### Mechanism Selection
- **Enabled mechanisms**: Set in broker config
- **Immutable per broker start**: No dynamic mechanism enable/disable
- **Risk**: If admin mistakenly enables PLAIN over SASL_PLAINTEXT, credentials exposed

---

### Re-authentication Attack Surface

#### Mechanism Switch Prevention
- **Line 532 in SaslServerAuthenticator**: `reauthInfo.saslMechanismUnchanged(clientMechanism)`
- **Behavior**: If mechanism changes, sets REAUTH_BAD_MECHANISM state
- **Mitigation**: Prevents downgrade (e.g., SCRAM → PLAIN)
- **Effectiveness**: Good

#### Principal Change Prevention
- **Line 427, 464 in SaslServerAuthenticator**: `reauthInfo.ensurePrincipalUnchanged(principal())`
- **Behavior**: Compares new principal with old principal
- **Mitigation**: Prevents privilege escalation via re-auth
- **Effectiveness**: Good, but depends on principal extraction consistency

#### Session Timeout
- **Configuration**: `CONNECTIONS_MAX_REAUTH_MS_CONFIG` per mechanism
- **Behavior**: Broker forces re-auth after timeout
- **Mitigation**: Limits window for stolen session token
- **Gap**: If token/session is stolen, re-auth required before timeout

---

### Authorization Attack Surface

#### Principal Serialization
- **File**: `DefaultKafkaPrincipalBuilder.serialize()`
- **Line 115-120**: Encodes principal to byte[] with type, name, and tokenAuthenticated flag
- **Untrusted deserialization**: Broker could deserialize from untrusted source
- **Risk**: If custom principal serializer is used, could have deserialization attacks
- **Mitigation**: Default implementation is safe (manual serialization, no object deserialization)

#### ACL Matching
- **Authorizer.authorize()** uses principal name to match ACLs
- **Risk**: If principal name contains wildcards, could match unexpected ACLs
- **Example**: If principal name is "user/*", could grant more access than intended
- **Mitigation**: Depends on Authorizer implementation (typically exact match)

---

## Summary

### Critical Findings

1. **No username enumeration in PLAIN/SCRAM** ✓
   - Generic error messages prevent timing attacks
   - Both mechanisms throw same exception for missing user/wrong password

2. **Constant-time password comparison for PLAIN** ✓
   - `Utils.isEqualConstantTime()` prevents timing attacks on passwords

3. **Strong nonce-based protocol for SCRAM** ✓
   - RFC 5802 SCRAM-SHA-256/512 prevents replay attacks
   - Proof verification uses HMAC (cryptographically secure)

4. **Re-authentication mechanism switching protection** ✓
   - Prevents downgrade attacks (SCRAM → PLAIN)
   - Prevents principal switching during re-auth

5. **Mechanism selection locked to broker configuration** ✓
   - Client cannot request unsupported mechanism
   - Prevents mechanism downgrade attacks

### Vulnerabilities & Gaps

1. **No rate limiting on failed authentication**
   - Attackers can brute-force passwords indefinitely
   - No account lockout mechanism
   - **Impact**: High (password guessing attacks)
   - **Mitigation**: Implement rate limiting in broker or load balancer

2. **No audit logging of authentication attempts**
   - Cannot detect attack patterns
   - Compliance requirement often unsatisfied
   - **Impact**: Medium (forensics/compliance)
   - **Mitigation**: Add audit logging to authenticator

3. **PLAIN credentials sent in plaintext if not using SASL_SSL**
   - Configuration error could expose credentials
   - **Impact**: Critical if misconfigured
   - **Mitigation**: Enforce SASL_SSL mode, disable SASL_PLAINTEXT in production

4. **Principal name has no format validation**
   - Could contain special characters used by authorization system
   - Depends on Authorizer implementation for safety
   - **Impact**: Low to Medium (depends on Authorizer)
   - **Mitigation**: Validate principal name format in DefaultKafkaPrincipalBuilder

5. **No DoS protection for large SASL tokens**
   - 256KB max size is set, but no rate limiting on number of attempts
   - Attacker could fill broker memory with pending authentications
   - **Impact**: Medium (DoS)
   - **Mitigation**: Implement per-connection request rate limiting

6. **PLAIN UTF-8 decoding has no length limits per field**
   - Could process multi-MB usernames or passwords
   - JAAS config lookup could be slow
   - **Impact**: Low (caught by max size validation, but inefficient)
   - **Mitigation**: Add field-level length checks in token extraction

7. **RequestHeader parsing assumes Kafka protocol format**
   - Malformed request could throw exception (caught generically)
   - Legacy GSSAPI clients (pre-KIP-43) not properly handled
   - **Impact**: Low (handled with InvalidRequestException)
   - **Mitigation**: Already mitigated by error handling

8. **Custom callback handlers could bypass validation**
   - SaslChannelBuilder allows custom `SASL_SERVER_CALLBACK_HANDLER_CLASS_CONFIG`
   - Buggy custom handler could fail to authenticate properly
   - **Impact**: Medium (configuration-dependent)
   - **Mitigation**: Enforce strict callback handler interface contract, add validation tests

---

### Positive Security Properties

1. **Multi-mechanism support** with fallback to SCRAM for most deployments (strong)
2. **SCRAM RFC 5802 compliance** ensures industry-standard security
3. **Kerberos/GSSAPI support** for enterprise environments with KDC
4. **Principal extraction is mechanism-agnostic** (good architecture)
5. **Metadata registry tracks client information** for debugging/monitoring
6. **Extensible principal builder** allows custom authentication rules
7. **Separation of concerns**: Transport layer (TLS), SASL mechanism, callback handlers, principal extraction, authorization
8. **Pluggable authorization** allows custom ACL systems

---

### Recommendations

1. **Implement per-connection/IP rate limiting** on failed SASL authentication attempts
2. **Add field-level length validation** in PLAIN token extraction (username, password max lengths)
3. **Add audit logging** of all SASL authentication attempts (success/failure, mechanism, principal, client IP)
4. **Validate principal name format** in DefaultKafkaPrincipalBuilder (reject names with special characters)
5. **Add configuration validation** to prevent enabling PLAIN with SASL_PLAINTEXT (enforce SASL_SSL)
6. **Document custom callback handler requirements** and add validation tests
7. **Implement per-connection timeout** on incomplete SASL handshakes (default 10 seconds)
8. **Add metrics** for authentication success/failure rates by mechanism
9. **Add explicit nonce format validation** in SCRAM implementation
10. **Use constant-time HMAC comparison** in SCRAM proof verification (verify in code)

---

## Conclusion

Apache Kafka's SASL authentication flow implements a **defense-in-depth architecture** with multiple security mechanisms (PLAIN, SCRAM, GSSAPI, OAUTHBEARER). The implementation correctly handles the most critical aspects:

- ✓ Prevents username enumeration timing attacks
- ✓ Uses constant-time password comparison for PLAIN
- ✓ Implements RFC 5802 SCRAM-SHA-256/512 for hash-based authentication
- ✓ Prevents mechanism downgrade during re-authentication
- ✓ Validates SASL mechanism against broker configuration

However, there are **operational security gaps** that should be addressed for production deployments:

- ✗ No rate limiting on failed authentication attempts (brute-force vulnerability)
- ✗ No audit logging of authentication events
- ✗ No validation of principal name format (depends on Authorizer safety)
- ✗ No per-connection handshake timeout (DoS via incomplete handshakes)
- ✗ PLAIN credential exposure if misconfigured (requires SASL_SSL enforcement)

The **most critical risk** is misconfiguration: using PLAIN with SASL_PLAINTEXT instead of SASL_SSL will expose credentials on the network. This is an operational security issue, not an implementation bug.

**Overall assessment**: The authentication implementation is cryptographically sound and protocol-compliant. Most vulnerabilities are operational (configuration, rate limiting, audit logging) rather than implementation flaws. Authorization security depends entirely on the Authorizer implementation's handling of principal names.
