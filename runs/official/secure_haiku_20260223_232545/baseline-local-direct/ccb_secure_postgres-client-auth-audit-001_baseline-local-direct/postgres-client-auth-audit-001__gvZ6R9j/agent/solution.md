# PostgreSQL Client Authentication Pipeline Security Analysis

## Files Examined

### TCP Connection & Startup
- `src/backend/tcop/backend_startup.c` — TCP connection acceptance, startup packet processing (`ProcessStartupPacket`)
- `src/backend/libpq/libpq.c` — libpq initialization and message framing
- `src/backend/libpq/pqformat.c` — Protocol message formatting and parsing

### Authentication Dispatch & HBA Matching
- `src/backend/libpq/auth.c` — Main authentication dispatcher (`ClientAuthentication`), password/plaintext auth (`CheckPasswordAuth`, `CheckPWChallengeAuth`, `CheckMD5Auth`)
- `src/backend/libpq/hba.c` — HBA configuration loading (`load_hba`), rule matching (`check_hba`, `hba_getauthmethod`), database/role validation
- `src/backend/utils/init/postinit.c` — Post-initialization handler (`PerformAuthentication`), database validation (`CheckMyDatabase`)
- `src/backend/utils/init/miscinit.c` — Initialization and role lookup utilities

### Password & Credential Storage
- `src/backend/libpq/crypt.c` — Password retrieval from pg_authid (`get_role_password`), password type detection, encryption functions

### SASL/SCRAM Authentication
- `src/backend/libpq/auth-sasl.c` — SASL exchange handler (`CheckSASLAuth`), message loop protocol
- `src/backend/libpq/auth-scram.c` — SCRAM-SHA-256 mechanism (`scram_init`, `scram_exchange`), salt/iteration handling, HMAC verification

### Authentication Methods (External)
- `src/backend/libpq/auth.c` — GSSAPI (`pg_GSS_recvauth`), LDAP, PAM, BSD auth, SSPI, RADIUS, OAuth
- `src/backend/libpq/auth-oauth.c` — OAuth/OIDC authentication mechanism

### Role & ACL Validation
- `src/backend/catalog/pg_authid.h` — Role definitions and password storage schema
- `src/backend/utils/acl.c` — ACL checks and role permissions

---

## Entry Points

Entry points are locations where untrusted client data enters the authentication subsystem without validation or after minimal format validation:

### 1. Network Startup Packet Reception
**File:** `src/backend/tcop/backend_startup.c:ProcessStartupPacket` (line 492-866)

**Untrusted Input Type:** Raw network bytes from TCP socket

**Data Reception:**
```c
// Line 499-532: Read message length and validate bounds
pq_startmsgread();
if (pq_getbytes(&len, 1) == EOF) ...
if (pq_getbytes(((char *) &len) + 1, 3) == EOF) ...
len = pg_ntoh32(len);
len -= 4;
if (len < (int32) sizeof(ProtocolVersion) || len > MAX_STARTUP_PACKET_LENGTH) ...

// Line 549-558: Allocate buffer and receive startup packet bytes
buf = palloc(len + 1);
buf[len] = '\0';  // Add null terminator
if (pq_getbytes(buf, len) == EOF) ...
```

**Extracted Untrusted Parameters:**
- `port->user_name` (line 748): Username from startup packet's `user` parameter
- `port->database_name` (line 747): Database name from startup packet's `database` parameter
- `port->guc_options` (line 787-790): GUC options from key-value pairs
- `port->application_name` (line 800): Application name (cleaned with `pg_clean_ascii`)
- `port->cmdline_options` (line 751): Command-line options string

**Length Limits Applied:**
- Line 840-843: Usernames and database names truncated to `NAMEDATALEN - 1` (63 bytes)
- Line 536: Entire startup packet limited to `MAX_STARTUP_PACKET_LENGTH`

### 2. Password Packet Reception
**File:** `src/backend/libpq/auth.c:recv_password_packet` (line 706-778)

**Untrusted Input Type:** Plaintext password from client

