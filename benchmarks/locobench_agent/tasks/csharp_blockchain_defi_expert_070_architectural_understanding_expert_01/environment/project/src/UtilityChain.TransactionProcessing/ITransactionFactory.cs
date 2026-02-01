```csharp
// -----------------------------------------------------------------------------
//  UtilityChain Core Suite – Transaction Processing Module
//  Copyright ©
//  ----------------------------------------------------------------------------
//  File: ITransactionFactory.cs
//  Project: UtilityChain.TransactionProcessing
//  Description:
//      Declares the contract for the transaction-factory component responsible
//      for building canonical, signed, and metadata-rich TransactionEnvelope
//      objects for downstream use by the mem-pool, consensus, and ledger
//      sub-systems.
// -----------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using UtilityChain.Cryptography;       // Signature primitives
using UtilityChain.Domain.Common;      // Domain-level abstractions
using UtilityChain.SmartContracts;     // Contract invocation descriptors
using UtilityChain.Staking;            // Staking request descriptors
using UtilityChain.Governance;         // Governance proposal descriptors

namespace UtilityChain.TransactionProcessing;

/// <summary>
/// Factory abstraction responsible for producing <see cref="TransactionEnvelope"/>
/// instances from a variety of high-level domain requests.
///
/// The implementation is expected to handle:
/// • Payload serialization  
/// • Domain-specific validation  
/// • Fee calculation & injection  
/// • Canonical hashing and signing  
/// • Metadata population (nonce, timestamps, gas limits, etc)  
///
/// A single, cohesive factory eases the maintenance of transaction canonical-
/// ization rules while keeping the creation logic centralized and testable.
/// </summary>
public interface ITransactionFactory
{
    #region Standard Value Transfers
    /// <summary>
    /// Constructs a fungible-token transfer transaction.
    /// </summary>
    /// <param name="descriptor">Rich request object describing sender, receiver, and amount.</param>
    /// <param name="ct">Optional token that can be used to cancel the build operation.</param>
    ValueTask<TransactionEnvelope> CreateStandardAsync(
        StandardTransferDescriptor descriptor,
        CancellationToken ct = default);
    #endregion

    #region Staking
    /// <summary>
    /// Constructs either a stake, unstake, or reward-claim transaction depending
    /// on the <paramref name="descriptor"/> contents.
    /// </summary>
    ValueTask<TransactionEnvelope> CreateStakingAsync(
        StakingDescriptor descriptor,
        CancellationToken ct = default);
    #endregion

    #region Governance
    /// <summary>
    /// Builds a governance-proposal, vote, or tally request, embedding any
    /// supporting documents into the payload.
    /// </summary>
    ValueTask<TransactionEnvelope> CreateGovernanceAsync(
        GovernanceProposalDescriptor descriptor,
        CancellationToken ct = default);
    #endregion

    #region Smart Contracts
    /// <summary>
    /// Builds a transaction that deploys a new WASM/EVM smart contract to chain.
    /// </summary>
    ValueTask<TransactionEnvelope> CreateContractDeploymentAsync(
        ContractDeploymentDescriptor descriptor,
        CancellationToken ct = default);

    /// <summary>
    /// Builds a transaction that invokes an existing smart contract method.
    /// </summary>
    ValueTask<TransactionEnvelope> CreateContractCallAsync(
        ContractInvocationDescriptor descriptor,
        CancellationToken ct = default);
    #endregion

    #region Validation
    /// <summary>
    /// Performs a lightweight, synchronous validation pass on the supplied
    /// envelope before it is broadcast to the network or persisted to the
    /// mem-pool. Implementations should avoid any I/O and instead focus on
    /// cryptographic checks, schema validation, and semantic consistency.
    /// </summary>
    /// <param name="envelope">The envelope to validate.</param>
    /// <param name="validationErrors">
    /// Outputs a collection of validation errors, if any.
    /// </param>
    /// <returns><c>true</c> if the envelope is considered valid; otherwise <c>false</c>.</returns>
    bool TryValidate(
        TransactionEnvelope envelope,
        out IReadOnlyCollection<string> validationErrors);
    #endregion
}

/// <summary>
/// Represents the immutable, canonical form of a transaction recognized by all
/// sub-systems inside UtilityChain.  All payloads must be fully populated and
/// signed before an envelope is considered ready for mem-pool admission.
/// </summary>
/// <param name="Id">Deterministic UUID or hash of the envelope.</param>
/// <param name="Payload">Byte-serialized domain payload.</param>
/// <param name="Timestamp">Block-chain epoch timestamp (UTC).</param>
/// <param name="Signature">Detached signature produced from <c>Payload</c>.</param>
/// <param name="Metadata">Additional key/value pairs (nonce, gasLimit, etc.).</param>
public sealed record TransactionEnvelope(
    Guid Id,
    byte[] Payload,
    DateTimeOffset Timestamp,
    Signature Signature,
    TransactionMetadata Metadata);

/// <summary>
/// Arbitrary metadata dictionary attached to a <see cref="TransactionEnvelope"/>.
/// Common keys include: <c>nonce</c>, <c>gasLimit</c>, <c>maxFee</c>,
/// <c>networkId</c>, <c>memo</c>, etc.
/// </summary>
public sealed record TransactionMetadata(IReadOnlyDictionary<string, string> Items)
{
    public static TransactionMetadata Empty { get; } =
        new TransactionMetadata(new Dictionary<string, string>());
}
```