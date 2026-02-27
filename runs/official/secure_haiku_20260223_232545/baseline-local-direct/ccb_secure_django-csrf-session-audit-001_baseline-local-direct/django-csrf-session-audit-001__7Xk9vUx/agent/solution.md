# Django CSRF Protection and Session Handling Security Analysis

## Executive Summary

This analysis traces the complete Django CSRF protection and session handling pipeline from HTTP request reception through cryptographic validation and response cookie setting. The analysis identifies entry points where untrusted data enters the subsystem, maps the data flow through cryptographic operations, and documents security properties and potential vulnerabilities.

---

## Files Examined

### CSRF/Session Core
- **django/middleware/csrf.py** — CSRF token generation, masking, validation, and cookie management; primary entry point for CSRF protection
- **django/contrib/sessions/middleware.py** — Session middleware that loads and saves session data; integrates with CSRF middleware
- **django/contrib/sessions/backends/base.py** — Base session storage class; handles session encode/decode using signing
- **django/contrib/sessions/backends/db.py** — Database session backend; loads/saves signed session data to DB
- **django/contrib/sessions/backends/signed_cookies.py** — Signed cookie session backend; encodes entire session as signed cookie
- **django/core/signing.py** — Cryptographic signing/verification using HMAC-SHA256; supports timestamp-based expiry and compression

### Cryptographic Foundation
- **django/utils/crypto.py** — Low-level crypto utilities: get_random_string (using secrets module), constant_time_compare, salted_hmac, pbkdf2
- **django/http/request.py** — HTTP request parsing; provides COOKIES and POST access points

---

## Entry Points

### 1. CSRF Middleware Entry Points
**Location:** `django/middleware/csrf.py`

1. **process_request (line 401-412)**
   - **Input source:** `request.COOKIES[settings.CSRF_COOKIE_NAME]` (untrusted HTTP cookie)
   - **Input type:** Base62 alphanumeric string (32 or 64 characters)
   - **Processing:** Reads existing CSRF secret from cookie, validates format, stores in `request.META["CSRF_COOKIE"]`
   - **Validation:** `_check_token_format()` validates length (CSRF_SECRET_LENGTH=32 or CSRF_TOKEN_LENGTH=64) and allowed characters (alphanumeric only)

2. **process_view (line 414-469)**
   - **POST data source:** `request.POST.get("csrfmiddlewaretoken")` (line 368)
     - **Input type:** POST form field containing masked CSRF token
     - **Validation:** `_check_token_format()` validates format
   - **Header source:** `request.META[settings.CSRF_HEADER_NAME]` typically "HTTP_X_CSRFTOKEN" (line 384)
     - **Input type:** HTTP header containing masked or unmasked token
     - **Validation:** Same format validation
   - **Origin/Referer sources:** `request.META["HTTP_ORIGIN"]` and `request.META["HTTP_REFERER"]` (lines 272, 298)
     - **Input type:** User-supplied HTTP headers
     - **Processing:** URLs parsed via `urlsplit()`, validated against `CSRF_TRUSTED_ORIGINS`

3. **_get_secret (line 221-251)**
   - **Cookie source:** `request.COOKIES[settings.CSRF_COOKIE_NAME]` (line 240)
     - **Untrusted input:** Raw cookie value
     - **Processing:** Validated with `_check_token_format()`, unmasked if necessary

### 2. Session Middleware Entry Points
**Location:** `django/contrib/sessions/middleware.py`

1. **process_request (line 18-20)**
   - **Input source:** `request.COOKIES.get(settings.SESSION_COOKIE_NAME)` (untrusted HTTP cookie)
   - **Input type:** Session key (32 base-36 alphanumeric characters for DB backend, full signed session data for signed cookie backend)
   - **Processing:** Session key stored, SessionStore created with that key

2. **process_response (line 22-77)**
   - **Session save trigger:** Sets cookie with signed/encoded session data
   - **Cookie attributes:** HttpOnly, Secure, SameSite controlled by settings

### 3. Session Backend Entry Points
**Location:** `django/contrib/sessions/backends/` and `django/contrib/sessions/backends/base.py`

1. **SessionBase.decode (line 131-143)**
   - **Input source:** `session_data` parameter (signed string from DB or cookie)
   - **Input type:** HMAC-SHA256 signed, JSON serialized, optionally zlib-compressed base64 string
   - **Processing:** `signing.loads()` validates signature and deserializes
   - **Error handling:** BadSignature caught, empty dict returned (silent failure)

2. **signed_cookies.SessionStore.load (line 6-24)**
   - **Input source:** `self.session_key` (the session cookie value itself)
   - **Input type:** Signed session data (session_dict encoded as signed string)
   - **Processing:** `signing.loads()` validates signature, max_age check for expiry

