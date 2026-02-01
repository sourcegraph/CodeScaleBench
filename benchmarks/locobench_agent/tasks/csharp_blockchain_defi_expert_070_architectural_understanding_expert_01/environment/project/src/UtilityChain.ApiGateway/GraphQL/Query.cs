```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.ApiGateway/GraphQL/Query.cs

using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using HotChocolate;
using HotChocolate.Types;
using HotChocolate.Execution;
using Microsoft.Extensions.Logging;
using UtilityChain.Core.Abstractions.Chain;
using UtilityChain.Core.Abstractions.Governance;
using UtilityChain.Core.Abstractions.Staking;

namespace UtilityChain.ApiGateway.GraphQL;

/// <summary>
/// Root GraphQL query type for the UtilityChain API-Gateway.
/// All read-only endpoints exposed by the monolith are federated here.
/// </summary>
[ExtendObjectType(Name = "Query")]
public sealed class Query
{
    private readonly IChainQueryService   _chain;
    private readonly IStakingService      _staking;
    private readonly IGovernanceService   _governance;
    private readonly ILogger<Query>       _logger;

    public Query(
        IChainQueryService  chain,
        IStakingService     staking,
        IGovernanceService  governance,
        ILogger<Query>      logger)
    {
        _chain      = chain     ?? throw new ArgumentNullException(nameof(chain));
        _staking    = staking   ?? throw new ArgumentNullException(nameof(staking));
        _governance = governance?? throw new ArgumentNullException(nameof(governance));
        _logger     = logger    ?? throw new ArgumentNullException(nameof(logger));
    }

    #region ───────────────────────── Blockchain Queries ──────────────────────────

    [GraphQLDescription("Returns a single block by its hash.")]
    public async Task<BlockDto?> GetBlockAsync(
        string hash,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(hash))
        {
            throw new QueryException(
                ErrorBuilder.New()
                    .SetMessage("Block hash must be provided.")
                    .SetCode("BLOCK_HASH_REQUIRED")
                    .Build());
        }

        var block = await _chain.GetBlockByHashAsync(hash, cancellationToken);
        if (block is null)
        {
            _logger.LogWarning("Block with hash '{Hash}' not found.", hash);
            throw new QueryException(
                ErrorBuilder.New()
                    .SetMessage($"Block with hash '{hash}' not found.")
                    .SetCode("BLOCK_NOT_FOUND")
                    .Build());
        }

        return block;
    }

    [UsePaging]
    [UseSorting]
    [UseFiltering]
    [GraphQLDescription("Returns the latest blocks ordered by descending height.")]
    public Task<IReadOnlyList<BlockDto>> GetLatestBlocksAsync(
        int take = 10,
        CancellationToken cancellationToken = default)
    {
        if (take is < 1 or > 1000)
        {
            throw new QueryException(
                ErrorBuilder.New()
                    .SetMessage("The 'take' argument must be between 1 and 1000.")
                    .SetCode("TAKE_OUT_OF_RANGE")
                    .Build());
        }

        return _chain.GetLatestBlocksAsync(take, cancellationToken);
    }

    [GraphQLDescription("Returns the asset balance for a given wallet address.")]
    public Task<decimal> GetAccountBalanceAsync(
        string address,
        string? assetSymbol = null,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(address))
        {
            throw new QueryException(
                ErrorBuilder.New()
                    .SetMessage("Wallet address must be provided.")
                    .SetCode("ADDRESS_REQUIRED")
                    .Build());
        }

        return _chain.GetAssetBalanceAsync(address, assetSymbol, cancellationToken);
    }

    #endregion

    #region ───────────────────────── Staking Queries ────────────────────────────

    [GraphQLDescription("Returns a snapshot of the current staking state.")]
    public Task<StakingSummaryDto> GetStakingSummaryAsync(
        CancellationToken cancellationToken = default)
        => _staking.GetStakingSummaryAsync(cancellationToken);

    #endregion

    #region ──────────────────────── Governance Queries ──────────────────────────

    [GraphQLDescription("Returns a single governance proposal by its identifier.")]
    public async Task<ProposalDto?> GetGovernanceProposalAsync(
        Guid proposalId,
        CancellationToken cancellationToken = default)
    {
        if (proposalId == Guid.Empty)
        {
            throw new QueryException(
                ErrorBuilder.New()
                    .SetMessage("Proposal identifier must be provided.")
                    .SetCode("PROPOSAL_ID_REQUIRED")
                    .Build());
        }

        var proposal = await _governance.GetProposalAsync(proposalId, cancellationToken);
        if (proposal is null)
        {
            throw new QueryException(
                ErrorBuilder.New()
                    .SetMessage($"Proposal '{proposalId}' not found.")
                    .SetCode("PROPOSAL_NOT_FOUND")
                    .Build());
        }

        return proposal;
    }

    [UsePaging]
    [GraphQLDescription("Returns all open governance proposals.")]
    public Task<IReadOnlyList<ProposalDto>> GetOpenGovernanceProposalsAsync(
        CancellationToken cancellationToken = default)
        => _governance.GetOpenProposalsAsync(cancellationToken);

    #endregion

    #region ──────────────────────── Transaction Queries ─────────────────────────

    [GraphQLDescription("Searches for transactions that match the specified filter.")]
    [UsePaging]
    public Task<IReadOnlyList<TransactionDto>> SearchTransactionsAsync(
        TransactionSearchInput input,
        int take = 50,
        CancellationToken cancellationToken = default)
    {
        if (input is null)
        {
            throw new QueryException(
                ErrorBuilder.New()
                    .SetMessage("A search input object must be provided.")
                    .SetCode("SEARCH_INPUT_REQUIRED")
                    .Build());
        }

        if (take is < 1 or > 500)
        {
            throw new QueryException(
                ErrorBuilder.New()
                    .SetMessage("The 'take' argument must be between 1 and 500.")
                    .SetCode("TAKE_OUT_OF_RANGE")
                    .Build());
        }

        return _chain.SearchTransactionsAsync(input, take, cancellationToken);
    }

    #endregion
}

/// <summary>
/// Lightweight DTO representing a blockchain block.
/// </summary>
public sealed record BlockDto(
    string                              Hash,
    long                                Height,
    DateTimeOffset                      Timestamp,
    IReadOnlyCollection<string>         TransactionHashes);

/// <summary>
/// Details summarising current staking state.
/// </summary>
public sealed record StakingSummaryDto(
    decimal TotalStaked,
    decimal AnnualizedPercentageRate,
    int     ValidatorCount);

/// <summary>
/// High-level governance proposal information.
/// </summary>
public sealed record ProposalDto(
    Guid            Id,
    string          Title,
    string          Description,
    string          Status,
    DateTimeOffset  CreatedAt,
    DateTimeOffset? ExpiresAt);

/// <summary>
/// Basic transaction information.
/// </summary>
public sealed record TransactionDto(
    string          Hash,
    string          From,
    string          To,
    decimal         Amount,
    string          AssetSymbol,
    DateTimeOffset  Timestamp,
    string          Status);

/// <summary>
/// Input object type allowing consumers to filter transaction history.
/// </summary>
public sealed record TransactionSearchInput(
    string?         From              = null,
    string?         To                = null,
    string?         AssetSymbol       = null,
    DateTimeOffset? Since             = null,
    DateTimeOffset? Until             = null,
    decimal?        MinAmount         = null,
    decimal?        MaxAmount         = null);
```