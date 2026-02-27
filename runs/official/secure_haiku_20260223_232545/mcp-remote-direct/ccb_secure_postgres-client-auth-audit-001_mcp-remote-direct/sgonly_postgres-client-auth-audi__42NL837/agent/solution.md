# PostgreSQL Client Authentication Pipeline Security Analysis

## Files Examined

### Postmaster and Connection Acceptance
- `src/backend/postmaster/postmaster.c` — Main postmaster process, accepts TCP connections and forks backends
- `src/backend/postmaster/pmchild.c` — Postmaster child management

### Backend Startup and Startup Packet Processing
- `src/backend/tcop/backend_startup.c` — BackendMain() and BackendInitialize(), ProcessStartupPacket() entry point for client connections
- `src/backend/tcop/backend_startup.h` — Function declarations for backend startup

### HBA Configuration and Matching
- `src/backend/libpq/hba.c` — HBA file parsing (load_hba), rule matching (check_hba), and auth method selection (hba_getauthmethod)

### Authentication Methods
- `src/backend/libpq/auth.c` — Main authentication dispatcher (ClientAuthentication), password authentication flows (CheckPasswordAuth, CheckPWChallengeAuth, CheckMD5Auth)
- `src/backend/libpq/auth-sasl.c` — SASL authentication framework (CheckSASLAuth)
- `src/backend/libpq/auth-scram.c` — SCRAM-SHA-256 mechanism implementation
- `src/backend/libpq/auth-oauth.c` — OAuth mechanism implementation
- `src/backend/libpq/auth-gssapi.c` — GSSAPI mechanism implementation
- `src/backend/libpq/crypt.c` — Password verification (get_role_password, get_password_type, encrypt_password, md5_crypt_verify, plain_crypt_verify)

### Protocol and Communication
- `src/backend/libpq/pqcomm.c` — Low-level message I/O (pq_getbytes, pq_getmessage, pq_getbyte, recv operations)
- `src/backend/libpq/pqformat.c` — Message formatting
- `src/backend/libpq/libpq.h` — Protocol definitions

### Session Initialization and Role Validation
- `src/backend/utils/init/postinit.c` — InitPostgres(), PerformAuthentication(), CheckMyDatabase(), role validation during session setup
- `src/backend/utils/init/miscinit.c` — Miscellaneous initialization (InitPostmasterChild)

## Entry Points

1. **src/backend/tcop/backend_startup.c:BackendMain()** — Entry point for new backend process after postmaster forks. Calls BackendInitialize() which processes TCP connection.

2. **src/backend/tcop/backend_startup.c:BackendInitialize()** — Accepts client socket, initiates backend setup. Calls ProcessStartupPacket().

3. **src/backend/tcop/backend_startup.c:ProcessStartupPacket()** — **PRIMARY ENTRY POINT FOR STARTUP PACKET**
   - Accepts untrusted startup packet bytes from client via pq_getbytes()
   - Parses protocol version, SSL/GSS negotiation codes
   - Extracts database name, user name, options from packet
   - Line 735-750: Parses key-value pairs from packet buffer
   - Line 746-749: Extracts "database" and "user" strings from startup packet
   - Validates protocol version
   - No length validation on database or user name strings before storing

4. **src/backend/libpq/auth.c:ClientAuthentication()** — **PRIMARY AUTHENTICATION DISPATCHER**
   - Called from PostgresMain() via PerformAuthentication()
   - Dispatches to appropriate auth method based on HBA rule
   - Line 390: Calls hba_getauthmethod(port)
   - Line 422-630: Switch statement dispatches to auth handlers (uaTrust, uaPassword, uaSCRAM, uaMD5, uaGSS, uaIdent, etc.)

5. **src/backend/libpq/auth.c:recv_password_packet()** — **PASSWORD INPUT ENTRY POINT**
   - Receives password message from client
   - Line 715-716: Validates message type is PqMsg_PasswordMessage
   - Line 732: Calls pq_getmessage() to read password with PG_MAX_AUTH_TOKEN_LENGTH (1MB) limit
   - Line 744-747: Validates password packet length matches string length
   - Returns palloc'd password string