---

## Data Flow

### CSRF Protection Pipeline

#### Flow 1: CSRF Token Masking and Delivery
```
1. Source: django/middleware/csrf.py:_add_new_csrf_cookie (line 84-93)
   - Generate random 32-char secret via get_random_string(32)
   - Store unmasked secret in request.META["CSRF_COOKIE"]

2. Transform: django/middleware/csrf.py:get_token (line 96-114)
   - Input: request.META["CSRF_COOKIE"] (32-char unmasked secret)
   - Process: _mask_cipher_secret() (line 59-68)
     * Generate new 32-char random mask
     * XOR each char pair with modular arithmetic on char indices
     * Return: 64-char token = mask (32 chars) + cipher (32 chars)
   - Cryptographic rationale: Prevents BREACH attack (compressing known plaintext in HTTPS responses)

3. Sink: Application code calls get_token() in view
   - Typically rendered in HTML form or returned to client
   - Client returns masked token in POST data or HTTP header
```

#### Flow 2: CSRF Token Validation (Incoming Request)
```
1. Source: django/middleware/csrf.py:process_request (line 401-412)
   - Read CSRF_COOKIE from HTTP cookies via request.COOKIES[]
   - Input: Untrusted 32 or 64 char alphanumeric string
   - Validation: _check_token_format() validates length and chars
   - Store unmasked secret in request.META["CSRF_COOKIE"]

2. Transform: django/middleware/csrf.py:_get_secret (line 221-251)
   - If CSRF_USE_SESSIONS=False: Read from COOKIES[CSRF_COOKIE_NAME]
   - If CSRF_USE_SESSIONS=True: Read from request.session[_csrftoken]
   - Unmask if length == 64 (legacy format)
   - Output: 32-char unmasked secret stored in csrf_secret variable

3. Transform: django/middleware/csrf.py:process_view -> _check_token (line 349-399)
   - Extract request token from POST["csrfmiddlewaretoken"] or META[CSRF_HEADER_NAME]
   - Input: Untrusted 32 or 64 char masked/unmasked token
   - Validate: _check_token_format() ensures valid length and characters
   - Comparison: _does_token_match() (line 143-157)
     * If token is 64 chars (masked): _unmask_cipher_token() reverses masking
     * If token is 32 chars (unmasked): use as-is
     * Compare with stored secret using constant_time_compare()

4. Sink: django/middleware/csrf.py:process_view (line 464-467)
   - If comparison fails: _reject() returns 403 Forbidden
   - If comparison succeeds: _accept() sets request.csrf_processing_done = True
```

#### Flow 3: CSRF Token Storage (Outgoing Response)
```
1. Source: django/middleware/csrf.py:request.META["CSRF_COOKIE"]
   - Contains current 32-char unmasked secret (generated or loaded from cookie)

2. Transform: django/middleware/csrf.py:_set_csrf_cookie (line 253-269)
   - If CSRF_USE_SESSIONS=False: Set HTTP-only cookie with secret as value
     * Cookie attributes: HttpOnly, Secure, SameSite, path, domain, age
     * Value: Unmasked 32-char secret (not masked for cookie storage)
   - If CSRF_USE_SESSIONS=True: Store in session["_csrftoken"], rely on session cookie

3. Sink: HTTP response headers
   - Set-Cookie header with CSRF_COOKIE_NAME=secret, security flags applied
```

#### Flow 4: Origin/Referer Validation (HTTPS)
```
1. Source: django/middleware/csrf.py:process_view (line 436-462)
   - Input: request.META["HTTP_ORIGIN"] (cross-origin requests, sent by browser)
   - Input: request.META["HTTP_REFERER"] (same-site or cross-site requests)
   - Both are untrusted HTTP headers

2. Transform: django/middleware/csrf.py:_origin_verified (line 271-295)
   - Parse Origin header via urlsplit()
   - Compare against allowed origins from settings.CSRF_TRUSTED_ORIGINS
   - Supports exact matches and wildcard subdomain patterns (*.example.com)

3. Transform: django/middleware/csrf.py:_check_referer (line 297-340)
   - Parse Referer header via urlsplit()
   - Validate scheme is HTTPS (on HTTPS sites)
   - Validate netloc matches configured cookie domain or request.get_host()
   - Check against CSRF_TRUSTED_ORIGINS

4. Sink: django/middleware/csrf.py:process_view (line 437-462)
   - If validation fails: _reject() returns 403 Forbidden
   - If validation succeeds: continue to token validation
```

---

### Session Handling Pipeline

