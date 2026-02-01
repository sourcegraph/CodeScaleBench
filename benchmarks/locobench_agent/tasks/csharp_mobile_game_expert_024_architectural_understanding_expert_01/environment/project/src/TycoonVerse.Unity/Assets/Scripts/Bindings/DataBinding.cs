```csharp
// File: TycoonVerse/src/TycoonVerse.Unity/Assets/Scripts/Bindings/DataBinding.cs

using System;
using System.ComponentModel;
using System.Reflection;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;
using TMPro;

namespace TycoonVerse.Unity.Bindings
{
    /// <summary>
    ///     Supported binding modes.
    /// </summary>
    public enum BindingMode
    {
        OneTime,   // Apply once on Start().
        OneWay,    // View-Model -> View.
        TwoWay     // View-Model <-> View.
    }

    /// <summary>
    ///     Converts values between the View-Model and View targets.
    /// </summary>
    public interface IValueConverter
    {
        object Convert(object value, Type targetType);
        object ConvertBack(object value, Type targetType);
    }

    /// <summary>
    ///     Base class for ScriptableObject-based value converters that can be reused through the inspector.
    /// </summary>
    public abstract class ValueConverterAsset : ScriptableObject, IValueConverter
    {
        public abstract object Convert(object value, Type targetType);
        public abstract object ConvertBack(object value, Type targetType);
    }

    /// <summary>
    ///     Internal utilities for reflection-based member access. Kept light-weight for mobile.
    /// </summary>
    internal static class ReflectionUtility
    {
        private const BindingFlags Flags =
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

        public static MemberInfo[] CacheMemberChain(Type rootType, string path)
        {
            var segments = path.Split('.');
            var chain    = new MemberInfo[segments.Length];

            var currentType = rootType;

            for (var i = 0; i < segments.Length; i++)
            {
                var member = currentType.GetProperty(segments[i], Flags) as MemberInfo ??
                             (MemberInfo)currentType.GetField(segments[i], Flags);

                if (member == null)
                    throw new MissingMemberException(
                        $"Cannot locate member '{segments[i]}' on type '{currentType.FullName}'.");

                chain[i]    = member;
                currentType = GetMemberType(member);
            }

            return chain;
        }

        public static Type GetMemberType(MemberInfo member)
        {
            return member switch
            {
                FieldInfo f   => f.FieldType,
                PropertyInfo p=> p.PropertyType,
                _             => throw new ArgumentException("Unsupported member type.")
            };
        }

        public static object GetNestedValue(object root, MemberInfo[] chain)
        {
            var current = root;
            foreach (var member in chain)
            {
                if (current == null) return null;
                current = member switch
                {
                    FieldInfo f    => f.GetValue(current),
                    PropertyInfo p => p.GetValue(current),
                    _              => throw new ArgumentException("Unsupported member type.")
                };
            }

            return current;
        }

        public static void SetNestedValue(object root, MemberInfo[] chain, object value)
        {
            if (chain.Length == 0)
                throw new ArgumentException("Member chain is empty.");

            // Traverse until the penultimate node.
            object current = root;
            for (var i = 0; i < chain.Length - 1; i++)
            {
                current = chain[i] switch
                {
                    FieldInfo f    => f.GetValue(current),
                    PropertyInfo p => p.GetValue(current),
                    _              => throw new ArgumentException("Unsupported member type.")
                };
            }

            if (current == null)
                throw new NullReferenceException("Intermediate property in chain is null.");

            var last = chain[^1];
            switch (last)
            {
                case FieldInfo f:
                    f.SetValue(current, value);
                    break;
                case PropertyInfo p when p.CanWrite:
                    p.SetValue(current, value);
                    break;
                default:
                    throw new InvalidOperationException(
                        $"Member '{last.Name}' does not have a setter.");
            }
        }
    }

    /// <summary>
    ///     Binds a View-Model property path to a Unity component property, supporting One-Time, One-Way, and Two-Way modes.
    ///     The component handles all reflection plumbing and value conversions so designers only need to configure the
    ///     binding in the inspector.
    /// </summary>
    [AddComponentMenu("TycoonVerse/Bindings/Data Binding")]
    [DisallowMultipleComponent]
    public sealed class DataBinding : MonoBehaviour
    {
        [Header("View-Model Source")]
        [Tooltip("MonoBehaviour that implements INotifyPropertyChanged and represents the View-Model.")]
        [SerializeField] private MonoBehaviour _viewModelBehaviour;

        [Tooltip("Dot-separated property or field path inside the View-Model. Example: Portfolio.CashBalance")]
        [SerializeField] private string _viewModelPropertyPath;

        [Header("View Target")]
        [Tooltip("Unity component that owns the property to update (e.g., Text, TMP_Text, Slider).")]
        [SerializeField] private Component _targetComponent;

        [Tooltip("Name of the property or field on the component to update (e.g., text, value, isOn).")]
        [SerializeField] private string _targetPropertyName;

        [Header("Advanced")]
        [SerializeField] private BindingMode _mode = BindingMode.OneWay;

        [Tooltip("Optional converter. Leave empty for implicit conversion.")]
        [SerializeField] private ValueConverterAsset _converter;

        // Cached reflection information.
        private INotifyPropertyChanged _viewModel;
        private MemberInfo[]           _vmMemberChain;
        private MemberInfo             _targetMember;

        // Two-way listener holders.
        private bool _uiEventHooked;
        private bool _isUpdatingFromUI;  // Prevent re-entrancy loops.

        #region Unity lifecycle

        private void Awake()
        {
            ValidateSetup();
            CacheReflection();
        }

        private void OnEnable()
        {
            SubscribeToViewModel();

            if (_mode == BindingMode.TwoWay)
                HookUIEvents();

            // Apply initial value.
            ApplyViewModelToView();
        }

        private void OnDisable()
        {
            UnsubscribeFromViewModel();
            UnhookUIEvents();
        }

        #endregion

        #region Validation & Reflection

        private void ValidateSetup()
        {
            if (_viewModelBehaviour == null)
                throw new ArgumentNullException(nameof(_viewModelBehaviour),
                    $"{nameof(DataBinding)} on '{name}' is missing View-Model reference.");

            if (string.IsNullOrWhiteSpace(_viewModelPropertyPath))
                throw new ArgumentException("View-Model property path is required.",
                    nameof(_viewModelPropertyPath));

            if (_targetComponent == null)
                throw new ArgumentNullException(nameof(_targetComponent),
                    $"{nameof(DataBinding)} on '{name}' is missing target component.");

            if (string.IsNullOrWhiteSpace(_targetPropertyName))
                throw new ArgumentException("Target property name is required.",
                    nameof(_targetPropertyName));

            _viewModel = _viewModelBehaviour as INotifyPropertyChanged;
            if (_viewModel == null)
                throw new InvalidCastException(
                    $"The provided View-Model ({_viewModelBehaviour.GetType().Name}) does not implement INotifyPropertyChanged.");
        }

        private void CacheReflection()
        {
            // Cache ViewModel chain.
            _vmMemberChain = ReflectionUtility.CacheMemberChain(
                _viewModelBehaviour.GetType(), _viewModelPropertyPath);

            // Cache target member.
            const BindingFlags flags =
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
            _targetMember = _targetComponent.GetType().GetProperty(_targetPropertyName, flags) as MemberInfo ??
                            (MemberInfo)_targetComponent.GetType().GetField(_targetPropertyName, flags);

            if (_targetMember == null)
                throw new MissingMemberException(
                    $"Cannot locate target member '{_targetPropertyName}' on '{_targetComponent.GetType().Name}'.");
        }

        #endregion

        #region View-Model event handling

        private void SubscribeToViewModel()
        {
            _viewModel.PropertyChanged += OnViewModelPropertyChanged;
        }

        private void UnsubscribeFromViewModel()
        {
            _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
        }

        private void OnViewModelPropertyChanged(object sender, PropertyChangedEventArgs args)
        {
            if (_mode == BindingMode.OneTime) return;
            if (_isUpdatingFromUI) return; // Avoid feedback loop.

            // Fire for null/empty (refresh all) or exact member change.
            if (string.IsNullOrEmpty(args.PropertyName) ||
                args.PropertyName == _vmMemberChain[^1].Name)
            {
                ApplyViewModelToView();
            }
        }

        #endregion

        #region Apply VM -> View

        private void ApplyViewModelToView()
        {
            try
            {
                var rawValue = ReflectionUtility.GetNestedValue(_viewModelBehaviour, _vmMemberChain);

                object finalValue = _converter != null
                    ? _converter.Convert(rawValue, ReflectionUtility.GetMemberType(_targetMember))
                    : ChangeType(rawValue, ReflectionUtility.GetMemberType(_targetMember));

                SetTargetValue(finalValue);
            }
            catch (Exception ex)
            {
                Debug.LogError(
                    $"[{nameof(DataBinding)}] Failed to apply View-Model value to View on '{name}': {ex}");
            }
        }

        private void SetTargetValue(object value)
        {
            switch (_targetMember)
            {
                case FieldInfo f:
                    f.SetValue(_targetComponent, value);
                    break;
                case PropertyInfo p when p.CanWrite:
                    p.SetValue(_targetComponent, value);
                    break;
                default:
                    Debug.LogError(
                        $"[{nameof(DataBinding)}] Target member '{_targetPropertyName}' is not writable on '{name}'.");
                    break;
            }
        }

        #endregion

        #region Apply View -> VM (Two-Way)

        private void HookUIEvents()
        {
            if (_uiEventHooked) return;

            switch (_targetComponent)
            {
                case InputField inputField:
                    inputField.onEndEdit.AddListener(OnInputFieldValueChanged);
                    _uiEventHooked = true;
                    break;

                case TMP_InputField tmpInputField:
                    tmpInputField.onEndEdit.AddListener(OnInputFieldValueChanged);
                    _uiEventHooked = true;
                    break;

                case Slider slider:
                    slider.onValueChanged.AddListener(OnSliderValueChanged);
                    _uiEventHooked = true;
                    break;

                case Toggle toggle:
                    toggle.onValueChanged.AddListener(OnToggleValueChanged);
                    _uiEventHooked = true;
                    break;

                default:
                    Debug.LogWarning(
                        $"[{nameof(DataBinding)}] Two-Way binding is not supported for component type '{_targetComponent.GetType().Name}'.");
                    break;
            }
        }

        private void UnhookUIEvents()
        {
            if (!_uiEventHooked) return;

            switch (_targetComponent)
            {
                case InputField inputField:
                    inputField.onEndEdit.RemoveListener(OnInputFieldValueChanged);
                    break;
                case TMP_InputField tmpInputField:
                    tmpInputField.onEndEdit.RemoveListener(OnInputFieldValueChanged);
                    break;
                case Slider slider:
                    slider.onValueChanged.RemoveListener(OnSliderValueChanged);
                    break;
                case Toggle toggle:
                    toggle.onValueChanged.RemoveListener(OnToggleValueChanged);
                    break;
            }

            _uiEventHooked = false;
        }

        private void OnInputFieldValueChanged(string newValue)
        {
            PushValueToViewModel(newValue);
        }

        private void OnSliderValueChanged(float newValue)
        {
            PushValueToViewModel(newValue);
        }

        private void OnToggleValueChanged(bool newValue)
        {
            PushValueToViewModel(newValue);
        }

        private void PushValueToViewModel(object uiValue)
        {
            if (_mode != BindingMode.TwoWay) return;

            try
            {
                _isUpdatingFromUI = true;

                object vmTypeAdjusted = _converter != null
                    ? _converter.ConvertBack(uiValue, ReflectionUtility.GetMemberType(_vmMemberChain[^1]))
                    : ChangeType(uiValue, ReflectionUtility.GetMemberType(_vmMemberChain[^1]));

                ReflectionUtility.SetNestedValue(_viewModelBehaviour, _vmMemberChain, vmTypeAdjusted);
            }
            catch (Exception ex)
            {
                Debug.LogError(
                    $"[{nameof(DataBinding)}] Failed to push value back to View-Model on '{name}': {ex}");
            }
            finally
            {
                _isUpdatingFromUI = false;
            }
        }

        #endregion

        #region Helpers

        private static object ChangeType(object value, Type targetType)
        {
            if (value == null) return null;

            // Handle nullable types.
            var underlying = Nullable.GetUnderlyingType(targetType) ?? targetType;
            if (underlying.IsEnum && value is string s)
                return Enum.Parse(underlying, s, ignoreCase: true);

            // Use built-in conversion where possible.
            return System.Convert.ChangeType(value, underlying);
        }

#if UNITY_EDITOR
        // Editor-only helper to validate bindings without entering play-mode.
        private void OnValidate()
        {
            if (!Application.isPlaying) return;
            try
            {
                ValidateSetup();
                CacheReflection();
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[{nameof(DataBinding)}] Validation error on '{name}': {ex.Message}");
            }
        }
#endif

        #endregion
    }
}
```