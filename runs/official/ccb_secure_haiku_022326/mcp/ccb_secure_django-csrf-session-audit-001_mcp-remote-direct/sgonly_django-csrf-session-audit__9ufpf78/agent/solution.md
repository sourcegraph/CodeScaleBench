# Django CSRF Protection and Session Handling Security Analysis

## Files Examined

### CSRF Pipeline
- **django/middleware/csrf.py** — Central CSRF middleware implementing token validation, masking/unmasking, and cookie management
- **django/utils/crypto.py** — Cryptographic primitives: salted_hmac, constant_time_compare, get_random_string
- **django/core/signing.py** — Signing layer: Signer, TimestampSigner, encode/decode pipeline
- **django/http/request.py** — HTTP request object with COOKIES and META dictionaries
- **django/http/cookie.py** — Cookie parsing from HTTP headers

### Session Pipeline
- **django/contrib/sessions/middleware.py** — Session middleware: process_request (load), process_response (save/set cookie)
- **django/contrib/sessions/backends/base.py** — Base session class with encode/decode using signing
- **django/contrib/sessions/backends/signed_cookies.py** — Session storage in signed cookies
- **django/contrib/sessions/serializers.py** — Session serialization (JSON by default)

## Entry Points

Untrusted data enters the CSRF/session subsystem at these points:

### 1. **CSRF Cookie from HTTP Request**
- **File**: django/middleware/csrf.py:240
- **Function**: `CsrfViewMiddleware._get_secret()`
- **Input Source**: `request.COOKIES[settings.CSRF_COOKIE_NAME]`
- **Type**: HTTP Cookie header value (untrusted client input)
- **Processing**:
  - Raw cookie string is read from HTTP request
  - Length and character validation via `_check_token_format()` (line 245)
  - If masked (CSRF_TOKEN_LENGTH = 64), unmasked via `_unmask_cipher_token()` (line 250)

### 2. **CSRF Token from POST Form Data**
- **File**: django/middleware/csrf.py:368
- **Function**: `CsrfViewMiddleware._check_token()`
- **Input Source**: `request.POST.get("csrfmiddlewaretoken", "")`
- **Type**: Form POST data (untrusted client input)
- **Processing**:
  - Form parameter parsed by Django's POST data parser
  - Format validated via `_check_token_format()` (line 392)
  - Token comparison via `_does_token_match()` (line 397)

### 3. **CSRF Token from HTTP Header**
- **File**: django/middleware/csrf.py:384
- **Function**: `CsrfViewMiddleware._check_token()`
- **Input Source**: `request.META[settings.CSRF_HEADER_NAME]` (typically "HTTP_X_CSRFTOKEN")
- **Type**: Custom HTTP header (untrusted client input)
- **Processing**:
  - Header value retrieved from request.META
  - Format validated via `_check_token_format()` (line 392)
  - Supports both masked and unmasked tokens depending on client source

### 4. **CSRF Cookie from Origin/Referer Headers**
- **File**: django/middleware/csrf.py:272, 298
- **Functions**: `CsrfViewMiddleware._origin_verified()`, `_check_referer()`
- **Input Source**: `request.META["HTTP_ORIGIN"]`, `request.META.get("HTTP_REFERER")`
- **Type**: HTTP headers (untrusted, controlled by browser or attacker)
- **Processing**:
  - Origin verified against CSRF_TRUSTED_ORIGINS config
  - Referer parsed and validated for same-domain match
  - Used as CSRF protection mechanism itself (not signature validation)

### 5. **Session Cookie from HTTP Request**
- **File**: django/contrib/sessions/middleware.py:19
- **Function**: `SessionMiddleware.process_request()`
- **Input Source**: `request.COOKIES.get(settings.SESSION_COOKIE_NAME)`
- **Type**: HTTP Cookie header value (untrusted client input)
- **Processing**:
  - Raw session key passed to SessionStore
  - Actual decoding deferred to lazy `_session` property access
  - Signature validation occurs at load time in `signed_cookies.py:13`