6. **src/backend/libpq/auth.c:CheckPasswordAuth()** — **PLAINTEXT PASSWORD VERIFICATION**
   - Line 794: Sends AUTH_REQ_PASSWORD to client
   - Line 796: Calls recv_password_packet() to get untrusted password
   - Line 800: Calls get_role_password() to fetch stored password from pg_authid
   - Line 803: Calls plain_crypt_verify() to compare passwords

7. **src/backend/libpq/auth.c:CheckPWChallengeAuth()** — **MD5/SCRAM PASSWORD VERIFICATION**
   - Line 833: Calls get_role_password() to fetch stored password
   - Line 859-862: Branches to CheckMD5Auth or CheckSASLAuth based on password type
   - Implements timing-safe authentication (continues even if user doesn't exist)

8. **src/backend/libpq/auth.c:CheckMD5Auth()** — **MD5 CHALLENGE-RESPONSE AUTHENTICATION**
   - Line 890: Generates random salt via pg_strong_random()
   - Line 897: Sends AUTH_REQ_MD5 with salt to client
   - Line 899: Calls recv_password_packet() to get MD5 response
   - Line 904: Calls md5_crypt_verify() to verify response

9. **src/backend/libpq/auth-sasl.c:CheckSASLAuth()** — **SASL AUTHENTICATION FRAMEWORK**
   - Line 68: Sends AUTH_REQ_SASL with mechanism list
   - Line 81-94: Message loop reads PqMsg_SASLResponse messages
   - Line 98: Calls pq_getmessage() with mech->max_message_length limit
   - Line 131: Initializes SASL mechanism (calls scram_init or oauth_init)
   - Line 157-159: Calls mech->exchange() for each SASL message

10. **src/backend/libpq/auth-scram.c:scram_init()** — **SCRAM MECHANISM INITIALIZATION**
    - Accepts selected mechanism name from client (SASL_mechanism parameter)
    - Line 258-267: Validates mechanism is SCRAM-SHA-256 or SCRAM-SHA-256-PLUS
    - Line 272-330: Parses stored password from pg_authid.rolpassword
    - Implements "doomed authentication" for nonexistent users

11. **src/backend/libpq/auth-scram.c:scram_exchange()** — **SCRAM MESSAGE EXCHANGE**
    - Line 352-475: Processes SCRAM authentication flow
    - State machine: SCRAM_AUTH_INIT → SCRAM_AUTH_SALT_SENT → SCRAM_AUTH_FINISHED
    - Line 399: Calls read_client_first_message() to parse client's initial response
    - Line 415: Calls read_client_final_message() to parse final client message
    - Line 417-421: Verifies nonce matches
    - Line 442: Calls verify_client_proof() to verify HMAC proof
    - Line 469-471: Stores ClientKey and ServerKey for later use

12. **src/backend/libpq/crypt.c:get_role_password()** — **PASSWORD RETRIEVAL FROM CATALOG**
    - Line 47: Looks up role in pg_authid catalog
    - Line 55-56: Retrieves rolpassword attribute
    - Line 66-69: Checks password validity timestamp
    - Returns palloc'd password string or NULL

13. **src/backend/libpq/hba.c:hba_getauthmethod()** — **HBA RULE MATCHING ENTRY POINT**
    - Line 3112: Calls check_hba()
    - Returns matched HBA rule stored in port->hba

14. **src/backend/libpq/hba.c:check_hba()** — **HBA RULE MATCHING LOGIC**
    - Line 2538: Calls get_role_oid() to validate role exists
    - Line 2540-2625: Iterates through parsed_hba_lines list
    - Line 2545-2625: Checks connection type, IP address, database, and role
    - Line 2623: Sets port->hba to matched rule
    - Line 2628-2630: Creates implicit reject entry if no match

15. **src/backend/libpq/hba.c:load_hba()** — **HBA CONFIGURATION PARSING**
    - Line 2645-2700+: Parses pg_hba.conf file
    - Reads and validates HBA file entries

## Data Flow

### Flow 1: Startup Packet Processing

1. **Source**: `src/backend/tcop/backend_startup.c:ProcessStartupPacket()` line 492-750
   - Untrusted client data enters via TCP socket
   - pq_getbytes() reads raw bytes from network buffer
   - Line 532: len = pg_ntoh32(len) — converts network byte order to host order
   - Line 549: buf = palloc(len + 1) — allocates buffer for startup packet

2. **Transform**: `src/backend/tcop/backend_startup.c:ProcessStartupPacket()` line 733-750
   - **Parsing without validation**: While loop iterates through key-value pairs
   - Line 735: nameptr = buf + offset — pointer to key name (untrusted string)
   - Line 741: valoffset = offset + strlen(nameptr) + 1 — strlen used on untrusted data
   - Line 748-749: strcmp(nameptr, "user") == 0 — string comparison on untrusted data
   - Line 749: port->user_name = pstrdup(valptr) — **No validation of user name length**
   - Line 746-747: port->database_name = pstrdup(valptr) — **No validation of database name length**

3. **Sink**: Role lookup in `src/backend/libpq/hba.c:check_hba()` line 2538
   - get_role_oid(port->user_name, true) — queries pg_authid catalog with untrusted user name
   - and `src/backend/libpq/crypt.c:get_role_password()` line 47
   - SearchSysCache1(AUTHNAME, PointerGetDatum(role)) — catalog lookup with untrusted data

### Flow 2: Password Authentication (Plaintext)

1. **Source**: `src/backend/libpq/auth.c:recv_password_packet()` line 707-776
   - Untrusted password bytes from client via pq_getmessage()
   - Line 732: pq_getmessage(&buf, PG_MAX_AUTH_TOKEN_LENGTH) — reads up to 1MB
   - Maximum size enforced: PG_MAX_AUTH_TOKEN_LENGTH (1048576 bytes)

2. **Transform**: `src/backend/libpq/auth.c:recv_password_packet()` line 744-747
   - Line 744: if (strlen(buf.data) + 1 != buf.len) — validates null termination
   - Line 762: if (buf.len == 1) — rejects empty password
   - No encoding validation, no special character filtering
   - **Direct string storage**: buf.data is returned as-is

3. **Sink**: Password comparison in `src/backend/libpq/crypt.c:plain_crypt_verify()` line 251-280+
   - strcmp(client_pass, shadow_pass) — direct string comparison
   - No timing attack protection for plaintext passwords (but rarely used)

### Flow 3: MD5 Challenge-Response Authentication

1. **Source**: `src/backend/libpq/auth.c:CheckMD5Auth()` line 883-912
   - Salt generation: Line 890: pg_strong_random(md5Salt, 4) — cryptographically random 4-byte salt
   - Line 897: sendAuthRequest(port, AUTH_REQ_MD5, md5Salt, 4) — sends salt to client
   - Response reception: Line 899: passwd = recv_password_packet(port)
   - **Untrusted client response**: MD5 hash computed by client

2. **Transform**: `src/backend/libpq/crypt.c:md5_crypt_verify()` line 202-243
   - Line 225: pg_md5_encrypt(shadow_pass + strlen("md5"), md5_salt, md5_salt_len, crypt_pwd, &errstr)
   - Recomputes expected MD5(expected_hash + salt) from stored password
   - Line 233: strcmp(client_pass, crypt_pwd) — compares computed hash with received response

3. **Sink**: Password verification result
   - Line 234: Returns STATUS_OK on match
   - Line 239: Returns STATUS_ERROR on mismatch

### Flow 4: SCRAM-SHA-256 Challenge-Response Authentication

1. **Source**: `src/backend/libpq/auth-sasl.c:CheckSASLAuth()` line 43-194
   - Line 68: sendAuthRequest(port, AUTH_REQ_SASL, mechanisms_list) — advertises mechanisms
   - **SASL message reception loop**: Line 78-185: do { } while(result == PG_SASL_EXCHANGE_CONTINUE)
   - Line 81: mtype = pq_getbyte() — message type
   - Line 98: pq_getmessage(&buf, mech->max_message_length) — reads SASL message
   - **Untrusted SASL tokens**: Client-provided authentication data

2. **Transform**: `src/backend/libpq/auth-sasl.c:CheckSASLAuth()` line 113-145
   - Initial message processing: Line 113-140
   - Line 117: selected_mech = pq_getmsgrawstring(&buf) — **untrusted mechanism name**
   - Line 131: opaq = mech->init(port, selected_mech, shadow_pass) — calls scram_init()
   - Line 133-137: Extracts initial client response from message
   - **Subsequent message processing**: Line 142-145
   - Line 143: inputlen = buf.len; input = pq_getmsgbytes(&buf, buf.len)
   - Line 157-159: mech->exchange(opaq, input, inputlen, &output, &outputlen, logdetail)

3. **Transform (SCRAM mechanism)**: `src/backend/libpq/auth-scram.c:scram_init()` line 240-333
   - **Mechanism selection validation**: Line 258-267
   - Line 258: if (strcmp(selected_mech, SCRAM_SHA_256_PLUS_NAME) == 0 && port->ssl_in_use)
   - Line 262: if (strcmp(selected_mech, SCRAM_SHA_256_NAME) == 0)
   - Line 265: else ereport(ERROR) if mechanism doesn't match
   - **Stored password parsing**: Line 272-315
   - Line 278-282: parse_scram_secret(shadow_pass, ...) — parses stored SCRAM secret
   - Extracts: iterations, hash_type, key_length, salt, StoredKey, ServerKey
   - **Mock authentication for nonexistent users**: Line 323-330
   - Line 325: mock_scram_secret() — generates fake credentials to prevent user enumeration

4. **Transform (SCRAM exchange)**: `src/backend/libpq/auth-scram.c:scram_exchange()` line 352-475
   - **Initial phase**: Line 392-406
   - Line 399: read_client_first_message(state, input) — parses client's initial message
   - Validates: channel binding, GS2 header, username
   - Line 402: build_server_first_message(state) — generates server challenge
   - Response message: salted password computation parameters (iterations, salt)
   - **Final phase**: Line 408-454
   - Line 415: read_client_final_message(state, input) — parses client's final proof
   - Line 417-421: verify_final_nonce(state) — validates nonce matches
   - Line 442: verify_client_proof(state) — **KEY VERIFICATION**
   - Compares ClientKey derived from HMAC(StoredKey, client_sig)
   - Line 442: if (!verify_client_proof(state) || state->doomed)
   - Returns PG_SASL_EXCHANGE_FAILURE if proof doesn't match or authentication is doomed

5. **Sink**: Session establishment in `src/backend/utils/init/postinit.c:InitPostgres()` line 711+
   - Role lookup and validation
   - Database access control checks

### Flow 5: HBA Configuration Matching

1. **Source**: `src/backend/libpq/hba.c:load_hba()` line 2645-2700+
   - Untrusted HBA configuration file (pg_hba.conf)
   - Line 2647: FILE *file — opened HBA file
   - Parsed into HbaLine structures
   - Stored in global parsed_hba_lines list

2. **Transform**: `src/backend/libpq/hba.c:check_hba()` line 2531-2631
   - **Role lookup**: Line 2538: roleid = get_role_oid(port->user_name, true)
   - Uses untrusted user_name from startup packet
   - **Connection type check**: Line 2545-2580
   - Line 2547: port->raddr.addr.ss_family != AF_UNIX
   - Line 2556: port->ssl_in_use — checks SSL state
   - **IP address matching**: Line 2583-2611
   - Line 2588-2590: check_hostname(port, hba->hostname) if hostname in HBA rule
   - Line 2594-2597: check_ip(&port->raddr, &hba->addr, &hba->mask)
   - **Database and role matching**: Line 2614-2620
   - Line 2615: check_db(port->database_name, port->user_name, roleid, hba->databases)
   - Uses untrusted database_name and user_name from startup packet
   - Line 2619: check_role(port->user_name, roleid, hba->roles, false)

3. **Sink**: Authentication method selection
   - Line 2623: port->hba = hba — matched HBA rule assigned
   - Line 2628-2630: Creates implicit reject if no match
   - Used in auth.c:ClientAuthentication() line 422 for method dispatch

### Flow 6: Role Validation and Session Establishment

1. **Source**: `src/backend/utils/init/postinit.c:InitPostgres()` line 711-1000+
   - Role name from port->user_name (from startup packet)
   - Database name from port->database_name (from startup packet)

2. **Transform**: `src/backend/utils/init/postinit.c:InitPostgres()` line 711-900
   - Database lookup and validation
   - Role attribute checks (superuser, canlogin, etc.)
   - Database permission checks

3. **Sink**: Session context setup
   - MyDatabaseId set to authenticated database OID
   - MyUserId set to authenticated role OID
   - Process-wide state established

## Dependency Chain

The complete authentication flow from TCP connection acceptance to authenticated session:

1. Postmaster accepts TCP connection
2. Forks backend process
3. **BackendMain()** → **BackendInitialize()** → **ProcessStartupPacket()**
   - Parses startup packet (database, user, options, etc.)
   - Extracts untrusted strings from packet buffer
4. **InitPostgres()** calls **PerformAuthentication()**
5. **PerformAuthentication()** calls **ClientAuthentication()**
6. **ClientAuthentication()** calls **hba_getauthmethod()** → **check_hba()**
   - Loads and matches HBA configuration rules
   - Determines authentication method (trust, password, scram, md5, gss, etc.)
7. Based on auth method, dispatches to handler:
   - **uaTrust** → Direct acceptance
   - **uaPassword** → **CheckPasswordAuth()** → **recv_password_packet()** → **plain_crypt_verify()**
   - **uaMD5** → **CheckPWChallengeAuth()** → **CheckMD5Auth()** → **recv_password_packet()** → **md5_crypt_verify()**
   - **uaSCRAM** → **CheckPWChallengeAuth()** → **CheckSASLAuth()** → **scram_exchange()**
   - **uaGSS** → **pg_GSS_recvauth()** → GSSAPI library calls
   - **uaIdent** → **ident_inet()** → Ident protocol (RFC 1413)
   - **uaPeer** → **auth_peer()** → Unix socket peer credentials
   - **uaLDAP** → **CheckLDAPAuth()** → LDAP library calls
   - **uaPAM** → **CheckPAMAuth()** → PAM library calls
8. **On success**: **set_authn_id()** logs authentication and sets MyClientConnectionInfo
9. **sendAuthRequest(port, AUTH_REQ_OK, NULL, 0)** signals successful authentication
10. Control returns to **PostgresMain()** for query processing

## Analysis

### Attack Surface

The attack surface for PostgreSQL authentication spans multiple attack vectors:

#### 1. Startup Packet Parsing (ATTACK VECTOR: Invalid/Malformed Startup Data)

**Vulnerability Class**: Protocol Violation, Denial of Service

**Entry Point**: `src/backend/tcop/backend_startup.c:ProcessStartupPacket()` lines 492-750

**Data Flow**: Raw network bytes → packet parsing → string extraction

**Issues Identified**:
- **Insufficient length validation on user/database names**:
  - Line 749: `port->user_name = pstrdup(valptr)` — No maximum length check before pstrdup
  - Line 747: `port->database_name = pstrdup(valptr)` — No maximum length check
  - Names are validated only later during role lookup or HBA matching
  - Attack: Attacker could send very long username (e.g., >NAMEDATALEN) to consume memory or trigger buffer issues

- **No encoding validation on startup packet parameters**:
  - Usernames and database names are stored as C strings without encoding validation
  - Line 773: Options parsed but not validated against dangerous values
  - Attack: Non-UTF-8 sequences could be injected into system logs

**Existing Mitigations**:
- Line 536-541: Packet length validated (4 bytes to MAX_STARTUP_PACKET_LENGTH = 10240)
- Line 532-533: Protocol version extracted safely via pg_ntoh32
- Line 739-747: Null termination of strings enforced by zero-padding buffer (line 550)
- Names are checked during role lookup and HBA matching, which may implicitly limit issues

**Recommended Remediation**:
- Validate database_name and user_name length ≤ NAMEDATALEN (64 bytes) in ProcessStartupPacket
- Add encoding validation for all string parameters from startup packet
- Implement explicit maximum length constants for all parsed fields

#### 2. Password Authentication (ATTACK VECTOR: Password Interception, Timing Attacks)

**Vulnerability Class**: Credential Exposure, Timing Attack

**Entry Points**:
- `src/backend/libpq/auth.c:CheckPasswordAuth()` lines 788-817 (plaintext password)
- `src/backend/libpq/auth.c:CheckPWChallengeAuth()` lines 823-880 (MD5/SCRAM wrapper)

**Data Flow**: Plaintext password from client → recv_password_packet() → plain_crypt_verify()

**Issues Identified**:
- **Plaintext password authentication (uaPassword method)**:
  - Line 794: sendAuthRequest(port, AUTH_REQ_PASSWORD, NULL, 0) — requests plaintext password
  - Line 796: passwd = recv_password_packet(port) — receives password as cleartext from client
  - Vulnerability: Password transmitted in plaintext over network unless TLS is used
  - This method is deprecated but still supported for backwards compatibility
  - Attack: Network sniffer on unencrypted connection captures password

- **No rate limiting on password attempts**:
  - Client can attempt unlimited passwords in rapid succession
  - No exponential backoff after failed attempts
  - Attack: Brute force attack on weak passwords

- **Timing side-channel in plaintext verification**:
  - `src/backend/libpq/crypt.c:plain_crypt_verify()` line 251-280: strcmp() comparison is non-constant-time
  - Attack: Attacker can determine correct password length by measuring response time

**Existing Mitigations**:
- Line 762: Empty passwords rejected
- Plaintext method rarely used in modern PostgreSQL (deprecated)
- SCRAM-SHA-256 is default and uses challenge-response
- `src/backend/libpq/auth.c` line 244-246: ClientAuthInProgress = true limits log verbosity
- Comparison of MD5 hashes and SCRAM proofs uses proper verification functions
- SCRAM-SHA-256 computes proof even for nonexistent users (line 442: state->doomed prevents user enumeration)

**Recommended Remediation**:
- Disable uaPassword authentication method in default configurations
- Implement rate limiting and exponential backoff for failed authentication attempts
- Use constant-time comparison for all password checks (strcoll vs strcmp)
- Log failed authentication attempts with rate limiting
- Recommend forced use of TLS when password authentication is enabled

#### 3. Password Storage Retrieval (ATTACK VECTOR: SQL Injection via Stored Password Manipulation)

**Vulnerability Class**: Information Disclosure (limited), Potential Injection

**Entry Point**: `src/backend/libpq/crypt.c:get_role_password()` lines 37-84

**Data Flow**: Role name from startup packet → SQL catalog lookup → password retrieval

**Issues Identified**:
- **User-supplied role name used in catalog lookup**:
  - Line 47: roleTup = SearchSysCache1(AUTHNAME, PointerGetDatum(role))
  - Role name comes from untrusted startup packet
  - Vulnerability: If role names are not properly validated, attacker could attempt to access other users' passwords
  - Attack: Supply username = "superuser'; --" (though this is C code, not SQL, so SQL injection unlikely)
  - More realistic attack: Valid usernames with special characters if not normalized

- **Timing information leak on nonexistent users**:
  - `src/backend/libpq/auth-scram.c` line 323-330: **MITIGATED** via doomed authentication
  - When user doesn't exist, mock_scram_secret() is called to generate fake credentials
  - Server proceeds with authentication exchange, same as valid user (timing consistent)
  - This is excellent security design

**Existing Mitigations**:
- Line 48: SearchSysCache uses AUTHNAME lookup with proper escaping (catalog lookup, not SQL)
- System cache lookups are parameterized and safe from injection
- **User enumeration prevented**: Nonexistent users trigger doomed authentication (SCRAM/MD5) or consistent error handling
- Invalid password expiration checks (line 76) ensure consistent error messages

**Recommended Remediation**:
- Validate role names against NAMEDATALEN immediately after startup packet parsing
- Document that role names must be valid pg_authid entries
- Consider adding query plan explanation for catalog lookups to confirm no unexpected data access

#### 4. HBA Configuration Matching (ATTACK VECTOR: Configuration-Based Bypass)

**Vulnerability Class**: Authorization Bypass (if HBA misconfigured), Information Disclosure

**Entry Point**: `src/backend/libpq/hba.c:check_hba()` lines 2531-2631

**Data Flow**: Client IP address + user name + database name → HBA rule matching → authentication method selection

**Issues Identified**:
- **Hostname validation only if hostname in HBA rule**:
  - Line 2586-2590: check_hostname() only called if hba->hostname is set
  - Line 2588-2590: DNS lookups occur for reverse DNS verification
  - Vulnerability: If HBA rule contains hostname, DNS lookup happens
  - Attack: DNS rebinding attack if attacker controls DNS zone
  - Attack: DNS amplification if DNS server is reflexive

- **No validation that user_name and database_name match expected format**:
  - Line 2615: check_db(port->database_name, ...) uses untrusted database_name
  - Database names not validated for length (though length checked on lookup)
  - Attack: Very long names could cause performance issues in HBA matching loop

- **Implicit reject on no match could leak user information**:
  - Line 2627-2630: Creates implicit reject if no rule matches
  - Attack: Client could probe which users have explicit rules vs implicit reject

**Existing Mitigations**:
- Line 2538: get_role_oid(port->user_name, true) — true parameter means "missing OK"
- No error message distinguishes between "user doesn't exist" and "HBA rule doesn't match"
- **Excellent user enumeration protection**: Both cases return implicit reject
- Connection type validation (local vs network, SSL state, etc.)
- IP masking validation when applicable

**Recommended Remediation**:
- Document DNS rebinding risk when using hostnames in HBA rules
- Consider adding audit logging for HBA rule matching process
- Validate role name format matches pg_authid naming constraints
- Implement DNS result caching to prevent repeated lookups

#### 5. SCRAM-SHA-256 Implementation (ATTACK VECTOR: Protocol Violations, Channel Binding Bypass)

**Vulnerability Class**: Authentication Bypass (if channel binding bypassed), Protocol Violation

**Entry Point**: `src/backend/libpq/auth-sasl.c:CheckSASLAuth()` lines 43-194

**Data Flow**: Untrusted SASL messages → SCRAM mechanism → proof verification → session establishment

**Issues Identified**:
- **Mechanism selection not validated against server's advertised mechanisms**:
  - Line 117: selected_mech = pq_getmsgrawstring(&buf) — untrusted mechanism name
  - Line 131: opaq = mech->init(port, selected_mech, shadow_pass)
  - Vulnerability: Client could request any mechanism name, even if not advertised
  - Attack: Client requests "SCRAM-SHA-256-PLUS" when server only advertised "SCRAM-SHA-256"
  - Mitigation: scram_init() validates mechanism (lines 258-267), returns ERROR if invalid

- **Message length limits enforced**:
  - Line 98: pq_getmessage(&buf, mech->max_message_length)
  - SCRAM max message length: PG_MAX_SASL_MESSAGE_LENGTH (1MB)
  - Good: Prevents memory exhaustion via huge SASL tokens

- **Channel binding implementation**:
  - Line 214-218: Only advertises SCRAM-SHA-256-PLUS if SSL in use
  - Line 258: Validates channel binding matches SSL state
  - Attack: Client on unencrypted connection tries to select SCRAM-SHA-256-PLUS
  - Mitigation: Line 265 returns ERROR for invalid mechanism selection

- **Nonce verification**:
  - Line 417-421: verify_final_nonce(state) validates nonce matches
  - Ensures server and client share same nonce
  - Good: Prevents replay attacks

- **No protection against SASL layer downgrade**:
  - Client could potentially select weaker mechanism if both advertised
  - Server doesn't force use of strongest mechanism
  - Current: Only SCRAM-SHA-256 and SCRAM-SHA-256-PLUS advertised (both strong)

**Existing Mitigations**:
- Mechanism validation (scram_init lines 258-267)
- Message length limits
- Nonce verification (verify_final_nonce)
- Client proof verification using HMAC comparison
- Doomed authentication for nonexistent users (timing attack prevention)
- SASLprep processing for password normalization (with fallback for non-UTF-8)
- Line 469-471: Stores ClientKey and ServerKey for potential later verification

**Recommended Remediation**:
- Add explicit validation that selected_mech matches advertised mechanisms
- Document that SCRAM-SHA-256-PLUS is only secure with TLS
- Consider adding SCRAM-SHA-512 variant for future upgrades
- Implement audit logging for mechanism selection

#### 6. Password Verification Implementation (ATTACK VECTOR: Timing Attacks, Weak Hashing)

**Vulnerability Class**: Timing Attack, Information Disclosure

**Entry Point**: `src/backend/libpq/crypt.c` password verification functions

**Data Flow**: Client password/proof → comparison → authentication result

**Issues Identified**:
- **MD5 password support (deprecated)**:
  - Line 213-219: get_password_type() checks for MD5 passwords
  - Line 225: pg_md5_encrypt() recomputes MD5(stored_hash + salt)
  - Line 233: strcmp(client_pass, crypt_pwd) — **NON-CONSTANT-TIME COMPARISON**
  - Vulnerability: strcmp() returns on first byte mismatch, allowing timing attacks
  - Attack: Attacker measures response time to determine correct MD5 prefix
  - Note: MD5 passwords are deprecated in PostgreSQL 10+

- **SCRAM proof verification timing attack mitigation**:
  - Line 442: verify_client_proof(state) — calls HMAC verification
  - HMAC comparison likely uses constant-time comparison
  - Good: SCRAM uses cryptographic proof, not direct password comparison
  - Good: Proof is only verified after doomed authentication check (prevents user enumeration)

**Existing Mitigations**:
- SCRAM-SHA-256 is default, not vulnerable to timing attacks
- MD5 passwords deprecated and logged as deprecated
- CheckPWChallengeAuth() line 842: Continues even if user doesn't exist to prevent timing attacks
- Line 438-440: "Mock authentication" for nonexistent users ensures consistent timing
- All SCRAM operations proceed identically for doomed and real authentications

**Recommended Remediation**:
- Enforce deprecation of MD5 passwords (consider removal in major version)
- Use constant-time comparison for all password/proof comparisons
- Document timing attack risks in authentication methods
- Log deprecation warnings when MD5 passwords are used

### Security Properties

#### Strengths
1. **Excellent user enumeration protection**: Doomed authentication for SCRAM prevents user enumeration via timing
2. **Proper salt usage**: MD5 and SCRAM both use random per-connection or per-user salts
3. **Challenge-response authentication**: SCRAM-SHA-256 avoids plaintext password transmission
4. **Separation of concerns**: Authentication is separate from authorization
5. **Memory safety**: Uses palloc() for all dynamic allocations, with proper cleanup
6. **Protocol validation**: Extensive checks on message types and lengths

#### Weaknesses
1. **Plaintext password authentication still supported**: uaPassword method allows cleartext transmission
2. **No rate limiting**: Attackers can perform unlimited brute force attempts
3. **HBA configuration-dependent security**: Weak HBA rules can bypass authentication entirely (uaTrust)
4. **Legacy MD5 support**: Deprecated but still enabled by default in older versions
5. **No authentication attempt logging by default**: Difficult to detect brute force attacks
6. **DNS-based authentication vulnerable to rebinding**: If HBA uses hostname-based rules

### Vulnerability Classes Identified

1. **Authentication Bypass**: Via misconfigured HBA rules (uaTrust, uaReject misconfiguration)
2. **Information Disclosure**: User enumeration (mitigated by doomed authentication in SCRAM/MD5)
3. **Credential Interception**: Plaintext password authentication without TLS
4. **Timing Attacks**: Non-constant-time comparison in MD5 authentication
5. **Denial of Service**: No rate limiting on authentication attempts
6. **Protocol Violations**: Insufficient input validation on startup packet (potential buffer issues)

### Recommended Defenses

1. **Always use TLS in production**: Prevents plaintext password interception
2. **Disable uaPassword authentication**: Use SCRAM-SHA-256 exclusively
3. **Implement rate limiting**: Per-IP or per-user authentication attempt limits
4. **Enable authentication logging**: Track all authentication attempts
5. **Use strong HBA configuration**: Avoid uaTrust method, always use explicit authentication
6. **Upgrade PostgreSQL regularly**: Fixes security issues in authentication code
7. **Monitor for timing attack patterns**: Track authentication response times
8. **Validate startup packet thoroughly**: Enforce strict limits on user/database name lengths

## Summary

The PostgreSQL client authentication pipeline implements a multi-layer defense strategy that is generally robust:

1. **Startup Packet Processing** accepts untrusted network data and parses it with reasonable validation
2. **HBA Configuration Matching** applies policy-based authentication method selection
3. **Password/SCRAM Verification** implements challenge-response authentication with excellent timing attack mitigation
4. **Role Validation** confirms authenticated user's database access rights

The primary attack surface includes startup packet parsing (insufficient length validation), plaintext password method (deprecated), and HBA configuration enforcement (policy-dependent). The implementation demonstrates excellent security design in areas like doomed authentication to prevent user enumeration and constant-time authentication for SCRAM.

The authentication pipeline is **secure by default** in modern PostgreSQL versions when:
- TLS is enforced for connections from untrusted networks
- SCRAM-SHA-256 authentication is configured (default in v10+)
- HBA rules explicitly require authentication (avoid uaTrust)
- Authentication logging is enabled for monitoring
- Rate limiting is implemented at application or network level

