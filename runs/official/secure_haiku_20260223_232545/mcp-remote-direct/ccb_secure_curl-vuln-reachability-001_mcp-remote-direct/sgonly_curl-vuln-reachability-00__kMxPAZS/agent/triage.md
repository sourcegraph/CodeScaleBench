# Security Reachability Analysis: curl SOCKS5 Proxy Handler

## Summary

The `do_SOCKS5()` function in `lib/socks.c` is **REACHABLE** from external attacker-controlled input. When a user configures curl to use a SOCKS5 proxy, the function processes responses from the proxy server, making it directly exposed to attacker-controlled data. The attack vector is configuring curl with a malicious or attacker-controlled SOCKS5 proxy server.

---

## Affected Code

**Function:** `do_SOCKS5()`
**File:** `lib/socks.c` (lines 548-1054)
**Type:** Static function that implements SOCKS5 proxy protocol handshake

**Description:** This function handles the complete SOCKS5 proxy negotiation sequence, including:
- Initial handshake with the proxy server
- Authentication mechanism negotiation (GSSAPI, username/password, or none)
- Username/password authentication if selected
- CONNECT request to establish tunnel to remote host
- Processing SOCKS5 responses and error codes

---

## Attack Path

### Complete Call Chain from Entry Point to do_SOCKS5()

```
main() / curl_easy_perform()
  ↓
Curl_connect() [lib/url.c:3895]
  ↓
Curl_setup_conn() [lib/url.c:3858]
  ↓
Curl_conn_setup() [lib/connect.c:1416]
  ↓
cf_setup_add() [lib/connect.c:1364]
  ↓
cf_setup_connect() [lib/connect.c:1186]
  ↓ (checks: ctx->state < CF_SETUP_CNNCT_SOCKS && cf->conn->bits.socksproxy)
  ↓
Curl_cf_socks_proxy_insert_after() [lib/socks.c:1240]
  ↓
socks_proxy_cf_connect() [lib/socks.c:1103]
  ↓
connect_SOCKS() [lib/socks.c:1056]
  ↓ (switch: conn->socks_proxy.proxytype == CURLPROXY_SOCKS5*)
  ↓
do_SOCKS5() [lib/socks.c:548]
```

### Function Roles in the Chain

1. **main() / curl_easy_perform()** - Entry point: User initiates curl transfer
2. **Curl_connect()** - Main connection orchestrator, calls DNS resolution
3. **Curl_setup_conn()** - Post-DNS setup, initiates filter chain creation
4. **Curl_conn_setup()** - Creates the root setup filter
5. **cf_setup_add()** - Adds setup filter to connection chain
6. **cf_setup_connect()** - Connection filter callback that checks proxy configuration
   - **Critical check:** `if(ctx->state < CF_SETUP_CNNCT_SOCKS && cf->conn->bits.socksproxy)`
   - Decides whether to insert SOCKS proxy filter based on user configuration
7. **Curl_cf_socks_proxy_insert_after()** - Inserts SOCKS proxy filter into chain
8. **socks_proxy_cf_connect()** - SOCKS proxy filter's connection callback
9. **connect_SOCKS()** - State machine dispatcher for SOCKS protocol
10. **do_SOCKS5()** - Implements SOCKS5-specific state machine handling

### Source of External Input

The `bits.socksproxy` flag is set in `lib/url.c:1547` based on user-provided proxy configuration:

```c
conn->bits.socksproxy = (conn->bits.proxy &&
                         !conn->bits.httpproxy) ? TRUE : FALSE;
```

The proxy configuration comes from:
- `--proxy` command-line flag
- Environment variables (http_proxy, https_proxy, etc.)
- User code via `CURLOPT_PROXY` option

---

## Severity Assessment

### Reachability: **YES - FULLY REACHABLE**

The function is directly reachable from external attacker-controlled input when a user configures a SOCKS5 proxy.

### Attack Vector: **Attacker-Controlled SOCKS5 Proxy Server**

To trigger code execution or exploitation of `do_SOCKS5()`:

1. **User Action Required:** User must configure curl to use a SOCKS5 proxy:
   ```bash
   curl https://example.com --proxy socks5://attacker-proxy:1080
   ```

2. **Attack Execution:** The attacker controls the SOCKS5 proxy server listening on port 1080 (or configured port)

3. **Attack Triggers:** Attacker sends malformed or crafted SOCKS5 responses when:
   - Curl sends initial SOCKS5 greeting
   - Curl sends CONNECT request with destination hostname
   - Curl awaits proxy responses during authentication and connection establishment