**Data Reception:**
```c
// Line 712-728: Receive password message
pq_startmsgread();
mtype = pq_getbyte();
if (mtype != PqMsg_PasswordMessage) ...

// Line 732-747: Receive password and validate size
initStringInfo(&buf);
if (pq_getmessage(&buf, PG_MAX_AUTH_TOKEN_LENGTH)) ...
if (strlen(buf.data) + 1 != buf.len) ...  // Size validation
if (buf.len == 1) ...  // Empty password check
```

**Extracted Untrusted Parameter:**
- Plaintext password string (returned at line 776)

**Validation:**
- Maximum length: `PG_MAX_AUTH_TOKEN_LENGTH` (1 MB)
- Empty password rejection (line 762-765)
- Length consistency check (line 744-747)

### 3. SASL/SCRAM Initial Response
**File:** `src/backend/libpq/auth-sasl.c:CheckSASLAuth` (line 44-194)

**Untrusted Input Type:** SASL mechanism selection and challenge response

**Data Reception:**
```c
// Line 77-103: SASL message loop
do {
    pq_startmsgread();
    mtype = pq_getbyte();
    if (mtype != PqMsg_SASLResponse) ...

    initStringInfo(&buf);
    if (pq_getmessage(&buf, mech->max_message_length)) ...  // Length limit
}

// Line 113-139: First SASLInitialResponse unpacking
if (initial) {
    selected_mech = pq_getmsgrawstring(&buf);  // Mechanism name
    opaq = mech->init(port, selected_mech, shadow_pass);  // Initialization

    inputlen = pq_getmsgint(&buf, 4);
    if (inputlen == -1)
        input = NULL;
    else
        input = pq_getmsgbytes(&buf, inputlen);  // SASL payload
}
```

**Extracted Untrusted Parameters:**
- Mechanism name string (line 117): e.g., "SCRAM-SHA-256"
- SASL exchange payload (line 137, 144): Client response tokens

**Validation:**
- Message length limited by `mech->max_message_length` (1 MB for SCRAM)
- Mechanism name validated against supported mechanisms in `scram_get_mechanisms`

### 4. SCRAM Challenge Response
**File:** `src/backend/libpq/auth-scram.c:scram_exchange` (called from auth-sasl.c:157-159)

**Untrusted Input Type:** SCRAM challenge/response tokens

**Data Reception:** Via parent `CheckSASLAuth`, but processed through:
```c
// auth-scram.c: scram_exchange receives
// - First client message: "[reserved-mext=,]username,nonce=<cnonce>[,extensions]"
// - Subsequent messages: challenge/response tokens
```

**Validation:**
- Base64 decoding of salt and stored key
- UTF-8 validation for username
- Channel binding data validation (if enabled)

---

## Data Flow

### Flow 1: Startup Packet → HBA Rule Matching → Authentication Method Selection

**Source:** `src/backend/tcop/backend_startup.c:ProcessStartupPacket` (lines 499-866)
- Untrusted input: Network bytes parsed into `port->user_name`, `port->database_name`
- Validation: Length truncation, null termination
- Stored in: `Port` structure (allocated in `TopMemoryContext`)

**Transform 1:** `src/backend/tcop/backend_startup.c` (lines 747-748, 836-843)
- Database name defaults to user name if not provided
- Names truncated to `NAMEDATALEN - 1` (63 bytes)
- No further validation of contents (special characters allowed)

**Transform 2:** `src/backend/utils/init/postinit.c:PerformAuthentication` (line 217-226)
- Loads HBA config via `load_hba()` from file system
- HBA rules are pre-parsed in `PostmasterContext`

**Transform 3:** `src/backend/libpq/hba.c:check_hba` (lines 2531-2631)
- Matches `port->user_name` and `port->database_name` against HBA rules
- Line 2538: `get_role_oid(port->user_name, true)` — role lookup (returns OID or InvalidOid if not found)
- Line 2615: `check_db()` — database name matching (glob patterns)
- Line 2619: `check_role()` — role matching (glob patterns, group membership, ident mapping)
- Line 2623: Selected HBA rule stored in `port->hba`

