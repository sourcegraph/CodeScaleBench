# Security Reachability Analysis: curl SOCKS5 Proxy Handler

## 1. Summary

This analysis determines whether the `do_SOCKS5()` function in curl's SOCKS proxy implementation is reachable from external network input under normal operation.

**CONCLUSION: REACHABLE from external attacker-controlled input**

The `do_SOCKS5()` function IS reachable when a user configures curl to use a SOCKS5 proxy. The function processes network data directly from the SOCKS5 proxy server, which is an external input source. An attacker who can intercept or control the SOCKS5 proxy server response can craft malicious packets that reach this function's input processing code.

---

## 2. Affected Code

**Function:** `do_SOCKS5()`
**Location:** `/workspace/lib/socks.c`, lines 548-1054
**Source File:** `/workspace/lib/socks.c`

### Function Purpose

`do_SOCKS5()` implements the SOCKS5 (RFC 1928) protocol handshake and connection establishment. It:
- Sends SOCKS5 authentication method selection
- Handles authentication responses (no auth, username/password, GSS-API)
- Sends SOCKS5 connection requests
- Processes SOCKS5 server responses containing bound address information
- Validates protocol version and reply codes

### Input Processing

The function processes responses from the SOCKS5 proxy server, stored in the shared buffer `socksreq` (`data->state.buffer`):
- Reads authentication method selection response (2 bytes minimum)
- Reads authentication subnegotiation responses (variable length)
- Reads CONNECT request responses with address binding information (10+ bytes)

All response data originates from the network (SOCKS5 proxy server) and is therefore attacker-controlled if an attacker can act as or intercept the proxy server.

---

## 3. Attack Path

### Complete Call Chain

```
main()
  ↓
curl_easy_perform() [lib/easy.c]
  ↓
easy_perform() [lib/easy.c]
  ↓
curl_multi_perform() [lib/multi.c]
  ↓
Protocol handler (e.g., http, https, ftp, etc.) [various files]
  ↓
Curl_connect() [lib/url.c]
  ├─ create_conn() - creates connection structure
  ├─ Curl_setup_conn() - initializes connection
  │   ↓
  │   Curl_conn_setup() [lib/connect.c]
  │   ├─ For HTTPS: Curl_cf_https_setup() [lib/cf-https-connect.c]
  │   ├─ For HTTP/other: cf_setup_add() [lib/connect.c]
  │   │   ↓
  │   │   cf_setup_create() [lib/connect.c] - creates setup filter
  │   │
  │   └─ Creates filter chain in conn->cfilter[sockindex]
  │
  └─ Curl_conn_cf_connect() [lib/cfilters.c]
      ↓
      Calls each filter's do_connect() method through the filter chain
        ↓
        cf_setup_connect() [lib/connect.c] - setup filter's connect handler
          ↓
          Checks: if(cf->conn->bits.socksproxy) [line 1217]
            ↓ YES - SOCKS proxy configured
            ↓
            Curl_cf_socks_proxy_insert_after() [lib/socks.c:1240]
              ↓
              Inserts SOCKS proxy filter into chain
                ↓
                socks_proxy_cf_connect() [lib/socks.c:1103]
                  ↓
                  connect_SOCKS() [lib/socks.c:1056]
                    ↓
                    Checks: switch(conn->socks_proxy.proxytype) [line 1064]
                      ↓ CASE: CURLPROXY_SOCKS5 or CURLPROXY_SOCKS5_HOSTNAME
                      ↓
                      do_SOCKS5(cf, sxstate, data) [lib/socks.c:548] ← ENTRY POINT
```

### Intermediate Functions and Their Roles

1. **main() / curl_easy_perform()** - User-facing entry point
2. **easy_perform()** - Internal easy handle wrapper
3. **curl_multi_perform()** - Core transfer loop (multi interface)
4. **Protocol-specific handlers** - HTTP, FTP, etc. handlers that initiate connections
5. **Curl_connect()** - Primary connection function that:
   - Parses proxy URL and determines proxy type (line 1547 in url.c)
   - Sets `conn->bits.socksproxy = TRUE` if SOCKS proxy is configured
   - Initiates connection setup