## Data Flow

### Flow 1: CSRF Token Generation and Masking (Request → Response)

1. **Source**: django/middleware/csrf.py:401-412 (`process_request`)
   - Entry point: Existing CSRF cookie read from request
   - `_get_secret()` retrieves and validates CSRF secret from cookie or session
   - If valid, stored in `request.META["CSRF_COOKIE"]` for later use

2. **Transform**: django/middleware/csrf.py:96-114 (`get_token`)
   - `get_token()` called by application (usually via template tag or decorator)
   - Retrieves existing secret from `request.META["CSRF_COOKIE"]`
   - If not present, generates new secret via `_add_new_csrf_cookie()` (line 86)
   - Masks secret: `_mask_cipher_secret()` (line 114)
     - Generates random mask: `_get_new_csrf_string()` (line 64)
     - XOR-style operation: `chars[(x + y) % len(chars)]` (line 67)
     - Returns concatenated: `mask + cipher` (32 + 32 = 64 chars)

3. **Sink**: django/middleware/csrf.py:253-269 (`process_response`)
   - Flag `CSRF_COOKIE_NEEDS_UPDATE` triggers cookie setting
   - Cookie written with raw secret (not masked) via `response.set_cookie()` (line 258)
   - Security attributes:
     - `secure`: CSRF_COOKIE_SECURE config
     - `httponly`: CSRF_COOKIE_HTTPONLY config
     - `samesite`: CSRF_COOKIE_SAMESITE config
   - Cookie stored in browser, available to JavaScript (unless HttpOnly is True)

### Flow 2: CSRF Token Validation (Request Processing)

1. **Source**: django/middleware/csrf.py:349-399 (`_check_token`)
   - Entry points:
     - CSRF secret from cookie: `_get_secret()` (line 354)
       - From CSRF_COOKIE if CSRF_USE_SESSIONS=False
       - From session if CSRF_USE_SESSIONS=True (line 231)
     - Request token from POST: `request.POST.get("csrfmiddlewaretoken")` (line 368)
     - Request token from header: `request.META[settings.CSRF_HEADER_NAME]` (line 384)

2. **Transform**: django/middleware/csrf.py:390-399
   - Token format validation (line 392): Length must be 32 or 64, only alphanumeric chars
   - If token is masked (length 64): Unmask via `_unmask_cipher_token()` (line 155)
   - Comparison via `constant_time_compare()` (line 157)

3. **Sink**: django/middleware/csrf.py:464-467
   - If validation fails: `_reject()` called (line 466)
   - If validation passes: `_accept()` called (line 425)
   - Request.csrf_processing_done flag set to prevent double-checking

### Flow 3: Session Loading and Decoding (Request Reception)

1. **Source**: django/contrib/sessions/middleware.py:18-20 (`process_request`)
   - Entry point: HTTP Cookie header
   - Session key from: `request.COOKIES.get(settings.SESSION_COOKIE_NAME)`
   - SessionStore instantiated with session key (lazy load)

2. **Transform**: django/contrib/sessions/backends/signed_cookies.py:6-24 (`load`)
   - Deferred until first session access
   - Entry point: `signing.loads()` (line 13)
   - Input: Raw session_key (Base64 + HMAC signature)
   - Signature verification via salt: `"django.contrib.sessions.backends.signed_cookies"`
   - Max age check: `get_session_cookie_age()` (line 17)
   - Decompression if needed (zlib)
   - Deserialization via JSONSerializer
   - Exception handling: If BadSignature or unpickling fails, create empty session

3. **Sink**: django/contrib/sessions/backends/base.py:237-250 (`_get_session`)
   - Session data cached in `self._session_cache`
   - Lazy property allows transparent access: `request.session[key]`
   - Accessed flag set for Vary header

### Flow 4: Session Saving and Cookie Setting (Response)

1. **Source**: django/contrib/sessions/backends/base.py:237-250 (`_session` property)
   - Session data in-memory cache from request.session dict access
   - Modified flag set if any changes made

