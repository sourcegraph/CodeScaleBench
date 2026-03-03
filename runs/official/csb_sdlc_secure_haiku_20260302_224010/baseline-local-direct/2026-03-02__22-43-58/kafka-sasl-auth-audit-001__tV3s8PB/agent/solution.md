# Apache Kafka SASL Authentication Flow Security Analysis

## Files Examined

### Channel Building & Network Layer
- `clients/src/main/java/org/apache/kafka/common/network/ChannelBuilders.java` — Factory for creating secure channel builders, routes to SaslChannelBuilder for SASL mechanisms
- `clients/src/main/java/org/apache/kafka/common/network/SaslChannelBuilder.java` — Constructs SASL channels, initializes callback handlers, creates SaslServerAuthenticator
- `clients/src/main/java/org/apache/kafka/common/network/KafkaChannel.java` — Per-connection state machine, manages authenticator lifecycle
- `clients/src/main/java/org/apache/kafka/common/network/NetworkReceive.java` — Size-delimited byte buffer for receiving SASL tokens and requests
- `clients/src/main/java/org/apache/kafka/common/network/TransportLayer.java` — Abstracts SSL/plaintext socket I/O

### SASL Server Authenticator (Core Entry Point)
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java` — State machine handling SASL handshake and challenge-response, where untrusted bytes enter the system

### PLAIN Mechanism
- `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainSaslServer.java` — Parses `[authzid]\0username\0password` from client token
- `clients/src/main/java/org/apache/kafka/common/security/plain/internals/PlainServerCallbackHandler.java` — Verifies credentials against JAAS config entries (user_* keys)

### SCRAM Mechanism (RFC 5802)
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java` — Implements SCRAM-SHA-256/SHA-512 server-side; parses ClientFirstMessage and ClientFinalMessage
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramServerCallbackHandler.java` — Retrieves salted credentials from CredentialCache
- `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramMessages.java` — Parses client messages and constructs server challenges
- `clients/src/main/java/org/apache/kafka/common/security/scram/ScramCredential.java` — Stores hashed password, salt, iterations for SCRAM verification

### OAUTHBEARER Mechanism
- `clients/src/main/java/org/apache/kafka/common/security/oauthbearer/internals/OAuthBearerSaslServer.java` — Validates Bearer token format and delegates to callback handler
- `clients/src/main/java/org/apache/kafka/common/security/oauthbearer/internals/OAuthBearerClientInitialResponse.java` — Parses Bearer token from `n,,*token*` format
- `clients/src/main/java/org/apache/kafka/common/security/oauthbearer/internals/secured/DefaultJwtValidator.java` — Validates JWT signature and claims

### GSSAPI/Kerberos Mechanism
- `clients/src/main/java/org/apache/kafka/common/security/kerberos/KerberosClientCallbackHandler.java` — Delegates to Java GSS-API for Kerberos negotiation
- `clients/src/main/java/org/apache/kafka/common/security/kerberos/KerberosName.java` — Parses and extracts principal components

### Principal Extraction & Authorization
- `clients/src/main/java/org/apache/kafka/common/security/auth/KafkaPrincipal.java` — Represents authenticated principal (type + name)
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/DefaultKafkaPrincipalBuilder.java` — Extracts principal from SASL authentication context; applies Kerberos name mapping
- `clients/src/main/java/org/apache/kafka/server/authorizer/Authorizer.java` — Pluggable interface for ACL enforcement; `authorize(AuthorizableRequestContext, List)` checks principal against ACLs

### Credential Storage
- `clients/src/main/java/org/apache/kafka/common/security/authenticator/CredentialCache.java` — In-memory cache of credentials (SCRAM hashes, delegation tokens)
- `clients/src/main/java/org/apache/kafka/common/security/token/delegation/internals/DelegationTokenCache.java` — Cache for delegation token credentials

---

## Entry Points

All of these accept untrusted data from the network:

1. **`SaslServerAuthenticator.authenticate()` (line 250)**
   - **Accepts:** Raw byte array from `NetworkReceive.payload()` (client-provided bytes)
   - **Type:** Network I/O; up to `SASL_SERVER_MAX_RECEIVE_SIZE` bytes (default 1MB)
   - **Untrusted:** ✓ All bytes directly from socket

2. **`SaslServerAuthenticator.handleKafkaRequest(byte[] requestBytes)` (line 507)**
   - **Accepts:** Byte array containing RequestHeader + request data
   - **Type:** Binary protocol message parsing
   - **Untrusted:** ✓ Bytes are parsed as RequestHeader; client-controlled api key and version
   - **Validation:** Only ApiKeys.API_VERSIONS and ApiKeys.SASL_HANDSHAKE allowed (line 515)

3. **`SaslServerAuthenticator.handleHandshakeRequest(RequestContext, SaslHandshakeRequest)` (line 549)**
   - **Accepts:** `SaslHandshakeRequest.data().mechanism()` — SASL mechanism name string
   - **Type:** String identifier (e.g., "PLAIN", "SCRAM-SHA-256", "OAUTHBEARER")
   - **Untrusted:** ✓ Client-supplied mechanism name
   - **Validation:** Checked against `enabledMechanisms` list (line 554)

4. **`SaslServerAuthenticator.handleSaslToken(byte[] clientToken)` (line 421)**
   - **Accepts:** Mechanism-specific SASL response bytes
   - **Type:** Binary token (opaque to authenticator; meaning depends on mechanism)
   - **Untrusted:** ✓ All mechanism-specific parsing delegated to SaslServer

5. **`PlainSaslServer.evaluateResponse(byte[] responseBytes)` (line 71)**
   - **Accepts:** Raw bytes expected to be `[authzid]\0username\0password` (RFC 4616)
   - **Type:** UTF-8 string with NUL delimiters
   - **Untrusted:** ✓ All bytes from client; no prior validation
   - **Parsing Logic:** `extractTokens()` (line 116) splits on `\0` using `indexOf()` and `substring()`
   - **Vulnerability Risk:** Unbounded parsing; if client sends many NUL bytes, `tokens.size()` could be large; no explicit size limit per token

6. **`PlainSaslServer.extractTokens(String string)` (line 116)**
   - **Accepts:** UTF-8-decoded string from client SASL token
   - **Parsing:** Linear scan for NUL delimiters; up to 4 tokens extracted
   - **Vulnerability Risk:** No validation that tokens are within expected bounds; empty tokens are allowed (and rejected later)

7. **`ScramSaslServer.evaluateResponse(byte[] response)` (line 96)**
   - **Accepts:** SCRAM protocol messages (ClientFirstMessage, ClientFinalMessage)
   - **Type:** Binary SCRAM message format
   - **Untrusted:** ✓ All bytes from client; parsed by `ClientFirstMessage(response)` (line 100)
   - **Key Data Extracted:** Client nonce, username (saslName), authorization ID, extensions

8. **`ClientFirstMessage` constructor**
   - **Accepts:** Raw bytes expected to be valid SCRAM ClientFirstMessage
   - **Parsing:** Decodes GS2 header + client-first-bare message
   - **Vulnerability Risk:** Client controls nonce length, username encoding, CBIND data, extensions

9. **`OAuthBearerSaslServer.evaluateResponse(byte[] response)` (line 86)**
   - **Accepts:** OAuth Bearer initial response (SASL response bytes)
   - **Type:** `n,,` header + Bearer token
   - **Untrusted:** ✓ Token string extracted and passed to validator
   - **Validation:** Delegated to callback handler's `OAuthBearerValidatorCallback`

10. **`SaslAuthenticateRequest` parsing**
    - **Accepts:** Kafka SaslAuthenticateRequest protocol message from client
    - **Type:** Protobuf-encoded message with `authBytes` field (opaque to broker)
    - **Untrusted:** ✓ `authBytes` are passed directly to mechanism's `evaluateResponse()`

---

## Data Flow

### Flow 1: PLAIN Mechanism Authentication