#### Flow 1: Session Loading (Incoming Request)
```
1. Source: django/contrib/sessions/middleware.py:process_request (line 18-20)
   - Input: request.COOKIES[SESSION_COOKIE_NAME] (untrusted HTTP cookie)
   - Input type: Session key (32 chars for DB backend) or signed session data (for cookie backend)

2. Transform: SessionStore.__init__() stores session_key

3. Transform: SessionBase._get_session() (line 237-250)
   - Lazy load triggered on first access
   - Calls self.load() with session_key

4. Transform: Database backend load() (django/contrib/sessions/backends/db.py:54-56)
   - Query: SELECT session_data FROM django_session WHERE session_key=? AND expire_date > now()
   - Input: session_key from cookie (untrusted)
   - Validates session_key is at least 8 chars alphanumeric (line 215-220)
   - Database retrieval is parameterized (SQL injection prevented)
   - Calls self.decode(session_data)

5. Transform: SessionBase.decode() (line 131-143)
   - Input: Signed JSON string (from DB or cookie backend)
   - Call: signing.loads(session_data, salt="django.contrib.sessions.db", ...)
   - Signature verification validates data integrity and authenticity
   - Decompression if zlib marker present
   - Deserialization via JSONSerializer

6. Sink: request.session dictionary
   - Contains user data (CSRF token, user ID, etc.)
   - Available as dict-like object to view code
```

#### Flow 2: Session Modification and Persistence (Request Processing)
```
1. Source: Application code modifies request.session
   - Setting: request.session["key"] = value
   - Sets self.modified = True (line 58-59)

2. Transform: SessionMiddleware.process_response() (line 22-77)
   - Check if session was modified or SESSION_SAVE_EVERY_REQUEST=True
   - Call: request.session.save()

3. Transform: Database backend save() (django/contrib/sessions/backends/db.py:114-137)
   - Call: self.encode(session_dict) (line 122)
   - Encoding: signing.dumps(session_dict, salt="...", compress=True)

4. Transform: SessionBase.encode() (line 122-129)
   - Input: session_dict (untrusted application data, since app code sets it)
   - Process: signing.dumps()
     * JSONSerializer.dumps() serializes dict to JSON
     * Compression via zlib if beneficial
     * Base64 encoding
     * HMAC-SHA256 signature with salt

5. Transform: Signing pipeline (django/core/signing.py)
   - salted_hmac() derives key: SHA256(key_salt + settings.SECRET_KEY)
   - HMAC signature: HMAC-SHA256(key, "base64_data:timestamp")
   - Base64 encode signature
   - Result: "base64_data:timestamp:signature"

6. Sink: Database store (django/contrib/sessions/backends/db.py:126-129)
   - INSERT/UPDATE django_session(session_key, session_data, expire_date)
   - session_data is signed string (integrity preserved by signature)
```

#### Flow 3: Session Cookie Setting (Outgoing Response)
```
1. Source: request.session.session_key (32 char alphanumeric for DB backend)

2. Transform: SessionMiddleware.process_response() (line 66-76)
   - Call: response.set_cookie(SESSION_COOKIE_NAME, session_key, ...)
   - Cookie attributes: HttpOnly, Secure, SameSite, path, domain, max_age/expires

3. Sink: HTTP response Set-Cookie header
   - For DB backend: session_key sent (actual data in database)
   - For signed cookie backend: entire encoded/signed session sent as cookie value
```

---

## Dependency Chain

### CSRF Data Flow (Request)
1. HTTP request received → WSGI server parses cookies → request.COOKIES dict
2. `CsrfViewMiddleware.process_request()` reads `request.COOKIES[CSRF_COOKIE_NAME]`
3. `_get_secret()` validates and returns unmasked 32-char secret
4. `_check_token()` extracts token from POST or header
5. `_check_token_format()` validates (length, chars)
6. `_unmask_cipher_token()` reverses masking if needed
7. `constant_time_compare()` (uses `secrets.compare_digest()`) compares tokens
8. Decision: accept or reject request

### CSRF Data Flow (Response)
1. Application calls `get_token(request)`
2. `_add_new_csrf_cookie()` generates random 32-char secret
3. `_mask_cipher_secret()` generates random mask, XORs with secret
4. Masked token (64 chars) returned to application
5. Application renders in form/HTML
6. `CsrfViewMiddleware.process_response()` called
7. `_set_csrf_cookie()` sets cookie with unmasked secret
8. HTTP response Set-Cookie header sent to client

### Session Data Flow (Request)
1. HTTP request received → WSGI server parses cookies → request.COOKIES dict
2. `SessionMiddleware.process_request()` reads `request.COOKIES[SESSION_COOKIE_NAME]`
3. Session key stored in `SessionStore` instance
4. Lazy load: `SessionBase._get_session()` calls `load()`
5. `db.SessionStore.load()` queries database with session_key (parameterized query)
6. `SessionBase.decode()` calls `signing.loads()`
7. `Signer.unsign()` verifies HMAC-SHA256 signature
8. `constant_time_compare()` compares signatures (timing-resistant)
9. Decompression and JSON deserialization
10. Session dict returned, available to views