**Sink:** `src/backend/libpq/auth.c:ClientAuthentication` (line 390)
- Dispatches to authentication handler based on `port->hba->auth_method`
- Example: `uaPassword`, `uaSCRAM`, `uaGSS`, `uaLDAP`, `uaPAM`, etc.

**Security Properties:**
- **Attack Surface:** Username and database name used directly in SQL catalog queries without parameterization, but via OID lookup functions which are robust
- **Mitigations:**
  - Length limits prevent buffer overflows
  - Role lookups are case-insensitive and use syscache (`SearchSysCache1(AUTHNAME, ...)`)
  - HBA rule matching is case-insensitive for role/database names
  - Special characters in usernames are allowed and don't bypass authentication

---

### Flow 2: Password-Based Authentication (MD5)

**Source:** `src/backend/libpq/auth.c:CheckPWChallengeAuth` (lines 823-880)
- Untrusted input: `port->user_name` from startup packet
- Entry point: Password verification using MD5 challenge-response

**Transform 1:** `src/backend/libpq/crypt.c:get_role_password` (lines 38-84)
- Input: `port->user_name` (untrusted)
- Database lookup: `SearchSysCache1(AUTHNAME, PointerGetDatum(role))`
  - Searches `pg_authid` catalog for `rolname = role`
  - Returns `NULL` if role not found (line 48-52)
- Output: `shadow_pass` (MD5 hash from `pg_authid.rolpassword`)
- Validation:
  - Line 76: Checks if password is expired (`rolvaliduntil < now`)
  - Line 76-81: Returns `NULL` if expired

**Transform 2:** `src/backend/libpq/auth.c:CheckMD5Auth` (lines 883-912)
- Line 890: Generates random 4-byte salt via `pg_strong_random()`
- Line 897: Sends salt to client in `AUTH_REQ_MD5` response
- Line 899: Receives password response via `recv_password_packet()`
- Line 904: **Sensitive Operation:** `md5_crypt_verify(port->user_name, shadow_pass, passwd, md5Salt, 4, logdetail)`
  - Verifies client password against stored MD5 hash
  - Computes `MD5(MD5(password) + salt)`
  - Compares with stored hash (timing-safe comparison in modern versions)

**Sink:** `src/backend/libpq/auth.c:ClientAuthentication` (lines 813-817, 876-879)
- On successful verification: `set_authn_id(port, port->user_name)` (line 814)
- Returns `STATUS_OK` to parent
- Session is established in `PostgresMain`

**Security Properties:**
- **Vulnerability Class:** MD5 is cryptographically broken; weak password hashing
- **Mitigations:**
  - Random salt generated per session
  - Password stored as salted MD5 hash, not plaintext
  - User account lookup uses parameterized OID search
  - Timing-safe comparison (in recent versions)
- **Risks:**
  - MD5 is obsolete; vulnerable to pre-computed rainbow tables
  - Deprecated in PostgreSQL 13+ in favor of SCRAM

---

### Flow 3: SCRAM-SHA-256 Authentication

**Source:** `src/backend/libpq/auth-sasl.c:CheckSASLAuth` (lines 44-194)
- Untrusted input: Mechanism selection and SCRAM challenge/response

**Transform 1:** SCRAM Mechanism Initialization
**File:** `src/backend/libpq/auth-scram.c:scram_init` (called from auth-sasl.c:131)
- Input:
  - `port->user_name` (from startup packet)
  - `selected_mech` (from SASL initial response, untrusted)
  - `shadow_pass` (from `get_role_password`)
- Processing:
  - Line 131: `opaq = mech->init(port, selected_mech, shadow_pass)`
  - Validates mechanism name against `SCRAM-SHA-256` and variants
  - If user doesn't exist or password invalid: Sets `doomed` flag (mock authentication)
  - Initializes SCRAM state machine

**Transform 2:** Client Initial Message Processing
**File:** `src/backend/libpq/auth-scram.c` (scram_exchange, first iteration)
- Untrusted input: Client initial message (base64-encoded)
  - Format: `[reserved-mext=,]authzid,nonce=<cnonce>[,extensions]`
