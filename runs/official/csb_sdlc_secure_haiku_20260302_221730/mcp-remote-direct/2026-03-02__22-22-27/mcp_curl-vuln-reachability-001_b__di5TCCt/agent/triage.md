# Security Reachability Analysis: curl SOCKS5 Proxy Handler

## 1. Summary

The `do_SOCKS5()` function in `lib/socks.c` implements the SOCKS5 proxy protocol handshake. This analysis traces the complete call path from curl's HTTP handler to the SOCKS5 proxy handler to determine if this function is reachable from external input.

**Conclusion: REACHABLE from external input** (network data from SOCKS5 proxy server)

---

## 2. Affected Code

**Function:** `do_SOCKS5()`
**Location:** `lib/socks.c:548-1054`
**Function Type:** Internal proxy handler (CURLproxycode)

**Responsibility:**
The `do_SOCKS5()` function implements the complete SOCKS5 proxy negotiation state machine according to RFC 1928. It handles:
- Initial SOCKS5 greeting and authentication method negotiation
- Username/password authentication (SOCKS5 sub-negotiation)
- GSS-API authentication (GSSAPI per-message security)
- CONNECT request to establish a tunnel to the destination host
- Parsing of SOCKS5 server responses with variable-length address fields

---

## 3. Attack Path: Complete Call Chain

```
User Input (curl CLI or API)
  ↓
curl_easy_setopt(CURLOPT_PROXY, "socks5://proxy:1080")
  ↓
Curl_http_connect() [lib/http.c:1565]
  │ Entry point for HTTP/HTTPS protocol handler
  ↓
Curl_conn_connect() [lib/connect.c] (Connection filter setup)
  ↓
Multi Interface: curl_multi_perform() → multi_runsingle()
  │ DNS Resolution: MSTATE_RESOLVING → MSTATE_RESOLVECOMPLETE [lib/multi.c:2001-2070]
  ↓
Curl_once_resolved() [lib/hostip.c:1325]
  │ Called after DNS resolution completes
  ↓
Curl_setup_conn() [lib/url.c:3858]
  │ Post-DNS connection setup
  ↓
Curl_conn_setup() [lib/connect.c:1416]
  │ Creates connection filter chain
  ↓
cf_setup_create() → cf_setup_connect() [lib/connect.c:1186]
  │ State machine for filter chain creation
  │ Checks: cf->conn->bits.socksproxy (set at lib/url.c:1547-1548)
  ↓
Curl_cf_socks_proxy_insert_after() [lib/connect.c:1218]
  │ Inserts SOCKS proxy filter into chain
  ↓
socks_proxy_cf_connect() [lib/socks.c:1103]
  │ SOCKS proxy connection filter callback
  │ Initializes socks_state and sets:
  │ - sx->hostname: destination host
  │ - sx->remote_port: destination port
  │ - sx->proxy_user: proxy username (if configured)
  │ - sx->proxy_password: proxy password (if configured)
  ↓
connect_SOCKS() [lib/socks.c:1056]
  │ Switch statement routes to correct SOCKS version handler
  │ Condition: conn->socks_proxy.proxytype ∈ {CURLPROXY_SOCKS5, CURLPROXY_SOCKS5_HOSTNAME}
  ↓
do_SOCKS5() [lib/socks.c:548] ← VULNERABLE FUNCTION
  │ State machine with 18 states (enum connect_t)
  │ Receives and parses SOCKS5 server responses
  ↓
Network Data Sources:
  - SOCKS5 Proxy Server Response at proxy_addr:proxy_port
  - Username/password echoed by proxy
  - BND.ADDR and BND.PORT in response
```

### Key Functions in Call Chain