### Session Data Flow (Write)
1. View modifies `request.session["key"]`
2. `SessionBase.__setitem__()` sets `self.modified = True`
3. `SessionMiddleware.process_response()` checks modified flag
4. `SessionStore.save()` called
5. `SessionBase.encode()` calls `signing.dumps()`
6. `Signer.sign()` creates HMAC-SHA256 signature
7. Base64 encoding with compression
8. Database INSERT/UPDATE with signed session_data
9. Cookie set with session_key

### Cryptographic Dependency Chain
```
secrets.choice()
  ↓ (generates random mask/secret)
crypto.get_random_string()
  ↓ (generates CSRF secret/session key)
csrf.py: _get_new_csrf_string(), _mask_cipher_secret()
signing.py: salted_hmac()
  ↓ (derives HMAC key)
crypto.salted_hmac(): SHA256(key_salt + SECRET_KEY)
  ↓ (key derivation)
hmac.new(): HMAC-SHA256(key, value)
  ↓ (message authentication code)
signing.py: Signer.signature(), sign()
  ↓ (creates signed token)
session backends: encode()
  ↓ (signs session data)
Response cookies
  ↓
Client

Client → Request cookies
  ↓
csrf._does_token_match(): _unmask_cipher_token()
  ↓ (XOR reversal)
crypto.constant_time_compare(): secrets.compare_digest()
  ↓ (timing-safe comparison)
Accept/Reject decision
```

---

## Analysis

### 1. CSRF Token Masking Scheme (Security & Cryptography)

#### Design
- **Mask generation:** Random 32-char alphanumeric string from `secrets.choice()` (cryptographically secure)
- **Cipher operation:** XOR-like modular addition on character indices in CSRF_ALLOWED_CHARS
- **Token structure:** 64 chars = mask (32) + cipher (32)
  - Mask = random value
  - Cipher[i] = CSRF_ALLOWED_CHARS[(secret[i] + mask[i]) % len(CSRF_ALLOWED_CHARS)]

#### Security Properties
- **Prevents BREACH attack:** Token appears random in HTTPS responses (different every page load due to random mask)
- **Entropy:** 62^32 possibilities for mask alone (≈190 bits), secret independently random (≈190 bits)
- **Pattern concealment:** Repeated secrets not visible in responses
- **Stateless:** No server state needed for masking/unmasking

#### Cryptographic Analysis
- **Strength:** Effective against BREACH-style attacks on HTTPS with stream compression
- **Weakness:** XOR is not cryptographically strong, but only used for masking, not encryption
- **Modern context:** Token unmasking happens server-side only; masking mainly prevents response compression attacks
- **Token generation:** Both secret and mask use `secrets.choice()` (✓ cryptographically secure)

#### Implementation Details (django/middleware/csrf.py)
- `_get_new_csrf_string()` (line 55-56): Uses `get_random_string(CSRF_SECRET_LENGTH, CSRF_ALLOWED_CHARS)`
- `_mask_cipher_secret()` (line 59-68): Generates mask, performs XOR masking
- `_unmask_cipher_token()` (line 71-81): Reverses masking via modular subtraction

---

### 2. Cryptographic Signing (Session Integrity)

#### Design
```
signing.dumps(session_dict, salt="django.contrib.sessions.db", compress=True)
  → JSON serialize → optional zlib compress → base64 encode
  → salted_hmac() for signature → Signer.sign() appends signature
  Result: "base64_data:timestamp:signature"
```

#### Cryptographic Properties
- **HMAC algorithm:** SHA-256 (default in `signing.py` line 192)
- **Key derivation:** `salted_hmac(key_salt, value, secret, algorithm="sha1")`
  - Key = SHA1(key_salt + SECRET_KEY) for HMAC
  - Rationale: Derives a key deterministically from salt + master secret
  - Prevents key reuse across different salts
- **Message authentication:** HMAC-SHA256(derived_key, value) prevents tampering
- **Signature verification:** `constant_time_compare()` using `secrets.compare_digest()`
  - Prevents timing attacks on signature comparison

#### Entry Point Validation
```python
# Session decode (django/contrib/sessions/backends/base.py:131-143)
def decode(self, session_data):
    try:
        return signing.loads(session_data, salt=self.key_salt, ...)
    except signing.BadSignature:
        logger.warning("Session data corrupted")
    except Exception:
        pass
    return {}
```
- **Silent failure on corruption:** Returns empty dict if signature invalid (important for robustness)
- **Salt uniqueness:** Uses `"django.contrib.sessions." + class_qualname` as salt
- **Max age validation:** Timestamp in signature checked against max_age (session cookie age)

