using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;

namespace TycoonVerse.Application.Common
{
    /// <summary>
    /// Thread-safe, lightweight IoC container used across the application layer.
    /// Provides deterministic service registration/lookup without relying on 3rd-party
    /// frameworks (important for mobile size constraints and AOT builds).
    /// </summary>
    /// <remarks>
    /// Although Unity already ships with its own container, we keep a pure-C#
    /// implementation at the application boundary so domain libraries remain
    /// platform-agnostic and unit-test friendly.
    /// </remarks>
    public sealed class ServiceLocator : IDisposable
    {
        #region Singleton bootstrap

        private static readonly Lazy<ServiceLocator> _instance =
            new Lazy<ServiceLocator>(() => new ServiceLocator());

        /// <summary>
        /// Global access point. Meant to be called only from composition root
        /// or during unit test bootstrap.
        /// </summary>
        public static ServiceLocator Instance => _instance.Value;

        #endregion

        private readonly ConcurrentDictionary<Type, ServiceDescriptor> _descriptors =
            new ConcurrentDictionary<Type, ServiceDescriptor>();

        // Keep track of disposables so we can cleanly shut down the container.
        private readonly List<IDisposable> _trackedDisposables = new List<IDisposable>();

        private readonly ReaderWriterLockSlim _lock = new ReaderWriterLockSlim();

        private bool _disposed;

        #region Registration

        /// <summary>
        /// Registers <typeparamref name="TService"/> with a concrete
        /// <typeparamref name="TImplementation"/>.
        /// </summary>
        public void Register<TService, TImplementation>(
            Lifetime lifetime = Lifetime.Singleton)
            where TService : class
            where TImplementation : class, TService
        {
            EnsureNotDisposed();

            var descriptor = ServiceDescriptor.ForType(
                typeof(TService), typeof(TImplementation), lifetime);

            AddDescriptor(descriptor);
        }

        /// <summary>
        /// Registers a factory delegate to lazily build <typeparamref name="TService"/>.
        /// Useful when explicit runtime arguments are needed.
        /// </summary>
        public void Register<TService>(
            Func<ServiceLocator, TService> factory,
            Lifetime lifetime = Lifetime.Singleton)
            where TService : class
        {
            EnsureNotDisposed();

            if (factory is null) throw new ArgumentNullException(nameof(factory));

            var descriptor = ServiceDescriptor.ForFactory(
                typeof(TService), (sl) => factory(sl), lifetime);

            AddDescriptor(descriptor);
        }

        /// <summary>
        /// Registers a pre-constructed instance as a singleton.
        /// </summary>
        public void RegisterInstance<TService>(TService instance)
            where TService : class
        {
            EnsureNotDisposed();

            if (instance is null) throw new ArgumentNullException(nameof(instance));

            var descriptor = ServiceDescriptor.ForInstance(typeof(TService), instance);

            AddDescriptor(descriptor);
        }

        private void AddDescriptor(ServiceDescriptor descriptor)
        {
            if (!_descriptors.TryAdd(descriptor.ServiceType, descriptor))
            {
                throw new InvalidOperationException(
                    $"Service '{descriptor.ServiceType.FullName}' is already registered.");
            }
        }

        #endregion

        #region Resolution

        public TService Resolve<TService>() where TService : class
            => (TService)Resolve(typeof(TService));

        public object Resolve(Type serviceType)
        {
            EnsureNotDisposed();

            if (!_descriptors.TryGetValue(serviceType, out var descriptor))
            {
                throw new InvalidOperationException(
                    $"Service '{serviceType.FullName}' has not been registered.");
            }

            return descriptor.GetInstance(this);
        }

        /// <summary>
        /// Creates a new instance using constructor injection.
        /// Chooses the constructor with the most parameters it can fully satisfy.
        /// </summary>
        internal object Create(Type implementationType)
        {
            // Discover constructors ordered by parameter count (DESC).
            var candidates = implementationType
                .GetConstructors(BindingFlags.Public | BindingFlags.Instance)
                .OrderByDescending(c => c.GetParameters().Length);