- Processing:
  - Base64 decode
  - Parse GS2 header (channel binding info)
  - Extract username (must be empty per RFC 5802 section 7.1)
  - Extract client nonce
  - Validate against username from startup packet
- Mock authentication:
  - If `doomed` flag set: Generate fake salt and iteration count
  - Proceeding with mock values ensures attacker can't distinguish valid/invalid users

**Transform 3:** Password Preparation
- Input: Stored SCRAM secret from `pg_authid.rolpassword`
  - Format: `SCRAM-SHA-256$<iterations>$<salt>$<StoredKey>$<ServerKey>`
  - Example: `SCRAM-SHA-256$4096$QNVGQ3DQndQ8ZQ==$...`
- Processing:
  - Parse iterations count
  - Decode salt (base64)
  - Extract StoredKey (HMAC-SHA256 of ClientKey)
  - Extract ServerKey (HMAC-SHA256 of SaltedPassword)
- SASLprep processing:
  - Normalize password as UTF-8
  - If invalid UTF-8: Use raw bytes (line 42-49 of auth-scram.c)

**Transform 4:** Client Proof Verification
**File:** `src/backend/libpq/auth-scram.c` (scram_exchange, subsequent iterations)
- Untrusted input: Client proof (ClientKey XOR with H(StoredKey))
- Algorithm (RFC 5802):
  1. Receive client-final-message: `channel-binding,nonce,proof=...`
  2. Compute `ClientKey = HMAC(SaltedPassword, "Client Key")`
  3. Compute `StoredKey = SHA256(ClientKey)` — compare with stored value
  4. On match: Derive `ServerKey = HMAC(SaltedPassword, "Server Key")`
  5. Send server-final-message with `ServerSignature = HMAC(ServerKey, auth-message)`

**Sink:** `src/backend/libpq/auth-sasl.c` (lines 178-181)
- On successful SCRAM exchange: `AUTH_REQ_SASL_FIN` sent to client
- Server-side verification succeeds
- Returns `PG_SASL_EXCHANGE_SUCCESS`

**Security Properties:**
- **Vulnerability Class:** Challenge-response is secure; strong PBKDF2-like stretching
- **Mitigations:**
  - HMAC-SHA256 for message integrity and authenticity
  - Salted password with configurable iterations (default 4096, recommended 10000+)
  - Channel binding (tls-server-end-point) prevents MITM if TLS enabled
  - "Doomed" authentication prevents username enumeration
  - SASLprep unicode normalization prevents homograph attacks
- **Strengths:**
  - StoredKey design prevents offline password recovery from database dump
  - Server doesn't store cleartext password or intermediate keys
  - Multi-round exchange prevents replay attacks
  - Iteration count (PBKDF2 factor) configurable per password

---

### Flow 4: HBA File Loading and Parsing

**Source:** `src/backend/libpq/hba.c:load_hba` (lines 2644-2733)
- Untrusted input: File system (pg_hba.conf)

**Transform 1:** File Reading
- Line 2655: `open_auth_file(HbaFileName, LOG, 0, NULL)`
- Reads HBA configuration from disk
- Permissions checked by OS file system

**Transform 2:** Tokenization
- Line 2662: `tokenize_auth_file(HbaFileName, file, &hba_lines, LOG, 0)`
- Parses line-by-line into tokens
- Handles quoting, escaping, comments

**Transform 3:** Parsing and Compilation
- Lines 2670-2696: For each tokenized line:
  - Line 2682: `parse_hba_line(tok_line, LOG)`
  - Validates fields: connection type, database, role, IP/mask, auth method, options
  - Compiles regex patterns (for role and database matching)
  - Allocates `HbaLine` structure in `hbacxt` memory context

**Transform 4:** Installation
- Lines 2727-2730: Replace global `parsed_hba_lines` and `parsed_hba_context`
- Old context deleted via `MemoryContextDelete()`

**Sink:** `src/backend/libpq/hba.c:check_hba` (line 2540)
- Uses `parsed_hba_lines` list to match incoming connection