1. **Source:** Socket → `SaslServerAuthenticator.authenticate()` (untrusted client bytes)
2. **Transform 1:** `NetworkReceive.readFrom(transportLayer)` — reads size-delimited bytes from network
3. **Transform 2:** `RequestHeader.parse()` (SaslAuthenticateRequest) — extracts apiKey=SASL_AUTHENTICATE and version
4. **Transform 3:** `SaslAuthenticateRequest` deserialization — extracts `authBytes` field (SASL token)
5. **Transform 4:** `SaslServer.evaluateResponse(authBytes)` → `PlainSaslServer.evaluateResponse()`
6. **Transform 5:** `extractTokens()` — splits UTF-8 string by `\0` into [authzid, username, password]
7. **Transform 6:** `new NameCallback("username", username)` + `PlainAuthenticateCallback`
8. **Validation:** `PlainServerCallbackHandler.authenticate(username, password)` — looks up `user_<username>` in JAAS config, compares password via constant-time function
9. **Sink 1:** `authorizationId = username` stored in PlainSaslServer
10. **Sink 2:** `SaslServerAuthenticator.principal()` → `DefaultKafkaPrincipalBuilder.build(SaslAuthenticationContext)` → `new KafkaPrincipal(USER_TYPE, authorizationId)`
11. **Final Use:** `KafkaPrincipal` passed to `Authorizer.authorize(context)` for ACL checks

**Vulnerable Points:**
- No length validation in `extractTokens()` — malformed messages could be processed
- UTF-8 decoding on untrusted bytes at line 85: `new String(responseBytes, StandardCharsets.UTF_8)` — could be memory-inefficient if huge
- No rate limiting or per-connection token size limits

---

### Flow 2: SCRAM Mechanism Authentication

1. **Source:** Socket → `SaslServerAuthenticator.authenticate()` (untrusted client bytes)
2. **Transform 1:** `NetworkReceive.readFrom(transportLayer)` — reads bytes
3. **Transform 2:** `requestContext.parseRequest()` (SaslAuthenticateRequest)
4. **Transform 3:** Extract `authBytes`
5. **Transform 4:** `ScramSaslServer.evaluateResponse(response)`
   - **State: RECEIVE_CLIENT_FIRST_MESSAGE**
   - `ClientFirstMessage clientFirstMessage = new ClientFirstMessage(response)` (line 100) — parses:
     - GS2 header (gs2-cbind-flag, authzid)
     - Client nonce
     - Channel binding data (if present)
     - Extensions (SCRAM-PLUS)
6. **Transform 5:** Extract `saslName` and `serverNonce` (random, generated server-side)
7. **Transform 6:** `ScramFormatter.username(saslName)` — decodes username from SCRAM SASLname format
8. **Transform 7:** `NameCallback` + credential lookup via `ScramServerCallbackHandler.handle()`
   - Callback handler retrieves `ScramCredential` from `CredentialCache.get(username)`
9. **Transform 8:** Construct `ServerFirstMessage` with client nonce + server nonce + salt + iterations (from credential)
10. **Validation Trigger:** `ScramSaslServer.evaluateResponse()` on ClientFinalMessage (line 147+)
    - Verify nonce matches (client nonce + server nonce)
    - Compute HMAC proof and compare against expected
11. **Sink 1:** `authorizationId = username` or `tokenCallback.tokenOwner()` (if delegation token auth)
12. **Sink 2:** `DefaultKafkaPrincipalBuilder.build()` → `KafkaPrincipal`
13. **Final Use:** ACL authorization

**Vulnerable Points:**
- `ClientFirstMessage` constructor parses untrusted bytes without size bounds on nonce/authzid/extensions
- SCRAM-PLUS channel binding validation depends on SSL transport layer; client can claim binding support
- Extension parsing in `ScramExtensions` can be exploited if extensions are not validated strictly
- Username extracted from SCRAM SASLname could contain special characters (e.g., escaped NUL bytes) that are then passed to credentials lookup

---

### Flow 3: OAUTHBEARER Mechanism Authentication