#### Signature Format (django/core/signing.py:177-213)
```
Signer.sign(value):
  value = "data" (base64 encoded session)
  signature = base64_hmac(salt + "signer", value, key, algorithm="sha256")
  return "data:signature"

TimestampSigner.sign(value):
  timestamp = b62_encode(int(time.time()))  # Base62-encoded Unix timestamp
  value = "data:timestamp"
  return Signer.sign("data:timestamp") → "data:timestamp:signature"
```

#### Constant-Time Comparison (django/utils/crypto.py:65-67)
```python
def constant_time_compare(val1, val2):
    return secrets.compare_digest(force_bytes(val1), force_bytes(val2))
```
- Uses `secrets.compare_digest()` (guaranteed constant-time in Python 3.3+)
- Prevents timing-based signature forgery attacks
- All signature comparisons in signing.py use this (line 211)

---

### 3. Cookie Security Attributes

#### CSRF Cookie Settings (django/middleware/csrf.py:258-267)
```python
response.set_cookie(
    settings.CSRF_COOKIE_NAME,           # "csrftoken"
    request.META["CSRF_COOKIE"],         # 32-char secret
    max_age=settings.CSRF_COOKIE_AGE,    # 31449600 (1 year default)
    domain=settings.CSRF_COOKIE_DOMAIN,  # None (omit Domain header) or specific domain
    path=settings.CSRF_COOKIE_PATH,      # "/" (default)
    secure=settings.CSRF_COOKIE_SECURE,  # True on HTTPS sites (default)
    httponly=settings.CSRF_COOKIE_HTTPONLY,  # True (prevent JS access)
    samesite=settings.CSRF_COOKIE_SAMESITE,  # "Strict" or "Lax" (default "Lax")
)
```

#### Security Analysis
- **HttpOnly=True:** Prevents XSS from reading token via JavaScript; app must embed in form/HTML
- **Secure=True:** Only sent over HTTPS; prevents MITM downgrade attacks
- **SameSite=Lax:** Cookie sent on top-level navigations (forms) but not subresource requests
  - Prevents CSRF in most scenarios
  - Complements CSRF token validation for defense-in-depth
- **Path=/:** Standard application-wide setting
- **Domain:** If None, browser restricts to exact domain (no subdomain leakage)

#### Session Cookie Settings (django/contrib/sessions/middleware.py:66-76)
```python
response.set_cookie(
    settings.SESSION_COOKIE_NAME,        # "sessionid"
    request.session.session_key,         # 32-char random key (DB backend)
    max_age=max_age,                     # Based on expiry settings
    expires=expires,                     # Absolute expiration time
    domain=settings.SESSION_COOKIE_DOMAIN,  # None or specific domain
    path=settings.SESSION_COOKIE_PATH,   # "/" (default)
    secure=settings.SESSION_COOKIE_SECURE or None,
    httponly=settings.SESSION_COOKIE_HTTPONLY or None,
    samesite=settings.SESSION_COOKIE_SAMESITE,
)
```

#### Security Considerations
- **HttpOnly=True:** Mandatory for session cookies (user authentication data)
- **Secure=True:** Essential if site uses HTTPS
- **SameSite:** Prevents session fixation via cross-site requests (when combined with token validation)
- **Max-Age:** Server-side session expiry enforced in DB query (expire_date__gt=now)
- **Signed session backend:** Cookie value is signed session data (full HMAC protection)

---

### 4. Entry Point Validation Summary

| Entry Point | Input Source | Validation | Security |
|---|---|---|---|
| CSRF Cookie | `request.COOKIES[CSRF_COOKIE_NAME]` | `_check_token_format()`: length (32 or 64), alphanumeric only | ✓ Length/charset validated, format checked |
| CSRF POST Token | `request.POST["csrfmiddlewaretoken"]` | `_check_token_format()`: length, chars | ✓ Validated before comparison |
| CSRF Header | `request.META[CSRF_HEADER_NAME]` | `_check_token_format()`: length, chars | ✓ Validated before comparison |
| Origin/Referer Headers | `request.META["HTTP_ORIGIN"]` | `urlsplit()`, domain matching against whitelist | ✓ Parsed, validated against CSRF_TRUSTED_ORIGINS |
| Session Key | `request.COOKIES[SESSION_COOKIE_NAME]` | Length ≥ 8 alphanumeric (for DB backend) | ⚠ Minimal validation, rely on signature |
| Session Data (Cookie backend) | Session key = signed data | HMAC-SHA256 signature verified | ✓ Signature validated before deserialization |