**Security Properties:**
- **Vulnerability Class:** Configuration file injection (if HBA file writable by unprivileged user)
- **Mitigations:**
  - File permissions checked by OS
  - Regex compilation errors logged but don't crash server
  - Invalid parsing errors logged but don't block startup
  - HBA rules are pre-compiled, not evaluated at connection time (no injection at auth time)
- **Risks:**
  - If `pg_hba.conf` writable: Attacker can change auth rules (requires OS-level compromise)
  - Glob patterns in role/database fields could be misused for bypass

---

### Flow 5: Role and Database Matching

**Source:** `src/backend/libpq/hba.c:check_hba` (line 2615)
- Untrusted input: `port->user_name`, `port->database_name` from startup packet

**Transform 1:** Database Name Matching
- Line 2615: `check_db(port->database_name, port->user_name, roleid, hba->databases)`
- HBA rule specifies database match criteria (glob patterns or "all")
- Matching is case-insensitive
- Special case: `sameuser` — database name must match role name

**Transform 2:** Role Name Matching
- Line 2619: `check_role(port->user_name, roleid, hba->roles, false)`
- Validates role exists and matches HBA criteria
- Supports:
  - Role glob patterns (e.g., `user*`, `+group_name`)
  - Group membership (roles with `rolcanlogin = false`)
  - Ident mapping (mapping system user to PostgreSQL role)

**Sink:** `src/backend/libpq/hba.c:check_hba` (line 2623)
- Selected HBA rule stored in `port->hba`
- Used by `ClientAuthentication` to select auth method

**Security Properties:**
- **Vulnerability Class:** Authentication rule bypass via glob pattern confusion
- **Mitigations:**
  - Database/role matching is strict and case-insensitive
  - Group membership is validated in catalog
  - Ident mapping is checked against ident.conf rules
- **Gaps:**
  - Wildcard matching could be confusing (`user*` matches `user`, `user1`, `username`, etc.)
  - No CIDR validation on IP ranges (assuming admins get this right)

---

## Dependency Chain

**Order from Entry Point to Sensitive Operation:**

1. **Network Receiver** (`backend_startup.c:ProcessStartupPacket`)
   - Receives raw bytes from TCP socket
   - Extracts startup packet fields

2. **Startup Parameter Extraction** (`backend_startup.c:ProcessStartupPacket`)
   - Parses user_name, database_name, guc_options
   - Length validation and null termination

3. **HBA Configuration Loader** (`hba.c:load_hba`)
   - Reads and pre-parses pg_hba.conf
   - Compiled once at startup or SIGHUP

4. **HBA Rule Matcher** (`hba.c:check_hba`)
   - Matches connection against HBA rules
   - Uses username and database from startup packet
   - Calls `get_role_oid(port->user_name, true)`

5. **Role Lookup** (`crypt.c:get_role_password`)
   - Searches `pg_authid` catalog for role
   - Retrieves password hash and expiry
   - Via `SearchSysCache1(AUTHNAME, ...)`

6. **Authentication Dispatcher** (`auth.c:ClientAuthentication`)
   - Dispatches to auth method based on HBA rule
   - Routes to `CheckPasswordAuth`, `CheckPWChallengeAuth`, `CheckSASLAuth`, etc.

7. **Password Receiver** (`auth.c:recv_password_packet`)
   - Receives plaintext or challenge response
   - Via socket message protocol

8. **Password Verification** (method-specific)
   - **For plaintext:** `plain_crypt_verify()` — direct comparison
   - **For MD5:** `md5_crypt_verify()` — compute and compare hash
   - **For SCRAM:** `scram_exchange()` → HMAC verification

9. **Successful Authentication** (`auth.c:set_authn_id`)
   - Sets authenticated identity in `MyClientConnectionInfo`
   - Disables authentication timeout
   - Returns control to `PostgresMain`

10. **Session Establishment** (`postinit.c:CheckMyDatabase`)
    - Validates database exists and is accepting connections
    - Checks user has `CONNECT` privilege
    - Sets up transaction system
    - Initializes locale and encoding

---

## Analysis

### Vulnerability Classes