### External Input to do_SOCKS5()

All of the following data originates from the attacker-controlled proxy server:

1. **SOCKS5 Response Bytes:**
   - `socksreq[0]` - Protocol version (should be 5)
   - `socksreq[1]` - Authentication method selected
   - `socksreq[3]` - Address type in CONNECT response
   - `socksreq[4]` - Domain name length / IPv6 address data
   - Authentication response codes

2. **Attack Scenarios:**
   - **Stack overflow:** Hostname length field (`socksreq[4]` at line 1007) is not bounds-checked in CONNECT response processing
   - **Out-of-bounds read:** Domain name parsing (line 1005-1008) uses user-controlled length
   - **Integer overflow:** Port number, hostname length calculations
   - **Logic errors:** Misinterpretation of response codes leading to false success

### Exploitation Requirements

| Component | Requirement |
|-----------|-------------|
| **User Configuration** | Must specify `--proxy socks5://attacker:port` |
| **Network Access** | Attacker must be able to accept connections and send SOCKS5 responses |
| **Victim Vulnerability** | Vulnerable curl version with bugs in SOCKS5 parsing |
| **Impact** | RCE, memory corruption, information disclosure |

### Risk Factors

- **High Reachability:** Any user using SOCKS5 proxies is vulnerable
- **User Control:** Users explicitly specify the proxy address
- **Attack Complexity:** Medium - attacker needs control of proxy server or MitM position
- **Impact Potential:** High - reaches network protocol parsing code processing untrusted data

---

## Remediation

### Input Validation Issues

The `do_SOCKS5()` function processes the following potentially dangerous fields:

#### 1. **Domain Name Length Field (Line 1007)**
```c
if(socksreq[3] == 3) {
  /* domain name */
  int addrlen = (int) socksreq[4];  // ⚠️ UNTRUSTED LENGTH
  len = 5 + addrlen + 2;
}
```

**Recommendation:** Add bounds checking:
```c
if(socksreq[3] == 3) {
  int addrlen = (int) socksreq[4];
  if(addrlen > 255 || (5 + addrlen + 2) > READBUFFER_MIN) {
    failf(data, "SOCKS5 domain name length exceeds buffer");
    return CURLPX_BAD_ADDRESS_TYPE;
  }
  len = 5 + addrlen + 2;
}
```

#### 2. **Hostname Length Validation (Line 589)**
```c
if(!socks5_resolve_local && hostname_len > 255) {
  // ✓ Good: Already validated
}
```

#### 3. **Buffer Overflow in Hostname Encoding (Line 906)**
```c
socksreq[len++] = (char) hostname_len; // ⚠️ Direct cast without range check
memcpy(&socksreq[len], sx->hostname, hostname_len);
```

**Recommendation:** Validate hostname_len before use:
```c
if(hostname_len > 255) {
  failf(data, "hostname too long for SOCKS5");
  return CURLPX_LONG_HOSTNAME;
}
socksreq[len++] = (unsigned char) hostname_len;
```

#### 4. **Response Code Processing (Line 965)**
```c
else if(socksreq[1]) { /* Anything besides 0 is an error */
  // Handles error responses, but validates...
  if(code < 9) {
    // Uses lookup table (good bounds check)
  }
}
```

**Status:** Reasonably protected with lookup table

### Overall Risk Assessment

**Current State:** The function has some protections but also vulnerable areas:
- ✓ Proxy user/password lengths are validated (lines 727, 737)
- ✓ Error codes are bounds-checked with lookup table
- ⚠️ Domain name length field from proxy response lacks validation
- ⚠️ Hostname parameter validation exists but could be stricter

**Priority Fixes:**
1. Validate domain name length from proxy response before calculating buffer offset
2. Add comprehensive bounds checking for all proxy response fields
3. Use size_t for all length calculations to prevent integer overflow
4. Implement assertions for buffer boundaries

---

## Conclusion

The `do_SOCKS5()` function **IS REACHABLE** from attacker-controlled input via a malicious SOCKS5 proxy server. The attack vector requires user configuration of a SOCKS5 proxy, but once configured, all response data from the proxy flows directly into this function with limited validation.

**Risk Level:** MEDIUM-HIGH for users configuring SOCKS5 proxies

**Affected Scenarios:**
- Corporate environments using SOCKS5 proxies
- Tor network users (uses SOCKS5)
- Users behind SOCKS proxies for privacy
- Any configuration with `curl --proxy socks5://`