---

### 5. Potential Attack Scenarios and Mitigations

#### A. CSRF Token Prediction Attack
**Scenario:** Attacker tries to predict CSRF token for victim user

**Mitigation Chain:**
1. Token depends on unpredictable random 32-char secret (secrets.choice, ~190 bits entropy)
2. Secret generated independently per-request (CSRF_COOKIE_NEEDS_UPDATE flag)
3. Attacker cannot access secret (not in response due to masking, HttpOnly flag)
4. Even with token, validation requires matching stored secret
5. HTTPS+SameSite prevents cookie leakage across sites

**Residual Risk:** Low. Token generation uses cryptographically secure RNG, no predictable patterns exposed.

#### B. Session Fixation via Cookie Injection
**Scenario:** Attacker sets session cookie to known value (via HTTPOnly bypass, form submission, etc.)

**Mitigation Chain:**
1. Session data signed with HMAC-SHA256 (attacker cannot forge valid signature)
2. Signature verified on load (BadSignature caught, empty dict returned)
3. Server-side session expiry checked (expire_date__gt=now in DB query)
4. Session key rotation via `rotate_token()` on login

**Residual Risk:** Low if:
- SECRET_KEY kept confidential (shared with no other services)
- Session expiry properly configured
- Login triggers session rotation

**Potential Gap:** If attacker compromises SECRET_KEY, all sessions forgeable (but this is catastrophic anyway).

#### C. BREACH Attack on CSRF Token Response
**Scenario:** Attacker compresses HTTPS response to infer token via response size

**Mitigation Chain:**
1. CSRF token masked with random 32-char mask on every render
2. Unmasking happens server-side only (client cannot expose plaintext)
3. Mask changes on every page load (different compressed size)
4. SameSite cookie prevents token from being sent in attacker's request

**Residual Risk:** Very low. Token masking specifically designed against this. Note: BREACH mitigation has diminished importance with modern TLS (no compression by default).

#### D. Man-in-the-Middle (MITM) Downgrade on HTTP
**Scenario:** Attacker forces HTTP connection instead of HTTPS

**Mitigation Chain:**
1. CSRF cookie: `secure=True` prevents HTTP transmission
2. Session cookie: `secure=True` prevents HTTP transmission
3. Origin/Referer validation: HTTPS-only sites reject HTTP Referer (line 312)
4. Browsers: HSTS, Upgrade-Insecure-Requests directives

**Residual Risk:** Medium on non-HSTS sites. Initial visit vulnerable to downgrade if no HSTS header.

#### E. Cross-Site Session Hijacking via Signed Cookie Forgery
**Scenario:** Attacker tries to forge signed session cookie

**Mitigation Chain:**
1. Session signed with HMAC-SHA256 using salted key
2. Signature verification happens before deserialization (line 133)
3. BadSignature exception caught, empty dict returned (no crash or data leak)
4. Constant-time comparison prevents timing attacks

**Residual Risk:** Very low if:
- SECRET_KEY is unique per deployment
- No side-channel attacks on timing comparison (secrets module handles this)

#### F. Session Data Tampering (if using DB backend)
**Scenario:** Attacker modifies session_data in database

**Mitigation Chain:**
1. Session_data is signed string (attacker cannot modify without signature)
2. Signature verification (HMAC-SHA256) detects any modification
3. BadSignature caught, session reset to empty

**Residual Risk:** Low if database access controlled. If DB is compromised, all sessions forgeable anyway.

#### G. CSRF Token Reuse Across Requests
**Scenario:** Attacker captures masked token, uses it in multiple requests

**Mitigation Chain:**
1. Token validation checks request.META["CSRF_COOKIE"] against POST/header token
2. Server regenerates token on each page load (CSRF_COOKIE_NEEDS_UPDATE flag)
3. Each token is valid only if it matches current cookie value
4. Attacker cannot use old token after cookie rotates

**Residual Risk:** Very low. Validation is per-request against current cookie.

---

### 6. Cryptographic Strength Assessment

#### CSRF Secret Generation
- **Source:** `secrets.choice(CSRF_ALLOWED_CHARS)` repeated 32 times
- **Entropy:** log₂(62^32) ≈ 190 bits
- **Assessment:** ✓ Strong. Exceeds standard recommendations (128 bits minimum)

#### Session Key Generation
- **Source:** `secrets.choice(VALID_KEY_CHARS)` repeated 32 times (line 195)
- **Entropy:** log₂(36^32) ≈ 165 bits
- **Assessment:** ✓ Strong enough for session key (collision-resistant via DB existence check)