#### 1. User Enumeration via Timing Attacks
**Classification:** Timing-based information disclosure

**Description:**
- SCRAM authentication implements "doomed" authentication (mock mode) to prevent timing-based user enumeration
- When a user doesn't exist, a fake salt/iteration count is used, and the server proceeds with authentication
- However, early releases may have had timing differences in catalog lookup vs. mock mode
- Modern versions mitigate via consistent timing

**Mitigations:**
- "Doomed" authentication path (auth-scram.c:73)
- Constant-time comparison in HMAC verification
- Same execution path whether user exists or password wrong

**Recommended Remediation:**
- Ensure timing-constant password comparison in all code paths
- Use constant-time string comparison for username matches

---

#### 2. Information Disclosure via Error Messages
**Classification:** Authentication bypass / information disclosure

**Description:**
- Error messages distinguish between:
  - "Role does not exist" (crypt.c:50)
  - "User has no password assigned" (crypt.c:60)
  - "User has an expired password" (crypt.c:78)
- Attacker can enumerate valid usernames by observing error responses
- These messages are logged but not sent to unauthenticated clients (good practice)

**Mitigations:**
- Error messages only logged (not sent to unauthenticated clients in modern versions)
- "Doomed" authentication path hides user existence from remote attacker

**Recommended Remediation:**
- Verify error messages are never sent to clients during authentication
- Ensure all auth failure paths return generic error message to client

---

#### 3. Man-in-the-Middle (MITM) Attack via Plaintext MD5
**Classification:** Cryptographic weakness

**Description:**
- MD5 is cryptographically broken (collision attacks, precomputation)
- Challenge-response over plain TCP (without TLS) is vulnerable to MITM
- Attacker can:
  - Eavesdrop on MD5 salt and client response
  - Capture password hash and compute offline
  - Perform dictionary/brute-force attack on captured hash

**Mitigations:**
- TLS encryption (via `hostssl` HBA entries)
- SCRAM-SHA-256 uses stronger algorithm (line 588 of auth.c)
- MD5 deprecated; users should migrate to SCRAM

**Recommended Remediation:**
- Enforce `hostssl` in pg_hba.conf for production
- Require SCRAM-SHA-256 (`password_encryption = 'scram-sha-256'` GUC)
- Deprecate MD5 support (already deprecated as of PG 13+)

---

#### 4. SQL Injection via Username/Database Name (Historical)
**Classification:** SQL injection (unlikely, well-mitigated)

**Description:**
- Username and database name extracted from startup packet (untrusted)
- Used in catalog lookups: `SearchSysCache1(AUTHNAME, PointerGetDatum(role))`
- Historical concern: Could SQL injection be possible?

**Mitigations:**
- Syscache lookups use parameterized queries internally
- `PointerGetDatum()` passes string to Datum, not SQL text
- No string concatenation in SQL queries
- Length limits prevent buffer overflows

**Assessment:**
- **Low Risk:** Mitigations are robust; SQL injection is not a viable attack

---

#### 5. Password Storage Security
**Classification:** Cryptographic weakness (MD5), Information disclosure (database dump)

**Description:**
- MD5 hashes stored in `pg_authid.rolpassword` are weak
- SCRAM secrets stored as salted, iterated HMAC (better)
- Database dump exposes password hashes; attacker can perform offline cracking

**Mitigations:**
- SCRAM uses 4096 iterations (PBKDF2-like) by default
- StoredKey design prevents direct password recovery from stored value
- Iterations count is configurable and should be increased for new passwords

**Recommended Remediation:**
- Increase SCRAM iterations to 10000+ (via `scram.c:SCRAM_SALT_STRING`)
- Remove MD5 support entirely
- Use bcrypt or Argon2 for even stronger hashing (future improvement)
- Enforce role password expiry to force periodic credential rotation

---

#### 6. Plaintext Password Authentication
**Classification:** Cryptographic weakness

**Description:**
- `uaPassword` method sends plaintext password to server (line 593 of auth.c)
- Over TLS, this is acceptable; over plain TCP, it's a serious risk
- Attacker can eavesdrop and capture password directly

