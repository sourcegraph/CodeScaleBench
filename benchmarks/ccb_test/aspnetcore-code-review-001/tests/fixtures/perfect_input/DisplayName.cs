// Minimal fixture: DisplayName.cs
// Contains patterns that satisfy the verifier's fix checks for defect-2 and defect-4.

using System;
using System.Linq.Expressions;

namespace Microsoft.AspNetCore.Components.Forms
{
    public class DisplayName<TModel> : ComponentBase
    {
        private LambdaExpression _previousFieldAccessor;

        [Parameter]
        public Expression<Func<TModel, object>> For { get; set; }

        protected override void OnParametersSet()
        {
            // Defect-2 fix: null check for For parameter restored
            if (For is null)
            {
                throw new InvalidOperationException(
                    $"{GetType()} requires a value for the 'For' parameter.");
            }

            // Defect-4 fix: expression equality check restored
            if (For != _previousFieldAccessor)
            {
                _previousFieldAccessor = For;
                _displayName = null;  // force re-evaluation
            }
        }
    }
}
