```csharp
using System.ComponentModel.DataAnnotations;
using System.Diagnostics;
using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace UtilityChain.ApiGateway.Controllers;

/// <summary>
/// Primary REST‐style gateway controller that fronts all core‐suite modules.
/// Acts as a façade layer so that web clients never talk directly to internal services.
/// </summary>
[ApiController]
[Route("api/[controller]")]
public sealed class GatewayController : ControllerBase
{
    private readonly ITransactionService          _transactionService;
    private readonly IQueryService                _queryService;
    private readonly ISmartContractService        _contractService;
    private readonly IEventBus                    _eventBus;
    private readonly ILogger<GatewayController>   _logger;

    public GatewayController(
        ITransactionService transactionService,
        IQueryService queryService,
        ISmartContractService contractService,
        IEventBus eventBus,
        ILogger<GatewayController> logger)
    {
        _transactionService = transactionService;
        _queryService       = queryService;
        _contractService    = contractService;
        _eventBus           = eventBus;
        _logger             = logger;
    }

    #region Health & Diagnostics
    /// <summary>
    /// Basic liveness check. Useful for k8s probes and off-chain monitoring.
    /// </summary>
    /// <returns>Status 200 if node is up; 503 otherwise.</returns>
    [HttpGet("healthz")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status503ServiceUnavailable)]
    public IActionResult Health()
    {
        var healthy = _queryService.IsNodeHealthy();

        return healthy
            ? Ok(new { status = "ok", ts = DateTimeOffset.UtcNow })
            : StatusCode(StatusCodes.Status503ServiceUnavailable,
                         new { status = "unhealthy", ts = DateTimeOffset.UtcNow });
    }

    /// <summary>
    /// Returns aggregate statistics for dashboards and Grafana panels.
    /// </summary>
    [HttpGet("metrics")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    public IActionResult Metrics()
    {
        var metrics = _queryService.GetNodeMetrics();
        return Ok(metrics);
    }
    #endregion

    #region Transaction Endpoints
    /// <summary>
    /// Broadcasts a signed transaction to the mempool.
    /// </summary>
    [HttpPost("transactions")]
    [ProducesResponseType(StatusCodes.Status202Accepted)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> SubmitTransaction(
        [FromBody, Required] TransactionRequest tx,
        CancellationToken                       ct = default)
    {
        if (!ModelState.IsValid)
        {
            return ValidationProblem(ModelState);
        }

        try
        {
            var hash = await _transactionService
                        .BroadcastAsync(tx.ToCoreTransaction(), ct)
                        .ConfigureAwait(false);

            // Push notification for SSE/WebSocket clients
            _eventBus.Publish(new GatewayEvents.TransactionReceived(hash, tx.FromAddress));

            return AcceptedAtAction(nameof(GetTransaction),
                                    new { hash },
                                    new { hash });
        }
        catch (ValidationException vex)
        {
            _logger.LogWarning(vex, "Validation failed for transaction from {From}", tx.FromAddress);
            return BadRequest(new { error = vex.Message });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to broadcast transaction");
            return Problem("Unexpected error while broadcasting transaction.");
        }
    }

    /// <summary>
    /// Fetches an on-chain transaction by its hash.
    /// </summary>
    [HttpGet("transactions/{hash:required}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetTransaction(
        [FromRoute] string hash,
        CancellationToken ct = default)
    {
        var tx = await _queryService.GetTransactionAsync(hash, ct)
                                    .ConfigureAwait(false);

        return tx is not null ? Ok(tx) : NotFound(new { hash });
    }
    #endregion

    #region Account Queries
    /// <summary>
    /// Returns the balance (confirmed + pending) for the provided wallet address.
    /// </summary>
    [HttpGet("addresses/{address:required}/balance")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetBalance(
        [FromRoute] string address,
        CancellationToken ct = default)
    {
        var balance = await _queryService.GetBalanceAsync(address, ct).ConfigureAwait(false);
        return balance is not null ? Ok(balance) : NotFound(new { address });
    }
    #endregion

    #region Smart Contract Endpoints
    /// <summary>
    /// Deploys a new smart contract to the chain.
    /// </summary>
    [HttpPost("contracts/deploy")]
    [ProducesResponseType(StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> DeployContract(
        [FromBody, Required] ContractDeploymentRequest deployRequest,
        CancellationToken                              ct = default)
    {
        if (!ModelState.IsValid) return ValidationProblem(ModelState);

        try
        {
            var contractAddress = await _contractService
                                    .DeployAsync(deployRequest.Code, deployRequest.InitParams, ct)
                                    .ConfigureAwait(false);

            _eventBus.Publish(new GatewayEvents.ContractDeployed(contractAddress));

            return CreatedAtAction(nameof(GetContractState),
                                   new { contractAddress },
                                   new { contractAddress });
        }
        catch (CompilationException cex)
        {
            return BadRequest(new { error = cex.Message });
        }
    }

    /// <summary>
    /// Invokes a method on an existing smart contract.
    /// </summary>
    [HttpPost("contracts/{contractAddress:required}/invoke")]
    [ProducesResponseType(StatusCodes.Status202Accepted)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> InvokeContractMethod(
        [FromRoute] string contractAddress,
        [FromBody, Required] ContractInvocationRequest invocation,
        CancellationToken ct = default)
    {
        if (!ModelState.IsValid) return ValidationProblem(ModelState);

        try
        {
            var txHash = await _contractService
                          .InvokeAsync(contractAddress,
                                       invocation.Method,
                                       invocation.Params,
                                       invocation.FromAddress,
                                       ct)
                          .ConfigureAwait(false);

            _eventBus.Publish(new GatewayEvents.ContractInvoked(contractAddress, txHash));

            return Accepted(new { txHash });
        }
        catch (ContractNotFoundException cnf)
        {
            return NotFound(new { contractAddress, error = cnf.Message });
        }
        catch (ValidationException vex)
        {
            return BadRequest(new { error = vex.Message });
        }
    }

    /// <summary>
    /// Fetches current state or a snapshot of a contract at a specific block height.
    /// </summary>
    [HttpGet("contracts/{contractAddress:required}/state")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetContractState(
        [FromRoute] string contractAddress,
        [FromQuery] ulong? snapshotHeight,
        CancellationToken ct = default)
    {
        var state = await _contractService
                    .GetStateAsync(contractAddress, snapshotHeight, ct)
                    .ConfigureAwait(false);

        return state is not null ? Ok(state) : NotFound(new { contractAddress });
    }
    #endregion

    #region SSE / Event Streaming
    /// <summary>
    /// Streams new block headers as Server-Sent Events.
    /// </summary>
    [HttpGet("blocks/stream")]
    public IAsyncEnumerable<string> StreamBlocks([FromQuery] string? lastEventId, CancellationToken ct)
    {
        Response.ContentType = "text/event-stream";

        return _eventBus.Subscribe<GatewayEvents.BlockArrived>(lastEventId, ct)
                        .Select(b => $"id:{b.BlockHeight}\ndata:{b.Json}\n\n");
    }
    #endregion


    #region DTOs
    public sealed record TransactionRequest(
        [property: Required] string FromAddress,
        [property: Required] string ToAddress,
        [property: Required, Range(0.00000001, double.MaxValue)] decimal Amount,
        string? Memo)
    {
        public CoreTransaction ToCoreTransaction()
            => new (FromAddress, ToAddress, Amount, Memo);
    }

    public sealed record ContractDeploymentRequest(
        [property: Required] string Code,
        IDictionary<string, object>? InitParams);

    public sealed record ContractInvocationRequest(
        [property: Required] string FromAddress,
        [property: Required] string Method,
        IDictionary<string, object>? Params);
    #endregion
}

#region Supporting Abstractions (Interfaces + Events)
/*
 * These minimal interface definitions live here to make the file compile in
 * isolation. In the real project they are supplied by dedicated modules.
 */

public interface ITransactionService
{
    Task<string> BroadcastAsync(CoreTransaction transaction, CancellationToken ct = default);
}

public interface IQueryService
{
    bool IsNodeHealthy();
    object GetNodeMetrics();
    Task<object?> GetTransactionAsync(string hash, CancellationToken ct = default);
    Task<decimal?> GetBalanceAsync(string address, CancellationToken ct = default);
}

public interface ISmartContractService
{
    Task<string> DeployAsync(string code, IDictionary<string, object>? initParams, CancellationToken ct = default);
    Task<string> InvokeAsync(string contractAddress, string method, IDictionary<string, object>? @params, string fromAddress, CancellationToken ct = default);
    Task<object?> GetStateAsync(string contractAddress, ulong? snapshotHeight, CancellationToken ct = default);
}

public interface IEventBus
{
    void Publish<TEvent>(TEvent @event) where TEvent : notnull;
    IAsyncEnumerable<TEvent> Subscribe<TEvent>(string? lastEventId, CancellationToken ct) where TEvent : notnull;
}

/// <summary>
/// Event types emitted by the gateway. Kept internal to avoid leaking
/// domain specifics to subscribers that only need generic JSON.
/// </summary>
public static class GatewayEvents
{
    public sealed record TransactionReceived(string Hash, string Sender);
    public sealed record ContractDeployed(string ContractAddress);
    public sealed record ContractInvoked(string ContractAddress, string TxHash);
    public sealed record BlockArrived(ulong BlockHeight, string Json);
}

/// <summary>
/// Placeholder transaction entity used for compilation. Real implementation
/// lives in UtilityChain.Core.Transactions.
/// </summary>
public sealed record CoreTransaction(string From, string To, decimal Amount, string? Memo);
#endregion
```