**Mitigations:**
- TLS encryption (required in production)
- HBA rules can enforce `hostssl` only

**Recommended Remediation:**
- Disable `uaPassword` method; require challenge-response (SCRAM-SHA-256)
- Document requirement for TLS with plaintext passwords
- Set default auth method to SCRAM-SHA-256 in pg_hba.conf

---

#### 7. Ident-Based Authentication Bypass
**Classification:** Authentication bypass (if system user is compromised)

**Description:**
- `ident` authentication maps system OS user to PostgreSQL role
- If system user account is compromised (SSH key, password), attacker can login as any mapped role
- `ident` mapping is OS-user-specific, not cryptographically verified

**Mitigations:**
- Only viable on local connections (`ctLocal`)
- Requires compromised system user account
- Mapping is checked against ident.conf rules

**Recommended Remediation:**
- Prefer peer authentication (uses OS socket credentials, more secure)
- For remote connections, require strong authentication (SCRAM, TLS certificate)
- Audit ident.conf mappings regularly

---

#### 8. GSSAPI/Kerberos Authentication
**Classification:** Delegation of trust to external system

**Description:**
- `uaGSS` (GSSAPI) delegates authentication to Kerberos/GSS
- Security depends on:
  - Kerberos infrastructure setup
  - Server keytab management (`pg_krb_server_keyfile`)
  - Client principal validation

**Mitigations:**
- Server keytab file permissions checked by OS
- Principal validation in `pg_GSS_recvauth` (auth.c:920+)
- Encrypted channel (GSS provides encryption after auth)

**Recommended Remediation:**
- Secure Kerberos infrastructure (outside PostgreSQL scope)
- Regularly rotate server keytab
- Monitor keytab file permissions

---

#### 9. LDAP Authentication
**Classification:** Delegation of trust to external system

**Description:**
- `uaLDAP` connects to external LDAP server to verify password
- Password sent to LDAP server (not PostgreSQL)
- Security depends on LDAP server security

**Mitigations:**
- TLS to LDAP server (via `ldaptls` HBA option)
- Bind as restricted account if using search-and-bind
- Timeout protection against slow LDAP servers

**Recommended Remediation:**
- Require TLS to LDAP server
- Use search-and-bind with restricted account
- Implement timeouts and retry limits
- Audit LDAP server logs for failed bind attempts

---

#### 10. PAM Authentication
**Classification:** Delegation of trust to OS PAM system

**Description:**
- `uaPAM` forwards password to OS PAM module
- Security depends on PAM configuration

**Mitigations:**
- PAM is OS-managed
- Timeout protection (line 247 of postinit.c)

**Recommended Remediation:**
- Audit PAM configuration
- Ensure PAM supports TLS to external auth services
- Monitor PAM logs

---

### Existing Mitigations Summary

1. **Length Limits:**
   - Startup packet: `MAX_STARTUP_PACKET_LENGTH` (10 MB)
   - Username/database: `NAMEDATALEN - 1` (63 bytes)
   - Password: `PG_MAX_AUTH_TOKEN_LENGTH` (1 MB)
   - SASL messages: `mech->max_message_length` (1 MB)

2. **Parameterized Lookups:**
   - `SearchSysCache1(AUTHNAME, ...)` — OID-based, not string SQL

3. **Timing-Constant Comparison:**
   - HMAC verification and password comparison use constant-time functions

4. **"Doomed" Authentication:**
   - User non-existence is masked by proceeding with mock authentication

5. **Protocol-Level Validation:**
   - Message type checking (PqMsg_PasswordMessage, PqMsg_SASLResponse)
   - Length validation before parsing
   - Null termination of received data

6. **TLS Support:**
   - `hostssl` HBA rule enforces TLS
   - Channel binding in SCRAM prevents MITM

7. **Password Expiry:**
   - Stored in `pg_authid.rolvaliduntil`
   - Checked before authentication (crypt.c:76)

---

### Security Gaps

1. **MD5 Support (Deprecated):**
   - Weak cryptographic primitive
   - Should be removed entirely
   - Currently deprecated but still supported for backward compatibility