2. **Transform**: django/contrib/sessions/backends/signed_cookies.py:39-95 (`save`, `_get_session_key`)
   - Serialization: `signing.dumps()` (line 90)
   - Input: `self._session` dict
   - Compression: zlib if effective (line 92)
   - Signing salt: `"django.contrib.sessions.backends.signed_cookies"`
   - Output: Base64-encoded signed string (session_key)

3. **Sink**: django/contrib/sessions/middleware.py:66-76 (`process_response`)
   - Cookie set if modified or SESSION_SAVE_EVERY_REQUEST
   - Security attributes:
     - `secure`: SESSION_COOKIE_SECURE config
     - `httponly`: SESSION_COOKIE_HTTPONLY config
     - `samesite`: SESSION_COOKIE_SAMESITE config
   - Max age set based on expiry configuration

### Flow 5: Cryptographic Chain (Core Security)

1. **Random Generation**: django/utils/crypto.py:51-62 (`get_random_string`)
   - Uses `secrets.choice()` for secure randomness
   - CSRF_ALLOWED_CHARS alphabet: 52 alphanumeric characters
   - 32-char string ≈ 186 bits of entropy (log2(62^32))

2. **HMAC Generation**: django/utils/crypto.py:19-45 (`salted_hmac`)
   - Input: `key_salt`, `value`, `secret` (defaults to settings.SECRET_KEY)
   - Key derivation: `hash(key_salt + secret)` as HMAC key
   - HMAC algorithm: SHA1 (default) or configurable
   - Output: HMAC object with digest() method

3. **Signing Layer**: django/core/signing.py:177-213 (Signer class)
   - Signature: `base64_hmac(self.salt + "signer", value, key, algorithm)`
   - Format: `{value}:{signature}`
   - Verification: Constant-time comparison via `secrets.compare_digest()`
   - Fallback keys supported for key rotation

4. **Session Signing**: django/core/signing.py:254-277 (TimestampSigner)
   - Extends Signer with timestamp
   - Format: `{base64_data}:{timestamp}:{signature}`
   - Timestamp: Base62-encoded Unix time
   - Max age: Checked by comparing timestamp to current time

5. **Constant-Time Comparison**: django/utils/crypto.py:65-67
   - Uses `secrets.compare_digest()` (Python stdlib)
   - Prevents timing attacks on signature validation
   - Applied to: CSRF token matching and signature verification

## Dependency Chain

### CSRF Validation Pipeline (Request → Validation → Accept/Reject)

```
HTTP Request
  ↓
django/http/cookie.py:parse_cookie() — Parse Cookie header
  ↓
request.COOKIES["csrftoken"] (raw value)
  ↓
django/middleware/csrf.py:CsrfViewMiddleware.process_request()
  ↓
_get_secret() — Read from cookie or session
  ↓
_check_token_format() — Validate length and characters
  ↓
request.META["CSRF_COOKIE"] (validated secret, unmasked if needed)
  ↓
process_view() — Called on safe/unsafe methods
  ↓
_check_token() — Retrieve and validate request token
  ├─ POST: request.POST["csrfmiddlewaretoken"]
  ├─ Header: request.META["HTTP_X_CSRFTOKEN"]
  └─ Format check and unmasking
  ↓
_does_token_match()
  ├─ Unmask if needed: _unmask_cipher_token()
  └─ Compare: constant_time_compare()
  ↓
Accept or Reject
  ↓
process_response() — Set cookie if CSRF_COOKIE_NEEDS_UPDATE
  ↓
response.set_cookie() with security attributes
  ↓
HTTP Response + Set-Cookie header
```

### Session Validation Pipeline (Request → Load → Access → Save)