1. **Source:** Socket → `SaslServerAuthenticator.authenticate()` (untrusted client bytes)
2. **Transform 1:** Raw bytes → `NetworkReceive` → `SaslAuthenticateRequest` → `authBytes`
3. **Transform 2:** `OAuthBearerSaslServer.evaluateResponse(response)` (line 86)
4. **Transform 3:** `OAuthBearerClientInitialResponse clientResponse = new OAuthBearerClientInitialResponse(response)` (line 95)
   - Parses `n,,<token>` format
   - Extracts Bearer token string
5. **Transform 4:** Token string → `OAuthBearerValidatorCallback` → custom callback handler
6. **Transform 5:** Callback handler invokes `JwtValidator.validate(token)` or similar
7. **Transform 6:** JWT decoded, signature verified, claims extracted
8. **Validation:** Signature validation via public key (JWKS or file-based)
   - Claims checked: `iss` (issuer), `aud` (audience), `exp` (expiration), `principal_claim` (username)
9. **Sink 1:** `authorizationId = token.principal()` (extracted from JWT claims)
10. **Sink 2:** `KafkaPrincipal` created with JWT-derived principal name
11. **Final Use:** ACL authorization

**Vulnerable Points:**
- JWT validation is optional (unsecured validator allows unsigned JWTs if configured)
- Principal name from JWT claims is not validated; any claim value becomes the principal
- JWKS HTTP endpoints could be exploited if URL is attacker-controlled
- No rate limiting on token validation operations

---

### Flow 4: GSSAPI/Kerberos Mechanism Authentication

1. **Source:** Socket → `SaslServerAuthenticator.authenticate()` (untrusted client bytes)
2. **Transform 1:** Bytes → `NetworkReceive` → SASL token
3. **Transform 2:** `SaslServerAuthenticator.createSaslKerberosServer()` (line 219) creates Java GSS-API SaslServer
4. **Transform 3:** `Sasl.createSaslServer(GSSAPI, servicePrincipal, hostname, configs, callbackHandler)` (line 234)
   - Server creates GSSContext via KerberosClientCallbackHandler
5. **Transform 4:** Client tokens processed by GSSContext.acceptSecToken()
6. **Validation:** Kerberos KDC validates client tickets; GSS-API layer verifies signatures and mutual auth
7. **Transform 5:** Upon completion, `saslServer.getAuthorizationID()` returns Kerberos principal (e.g., `user@REALM`)
8. **Transform 6:** `DefaultKafkaPrincipalBuilder.applyKerberosShortNamer()` (line 90)
   - Parses principal with `KerberosName.parse(authorizationId)` (line 91)
   - Applies `KerberosShortNamer.shortName()` to transform (e.g., `user@REALM` → `user`)
9. **Sink 1:** Short name → `KafkaPrincipal`
10. **Final Use:** ACL authorization

**Vulnerable Points:**
- `KerberosName.parse()` could fail with malformed principals; exception handling critical
- `KerberosShortNamer.shortName()` uses regex-based rules (line 93); rules could have injection risks if user-configurable
- GSS-API delegation: if impersonation is not carefully controlled, user tokens could be misused

---

## Dependency Chain

### For PLAIN Authentication:
1. `KafkaChannel.prepare()` calls `SaslServerAuthenticator.authenticate()`
2. `SaslServerAuthenticator.authenticate()` → `handleKafkaRequest()` → RequestHeader.parse()
3. RequestHeader identifies `SASL_HANDSHAKE` → `handleHandshakeRequest()` → validates mechanism → `createSaslServer(mechanism)`
4. `SaslChannelBuilder.createServerCallbackHandlers()` instantiates `PlainServerCallbackHandler` (line 327)
5. For subsequent `SASL_AUTHENTICATE`: `handleSaslToken()` → `PlainSaslServer.evaluateResponse()`
6. `PlainSaslServer` calls `callbackHandler.handle(callbacks)` (line 101)
7. `PlainServerCallbackHandler.handle()` → `authenticate(username, password)` → JAAS config lookup
8. Upon success, `SaslServerAuthenticator.principal()` → `DefaultKafkaPrincipalBuilder.build(SaslAuthenticationContext)`
9. Principal passed to authorization layer

