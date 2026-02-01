```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Tokens
{
    /// <summary>
    ///     Exposes high-level operations for fungible and non-fungible tokens. 
    ///     Internally delegates to strategy implementations that understand the
    ///     concrete token standard (e.g. ERC-20-like, ERC-721-like).
    ///     
    ///     TokenService is designed to be thread-safe, idempotent where possible,
    ///     and fully asynchronous.  
    ///     
    ///     In addition to command-side operations, the service publishes domain
    ///     events through an <see cref="IEventBus"/>, allowing downstream modules
    ///     (wallet UI, indexer, governance, etc.) to react in an event-driven way.
    /// </summary>
    public sealed partial class TokenService : ITokenService, IObserver<BlockMinedEvent>, IDisposable
    {
        private readonly ITokenRepository           _repository;
        private readonly IEventBus                  _eventBus;
        private readonly ITokenStandardFactory      _standardFactory;
        private readonly ILogger<TokenService>      _logger;
        
        //   Extremely light-weight cache for hot token instances.
        private readonly ConcurrentDictionary<TokenId, ITokenStandardStrategy> _strategies = new();

        //   Used to avoid double-registration with the event bus.
        private int _isSubscribedToBlockEvents;

        public TokenService(
            ITokenRepository repository,
            IEventBus eventBus,
            ITokenStandardFactory standardFactory,
            ILogger<TokenService> logger)
        {
            _repository       = repository  ?? throw new ArgumentNullException(nameof(repository));
            _eventBus         = eventBus    ?? throw new ArgumentNullException(nameof(eventBus));
            _standardFactory  = standardFactory ?? throw new ArgumentNullException(nameof(standardFactory));
            _logger           = logger      ?? throw new ArgumentNullException(nameof(logger));
        }

        #region ITokenService

        public async Task<TokenId> CreateTokenAsync(CreateTokenRequest request, CancellationToken ct = default)
        {
            ArgumentNullException.ThrowIfNull(request);

            var tokenId = TokenId.New();
            
            ITokenStandardStrategy strategy = _standardFactory.Create(request.Standard, tokenId, request.Metadata);

            //  Save token metadata & initial state.
            await _repository.AddTokenAsync(strategy.Descriptor, ct).ConfigureAwait(false);
            _strategies[tokenId] = strategy;

            _eventBus.Publish(new TokenCreatedEvent(tokenId, request.Owner, request.Standard));

            _logger.LogInformation("Created token {TokenId} ({Standard}) by {Owner}", tokenId, request.Standard, request.Owner);
            EnsureBlockSubscription();
            return tokenId;
        }

        public Task MintAsync(TokenId tokenId, Address to, ulong amount, CancellationToken ct = default)
            => ExecuteAsync(tokenId, strategy => strategy.MintAsync(to, amount, ct), ct);

        public Task BurnAsync(TokenId tokenId, Address from, ulong amount, CancellationToken ct = default)
            => ExecuteAsync(tokenId, strategy => strategy.BurnAsync(from, amount, ct), ct);

        public Task TransferAsync(TokenId tokenId, Address from, Address to, ulong amount, CancellationToken ct = default)
            => ExecuteAsync(tokenId, strategy => strategy.TransferAsync(from, to, amount, ct), ct);

        public Task<ulong> GetBalanceAsync(TokenId tokenId, Address address, CancellationToken ct = default)
            => ExecuteAsync(tokenId, strategy => strategy.GetBalanceAsync(address, ct), ct);

        public async Task<TokenDescriptor?> GetTokenDescriptorAsync(TokenId tokenId, CancellationToken ct = default)
        {
            if (_strategies.TryGetValue(tokenId, out var existing))
                return existing.Descriptor;

            var descriptor = await _repository.TryGetTokenAsync(tokenId, ct).ConfigureAwait(false);
            return descriptor;
        }

        #endregion

        #region Observer Pattern – listen to chain events
        
        private void EnsureBlockSubscription()
        {
            if (Interlocked.Exchange(ref _isSubscribedToBlockEvents, 1) == 1) return;
            _eventBus.Subscribe<BlockMinedEvent>(this);
        }

        public void OnCompleted() { /* noop */ }

        public void OnError(Exception error)
            => _logger.LogError(error, "Error while observing BlockMined events.");

        public async void OnNext(BlockMinedEvent value)
        {
            try
            {
                // Persist any dirty balances periodically to durable storage
                foreach (var strategy in _strategies.Values)
                    await strategy.CommitAsync().ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to flush token state after block {BlockHeight}", value.Height);
            }
        }

        #endregion

        #region Helper Methods

        private async Task<T> ExecuteAsync<T>(TokenId tokenId, Func<ITokenStandardStrategy, Task<T>> action, CancellationToken ct)
        {
            ITokenStandardStrategy strategy = await ResolveStrategyAsync(tokenId, ct).ConfigureAwait(false);
            T result = await action(strategy).ConfigureAwait(false);
            return result;
        }

        private async Task<ITokenStandardStrategy> ResolveStrategyAsync(TokenId tokenId, CancellationToken ct)
        {
            if (_strategies.TryGetValue(tokenId, out var existing))
                return existing;

            TokenDescriptor descriptor = await _repository
                .TryGetTokenAsync(tokenId, ct)
                .ConfigureAwait(false)
                ?? throw new TokenNotFoundException(tokenId);

            var strategy = _standardFactory.Create(
                descriptor.Standard,
                descriptor.TokenId,
                descriptor.Metadata);

            _strategies[tokenId] = strategy;
            return strategy;
        }

        #endregion

        public void Dispose()
        {
            _eventBus.Unsubscribe<BlockMinedEvent>(this);
            foreach (var strategy in _strategies.Values)
                (strategy as IDisposable)?.Dispose();
        }
    }

    #region Domain Primitives & DTOs

    public readonly record struct TokenId(Guid Value)
    {
        public static TokenId New() => new(Guid.NewGuid());
        public override string ToString() => Value.ToString("N");
    }

    public readonly record struct Address(string Value)
    {
        public static readonly Address None = new("0x0");
        public override string ToString() => Value;
    }

    public sealed class CreateTokenRequest
    {
        public required TokenStandard Standard { get; init; }
        public required Address Owner          { get; init; }
        public required IReadOnlyDictionary<string, string> Metadata { get; init; }
    }

    #endregion

    #region Events

    public sealed record TokenCreatedEvent(TokenId TokenId, Address Owner, TokenStandard Standard);
    public sealed record BlockMinedEvent(long Height);

    #endregion

    #region Interfaces

    public interface ITokenService
    {
        Task<TokenId> CreateTokenAsync(CreateTokenRequest request, CancellationToken ct = default);
        Task MintAsync(TokenId tokenId, Address to, ulong amount, CancellationToken ct = default);
        Task BurnAsync(TokenId tokenId, Address from, ulong amount, CancellationToken ct = default);
        Task TransferAsync(TokenId tokenId, Address from, Address to, ulong amount, CancellationToken ct = default);
        Task<ulong> GetBalanceAsync(TokenId tokenId, Address address, CancellationToken ct = default);
        Task<TokenDescriptor?> GetTokenDescriptorAsync(TokenId tokenId, CancellationToken ct = default);
    }

    public interface IEventBus
    {
        void Publish<TEvent>(TEvent ev);
        void Subscribe<TEvent>(IObserver<TEvent> observer);
        void Unsubscribe<TEvent>(IObserver<TEvent> observer);
    }

    public interface ITokenRepository
    {
        Task AddTokenAsync(TokenDescriptor descriptor, CancellationToken ct);
        Task<TokenDescriptor?> TryGetTokenAsync(TokenId id, CancellationToken ct);
        Task PersistBalanceAsync(TokenId id, Address address, ulong balance, CancellationToken ct);
        Task<ulong?> TryGetBalanceAsync(TokenId id, Address address, CancellationToken ct);
    }
    
    public interface ITokenStandardFactory
    {
        ITokenStandardStrategy Create(TokenStandard standard, TokenId id, IReadOnlyDictionary<string, string> metadata);
    }

    public interface ITokenStandardStrategy : IDisposable
    {
        TokenDescriptor Descriptor { get; }
        Task MintAsync(Address to, ulong amount, CancellationToken ct);
        Task BurnAsync(Address from, ulong amount, CancellationToken ct);
        Task TransferAsync(Address from, Address to, ulong amount, CancellationToken ct);
        Task<ulong> GetBalanceAsync(Address address, CancellationToken ct);
        Task CommitAsync();
    }

    #endregion

    #region Strategy Implementations (Simplified Examples)

    internal sealed class FungibleTokenStrategy : ITokenStandardStrategy
    {
        private readonly TokenDescriptor                        _descriptor;
        private readonly ITokenRepository                       _repository;
        private readonly IEventBus                              _eventBus;
        private readonly ConcurrentDictionary<Address, ulong>   _balances = new();
        private readonly ILogger<FungibleTokenStrategy>         _logger;

        public FungibleTokenStrategy(
            TokenDescriptor descriptor,
            ITokenRepository repository,
            IEventBus eventBus,
            ILogger<FungibleTokenStrategy> logger)
        {
            _descriptor = descriptor;
            _repository = repository;
            _eventBus   = eventBus;
            _logger     = logger;
        }

        public TokenDescriptor Descriptor => _descriptor;

        public async Task MintAsync(Address to, ulong amount, CancellationToken ct)
        {
            _balances.AddOrUpdate(to, amount, (_, existing) => checked(existing + amount));
            _eventBus.Publish(new TokenMintedEvent(_descriptor.TokenId, to, amount));
            await Task.CompletedTask;
        }

        public async Task BurnAsync(Address from, ulong amount, CancellationToken ct)
        {
            if (!_balances.TryGetValue(from, out var current) || current < amount)
                throw new TokenBalanceException(_descriptor.TokenId, from, current, amount);

            _balances[from] = current - amount;
            _eventBus.Publish(new TokenBurnedEvent(_descriptor.TokenId, from, amount));
            await Task.CompletedTask;
        }

        public async Task TransferAsync(Address from, Address to, ulong amount, CancellationToken ct)
        {
            if (!_balances.TryGetValue(from, out var current) || current < amount)
                throw new TokenBalanceException(_descriptor.TokenId, from, current, amount);

            _balances[from] = current - amount;
            _balances.AddOrUpdate(to, amount, (_, existing) => checked(existing + amount));
            _eventBus.Publish(new TokenTransferredEvent(_descriptor.TokenId, from, to, amount));
            await Task.CompletedTask;
        }

        public Task<ulong> GetBalanceAsync(Address address, CancellationToken ct)
        {
            _balances.TryGetValue(address, out var bal);
            return Task.FromResult(bal);
        }

        public async Task CommitAsync()
        {
            foreach (var (addr, bal) in _balances)
            {
                await _repository.PersistBalanceAsync(_descriptor.TokenId, addr, bal, CancellationToken.None);
            }
        }

        public void Dispose()
        {
            // Commit pending balances on dispose for safety.
            CommitAsync().GetAwaiter().GetResult();
        }
    }

    #endregion

    #region Factory

    internal sealed class TokenStandardFactory : ITokenStandardFactory
    {
        private readonly ITokenRepository  _repository;
        private readonly IEventBus         _eventBus;
        private readonly ILoggerFactory    _loggerFactory;

        public TokenStandardFactory(
            ITokenRepository repository,
            IEventBus eventBus,
            ILoggerFactory loggerFactory)
        {
            _repository    = repository;
            _eventBus      = eventBus;
            _loggerFactory = loggerFactory;
        }

        public ITokenStandardStrategy Create(TokenStandard standard, TokenId id, IReadOnlyDictionary<string, string> metadata)
        {
            TokenDescriptor descriptor = new(id, standard, metadata);
            return standard switch
            {
                TokenStandard.Fungible => new FungibleTokenStrategy(
                    descriptor, _repository, _eventBus, 
                    _loggerFactory.CreateLogger<FungibleTokenStrategy>()),

                // Additional standards (ERC721-like, soulbound, etc.) would be plugged in here.
                _ => throw new NotSupportedException($"Token standard '{standard}' is not supported.")
            };
        }
    }

    #endregion

    #region Errors

    [SuppressMessage("ReSharper", "MemberCanBeMadeStatic.Global")]
    public sealed class TokenNotFoundException : Exception
    {
        public TokenNotFoundException(TokenId id)
            : base($"Token '{id}' not found.")
        { }
    }

    public sealed class TokenBalanceException : Exception
    {
        public TokenBalanceException(TokenId id, Address holder, ulong currentBalance, ulong requestedAmount)
            : base($"Insufficient balance for token '{id}' holder '{holder}'. Current={currentBalance} Requested={requestedAmount}")
        { }
    }

    #endregion

    #region Additional Domain Objects

    public sealed record TokenDescriptor(
        TokenId TokenId,
        TokenStandard Standard,
        IReadOnlyDictionary<string, string> Metadata);

    public enum TokenStandard : byte
    {
        Fungible = 0,
        NonFungible = 1,
        Soulbound = 2
    }

    public sealed record TokenMintedEvent(TokenId TokenId, Address To, ulong Amount);
    public sealed record TokenBurnedEvent(TokenId TokenId, Address From, ulong Amount);
    public sealed record TokenTransferredEvent(TokenId TokenId, Address From, Address To, ulong Amount);

    #endregion
}
```