2. **Plaintext Password Over TCP:**
   - `uaPassword` with `hostnossl` allows plaintext password transmission
   - No encryption enforcement in authentication layer
   - Relies on HBA rules for enforcement

3. **Default HBA Rule:**
   - Default `pg_hba.conf` may be permissive
   - Users must manually harden auth rules
   - Trust auth method is default (no password required)

4. **Limited Rate Limiting:**
   - No per-connection or per-IP password attempt limits
   - Could allow brute-force attacks on weak passwords
   - Mitigated by application-level rate limiting and fail2ban

5. **Ident Mapping:**
   - System user compromise allows role compromise
   - No cryptographic verification

6. **SCRAM Iteration Count:**
   - Default 4096 iterations (reasonable)
   - Could be higher (10000+ recommended)
   - No per-role iteration customization

---

## Summary

### Architecture Overview

PostgreSQL's authentication pipeline is a layered system:

1. **TCP Connection Layer** (`backend_startup.c`):
   - Accepts connections, receives startup packet
   - Extracts username, database, options
   - Limited validation (length, format)

2. **HBA Rule Matching** (`hba.c`):
   - Matches connection against pre-parsed HBA rules
   - Determines auth method based on IP, user, database
   - Prevents "wrong" auth method for connection

3. **Authentication Methods** (`auth.c`, `auth-sasl.c`, `auth-scram.c`, etc.):
   - Dispatch table of supported methods (SCRAM, MD5, Trust, GSSAPI, LDAP, PAM, etc.)
   - Each method implements challenge-response or external delegation

4. **Password Verification** (`crypt.c`):
   - Catalog lookup of stored password hash
   - Verification against client-supplied credential

5. **Session Establishment** (`postinit.c`):
   - Database and role validation
   - Transaction system initialization

### Key Security Properties

**Strengths:**
- Parameterized catalog lookups prevent SQL injection
- Length limits prevent buffer overflows
- TLS support for encryption
- SCRAM-SHA-256 is cryptographically sound (salted, iterated, HMAC-based)
- "Doomed" authentication prevents user enumeration
- Authentication timeout prevents slowdown attacks

**Weaknesses:**
- MD5 is deprecated but still supported
- Plaintext password auth requires TLS enforcement (external to auth layer)
- Timing attacks possible in some auth paths (mitigated but not perfect)
- SCRAM iteration count could be higher
- No rate limiting on authentication attempts (per IP/user)

### Vulnerability Impact

**Most Severe:**
- **MITM Attack on MD5 auth without TLS:** Attacker captures MD5 challenge and performs offline cracking
- **User Enumeration:** Attacker can distinguish valid users from invalid (mitigated by "doomed" auth)
- **Ident Bypass:** Compromised system user can authenticate as any mapped role

**Moderate:**
- **Weak Password Hashing:** MD5 is weak, but salted and iterated
- **Dictionary Attack on SCRAM:** If low iteration count or weak password
- **Plaintext Password Exposure:** If TLS not enforced

**Low:**
- **SQL Injection:** Well-mitigated by parameterized lookups
- **Buffer Overflow:** Length limits prevent this
- **Replay Attack:** SCRAM exchange is resistant

---

## Recommendations

1. **Remove MD5 Support:** Deprecate and eventually remove entirely (after major version)
2. **Enforce TLS:** Set `ssl = on` and require `hostssl` in pg_hba.conf
3. **Increase SCRAM Iterations:** Default to 10000+ (from 4096)
4. **Implement Rate Limiting:** Per-IP or per-user attempt limiting
5. **Default to SCRAM:** Make SCRAM-SHA-256 the default auth method
6. **Audit HBA Rules:** Regularly review pg_hba.conf for overly permissive rules
7. **Monitor Auth Failures:** Log and alert on repeated auth failures
8. **Use Strong Passwords:** Encourage or enforce password complexity
9. **Certificate Authentication:** Use TLS client certificates for additional security
10. **Periodic Rotation:** Enforce password expiry and rotation for sensitive roles

