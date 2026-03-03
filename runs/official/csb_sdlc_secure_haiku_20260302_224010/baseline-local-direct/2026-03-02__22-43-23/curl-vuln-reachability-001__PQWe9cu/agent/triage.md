# Security Reachability Analysis: curl SOCKS5 Proxy Handler

## 1. Summary

The `do_SOCKS5()` function in `lib/socks.c` is **REACHABLE** from external network input when curl is configured with a SOCKS5 proxy. This function handles the complete SOCKS5 protocol handshake, including authentication and connection establishment. External input from the SOCKS5 proxy server reaches this function and influences its control flow and buffer operations.

**Conclusion: REACHABLE**

---

## 2. Affected Code

**Function:** `do_SOCKS5()`
**File:** `/workspace/lib/socks.c`
**Lines:** 548-1054

**Purpose:**
This function implements the SOCKS5 proxy protocol as defined in RFC 1928. It handles:
- Initial proxy greeting and authentication method negotiation (lines 607-629)
- Username/password authentication (lines 702-777)
- GSSAPI authentication (lines 668-676, 693-696)
- Target server connection request (lines 782-912)
- Response parsing including address type validation and buffer length calculation (lines 951-1049)

The function is responsible for establishing a secure tunnel through a SOCKS5 proxy to reach the final destination server.

---

## 3. Attack Path

### Complete Call Chain

```
main()  (src/tool_main.c:228)
  ↓
operate()  (src/tool_operate.c)
  ↓
curl_easy_perform()  [libcurl API]
  ↓
curl_multi_perform()  [libcurl connection manager]
  ↓
Curl_connect()  [connection establishment]
  ↓
Curl_cfilter_setup()  [connection filter chain setup]
  ↓
Curl_cf_socks_proxy_insert_after()  (lib/socks.c:1240)
  ↓
socks_proxy_cf_connect()  (lib/socks.c:1103)
  ↓
connect_SOCKS()  (lib/socks.c:1056)
  ↓
do_SOCKS5()  (lib/socks.c:548)
```

### Function Roles in Call Chain

1. **main()** (src/tool_main.c:228)
   - Entry point of curl command-line tool
   - Initializes curl library and calls operate()

2. **operate()** (src/tool_operate.c)
   - Parses command-line arguments including `--proxy socks5://proxy:1080`
   - Sets up curl handles with CURLOPT_PROXY option (line 1546 in tool_operate.c)

3. **curl_easy_perform()/curl_multi_perform()**
   - libcurl's public API
   - Initiates HTTP/HTTPS request with configured proxy

4. **Curl_connect()** (lib/connect.c)
   - Establishes TCP connection to proxy server
   - Sets up connection filter chain based on proxy type

5. **Curl_cf_socks_proxy_insert_after()** (lib/socks.c:1240-1250)
   - Registers SOCKS proxy filter into the connection chain
   - Creates new filter with `socks_proxy_cf_connect` callback
   - Triggered when `conn->bits.socksproxy` is TRUE (set in lib/url.c:2519)

6. **socks_proxy_cf_connect()** (lib/socks.c:1103-1158)
   - Called when TCP connection to proxy is established
   - Initializes SOCKS state machine (sx)
   - Sets hostname, port, and credentials from connection config
   - Calls connect_SOCKS() to begin SOCKS protocol handshake

7. **connect_SOCKS()** (lib/socks.c:1056-1085)
   - Dispatches to appropriate SOCKS version handler
   - Routes SOCKS5 requests to do_SOCKS5() (line 1067)

8. **do_SOCKS5()** (lib/socks.c:548-1054)
   - Implements RFC 1928 SOCKS5 protocol
   - Processes external network input from proxy server
   - Performs state machine transitions based on proxy responses

### External Input Entry Point

The external input is **the SOCKS5 proxy server's network responses**. These responses are received and processed in the following locations within do_SOCKS5():

- **Authentication negotiation** (lines 645-692): Proxy responds with chosen authentication method
- **Authentication response** (lines 762-776): Proxy responds to credential submission
- **Connection request ACK** (lines 951-1049): Proxy responds to connection request with address type and binding information

---

## 4. Severity Assessment

### Reachability Analysis

**CAN AN ATTACKER TRIGGER THIS FUNCTION?** ✓ YES

The function is reachable under the following conditions:
1. User invokes curl with a SOCKS5 proxy: `curl https://example.com --proxy socks5://proxy:1080`
2. curl establishes a TCP connection to the specified proxy
3. The SOCKS5 protocol handler automatically begins
4. All responses from the proxy server are processed by do_SOCKS5()

### Attack Vector

**User Action Required:**
- Explicitly specify a SOCKS5 proxy via `--proxy socks5://proxy:1080` or `--proxy socks5h://proxy:1080`

**Network Conditions:**
- Network path to proxy must be compromised OR
- Proxy server itself is malicious OR
- Proxy server connection is intercepted (MITM attack)

The attacker does NOT need control of the destination server; they only need to control or intercept the connection to the SOCKS5 proxy.

### External Input Data Flow

The following data reaches do_SOCKS5() directly from the untrusted SOCKS5 proxy server:

1. **Line 654** - `socksreq[0]`: Protocol version byte (external)
2. **Line 654, 658, 663, 669, 680, 685** - `socksreq[1]`: Authentication method selection (external, attacker-controlled)
3. **Line 772** - `socksreq[1]`: Authentication response status (external)
4. **Line 960** - `socksreq[0]`: Response protocol version (external)
5. **Line 965** - `socksreq[1]`: Connection result code (external)
6. **Line 1005** - `socksreq[3]`: Address type field (external, attacker-controlled)
7. **Line 1007** - `socksreq[4]`: Address length for domain names (external, attacker-controlled)
   - Range: 0-255 bytes, used to calculate buffer read size
   - Calculated at line 1008: `len = 5 + addrlen + 2`
   - Used at line 1028: `sx->outstanding = len - 10`

### Critical Data: Address Type and Length

At lines 1005-1020, the function calculates the expected response packet size based on address type field `socksreq[3]`:

```c
if(socksreq[3] == 3) {
  /* domain name */
  int addrlen = (int) socksreq[4];  // <-- EXTERNAL INPUT (0-255)
  len = 5 + addrlen + 2;             // <-- Can be 7-262 bytes
}
else if(socksreq[3] == 4) {
  /* IPv6 */
  len = 4 + 16 + 2;  // 22 bytes
}
else if(socksreq[3] == 1) {
  len = 4 + 4 + 2;   // 10 bytes
}
```

This attacker-controlled length value directly influences how much data is read into the buffer:

```c
sx->outstanding = len - 10;  /* line 1028 */
sx->outp = &socksreq[10];
Curl_conn_cf_recv(cf->next, data, (char *)sx->outp, sx->outstanding, &result);
```

---

## 5. Vulnerability Assessment

### Buffer Safety Analysis

While the code appears to have basic bounds checking, the analysis reveals:

**Potential Issue:**
- The address length field from the proxy response (socksreq[4]) is treated as an unsigned byte (0-255)
- This value is used directly in arithmetic: `len = 5 + addrlen + 2`
- Maximum len = 5 + 255 + 2 = 262 bytes
- Buffer starting at socksreq[0] is at least READBUFFER_MIN (1024 bytes), so no immediate overflow

**However, the critical vulnerability vector is:**
1. **Attacker controls `socksreq[1]`** (line 658-689) - authentication method selection
   - Can force GSS-API authentication (line 669), BASIC auth (line 663), or no auth
   - This influences subsequent code paths and authentication processing
2. **Attacker controls `socksreq[3]`** (line 1005) - address type
   - Can be set to invalid values (not 1, 3, or 4)
   - Invalid values reach the else clause at line 1017 which still returns an error code
3. **Attacker controls `socksreq[4]`** (line 1007) - address length
   - While bounds are respected, the value drives the recv size
   - Could cause excessive reads if combined with network delays or incomplete responses

### Confirmation of Reachability

**Direct Evidence:**
- Line 1067: `pxresult = do_SOCKS5(cf, sxstate, data);` - Called directly when proxytype == CURLPROXY_SOCKS5
- Lines 645-692: Direct processing of proxy response data (socksreq[1]) in a switch statement
- Lines 1005-1020: Direct use of attacker-controlled socksreq[3] and socksreq[4] values

**Exploitation Prerequisite:**
User must explicitly configure a SOCKS5 proxy. This is a deliberate choice, not automatic behavior. However, once configured, all responses from the SOCKS5 proxy are treated as trusted protocol data and processed by do_SOCKS5().

---

## 6. Remediation

### Current Protections

The code has these mitigations in place:

1. **Buffer size validation** (line 287):
   ```c
   DEBUGASSERT(READBUFFER_MIN >= 600);
   ```
   Buffer is large enough for maximum responses.

2. **Address type validation** (line 1005-1020):
   Only processes address types 1, 3, and 4; rejects others.

3. **Hostname length check** (line 589):
   ```c
   if(!socks5_resolve_local && hostname_len > 255) {
     infof(data, "SOCKS5: server resolving disabled...");
     socks5_resolve_local = TRUE;
   }
   ```

### Recommended Enhancements

If a vulnerability were discovered in the SOCKS5 handler:

1. **Add explicit bounds check on calculated length:**
   ```c
   if(socksreq[3] == 3) {
     int addrlen = (int) socksreq[4];
     if(addrlen > 255 || (5 + addrlen + 2) > READBUFFER_MIN) {
       failf(data, "SOCKS5 response address length exceeds buffer");
       return CURLPX_BAD_ADDRESS_TYPE;
     }
     len = 5 + addrlen + 2;
   }
   ```

2. **Validate proxy responses against RFC 1928:**
   - Check version byte is exactly 0x05
   - Validate reply codes against specification
   - Ensure authentication methods are expected

3. **Add timeout protection** for partial responses:
   - If proxy sends incomplete packet, avoid indefinite waiting
   - Currently relies on lower-level timeout handlers

4. **Consider proxy response logging** in debug mode:
   - Log unexpected values from proxy for security auditing

---

## 7. Conclusion

The `do_SOCKS5()` function is **definitely reachable** from external input when a user specifies a SOCKS5 proxy. The attack vector requires:

1. **User action:** Explicit specification of a SOCKS5 proxy via `--proxy socks5://...`
2. **Network condition:** Attacker controls or intercepts the proxy connection
3. **Payload:** Malformed SOCKS5 protocol responses

All proxy server responses reach `do_SOCKS5()` and are processed without cryptographic verification, making external input processing the primary security concern. The function implements a state machine that processes untrusted network data based on the proxy's responses.

**Risk Level:** MEDIUM (requires user misconfiguration or network compromise)

**Recommendation:** Users should only use SOCKS5 proxies from trusted sources and ensure proxy connections are protected (e.g., SSH tunnels, VPNs with authentication).