| Function | Location | Role |
|----------|----------|------|
| `Curl_http_connect()` | lib/http.c:1565 | HTTP protocol handler entry point |
| `Curl_conn_connect()` | lib/connect.c | Connection filter chain driver |
| `curl_multi_perform()` | lib/multi.c | Multi-interface event loop |
| `Curl_once_resolved()` | lib/hostip.c:1325 | Post-DNS setup trigger |
| `Curl_setup_conn()` | lib/url.c:3858 | Connection filter chain initialization |
| `cf_setup_connect()` | lib/connect.c:1186 | Filter chain state machine |
| `Curl_cf_socks_proxy_insert_after()` | lib/connect.c:1218 | SOCKS filter insertion (conditional) |
| `socks_proxy_cf_connect()` | lib/socks.c:1103 | SOCKS proxy filter callback |
| `connect_SOCKS()` | lib/socks.c:1056 | SOCKS version dispatcher |
| `do_SOCKS5()` | lib/socks.c:548 | **SOCKS5 protocol implementation** |

---

## 4. Severity Assessment

### Reachability: YES - REACHABLE

**Conditions Required:**
1. **User Configuration (Mandatory):** The user MUST explicitly configure a SOCKS5 proxy via one of:
   - Command-line: `curl --socks5 proxy.example.com:1080 https://target.com`
   - Command-line: `curl --proxy socks5://proxy.example.com:1080 https://target.com`
   - API: `curl_easy_setopt(curl, CURLOPT_PROXY, "socks5://proxy.example.com:1080")`
   - Curl config: `socks5 = proxy.example.com:1080`

2. **Network Connectivity (Mandatory):** A network connection to the proxy server must be established at `proxy_host:proxy_port`

3. **Target URL (Mandatory):** User provides a target URL to connect through the proxy

### Attack Vector

**Primary:** Malicious SOCKS5 Proxy Server returning crafted responses

**Secondary:** Network MITM attack on the path to the SOCKS5 proxy server (man-in-the-middle)

### External Input Reaching do_SOCKS5()

The following network data from the SOCKS5 proxy server directly influences `do_SOCKS5()` behavior:

1. **Initial Greeting Response (2 bytes minimum):**
   - Byte 0: SOCKS version (0x05)
   - Byte 1: Selected authentication method (0x00, 0x01, 0x02, 0xFF, etc.)

2. **Authentication Sub-Negotiation Response (2 bytes minimum):**
   - Byte 0: Sub-negotiation version
   - Byte 1: Authentication status (0x00 = success)

3. **CONNECT Request Response (10+ bytes):**
   - Byte 0: SOCKS version (should be 0x05)
   - Byte 1: Reply code (0x00 = success, 0x01-0x08 = various errors)
   - Byte 2: Reserved (should be 0x00)
   - Byte 3: ATYP - Address type (0x01=IPv4, 0x03=domain name, 0x04=IPv6)
   - Bytes 4+: BND.ADDR (variable length, **UNTRUSTED from proxy**)
   - Bytes N+(4-6): BND.PORT (2 bytes, **UNTRUSTED from proxy**)

### Data Flow Analysis

```
Network (Proxy Server)
    ↓
    ├─→ socksreq[0-1]: Initial response
    ├─→ socksreq[0-1]: Auth response
    └─→ socksreq[0-9+]: CONNECT response
         ↓
    Parsed in do_SOCKS5():
    - Line 654: Check socksreq[0] == 0x05 (version)
    - Line 658: Check socksreq[1] for auth method
    - Line 960-985: Parse CONNECT response error codes
    - Line 1005-1020: Calculate packet size from socksreq[3-4]
         ↓
    Vulnerability Analysis (see below)
```

---

## 5. Remediation & Security Analysis

### Buffer Overflow Analysis

**Critical Code Section:** `lib/socks.c:1004-1030`

```c
1004:     /* Calculate real packet size */
1005:     if(socksreq[3] == 3) {
1006:       /* domain name */
1007:       int addrlen = (int) socksreq[4];
1008:       len = 5 + addrlen + 2;
1009:     }
```

**Potential Issue:** Domain name length field (`socksreq[4]`) is read directly from untrusted proxy response.

