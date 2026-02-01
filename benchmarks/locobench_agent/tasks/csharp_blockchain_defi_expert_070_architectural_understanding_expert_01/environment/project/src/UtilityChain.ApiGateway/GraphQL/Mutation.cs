```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright file="Mutation.cs">
//   Copyright © UtilityChain Contributors.  
//   This source code is licensed under the MIT license found in the root directory of this project.
// </copyright>
// --------------------------------------------------------------------------------------------------------------------

using System.ComponentModel.DataAnnotations;
using HotChocolate;
using HotChocolate.Execution;
using HotChocolate.Resolvers;
using HotChocolate.Types;
using Microsoft.Extensions.Logging;
using UtilityChain.Core.Domain.Consensus;
using UtilityChain.Core.Domain.Governance;
using UtilityChain.Core.Domain.Staking;
using UtilityChain.Core.Domain.Tokens;
using UtilityChain.Core.Domain.Wallets;
using UtilityChain.Core.SharedKernel;
using UtilityChain.Core.SharedKernel.Events;

namespace UtilityChain.ApiGateway.GraphQL;

/// <summary>
///     Exposes write-operations to the GraphQL schema.  
///     All methods are thin façade calls to the underlying domain services;  
///     they perform basic argument validation, translate domain-level exceptions to GraphQL-friendly
///     <see cref="QueryException"/> instances, and publish relevant notifications to the in-process event bus.
/// </summary>
public sealed class Mutation
{
    #region Wallet

    /// <summary>
    ///     Creates a new wallet protected by the supplied <see cref="CreateWalletInput.Password"/>.
    /// </summary>
    [GraphQLDescription("Creates a new wallet protected by the supplied password.")]
    public async Task<WalletDto> CreateWalletAsync(
        CreateWalletInput            input,
        [Service] IWalletService     walletService,
        [Service] IEventPublisher    eventPublisher,
        [Service] ILogger<Mutation>  logger,
        CancellationToken            ct)
    {
        ArgumentNullException.ThrowIfNull(input);
        Validate(input);

        try
        {
            var wallet = await walletService.CreateAsync(input.Password, ct)
                                            .ConfigureAwait(false);

            // Publish an in-process event so that other modules (e.g. notification, analytics) can react.
            await eventPublisher.PublishAsync(new WalletCreatedDomainEvent(wallet.Id), ct);

            return WalletDto.FromDomain(wallet);
        }
        catch (DomainException ex)
        {
            logger.LogError(ex, "Failed to create wallet.");
            throw ToGraphQlError(ex, "Could not create wallet.");
        }
    }

    #endregion

    #region Tokens

    /// <summary>
    ///     Transfers fungible tokens from one wallet to another.
    /// </summary>
    [GraphQLDescription("Transfers fungible tokens from one wallet to another.")]
    public async Task<TransactionResultDto> TransferTokenAsync(
        TransferTokenInput           input,
        [Service] ITokenService      tokenService,
        [Service] IEventPublisher    eventPublisher,
        [Service] ILogger<Mutation>  logger,
        CancellationToken            ct)
    {
        ArgumentNullException.ThrowIfNull(input);
        Validate(input);

        try
        {
            var result = await tokenService.TransferAsync(
                                         input.TokenSymbol,
                                         input.FromWalletId,
                                         input.ToWalletId,
                                         input.Amount,
                                         ct)
                                   .ConfigureAwait(false);

            await eventPublisher.PublishAsync(
                new TokenTransferredDomainEvent(
                    input.TokenSymbol,
                    input.FromWalletId,
                    input.ToWalletId,
                    input.Amount,
                    result.TransactionHash),
                ct);

            return TransactionResultDto.FromDomain(result);
        }
        catch (DomainException ex)
        {
            logger.LogError(ex, "Failed to transfer token.");
            throw ToGraphQlError(ex, "Could not transfer token.");
        }
    }

    #endregion

    #region Staking

    /// <summary>
    ///     Stakes tokens on behalf of the specified wallet.
    /// </summary>
    [GraphQLDescription("Locks tokens for staking and returns the resulting stake information.")]
    public async Task<StakeResultDto> StakeTokensAsync(
        StakeTokensInput             input,
        [Service] IStakingService    stakingService,
        [Service] ILogger<Mutation>  logger,
        CancellationToken            ct)
    {
        ArgumentNullException.ThrowIfNull(input);
        Validate(input);

        try
        {
            var stake = await stakingService.StakeAsync(
                                           input.WalletId,
                                           input.Amount,
                                           input.Duration,
                                           ct)
                                     .ConfigureAwait(false);

            return StakeResultDto.FromDomain(stake);
        }
        catch (DomainException ex)
        {
            logger.LogError(ex, "Failed to stake tokens.");
            throw ToGraphQlError(ex, "Could not stake tokens.");
        }
    }

    #endregion

    #region Consensus

    /// <summary>
    ///     Registers a validator node and returns the validator identifier.
    /// </summary>
    [GraphQLDescription("Registers a validator node and returns the validator identifier.")]
    public async Task<ValidatorRegistrationDto> RegisterValidatorAsync(
        RegisterValidatorInput         input,
        [Service] IConsensusService    consensusService,
        [Service] ILogger<Mutation>    logger,
        CancellationToken              ct)
    {
        ArgumentNullException.ThrowIfNull(input);
        Validate(input);

        try
        {
            var validator = await consensusService.RegisterValidatorAsync(
                                                   input.WalletId,
                                                   input.NodeId,
                                                   input.StakeAmount,
                                                   ct)
                                             .ConfigureAwait(false);

            return ValidatorRegistrationDto.FromDomain(validator);
        }
        catch (DomainException ex)
        {
            logger.LogError(ex, "Failed to register validator.");
            throw ToGraphQlError(ex, "Could not register validator.");
        }
    }

    #endregion

    #region Governance

    /// <summary>
    ///     Casts a governance vote.
    /// </summary>
    [GraphQLDescription("Casts a governance vote.")]
    public async Task<GovVoteResultDto> CastVoteAsync(
        CastVoteInput                 input,
        [Service] IGovernanceService  governanceService,
        [Service] ILogger<Mutation>   logger,
        CancellationToken             ct)
    {
        ArgumentNullException.ThrowIfNull(input);
        Validate(input);

        try
        {
            var result = await governanceService.CastVoteAsync(
                                               input.ProposalId,
                                               input.WalletId,
                                               input.Weight,
                                               input.Option,
                                               ct)
                                         .ConfigureAwait(false);

            return GovVoteResultDto.FromDomain(result);
        }
        catch (DomainException ex)
        {
            logger.LogError(ex, "Failed to cast vote.");
            throw ToGraphQlError(ex, "Could not cast vote.");
        }
    }

    #endregion

    #region Helpers

    /// <summary>
    ///     Ensures the given model is valid according to data-annotation attributes.
    /// </summary>
    private static void Validate(object model)
    {
        var ctx  = new ValidationContext(model);
        var errs = new List<ValidationResult>();

        if (!Validator.TryValidateObject(model, ctx, errs, validateAllProperties: true))
        {
            var message = string.Join(" | ", errs.Select(e => e.ErrorMessage));
            throw new QueryException(ErrorBuilder.New()
                                                 .SetMessage(message)
                                                 .SetCode("VALIDATION_ERROR")
                                                 .Build());
        }
    }

    /// <summary>
    ///     Converts a domain exception to a <see cref="QueryException"/> preserving the underlying message but adding a
    ///     GraphQL-friendly error code.
    /// </summary>
    private static QueryException ToGraphQlError(Exception ex, string friendlyMessage)
    {
        return new QueryException(ErrorBuilder.New()
                                              .SetMessage(friendlyMessage)
                                              .SetCode("DOMAIN_ERROR")
                                              .SetExtension("details", ex.Message)
                                              .Build());
    }

    #endregion
}

#region Input-Types

public sealed record CreateWalletInput(
    [property: Required(ErrorMessage = "Password is required.")]
    string Password);

public sealed record TransferTokenInput(
    [property: Required] string TokenSymbol,
    [property: Required] Ulid   FromWalletId,
    [property: Required] Ulid   ToWalletId,
    [property: Range(0.00000001, double.MaxValue, ErrorMessage = "Amount must be positive.")]
    decimal                    Amount);

public sealed record StakeTokensInput(
    [property: Required] Ulid   WalletId,
    [property: Range(1, double.MaxValue)] decimal Amount,
    [property: Range(1, 3650)]               int  Duration); // days

public sealed record RegisterValidatorInput(
    [property: Required] Ulid   WalletId,
    [property: Required] Guid   NodeId,
    [property: Range(1, double.MaxValue)] decimal StakeAmount);

public sealed record CastVoteInput(
    [property: Required] Ulid   ProposalId,
    [property: Required] Ulid   WalletId,
    [property: Range(1, double.MaxValue)] decimal Weight,
    [property: Required] VoteOption Option);

#endregion

#region DTO-Types

/// <summary>
///     DTO returned when a wallet is created.
/// </summary>
public sealed record WalletDto(Ulid Id, string Address)
{
    public static WalletDto FromDomain(Wallet wallet)
        => new(wallet.Id, wallet.Address);
}

/// <summary>
///     DTO returned when a transfer, contract call, or any ledger-mutating operation succeeds.
/// </summary>
public sealed record TransactionResultDto(string TransactionHash, DateTimeOffset Timestamp)
{
    public static TransactionResultDto FromDomain(TokenTransferResult result)
        => new(result.TransactionHash, result.Timestamp);
}

/// <summary>
///     DTO returned after a staking operation.
/// </summary>
public sealed record StakeResultDto(
    Ulid           StakeId,
    Ulid           WalletId,
    decimal        Amount,
    int            Duration,
    DateTimeOffset StartTime)
{
    public static StakeResultDto FromDomain(Stake stake)
        => new(stake.Id, stake.WalletId, stake.Amount, stake.Duration, stake.StartTime);
}

/// <summary>
///     DTO returned after anyone registers as validator.
/// </summary>
public sealed record ValidatorRegistrationDto(Ulid ValidatorId, Guid NodeId)
{
    public static ValidatorRegistrationDto FromDomain(Validator validator)
        => new(validator.Id, validator.NodeId);
}

/// <summary>
///     DTO returned after casting a vote in on-chain governance.
/// </summary>
public sealed record GovVoteResultDto(Ulid VoteId, Ulid ProposalId, DateTimeOffset Timestamp)
{
    public static GovVoteResultDto FromDomain(Vote vote)
        => new(vote.Id, vote.ProposalId, vote.Timestamp);
}

#endregion

#region Enumerations

/// <summary>
///     Options that can be chosen when casting a vote.
/// </summary>
public enum VoteOption
{
    Yes,
    No,
    Abstain
}

#endregion
```