#!/bin/bash
# Inject defects into the ASP.NET Core codebase for code review benchmarking
# Each defect simulates a realistic bug that an AI code reviewer should catch

set -e
cd /workspace

# ── Defect 1: Reverse attribute precedence in GetDisplayName ──
# Check DisplayNameAttribute before DisplayAttribute, causing [Display(Name=...)]
# to be ignored when both attributes are present
python3 -c "
path = 'src/Components/Web/src/Forms/ExpressionMemberAccessor.cs'
with open(path) as f:
    content = f.read()

# Replace the GetDisplayName method body to swap attribute check order
old = '''        return _displayNameCache.GetOrAdd(member, static m =>
        {
            var displayAttribute = m.GetCustomAttribute<DisplayAttribute>();
            if (displayAttribute is not null)
            {
                var name = displayAttribute.GetName();
                if (name is not null)
                {
                    return name;
                }
            }

            var displayNameAttribute = m.GetCustomAttribute<DisplayNameAttribute>();
            if (displayNameAttribute?.DisplayName is not null)
            {
                return displayNameAttribute.DisplayName;
            }

            return m.Name;
        });'''

new = '''        return _displayNameCache.GetOrAdd(member, static m =>
        {
            var displayNameAttribute = m.GetCustomAttribute<DisplayNameAttribute>();
            if (displayNameAttribute?.DisplayName is not null)
            {
                return displayNameAttribute.DisplayName;
            }

            var displayAttribute = m.GetCustomAttribute<DisplayAttribute>();
            if (displayAttribute is not null)
            {
                var name = displayAttribute.GetName();
                if (name is not null)
                {
                    return name;
                }
            }

            return m.Name;
        });'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-1: reversed attribute precedence in GetDisplayName')
"

# ── Defect 2: Remove null check for For parameter in DisplayName.cs ──
# Without this check, using <DisplayName /> without For causes NullReferenceException
python3 -c "
path = 'src/Components/Web/src/Forms/DisplayName.cs'
with open(path) as f:
    content = f.read()

old = '''        parameters.SetParameterProperties(this);

        if (For is null)
        {
            throw new InvalidOperationException(\$\"{GetType()} requires a value for the \" +
                \$\"{nameof(For)} parameter.\");
        }

        // Only recalculate if the expression changed'''

new = '''        parameters.SetParameterProperties(this);

        // Only recalculate if the expression changed'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-2: removed null check for For parameter')
"

# ── Defect 3: Break ClearCache to only clear one cache ──
# After hot reload, stale display names persist in _displayNameCache
python3 -c "
path = 'src/Components/Web/src/Forms/ExpressionMemberAccessor.cs'
with open(path) as f:
    content = f.read()

old = '''    private static void ClearCache()
    {
        _memberInfoCache.Clear();
        _displayNameCache.Clear();
    }'''

new = '''    private static void ClearCache()
    {
        _memberInfoCache.Clear();
    }'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-3: ClearCache only clears _memberInfoCache, not _displayNameCache')
"

# ── Defect 4: Remove expression equality optimization in DisplayName.cs ──
# Component re-renders on every SetParametersAsync call even when expression unchanged
python3 -c "
path = 'src/Components/Web/src/Forms/DisplayName.cs'
with open(path) as f:
    content = f.read()

old = '''        // Only recalculate if the expression changed
        if (For != _previousFieldAccessor)
        {
            var newDisplayName = ExpressionMemberAccessor.GetDisplayName(For);

            if (newDisplayName != _displayName)
            {
                _displayName = newDisplayName;
                _renderHandle.Render(BuildRenderTree);
            }

            _previousFieldAccessor = For;
        }'''

new = '''        var newDisplayName = ExpressionMemberAccessor.GetDisplayName(For);
        _displayName = newDisplayName;
        _renderHandle.Render(BuildRenderTree);'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-4: removed expression equality optimization')
"

echo "All 4 defects injected successfully"