            foreach (var ctor in candidates)
            {
                try
                {
                    var args = ctor.GetParameters()
                                    .Select(p => Resolve(p.ParameterType))
                                    .ToArray();

                    var instance = Activator.CreateInstance(implementationType, args);
                    TrackDisposable(instance);
                    return instance;
                }
                catch (InvalidOperationException)
                {
                    // Dependency chain not fully satisfied; try next constructor.
                }
            }

            throw new InvalidOperationException(
                $"Unable to create instance of '{implementationType.FullName}'. " +
                "Make sure all constructor dependencies are registered.");
        }

        #endregion

        #region Disposal & Maintenance

        /// <summary>
        /// Clears the container, disposing tracked singletons.
        /// Primarily intended for integration tests or application shutdown.
        /// </summary>
        public void Reset()
        {
            EnsureNotDisposed();

            _lock.EnterWriteLock();
            try
            {
                foreach (var disposable in _trackedDisposables)
                {
                    disposable.Dispose();
                }

                _trackedDisposables.Clear();
                _descriptors.Clear();
            }
            finally
            {
                _lock.ExitWriteLock();
            }
        }

        private void TrackDisposable(object instance)
        {
            if (instance is IDisposable disposable)
            {
                lock (_trackedDisposables)
                {
                    _trackedDisposables.Add(disposable);
                }
            }
        }

        private void EnsureNotDisposed()
        {
            if (_disposed)
                throw new ObjectDisposedException(nameof(ServiceLocator));
        }

        public void Dispose()
        {
            if (_disposed) return;

            Reset();
            _lock.Dispose();
            _disposed = true;
        }

        #endregion

        #region Nested types

        /// <summary>
        /// Indicates how the container handles object lifetime.
        /// </summary>
        public enum Lifetime
        {
            Singleton,
            Transient
        }

        /// <summary>
        /// Internal data-structure that maps a service type to its creation strategy.
        /// </summary>
        private sealed class ServiceDescriptor
        {
            private readonly Type _implementationType;
            private readonly Func<ServiceLocator, object> _factory;
            private readonly Lifetime _lifetime;
            private readonly object _instanceLock = new object();

            public Type ServiceType { get; }
            private object _cachedInstance;

            private ServiceDescriptor(
                Type serviceType,
                Type implementationType,
                Func<ServiceLocator, object> factory,
                Lifetime lifetime,
                object prebuilt)
            {
                ServiceType = serviceType;
                _implementationType = implementationType;
                _factory = factory;
                _lifetime = lifetime;
                _cachedInstance = prebuilt;
            }

            public static ServiceDescriptor ForType(
                Type serviceType,
                Type implementationType,
                Lifetime lifetime)
                => new ServiceDescriptor(serviceType, implementationType, null, lifetime, null);

            public static ServiceDescriptor ForFactory(
                Type serviceType,
                Func<ServiceLocator, object> factory,
                Lifetime lifetime)
                => new ServiceDescriptor(serviceType, null, factory, lifetime, null);

            public static ServiceDescriptor ForInstance(
                Type serviceType,
                object instance)
                => new ServiceDescriptor(serviceType, null, null, Lifetime.Singleton, instance);

            public object GetInstance(ServiceLocator locator)
            {
                if (_lifetime == Lifetime.Transient)
                {
                    return CreateInstance(locator);
                }

                if (_cachedInstance != null) return _cachedInstance;

                lock (_instanceLock)
                {
                    if (_cachedInstance == null)
                    {
                        _cachedInstance = CreateInstance(locator);
                    }
                }

                return _cachedInstance;
            }

            private object CreateInstance(ServiceLocator locator)
            {
                if (_factory != null)
                {
                    return _factory(locator);
                }

                if (_implementationType == null)
                {
                    throw new InvalidOperationException(
                        $"No factory or implementation type specified for '{ServiceType.FullName}'.");
                }

                return locator.Create(_implementationType);
            }
        }

        #endregion

        // Prevent outside instantiation.
        private ServiceLocator() { }
    }
}