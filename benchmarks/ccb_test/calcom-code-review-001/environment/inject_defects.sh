#!/bin/bash
# Inject defects into the cal.com codebase for code review benchmarking
# Each defect simulates a realistic bug that an AI code reviewer should catch

set -e
cd /workspace

# ── Defect 1: Invert filter in listFeaturesForUser ──
# Returns only globally DISABLED features instead of enabled ones
python3 -c "
path = 'packages/features/feature-opt-in/services/FeatureOptInService.ts'
with open(path) as f:
    content = f.read()

old = '''    return featureIds.map((featureId) => resolvedStates[featureId]).filter((state) => state.globalEnabled);'''

new = '''    return featureIds.map((featureId) => resolvedStates[featureId]).filter((state) => !state.globalEnabled);'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-1: inverted globalEnabled filter in listFeaturesForUser')
"

# ── Defect 2: Remove scope fallback in isFeatureAllowedForScope ──
# Features without explicit scope array are now rejected for all scopes
python3 -c "
path = 'packages/features/feature-opt-in/config.ts'
with open(path) as f:
    content = f.read()

old = '''  return !config.scope || config.scope.includes(scope);'''

new = '''  return config.scope.includes(scope);'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-2: removed scope fallback in isFeatureAllowedForScope')
"

# ── Defect 3: Remove isOptInFeature validation in setUserState ──
# Any arbitrary feature slug can now be set, bypassing the allowlist
python3 -c "
path = 'packages/trpc/server/routers/viewer/featureOptIn/_router.ts'
with open(path) as f:
    content = f.read()

old = '''    .mutation(async ({ ctx, input }) => {
      if (!isOptInFeature(input.slug)) {
        throw new TRPCError({
          code: \"BAD_REQUEST\",
          message: \"Invalid slug. This feature is not opt-in configurable.\",
        });
      }

      await featureOptInService.setUserFeatureState({'''

new = '''    .mutation(async ({ ctx, input }) => {
      await featureOptInService.setUserFeatureState({'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-3: removed isOptInFeature validation in setUserState')
"

# ── Defect 4: Hardcode policy to 'permissive' instead of reading from config ──
# Ignores per-feature policy configuration
python3 -c "
path = 'packages/features/feature-opt-in/services/FeatureOptInService.ts'
with open(path) as f:
    content = f.read()

old = '''    // Get the policy for this feature from the config
    const featureConfig = getOptInFeatureConfig(featureId);
    const policy: OptInFeaturePolicy = featureConfig?.policy ?? \"permissive\";'''

new = '''    const policy: OptInFeaturePolicy = \"permissive\";'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-4: hardcoded policy to permissive, ignoring config')
"

echo "All 4 defects injected successfully"
