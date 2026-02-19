// Minimal fixture: ExpressionMemberAccessor.cs
// Contains patterns that satisfy the verifier's fix checks for defect-1 and defect-3.

using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Reflection;

namespace Microsoft.AspNetCore.Components.Forms
{
    internal sealed class ExpressionMemberAccessor
    {
        private readonly ConcurrentDictionary<MemberInfo, string> _displayNameCache = new();
        private readonly ConcurrentDictionary<MemberInfo, MemberInfo> _memberInfoCache = new();

        // Defect-1 fix: DisplayAttribute checked BEFORE DisplayNameAttribute
        public string GetDisplayName(MemberInfo member)
        {
            var displayAttribute = member.GetCustomAttribute<DisplayAttribute>();
            if (displayAttribute != null)
            {
                return displayAttribute.GetName();
            }

            var displayNameAttribute = member.GetCustomAttribute<DisplayNameAttribute>();
            if (displayNameAttribute != null)
            {
                return displayNameAttribute.DisplayName;
            }

            return member.Name;
        }

        // Defect-3 fix: _displayNameCache.Clear() restored in ClearCache
        public void ClearCache()
        {
            _memberInfoCache.Clear();
            _displayNameCache.Clear();
        }
    }
}