**Entry Point → Credential Verification → Principal Extraction → Authorization**

### For SCRAM Authentication:
1. `KafkaChannel.prepare()` → `SaslServerAuthenticator.authenticate()`
2. Handshake: `handleKafkaRequest()` → `handleHandshakeRequest()` → `createSaslServer("SCRAM-SHA-256")`
3. `SaslChannelBuilder.createServerCallbackHandlers()` instantiates `ScramServerCallbackHandler` (line 329)
4. First response: `ScramSaslServer.evaluateResponse()` (RECEIVE_CLIENT_FIRST_MESSAGE) → `ClientFirstMessage(response)` → credential lookup
5. `ScramServerCallbackHandler.handle()` → `credentialCache.get(username)` (line 67)
6. Credential returned; `ServerFirstMessage` sent with salt + iterations
7. Second response: `evaluateResponse()` (RECEIVE_CLIENT_FINAL_MESSAGE) → HMAC verification
8. Upon success, `SaslServerAuthenticator.principal()` → `DefaultKafkaPrincipalBuilder.build()`
9. Principal → authorization

**Entry Point → Message Parsing → Credential Cache Lookup → HMAC Verification → Principal Extraction → Authorization**

### For OAUTHBEARER Authentication:
1. `SaslServerAuthenticator.authenticate()` → `handleHandshakeRequest()` → `createSaslServer("OAUTHBEARER")`
2. `SaslChannelBuilder.createServerCallbackHandlers()` instantiates `OAuthBearerUnsecuredValidatorCallbackHandler` or custom handler (line 331)
3. `handleSaslToken()` → `OAuthBearerSaslServer.evaluateResponse()`
4. `OAuthBearerClientInitialResponse(response)` → token extracted
5. `OAuthBearerValidatorCallback` → callback handler → `JwtValidator.validate(token)`
6. JWT signature verified; claims extracted
7. `authorizationId = token.principal()`
8. `DefaultKafkaPrincipalBuilder.build()` → `KafkaPrincipal`
9. Authorization

**Entry Point → Token Extraction → JWT Validation → Principal from Claims → Authorization**

---

## Analysis

### Vulnerability Class: Authentication Bypass & Principal Confusion

#### 1. **SASL Mechanism Negotiation Validation**

**Issue:** Client selects SASL mechanism via `SaslHandshakeRequest.mechanism()`.

**Mitigation in place:** `handleHandshakeRequest()` (line 549) checks `if (enabledMechanisms.contains(clientMechanism))` (line 554). Only broker-configured mechanisms accepted.

**Gap:** If mechanism name parsing is case-sensitive but lookup is not (or vice versa), case confusion attacks could bypass checks. Current code uses direct string comparison; should be robust if config is consistent.

**Attack Scenario:** If broker enables "PLAIN" and attacker requests "plain" (lowercase), check fails → good. But if multiple mechanisms differ only in case, configuration could be confused.

**Mitigation Status:** ✓ Sufficient (string comparison is case-sensitive; config must be consistent)

---

#### 2. **PLAIN Token Parsing: Unbounded Username/Password Handling**

**Issue:** `PlainSaslServer.evaluateResponse()` (line 85) blindly converts client bytes to UTF-8 string without size validation:
```java
String response = new String(responseBytes, StandardCharsets.UTF_8);
```

**Vulnerability:**
- If client sends 1MB of random bytes, UTF-8 decoding creates a 1MB string
- `extractTokens()` parses the string by scanning for NUL; linear time, but unbounded
- No explicit size limit per token (authzid, username, password)

**Attack Scenario:**
1. Client sends `PLAIN` token with 256KB username field
2. `PlainServerCallbackHandler.authenticate()` looks up `user_<256KB_string>` in JAAS config
3. JAAS config lookup is O(n) in config size; could trigger DoS via memory exhaustion or CPU spike
4. Even if lookup fails, temporary string objects are created