6. **Curl_conn_setup()** - Sets up socket filter chain
7. **cf_setup_create()** - Creates the setup filter
8. **cf_setup_connect()** - Setup filter's connect handler that conditionally inserts SOCKS filter
9. **Curl_cf_socks_proxy_insert_after()** - Inserts SOCKS proxy filter into the chain
10. **socks_proxy_cf_connect()** - SOCKS proxy filter's connect handler
11. **connect_SOCKS()** - Dispatches to SOCKS version-specific handler
12. **do_SOCKS5()** - SOCKS5 protocol implementation ← **VULNERABLE FUNCTION**

### Input Source to do_SOCKS5()

The `do_SOCKS5()` function receives its input from:
- **Direct input:** Network data from SOCKS5 proxy server
- **Buffer location:** `data->state.buffer` (shared buffer, minimum 1024 bytes)
- **Read mechanism:** `socks_state_recv()` function which calls `Curl_conn_cf_recv()` to read from the socket connected to the SOCKS5 proxy

The key data flow is:
```
SOCKS5 Proxy Server (Network)
  ↓ TCP/IP
Socket (proxy connection)
  ↓
Curl_conn_cf_recv() → socks_state_recv()
  ↓
data->state.buffer (socksreq)
  ↓
do_SOCKS5() - processes and parses the data
```

---

## 4. Severity Assessment

### Reachability: YES - REACHABLE

**Conditions Required to Reach do_SOCKS5():**
1. **User configures SOCKS5 proxy** via:
   - Command-line: `curl https://target.com --proxy socks5://proxy.com:1080`
   - Command-line: `curl https://target.com --proxy socks5h://proxy.com:1080` (remote DNS)
   - C API: `curl_easy_setopt(handle, CURLOPT_PROXY, "socks5://proxy.com:1080")`
   - C API: `curl_easy_setopt(handle, CURLOPT_PRE_PROXY, "socks5://proxy.com:1080")`

2. **Proxy connection is initiated** when curl attempts to access a URL (any protocol)

3. **SOCKS5 proxy responds** with protocol messages (the attacker must be able to intercept/control the proxy server response)

### Attack Vector: Man-in-the-Middle (MITM) on Proxy Connection

**Scenario 1: Direct MITM**
- Attacker intercepts traffic between curl and the SOCKS5 proxy server
- Attacker sends malformed SOCKS5 responses to reach `do_SOCKS5()` vulnerability

**Scenario 2: Compromised/Malicious Proxy**
- User unknowingly uses an attacker-controlled SOCKS5 proxy
- Attacker server sends crafted packets to exploit `do_SOCKS5()`

**Scenario 3: DNS Hijacking**
- Attacker hijacks DNS for the proxy hostname (e.g., proxy.example.com)
- Redirects to attacker's malicious SOCKS5 server

### External Input to do_SOCKS5()

The following network-controlled data reaches the function:

1. **Authentication method negotiation response** (2+ bytes):
   ```c
   Line 645-657: sx->outstanding = 2; // Read 2 bytes
   // Attacker controls socksreq[0] (version) and socksreq[1] (selected method)
   ```

2. **Authentication subnegotiation response** (2+ bytes):
   ```c
   Line 758-776: sx->outstanding = 2; // Read response
   // Attacker controls response codes
   ```

3. **SOCKS5 CONNECT response** (10+ bytes):
   ```c
   Line 951-959: sx->outstanding = 10; // Initial 10 bytes
   // Attacker controls:
   // - socksreq[0]: Version field
   // - socksreq[1]: Reply code
   // - socksreq[2]: Reserved
   // - socksreq[3]: Address type (1=IPv4, 3=domain, 4=IPv6)
   // - socksreq[4+]: Address data (variable length based on attacker)
   ```

4. **Bound address data** (variable length):
   ```c
   Line 1004-1020: Variable length address data
   // If socksreq[3] == 3 (domain), socksreq[4] is domain length
   // If socksreq[3] == 1 (IPv4), expects 4 bytes
   // If socksreq[3] == 4 (IPv6), expects 16 bytes
   // Attacker can send arbitrary lengths
   ```

### Input Validation Issues

Potential concerns in input processing:

1. **Line 1007: Unchecked cast and arithmetic**
   ```c
   if(socksreq[3] == 3) {
     int addrlen = (int) socksreq[4];  // No bounds check
     len = 5 + addrlen + 2;
   }
   ```
   - While mathematically safe (max 0-255), no explicit validation that value is within SOCKS5 spec