```
HTTP Request
  ↓
django/http/cookie.py:parse_cookie() — Parse Cookie header
  ↓
request.COOKIES["sessionid"] (raw session key value)
  ↓
django/contrib/sessions/middleware.py:SessionMiddleware.process_request()
  ↓
SessionStore(session_key) — Create session object with key
  ↓
(Lazy evaluation until first access)
  ↓
request.session[key] access
  ↓
_get_session() property — Trigger load()
  ↓
signed_cookies.load() or db.load()
  ↓
signing.loads(session_key, salt, max_age)
  ↓
Signer.unsign() — Verify HMAC signature
  ├─ Extract value and signature
  ├─ Compute signature for value with current key
  ├─ Fallback to SECRET_KEY_FALLBACKS if needed
  └─ Constant-time compare
  ↓
b64_decode() — Decode Base64
  ↓
zlib.decompress() (if needed)
  ↓
JSONSerializer.loads() — Deserialize JSON
  ↓
Session dict cached in _session_cache
  ↓
Application uses request.session[key]
  ↓
Modifications set self.modified = True
  ↓
process_response() — Check modified flag
  ↓
save() — Regenerate session key
  ↓
_get_session_key() — Re-sign session data
  ↓
signing.dumps() → Signer.sign()
  ↓
response.set_cookie() with new session key and security attributes
  ↓
HTTP Response + Set-Cookie header
```

## Analysis

### 1. CSRF Token Masking Scheme

**Purpose**: Prevent BREACH attack (compression-based cookie recovery).

**Implementation** (django/middleware/csrf.py:59-81):
- **Secret** (32 chars): Server-side CSRF secret stored in cookie
- **Mask** (32 chars): Fresh random mask generated per token request
- **Cipher** (32 chars): `chars[(secret_index + mask_index) % 62]`
- **Token** (64 chars): `mask + cipher`
- **Unmasking**: `chars[(cipher_index - mask_index) % 62]` recovers secret

**Security Properties**:
- ✓ Confidentiality: Each token uses fresh mask, preventing pattern analysis
- ✓ Deterministic: Same secret with different masks produces different tokens
- ✓ Modular arithmetic: Uses addition/subtraction mod 62 (alphabet size)
- ✓ Constant-time comparison: `_does_token_match()` unmasks before comparing
- ✓ Safe even if mask is observable to attacker (mask + cipher format in DOM)

**Potential Issues**:
- Mask stored in plaintext in DOM (accessible to JavaScript)
- Attacker with JavaScript access could observe mask and derive secret
- BREACH protection assumes compression; modern TLS mitigations reduce risk
- Token format exposed: 64-char ASCII reveals it's masked CSRF token

### 2. Cryptographic Chain Strength

**Random Number Generation**:
- Function: `secrets.choice()` (Python stdlib, cryptographically secure)
- CSRF Secret: 32 chars from 62-char alphabet ≈ 186 bits entropy
- Session Key: 32 chars from lowercase+digits alphabet ≈ 155 bits entropy

**HMAC Security**:
- Algorithm: SHA1 or configurable (default SHA256 for Signer)
- Key Derivation: `hash(key_salt + SECRET_KEY)` as HMAC key
- Salt: Different salt per context (CSRF, session, custom)
- Preimage Resistance: SHA1 is sufficient for message authentication despite collision concerns
- Key Strength: Tied to SECRET_KEY entropy (should be 32+ bytes)

**Signature Verification**:
- Constant-Time Comparison: `secrets.compare_digest()`
- Fallback Keys: Supports SECRET_KEY_FALLBACKS for rotation
- Timestamp Validation: Prevents replay attacks in TimestampSigner

### 3. Entry Point Vulnerabilities

**Attack Surface - CSRF Subsystem**:

1. **Cookie Parsing** (django/http/cookie.py:12-23)
   - Simple split-on-semicolon parser
   - Unquoting via stdlib `cookies._unquote()`
   - ✓ Safe: RFC-compliant parsing
   - ✓ No buffer overflows: Python string handling

2. **CSRF Secret Validation** (django/middleware/csrf.py:130-140)
   - Length check: Must be CSRF_SECRET_LENGTH (32) or CSRF_TOKEN_LENGTH (64)
   - Character check: Regex against `[^a-zA-Z0-9]` to ensure alphanumeric
   - ✓ Prevents injection: Only 62 allowed chars
   - ✓ No parsing after validation: Format guarantees structure