**Mitigation in place:**
- `SASL_SERVER_MAX_RECEIVE_SIZE` limits total message size to 1MB by default (line 195-197)
- After UTF-8 decode, `extractTokens()` validates `tokens.size() == 3` (line 129)
- Empty token check for username (line 91) and password (line 94)

**Mitigations are insufficient:**
- Per-token size limits not enforced (3 tokens could be [256KB, 256KB, 256KB])
- JAAS config lookup performance not bounded; no caching strategy if config is large
- Callback handler does not validate token contents (no regex on username, no special char rejection)

**Remediation:**
- Add per-token size limits (e.g., max 255 bytes per RFC 4616)
- Validate username format (e.g., alphanumeric + select punctuation)
- Implement credential cache with pre-computed hashes to avoid repeated JAAS lookups

---

#### 3. **SCRAM Username Handling: SASLname Decoding**

**Issue:** `ScramSaslServer` extracts username via `ScramFormatter.username(saslName)` (line 109).

**SCRAM RFC 5802 SASLname:** Username is UTF-8 encoded and may contain escaped NUL bytes (`=3D`, `=2C`, etc.)

**Vulnerability:**
- SCRAM allows usernames with arbitrary UTF-8 characters
- Upon decoding, username could contain characters that confuse downstream systems
- Credential cache lookup: `credentialCache.get(username)` (ScramServerCallbackHandler line 67)
  - If cache is backed by a map, any string is valid key; risk is low
  - If cache involves external lookup (LDAP, database), injection possible

**Attack Scenario:**
1. Attacker requests SCRAM auth with username `admin\0admin` (null byte injection)
2. If credential cache performs string operations without null-byte handling, could authenticate as wrong user
3. In Java, strings are null-byte safe, so this is low risk; but plugin developers might use unsafe C libraries

**Mitigation in place:**
- CredentialCache is in-memory Java map; null-byte safe
- Username validation depends on callback handler implementation

**Mitigations are insufficient:**
- Default cache does not validate username format
- No protection against plugin callback handlers that might be vulnerable to special characters
- SCRAM extensions (e.g., SCRAM-PLUS channel binding) are parsed but validation is incomplete

**Remediation:**
- Whitelist allowed characters in usernames (e.g., `[a-zA-Z0-9._-]`)
- Document security requirements for custom callback handler implementations
- Validate channel binding claim against SSL transport layer state strictly

---

#### 4. **OAUTHBEARER: JWT Validation Gaps**

**Issue:** OAuth Bearer token validation delegated to callback handler.

**Risk 1: Unsecured Validator**
- `OAuthBearerUnsecuredValidatorCallbackHandler` (line 331) is default for brokers
- If misconfigured, allows unsigned JWT tokens
- Principal extracted directly from JWT claims without signature verification
- Attacker can forge JWT with arbitrary principal name

**Attack Scenario:**
1. Broker configured with `sasl.oauthbearer.token.endpoint.url` = invalid (defaults to unsecured)
2. Attacker sends JWT `{"principal": "admin", ...}` (no signature)
3. Token accepted as-is; principal becomes "admin" without verification

**Mitigation in place:**
- Configuration should enforce JWT signature validation for production
- `DefaultJwtValidator` checks signature if configured
- Documentation warns against unsecured validator

**Mitigations are insufficient:**
- Default configuration is insecure if not explicitly set
- No compile-time enforcement of validation

**Risk 2: Principal Name Injection**
- JWT `principal_claim` (default: `sub`) value becomes KafkaPrincipal.name
- If JWT is forged/modified, attacker controls principal name
- ACL system trusts principal name → authorization bypass

**Remediation:**
- Require signed JWKS configuration
- Add principal name whitelist validation
- Implement JWT claim value sanitization

---

#### 5. **Principal Name to Authorization Mapping**

**Issue:** `DefaultKafkaPrincipalBuilder.build()` (line 69) extracts principal and creates `KafkaPrincipal`:

For SASL:
```java
SaslServer saslServer = ((SaslAuthenticationContext) context).server();
if (SaslConfigs.GSSAPI_MECHANISM.equals(saslServer.getMechanismName()))
    return applyKerberosShortNamer(saslServer.getAuthorizationID());
else
    return new KafkaPrincipal(KafkaPrincipal.USER_TYPE, saslServer.getAuthorizationID());
```

**Vulnerability: Principal Derivation Has No Injection Protection**

The `saslServer.getAuthorizationID()` is used directly as principal name for non-GSSAPI mechanisms.

**For PLAIN:**
- Username comes from client SASL token
- No further validation in principal builder
- Callback handler validates credentials, but principal name is not sanitized

**Attack Scenario (if auth succeeds but principal is malformed):**
1. Broker accepts SCRAM auth with username `admin/backup` (contains `/`)
2. ACL system might misinterpret principal as `admin` + `/backup` resource
3. Depending on ACL implementation, could cause scope confusion

**For GSSAPI:**
```java
return applyKerberosShortNamer(saslServer.getAuthorizationID());
```
- Principal parsed with `KerberosName.parse()` (line 91)
- `parse()` could throw if format is invalid (but GSSAPI already validated)
- `KerberosShortNamer.shortName()` applies regex rules; rules could have injection if user-controllable

**Mitigation in place:**
- For PLAIN/SCRAM: Direct credential verification ensures username is known/stored
- For GSSAPI: KDC validation ensures principal is legitimate
- For OAuth: JWT signature validation (if configured)

**Mitigations are insufficient:**
- Principal name passed to Authorizer without further validation
- If Authorizer uses principal name in file paths or shell commands, injection possible
- Custom Authorizer implementations may not handle all special characters

**Remediation:**
- Implement strict principal name validation in builder (whitelist: `[a-zA-Z0-9._-]`)
- Sanitize principal names before passing to Authorizer
- Document expectations for Authorizer implementations regarding principal format

---

#### 6. **Authorizer Invocation & ACL Enforcement**

**Issue:** `Authorizer.authorize(AuthorizableRequestContext context, List<Action> actions)` is called post-authentication.

**Vulnerability: Implicit Trust in Principal**

Once authentication succeeds, `context.principal()` is used for all authorization decisions. There is no re-validation of principal validity.

**Attack Scenario:**
1. Attacker authenticates via PLAIN with username `attacker`
2. During request processing, suppose connection is hijacked or principal is spoofed (post-auth)
3. Authorizer checks ACLs for `attacker` → access denied (expected)
4. But if Authorizer is stateless and doesn't verify principal on every request, could be exploited

**Mitigation in place:**
- Principal is bound to KafkaChannel; re-used for all requests on that channel
- Authorizer is invoked for every request; checks ACLs against principal

**Mitigations are sufficient for normal attacks:**
- Once channel is authenticated, principal cannot be changed mid-connection
- Authorization is checked per-request

**Potential gap:**
- If Authorizer is misconfigured with deny-all rules, legitimate users are blocked (not a security issue)
- If Authorizer has bugs (e.g., null principal handling), could bypass checks

**Remediation:**
- Authorizer implementations should validate principal is non-null before checking ACLs
- Implement logging of all authorization decisions for audit trail

---

#### 7. **Credential Storage: SCRAM in CredentialCache**

**Issue:** `ScramServerCallbackHandler` retrieves credentials from `CredentialCache` (line 67):
```java
ScramCredentialCallback sc = (ScramCredentialCallback) callback;
sc.scramCredential(credentialCache.get(username));
```

**Vulnerability: Credential Cache Key Extraction**

- Cache is indexed by username
- If credential lookup is not found, `credentialCache.get(username)` returns `null`
- Server sends `ScramException` → information leak

**Attack Scenario:**
1. Attacker tries SCRAM auth with username `admin`
2. If username not in cache: exception thrown → client learns "admin" doesn't exist
3. Attacker can enumerate valid usernames by timing responses or error messages