2. **Line 906: Hostname length as cast**
   ```c
   socksreq[len++] = (char) hostname_len;  // Type conversion, no validation
   ```

3. **Line 1027-1031: Dynamic buffer read size**
   ```c
   if(len > 10) {
     sx->outstanding = len - 10;  // Read remaining bytes
     // Relies on len calculation being correct
   }
   ```

### Overall Risk Assessment

| Factor | Assessment |
|--------|------------|
| **Reachability** | ✅ YES - Reachable through normal SOCKS5 proxy usage |
| **Exploitability** | ⚠️ MEDIUM - Requires MITM position or proxy control |
| **Data Sensitivity** | ⚠️ MEDIUM - Processes proxy responses (not user data directly) |
| **Impact Potential** | ⚠️ MEDIUM-HIGH - Could affect connection establishment |
| **Ease of Trigger** | ⚠️ MEDIUM - Requires user to use SOCKS5 proxy + network attack |

---

## 5. Remediation

### Current Protections

The code includes several defensive measures:

1. **Buffer size validation** (Line 287):
   ```c
   DEBUGASSERT(READBUFFER_MIN >= 600);  // Minimum 1024 bytes available
   ```

2. **Length bounds checking** for domain names (Line 589):
   ```c
   if(!socks5_resolve_local && hostname_len > 255) {
     // RFC1928 chapter 5 specifies max 255 chars for domain name
   }
   ```

3. **Protocol version validation** (Line 654-657, 960-964):
   ```c
   else if(socksreq[0] != 5) {  // Verify SOCKS5 version
     failf(data, "Received invalid version in initial SOCKS5 response.");
     return CURLPX_BAD_VERSION;
   }
   ```

4. **Reply code validation** (Line 965-986):
   ```c
   else if(socksreq[1]) {  // Check for non-zero reply codes
     // Map error codes according to RFC 1928
   }
   ```

### Recommended Input Validation Enhancements

If vulnerabilities are discovered, consider adding:

1. **Explicit bounds validation on address type parsing** (Line 1005-1020):
   ```c
   // Add validation before using ATYP-based calculations
   if(socksreq[3] == 3) {  // domain name
     unsigned char addrlen = socksreq[4];
     // Validate: addrlen > 0 && addrlen <= 255 (SOCKS5 spec)
     if(addrlen == 0 || addrlen > 255) {
       failf(data, "SOCKS5: Invalid domain name length %u", addrlen);
       return CURLPX_BAD_ADDRESS_TYPE;
     }
     len = 5 + (ssize_t)addrlen + 2;
   }
   ```

2. **Validate total packet size before reading**:
   ```c
   // Ensure len doesn't exceed buffer capacity
   if(len > READBUFFER_SIZE) {
     failf(data, "SOCKS5: Reply packet exceeds maximum size");
     return CURLPX_BAD_ADDRESS_TYPE;
   }
   ```

3. **Validate minimum response sizes** before accessing array indices

4. **Add protocol sanity checks** for unexpected state transitions

### Why Exploitation is Limited

Despite reachability, exploitation is somewhat limited by:
1. **Buffer size** - Minimum 1024 bytes provides reasonable headroom
2. **Protocol constraints** - SOCKS5 RFC 1928 limits most fields to 1 byte (0-255)
3. **State machine** - Strict state machine ensures data is processed in expected order
4. **Early validation** - Version and reply codes are validated early

---

## 6. Conclusion

The `do_SOCKS5()` function **IS REACHABLE** from external input when curl is configured to use a SOCKS5 proxy. The function directly processes network data from the SOCKS5 proxy server without significant input validation beyond basic sanity checks.

**Key Findings:**
- ✅ Function is called via normal SOCKS5 proxy configuration
- ✅ All input comes from network (SOCKS5 proxy server responses)
- ✅ Attacker can control input via MITM or compromised proxy
- ⚠️ Some input validation exists but could be more explicit
- ✅ Buffer size provides reasonable protection against some attacks
- ⚠️ Integer arithmetic and type conversions could use additional bounds checking

**Recommended Action:** Review specific input handling at lines 1004-1031 (address type parsing) and lines 700-740 (authentication handling) for potential integer overflow or buffer issues.

---

*Analysis completed: 2026-02-23*
*Tool: Reachability Analysis for curl SOCKS5 Proxy Handler*
*Status: REACHABLE from external network input*