3. **CSRF Token Comparison** (django/middleware/csrf.py:143-157)
   - Unmasks token before comparison
   - Constant-time comparison prevents timing attacks
   - ✓ Safe: No timing leaks on secret

**Attack Surface - Session Subsystem**:

1. **Session Key Deserialization** (django/contrib/sessions/backends/signed_cookies.py:12-24)
   - Entry: Raw session_key from cookie (untrusted)
   - First operation: Signature verification via `signing.loads()`
   - Exception handling: BadSignature creates empty session (doesn't fail open)
   - ✓ Safe: Signature verified before deserialization
   - ⚠ Unpickling: If using PickleSerializer (deprecated), could allow RCE
   - ✓ Default: JSONSerializer is safe

2. **JSON Deserialization** (django/core/signing.py:127-128)
   - JSONSerializer.loads() uses `json.loads()`
   - No arbitrary code execution possible
   - ✓ Safe: JSON format restricts to data structures

### 4. Timing Attack Resistance

**CSRF Token Validation**:
- `constant_time_compare()` at django/middleware/csrf.py:157
- Uses `secrets.compare_digest()` for token matching
- ✓ Resistant: All comparisons take same time regardless of mismatch position

**Session Signature Verification**:
- `constant_time_compare()` at django/core/signing.py:211
- Used in Signer.unsign() during signature comparison
- ✓ Resistant: All signature comparisons are constant-time

**Potential Issue**: If main secret is compromised, attacker can regenerate valid signatures for any data

### 5. Origin/Referer Validation

**Origin Header Validation** (django/middleware/csrf.py:271-295):
- Parsed via `urlsplit()` (safe URL parsing)
- Compared against request.get_host() or CSRF_TRUSTED_ORIGINS
- ✓ Safe: Trusted origins are configured at deployment time
- ⚠ Note: Not signed/verified; browser provides but can be missing (HTTPS only)

**Referer Header Validation** (django/middleware/csrf.py:297-340):
- Requires HTTPS requests to have matching Referer or Origin
- Referer must match configured cookie domain or request host
- ✓ Secure: Falls back to Referer only for HTTPS (MITM protection)
- ✓ Strict: Rejects if Referer is missing on HTTPS POST (0.2% false positives)

### 6. Cookie Security Attributes

**CSRF Cookie** (django/middleware/csrf.py:258-266):
- `secure`: CSRF_COOKIE_SECURE flag (should be True for HTTPS)
- `httponly`: CSRF_COOKIE_HTTPONLY flag
  - If False: Cookie accessible to JavaScript (needed for AJAX)
  - If True: Prevents XSS from reading CSRF secret
  - ⚠ Trade-off: AJAX must pass token via header instead
- `samesite`: CSRF_COOKIE_SAMESITE flag (Lax/Strict/None)
  - Lax (default): Sent on top-level navigations (allows POST form)
  - Strict: Never sent in cross-site requests
  - ✓ Lax is balanced: Allows legitimate use, blocks most CSRF

**Session Cookie** (django/contrib/sessions/middleware.py:66-76):
- `secure`: SESSION_COOKIE_SECURE flag (should be True for HTTPS)
- `httponly`: SESSION_COOKIE_HTTPONLY flag (should be True)
  - Prevents XSS from reading session ID
  - ✓ Best practice: Session ID should never be in JavaScript
- `samesite`: SESSION_COOKIE_SAMESITE flag (Lax/Strict/None)
  - Strict recommended: Session should not be sent cross-site

### 7. Session Fixation Resistance

**Key Rotation**:
- No automatic rotation per request
- Manual rotation available: `request.session.cycle_key()` or `request.session.flush()`
- Django recommends calling `request.session.cycle_key()` after login
- ✓ Safe: Requires explicit developer action (not automatic)
- ⚠ Weakness: Relies on developer remembering to rotate after authentication

### 8. Configuration Weaknesses

**Insecure Defaults**:

1. CSRF_COOKIE_HTTPONLY = False (by default, should be True for most apps)
2. SESSION_COOKIE_SECURE = False (by default, should be True for HTTPS)
3. CSRF_USE_SESSIONS = False (stores in separate cookie, but requires SESSION_MIDDLEWARE before CSRF)

**Attack Scenario: Missing Secure Flag**:
```
1. User makes HTTPS request to https://bank.com
2. Attacker on same network (WiFi, etc.) intercepts response
3. Without Secure flag, cookie also sent over HTTP
4. Attacker downgrades connection or intercepts HTTP
5. CSRF token leaked to attacker
6. Attacker forges CSRF request using stolen token
```

**Mitigation**: Always set CSRF_COOKIE_SECURE=True and SESSION_COOKIE_SECURE=True in production

### 9. Middleware Ordering Vulnerability

**Requirement**: SessionMiddleware must appear before CsrfViewMiddleware if CSRF_USE_SESSIONS=True

**Entry Point** (django/middleware/csrf.py:229-237):
```python
if settings.CSRF_USE_SESSIONS:
    try:
        csrf_secret = request.session.get(CSRF_SESSION_KEY)
    except AttributeError:
        raise ImproperlyConfigured(
            "CSRF_USE_SESSIONS is enabled, but request.session is not set..."
        )
```

**Risk**: Incorrect middleware ordering causes runtime error (caught), not silent failure

### 10. Secret Key Compromise

**Impact**: If SECRET_KEY is compromised:
- ✓ CSRF tokens cannot be forged (require fresh mask)
- ✓ Session signatures cannot be forged
- ✗ But attacker can modify any session data or create valid signatures
- ✗ Attacker can impersonate any user (sign valid session with modified UID)

**Mitigation**:
- Never commit SECRET_KEY to version control
- Rotate SECRET_KEY immediately if compromised
- Use SECRET_KEY_FALLBACKS for gradual key rotation
- Each app instance should have unique SECRET_KEY

## Summary

Django's CSRF and session protection implements a defense-in-depth approach:

1. **CSRF Protection**: Combines stateful secret (CSRF cookie) with masked tokens, Origin/Referer checks, and constant-time comparison. The masking scheme prevents BREACH attacks while maintaining confidentiality.

2. **Session Security**: Uses signed cookies (by default) with HMAC-SHA256 signature, compression, and timestamp validation. Session data is never trusted without signature verification.

3. **Cryptographic Strength**: Built on secure random generation, salted HMAC, and constant-time comparison. Supports key rotation through fallback keys.

4. **Entry Point Coverage**: All untrusted data (cookies, POST, headers) is validated and formatted before use. Signature verification happens before deserialization.

5. **Cookie Security**: Provides HttpOnly, Secure, and SameSite flags to mitigate XSS and CSRF. Default SameSite=Lax balances usability with security.

6. **Potential Weaknesses**:
   - Default CSRF_COOKIE_HTTPONLY=False exposes mask in DOM
   - Developers must manually rotate session keys after authentication
   - SECRET_KEY compromise allows session forgery (not CSRF forgery)
   - Incorrect middleware ordering could silently fail (but raises exception)
   - BREACH protection assumes compression; modern TLS mitigates this

7. **Attack Scenarios Prevented**:
   - ✓ CSRF attacks (without valid token)
   - ✓ Session hijacking (without valid signature)
   - ✓ Session fixation (with cycle_key)
   - ✓ Timing attacks on token/signature verification
   - ✓ Downgrade attacks (with Secure flag set)
   - ✓ Cross-site session theft (with HttpOnly flag set)
   - ✗ XSS with HttpOnly=False (CSRF mask visible)
   - ✗ Stolen SECRET_KEY (allows signature forgery)

The implementation is cryptographically sound with well-designed entry point validation and constant-time operations throughout the authentication and CSRF pipelines.