**Mitigation in place:**
- ScramException is caught and converted to generic error (line 127-128)
- Error message: "Authentication failed: Invalid user credentials" (generic)

**Mitigation is sufficient:**
- Exception message does not reveal whether username was found
- Timing might still leak info (credential lookup vs. missing user)

**Potential gap:**
- If cache lookup is slow for non-existent users (e.g., database round-trip), timing attack possible
- No rate limiting on auth attempts per username

**Remediation:**
- Implement constant-time credential lookup (e.g., always check against dummy credential if user not found)
- Add rate limiting per username + source IP
- Implement authentication attempt logging for intrusion detection

---

#### 8. **Re-authentication: Mechanism Switching**

**Issue:** `SaslServerAuthenticator.reauthenticate()` (line 343) handles connection re-auth:

```java
if (!reauthInfo.reauthenticating() || reauthInfo.saslMechanismUnchanged(clientMechanism)) {
    createSaslServer(clientMechanism);
    setSaslState(SaslState.AUTHENTICATE);
}
```

If mechanism is unchanged, new SaslServer is created. If changed, error is raised.

**Vulnerability: Mechanism Downgrade**

If re-authentication allows mechanism change, attacker could:
1. Authenticate with SCRAM (strong)
2. Request re-auth with PLAIN (weak)
3. If not properly validated, downgrade authentication

**Mitigation in place:**
- Line 532: `if (!reauthInfo.reauthenticating() || reauthInfo.saslMechanismUnchanged(clientMechanism))`
- If reauthenticating and mechanism changed → error raised
- State transitions to `REAUTH_BAD_MECHANISM` (line 115-116)

**Mitigation is sufficient:**
- Mechanism change during re-auth explicitly rejected

---

## Summary

**Vulnerability Classes Identified:**

1. **Unbounded Token Parsing (PLAIN)** — Per-token size limits not enforced; could cause DoS via large username fields
2. **Username Encoding Issues (SCRAM)** — SASLname decoding may produce special characters; credential cache lookup not validated for injection
3. **OAuth Token Validation Gaps** — Unsecured validator allows unsigned JWTs; principal name injection if signature missing
4. **Principal Name Injection** — Non-GSSAPI principals passed to Authorizer without sanitization; risk if Authorizer uses names in system calls
5. **Credential Enumeration via Timing** — Slow credential lookups leak username validity via timing side-channel
6. **Default Insecure Configuration (OAuth)** — Unsecured validator is default; must be explicitly hardened

**Overall Security Posture:**

The Kafka SASL authentication flow implements defense-in-depth:
- **Channel creation** routes to appropriate builder based on protocol
- **Handshake negotiation** validates mechanism selection against broker config
- **Mechanism-specific parsing** is delegated to well-tested implementations (RFC 4616 PLAIN, RFC 5802 SCRAM, JWT Bearer)
- **Credential verification** uses constant-time comparisons and callback handlers
- **Principal extraction** maps authentication results to Kafka principals
- **Authorization** checks principal against ACL rules per-request

**Mitigations are generally sufficient for common attack vectors** (credential brute-force, mechanism negotiation attacks, principal name collisions).

**Gaps exist in:**
- Per-token size validation (PLAIN)
- Credential enumeration protection (no constant-time cache lookup)
- Default OAuth configuration (allows unsigned tokens)
- Principal name sanitization (relies on Authorizer to handle safely)

**Recommended Hardening:**

1. **PLAIN:** Add per-token size limits (max 255 bytes per RFC 4616); validate username format
2. **SCRAM:** Implement constant-time credential lookup using dummy credentials for non-existent users
3. **OAuth:** Require signed JWKS configuration by default; reject unsigned tokens in production mode
4. **All mechanisms:** Add principal name whitelist validation in DefaultKafkaPrincipalBuilder
5. **Authorization:** Audit Authorizer implementations for principal name injection risks
6. **Monitoring:** Log all authentication failures and successful auth events for intrusion detection

The architecture is sound; gaps are primarily in hardening defaults and edge-case handling.