#### HMAC Algorithm
- **Algorithm:** HMAC-SHA256 (default in signing.py)
- **Key derivation:** SHA1(key_salt + SECRET_KEY)
- **MAC:** HMAC(derived_key, message)
- **Assessment:** ✓ Strong. SHA-256 is current standard, no known attacks

#### Timestamp Encoding
- **Method:** Base62 encoding of Unix timestamp (line 256)
- **Validation:** max_age parameter checks timestamp freshness
- **Assessment:** ✓ Sufficient for expiry validation, not security-critical

#### Constant-Time Comparison
- **Method:** `secrets.compare_digest()` (guaranteed constant-time in CPython 3.3+)
- **Assessment:** ✓ Prevents timing attacks on signature verification

---

### 7. Defense-in-Depth Analysis

The CSRF/session pipeline employs multiple complementary defenses:

| Layer | Mechanism | Threat Addressed |
|---|---|---|
| **Request Origin Validation** | Origin/Referer header checking | Prevents cross-site form submission |
| **Token Validation** | CSRF secret matching | Prevents CSRF even if cookies leaked |
| **Cookie Attributes** | HttpOnly, Secure, SameSite | Prevents XSS, MITM, cross-site leakage |
| **Signature Verification** | HMAC-SHA256 on session data | Prevents session tampering |
| **Session Expiry** | Timestamp validation, max_age | Prevents replay of expired sessions |
| **Token Masking** | Random XOR mask per response | Prevents BREACH attacks on HTTPS |
| **Constant-Time Comparison** | secrets.compare_digest() | Prevents timing attacks |
| **Stateless Secret** | Per-request CSRF secret in cookie | Prevents session fixation |

---

### 8. Identified Vulnerabilities and Mitigations

#### Vulnerability 1: Silent Failure on Corrupted Session Data
**Location:** `django/contrib/sessions/backends/base.py:131-143`
```python
def decode(self, session_data):
    try:
        return signing.loads(...)
    except signing.BadSignature:
        logger.warning("Session data corrupted")  # Only logs warning
    except Exception:
        pass  # Silently ignores all errors
    return {}  # Returns empty dict
```

**Issue:** Session corruption (due to tampering or data corruption) silently creates new empty session without explicit error to user

**Risk Class:** Denial of Service, Data Loss
- User loses session data silently
- No error message to help diagnose the issue
- Attacker can force user to lose session via cookie tampering (though signature prevents this)

**Existing Mitigation:** Signature validation prevents unauthorized modifications; logging provides audit trail

**Recommendation:** Consider logging at WARNING or ERROR level (already done), or optionally raising exception in production if SESSION_FAIL_SILENTLY=False

---

#### Vulnerability 2: HTTP Referer Validation Gap (when Origin header missing)
**Location:** `django/middleware/csrf.py:297-340`
```python
def _check_referer(self, request):
    referer = request.META.get("HTTP_REFERER")
    if referer is None:
        raise RejectRequest(REASON_NO_REFERER)  # Rejects if no Referer
    ...
```

**Issue:** On HTTPS sites without Origin header, request rejected if Referer missing (per RFC design)

**Risk Class:** Legitimate request rejection (false positive)
- Privacy-conscious users with strict Referer policy rejected
- Proxies that strip Referer cause false rejections
- ~0.2% of legitimate requests affected (per code comment, line 456)

**Existing Mitigation:** Comment explains this is acceptable tradeoff; SameSite cookie provides fallback

**Assessment:** By design; acceptable given CSRF token also required as backup

---

#### Vulnerability 3: CSRF Cookie Domain Configuration
**Location:** `django/middleware/csrf.py:258-267`
```python
response.set_cookie(
    settings.CSRF_COOKIE_NAME,
    ...,
    domain=settings.CSRF_COOKIE_DOMAIN,  # If set, domain is too broad
    ...
)
```

**Issue:** If CSRF_COOKIE_DOMAIN set to parent domain (e.g., ".example.com"), all subdomains receive cookie

**Risk Class:** Cookie leakage across subdomains
- Subdomain compromise leads to CSRF token leakage
- Attacker can use leaked token on main domain

**Existing Mitigation:** Default is None (no Domain cookie attribute, restricts to exact host)

**Recommendation:** Document that CSRF_COOKIE_DOMAIN should remain None unless specifically needed for shared subdomains

---

#### Vulnerability 4: No Invalidation on Login/Logout
**Location:** `django/middleware/csrf.py:117-122`
```python
def rotate_token(request):
    """Change the CSRF token in use for a request."""
    _add_new_csrf_cookie(request)
```

**Issue:** CSRF token rotation is manual; Django doesn't automatically call it on login/logout

**Risk Class:** Session fixation (if token not rotated on login)
- Attacker can set CSRF token before login
- If server uses same token for authenticated session, potential vulnerability
- However, CSRF validation requires matching stored secret, so attacker cannot forge

