#!/bin/bash
# Inject security-adjacent defects into the curl codebase for code review benchmarking
# Each defect simulates a realistic security vulnerability that an AI code reviewer should catch

set -e
cd /workspace

# ── Defect 1: Remove embedded NUL byte detection in TLS SAN cert verification ──
# Without this check, a certificate with "evil.com\0.good.com" in the SAN
# could pass hostname verification for "good.com" (CVE-2009-2408 class)
python3 -c "
path = 'lib/vtls/openssl.c'
with open(path) as f:
    content = f.read()

old = '''          if((altlen == strlen(altptr)) &&
             /* if this is not true, there was an embedded zero in the name
                string and we cannot match it. */
             subj_alt_hostcheck(data, altptr, altlen,
                                peer->hostname, hostlen,
                                peer->dispname)) {'''

new = '''          if(subj_alt_hostcheck(data, altptr, altlen,
                                peer->hostname, hostlen,
                                peer->dispname)) {'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-1: removed embedded NUL byte check in SAN cert verification')
"

# ── Defect 2: Off-by-one in cookie domain tail matching ──
# Shifts the dot boundary check by one character, allowing cookies for
# "example.com" to match "Xexample.com" instead of requiring ".example.com"
python3 -c "
path = 'lib/cookie.c'
with open(path) as f:
    content = f.read()

old = '''  if('.' == *(hostname + hostname_len - cookie_domain_len - 1))
    return TRUE;'''

new = '''  if('.' == *(hostname + hostname_len - cookie_domain_len))
    return TRUE;'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-2: off-by-one in cookie domain tail match boundary check')
"

# ── Defect 3: Remove buffer bounds check in SSL password callback ──
# Without the num > klen check, if the password is longer than OpenSSL's
# provided buffer, memcpy writes past the end of buf (heap overflow)
python3 -c "
path = 'lib/vtls/openssl.c'
with open(path) as f:
    content = f.read()

old = '''  if(!encrypting && num >= 0) {
    int klen = curlx_uztosi(strlen((char *)global_passwd));
    if(num > klen) {
      memcpy(buf, global_passwd, klen + 1);
      return klen;
    }
  }'''

new = '''  if(!encrypting) {
    int klen = curlx_uztosi(strlen((char *)global_passwd));
    memcpy(buf, global_passwd, klen + 1);
    return klen;
  }'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-3: removed buffer bounds check in passwd_callback')
"

# ── Defect 4: Remove NULL pointer guard in transfer shutdown ──
# Without the !data || !data->conn check, passing NULL data or a data
# with NULL conn causes a NULL pointer dereference crash
python3 -c "
path = 'lib/transfer.c'
with open(path) as f:
    content = f.read()

old = '''  if(!data || !data->conn)
    return CURLE_FAILED_INIT;
  if(data->conn->sockfd == CURL_SOCKET_BAD)
    return CURLE_FAILED_INIT;
  sockindex = (data->conn->sockfd == data->conn->sock[SECONDARYSOCKET]);
  return Curl_conn_shutdown(data, sockindex, done);
}

static bool xfer_recv_shutdown_started(struct Curl_easy *data)'''

new = '''  if(data->conn->sockfd == CURL_SOCKET_BAD)
    return CURLE_FAILED_INIT;
  sockindex = (data->conn->sockfd == data->conn->sock[SECONDARYSOCKET]);
  return Curl_conn_shutdown(data, sockindex, done);
}

static bool xfer_recv_shutdown_started(struct Curl_easy *data)'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-4: removed NULL guard in xfer_recv_shutdown')
"

# ── Defect 5: Remove integer overflow guard in base64 encoding ──
# On 32-bit platforms, without the UINT_MAX/4 check, (insize + 2) / 3 * 4
# can overflow size_t, causing a small malloc followed by massive out-of-bounds write
python3 -c "
path = 'lib/base64.c'
with open(path) as f:
    content = f.read()

old = '''#if SIZEOF_SIZE_T == 4
  if(insize > UINT_MAX/4)
    return CURLE_OUT_OF_MEMORY;
#endif

  base64data = output = malloc((insize + 2) / 3 * 4 + 1);'''

new = '''  base64data = output = malloc((insize + 2) / 3 * 4 + 1);'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-5: removed integer overflow guard in base64 encode')
"

echo "All 5 defects injected successfully"
