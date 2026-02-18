#!/bin/bash
set -e

# Defect 1 (critical): ScramSaslServer.java line 136 — invert iteration count check
# Security impact: Allows weak credentials with low iteration counts to bypass SCRAM strength requirements
FILE1="clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java"
python3 -c "
import sys
with open('$FILE1', 'r') as f:
    content = f.read()

# Find and replace the iteration check (line 136)
old = '''                        if (scramCredential.iterations() < mechanism.minIterations())
                            throw new SaslException(\"Iterations \" + scramCredential.iterations() +  \" is less than the minimum \" + mechanism.minIterations() + \" for \" + mechanism);'''

new = '''                        if (scramCredential.iterations() > mechanism.minIterations())
                            throw new SaslException(\"Iterations \" + scramCredential.iterations() +  \" is less than the minimum \" + mechanism.minIterations() + \" for \" + mechanism);'''

if old not in content:
    print('ERROR: Defect 1 pattern not found in ScramSaslServer.java', file=sys.stderr)
    sys.exit(1)

content = content.replace(old, new, 1)

with open('$FILE1', 'w') as f:
    f.write(content)
print('Defect 1 injected: Inverted iteration count check')
"

# Defect 2 (critical): ScramSaslServer.java line 226 — remove timing-safe comparison
# Security impact: Enables timing attacks to extract credential hashes
python3 -c "
import sys
with open('$FILE1', 'r') as f:
    content = f.read()

# Find and replace the timing-safe comparison (line 226-227)
old = '''            if (!MessageDigest.isEqual(computedStoredKey, expectedStoredKey))
                throw new SaslException(\"Invalid client credentials\");'''

new = '''            if (!Arrays.equals(computedStoredKey, expectedStoredKey))
                throw new SaslException(\"Invalid client credentials\");'''

if old not in content:
    print('ERROR: Defect 2 pattern not found in ScramSaslServer.java', file=sys.stderr)
    sys.exit(1)

content = content.replace(old, new, 1)

with open('$FILE1', 'w') as f:
    f.write(content)
print('Defect 2 injected: Replaced timing-safe MessageDigest.isEqual with Arrays.equals')
"

# Defect 3 (high): SaslServerAuthenticator.java line 698 — remove session expiration calculation
# Security impact: Sessions never expire even when credentials/tokens expire
FILE2="clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java"
python3 -c "
import sys
with open('$FILE2', 'r') as f:
    content = f.read()

# Find and comment out the sessionExpirationTimeNanos assignment (line 698)
old = '''                sessionExpirationTimeNanos = authenticationEndNanos + 1000 * 1000 * retvalSessionLifetimeMs;'''

new = '''                // sessionExpirationTimeNanos = authenticationEndNanos + 1000 * 1000 * retvalSessionLifetimeMs;'''

if old not in content:
    print('ERROR: Defect 3 pattern not found in SaslServerAuthenticator.java', file=sys.stderr)
    sys.exit(1)

content = content.replace(old, new, 1)

with open('$FILE2', 'w') as f:
    f.write(content)
print('Defect 3 injected: Commented out session expiration time calculation')
"

# Defect 4 (critical): AclAuthorizer.scala line 522 — invert DENY ACL check
# Security impact: Authorization bypass — DENY ACLs are ignored, allowing forbidden operations
FILE3="core/src/main/scala/kafka/security/authorizer/AclAuthorizer.scala"
python3 -c "
import sys
with open('$FILE3', 'r') as f:
    content = f.read()

# Find and invert the denyAclExists check in aclsAllowAccess (line 541)
old = '''      isEmptyAclAndAuthorized(acls) || (!denyAclExists(acls) && allowAclExists(acls))'''

new = '''      isEmptyAclAndAuthorized(acls) || (denyAclExists(acls) && allowAclExists(acls))'''

if old not in content:
    print('ERROR: Defect 4 pattern not found in AclAuthorizer.scala', file=sys.stderr)
    sys.exit(1)

content = content.replace(old, new, 1)

with open('$FILE3', 'w') as f:
    f.write(content)
print('Defect 4 injected: Removed negation from denyAclExists check')
"

# Defect 5 (high): CredentialCache.java line 36 — remove credential class type validation
# Security impact: Type confusion allows wrong credential type to be retrieved, bypassing auth checks
FILE4="clients/src/main/java/org/apache/kafka/common/security/authenticator/CredentialCache.java"
python3 -c "
import sys
with open('$FILE4', 'r') as f:
    content = f.read()

# Find and remove the credential class validation (lines 36-37)
old = '''            if (cache.credentialClass() != credentialClass)
                throw new IllegalArgumentException(\"Invalid credential class \" + credentialClass + \", expected \" + cache.credentialClass());'''

new = '''            // Type check removed - cache can return any credential type
            // if (cache.credentialClass() != credentialClass)
            //     throw new IllegalArgumentException(\"Invalid credential class \" + credentialClass + \", expected \" + cache.credentialClass());'''

if old not in content:
    print('ERROR: Defect 5 pattern not found in CredentialCache.java', file=sys.stderr)
    sys.exit(1)

content = content.replace(old, new, 1)

with open('$FILE4', 'w') as f:
    f.write(content)
print('Defect 5 injected: Removed credential class type validation')
"

echo "All 5 defects injected successfully"