**Existing Mitigation:** Secret stored in cookie (not in URL or form), making token hard to set before login

**Recommendation:** Document that developers should call `rotate_token()` on login; consider automatic rotation

---

#### Vulnerability 5: POST Data Reading Side Channel
**Location:** `django/middleware/csrf.py:366-374`
```python
try:
    request_csrf_token = request.POST.get("csrfmiddlewaretoken", "")
except UnreadablePostError:
    # Handle broken connection
    pass  # Pass silently, skip token validation later
```

**Issue:** If POST data unreadable (broken connection), token validation is skipped due to exception catch

**Risk Class:** Potential CSRF bypass on connection errors
- Attacker crafts request that causes UnreadablePostError
- CSRF validation skipped, request processed
- However, Origin/Referer validation still applies on HTTPS

**Existing Mitigation:** Exception is handled; Origin/Referer validation provides fallback. Code comment acknowledges this is acceptable.

**Assessment:** Low risk; exceptional condition unlikely to be exploitable

---

### 9. Configuration Security Implications

#### Critical Settings
```python
SECRET_KEY                          # Master key for all signatures - MUST be kept secret
CSRF_USE_SESSIONS                   # Store CSRF token in session instead of cookie
CSRF_COOKIE_SECURE                  # Must be True on HTTPS sites
CSRF_COOKIE_HTTPONLY                # Should be True (prevents JS access)
CSRF_COOKIE_SAMESITE                # Should be "Strict" or "Lax"
SESSION_COOKIE_SECURE               # Must be True on HTTPS sites
SESSION_COOKIE_HTTPONLY             # Must be True (prevents JS access)
CSRF_TRUSTED_ORIGINS                # Whitelist of allowed cross-origin endpoints
```

#### Unsafe Configurations
1. **DEBUG=True in production:** Exposes settings including SECRET_KEY in error pages
2. **ALLOWED_HOSTS missing:** HOST_HEADER validation can be bypassed
3. **CSRF_COOKIE_SECURE=False on HTTPS:** Cookies sent over HTTP, vulnerable to MITM
4. **SESSION_COOKIE_SECURE=False on HTTPS:** Same as above
5. **CSRF_COOKIE_HTTPONLY=False:** XSS can steal CSRF token (though token still validated)

---

## Summary

Django's CSRF protection and session handling implements a robust, multi-layered defense strategy:

### CSRF Protection
- **Mechanism:** Double-submit cookie validation with random unguessable token + Origin/Referer validation
- **Token masking:** XOR-based masking prevents BREACH attacks on HTTPS compression
- **Cryptographic strength:** 32-byte random secret (≈190 bits entropy) from cryptographically secure RNG
- **Constant-time comparison:** Uses `secrets.compare_digest()` to prevent timing attacks

### Session Handling
- **Integrity:** HMAC-SHA256 signatures with salted key derivation
- **Confidentiality:** HttpOnly and Secure cookie flags prevent XSS and MITM
- **Freshness:** Timestamp-based expiry with max_age validation
- **Stateless:** Signed cookies backend eliminates server-side session storage need

### Data Flow
- **Entry points:** HTTP cookies and POST/header fields (all validated before use)
- **Cryptographic chain:** Secure RNG → token generation/masking → HMAC signing → constant-time verification
- **Error handling:** Silent failures on corrupted data (logged), exceptions on validation failures

### Identified Risks
1. **Silent session corruption:** Returns empty dict on BadSignature (design choice, acceptable)
2. **Referer validation false positives:** 0.2% of legitimate HTTPS requests, compensated by SameSite
3. **Subdomain cookie leakage:** Mitigated by default None domain setting
4. **Manual token rotation:** Developers must call rotate_token() on login (not automatic)
5. **Connection error bypass:** UnreadablePostError bypasses token check, but Origin/Referer provides fallback

### Overall Assessment
**Security Grade: A**

The implementation is well-designed with appropriate use of:
- Cryptographically secure random number generation (secrets module)
- HMAC-SHA256 for message authentication
- Constant-time comparison for signature validation
- Defense-in-depth (origin validation + token validation + cookie attributes)
- Modern cookie security attributes (HttpOnly, Secure, SameSite)

**Recommended Actions:**
1. Keep SECRET_KEY highly confidential and unique per deployment
2. Ensure CSRF_COOKIE_SECURE and SESSION_COOKIE_SECURE are True on HTTPS
3. Call rotate_token() on login/password change for token rotation
4. Configure CSRF_TRUSTED_ORIGINS strictly (whitelist only necessary origins)
5. Monitor security logs for BadSignature warnings (indicates tampering attempts)
6. Use signed cookie backend for stateless session handling where possible