**Safety Assessment:**
- `socksreq[4]` is a single byte (max value 255)
- Calculation: `len = 5 + addrlen + 2` → maximum value = 5 + 255 + 2 = 262 bytes
- Buffer size: `READBUFFER_MIN = 1024` bytes (defined in lib/urldata.h:203)
- **Conclusion: NO buffer overflow** (262 << 1024)

### Hostname Length Truncation Analysis

**Critical Code Section:** `lib/socks.c:589-592, 906`

```c
589:     if(!socks5_resolve_local && hostname_len > 255) {
590:       infof(data, "SOCKS5: server resolving disabled for hostnames of "
591:             "length > 255 [actual len=%zu]", hostname_len);
592:       socks5_resolve_local = TRUE;
593:     }
...
906:     socksreq[len++] = (char) hostname_len; /* one byte address length */
```

**Potential Issue:** If `hostname_len > 255`, casting to `(char)` truncates the value.

**Safety Assessment:**
- Bounds check at line 589 forces local resolution if `hostname_len > 255`
- State machine ensures remote resolution path only taken when `!socks5_resolve_local`
- Logic prevents remote resolution with long hostnames
- **Conclusion: NO truncation vulnerability** (protected by bounds check)

### Input Validation Summary

| Input Field | Source | Validation | Risk Level |
|-------------|--------|-----------|-----------|
| SOCKS version byte | Network | `socksreq[0] == 5` check at line 654, 960 | Low |
| Auth method byte | Network | Array bounds check (values 0-255 valid) | Low |
| Auth response | Network | Status byte checked at line 772 | Low |
| ATYP byte | Network | Switch statement validates 1, 3, 4 (line 1005-1020) | Low |
| Domain length byte | Network | Max 255, buffer 1024 bytes, no overflow | Low |
| IPv4 address | Network | Fixed 4 bytes | Low |
| IPv6 address | Network | Fixed 16 bytes | Low |
| Port number | Network | Fixed 2 bytes | Low |

### Existing Protections

1. **Buffer bounds:** READBUFFER_MIN (1024 bytes) enforced at compile time
2. **Hostname length:** Pre-checks at line 589 prevent truncation
3. **Protocol validation:** ATYP field validated (line 1017-1019)
4. **Version checks:** SOCKS version must be 0x05 (line 654, 960)
5. **State machine:** Prevents out-of-order operations via enum connect_t

---

## 6. Conclusion

### Reachability Status

✅ **REACHABLE from external input**

The `do_SOCKS5()` function IS reachable from network input when:
1. A SOCKS5 proxy is explicitly configured by the user
2. The proxy server responds with crafted data

### Security Posture

✅ **APPEARS SECURE** with current implementation

**Key Findings:**
- No obvious buffer overflow vulnerabilities in response parsing
- Proper bounds checking prevents hostname length issues
- Network data parsing uses defensive programming (explicit length checks)
- State machine prevents protocol violations

**Recommendation:**
- Continue validating all network-sourced fields before use
- Maintain strict bounds checks on variable-length fields
- Regular fuzzing against malformed SOCKS5 responses recommended

### Attack Prerequisites

An attacker could exploit this code only if:
1. User voluntarily configures a SOCKS5 proxy (user-controlled)
2. Attacker controls the SOCKS5 proxy server OR performs MITM attack
3. Attacker sends carefully crafted SOCKS5 responses

**Risk Assessment:** MEDIUM (requires user configuration + network control)

---

## 7. Sources Analyzed

- `lib/socks.c`: SOCKS4/SOCKS5 proxy handler (1254 lines)
- `lib/socks.h`: SOCKS proxy header
- `lib/connect.c`: Connection filter chain management
- `lib/http.c`: HTTP protocol handler
- `lib/hostip.c`: DNS resolution interface
- `lib/url.c`: Connection initialization
- `lib/multi.c`: Multi-interface state machine
- `lib/urldata.h`: Data structures and constants
