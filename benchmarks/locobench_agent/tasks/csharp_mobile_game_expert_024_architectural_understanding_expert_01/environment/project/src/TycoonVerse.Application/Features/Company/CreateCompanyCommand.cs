```csharp
// File: TycoonVerse/src/TycoonVerse.Application/Features/Company/CreateCompanyCommand.cs

using System;
using System.Globalization;
using System.Threading;
using System.Threading.Tasks;
using MediatR;
using Microsoft.Extensions.Logging;
using TycoonVerse.Application.Abstractions.Persistence;
using TycoonVerse.Application.Abstractions.Services;
using TycoonVerse.Application.Common.Exceptions;
using TycoonVerse.Domain.CompanyAggregate;
using TycoonVerse.Domain.SharedKernel;

// The Application layer follows a CQRS + Mediator pattern (implemented with MediatR).
// This file defines the "command" DTO as well as its corresponding handler.

namespace TycoonVerse.Application.Features.Company
{
    #region Command / Result records ----------------------------------------------------------

    /// <summary>
    /// Command transported through MediatR to request the creation of a new Company aggregate.
    /// </summary>
    public sealed record CreateCompanyCommand(
        string Name,
        Industry Industry,
        decimal InitialCapital,
        string CountryIsoCode,      // ISO 3166-1 alpha-2
        Guid RequestedByPlayerId) : IRequest<CreateCompanyResult>;

    /// <summary>
    /// Returned to the presentation/UI layer once the Company has been created and persisted.
    /// </summary>
    /// <param name="CompanyId">Deterministic identifier of the newly created company.</param>
    /// <param name="UtcCreatedAt">Server-side UTC timestamp.</param>
    public sealed record CreateCompanyResult(Guid CompanyId, DateTime UtcCreatedAt);

    #endregion

    #region Command Handler -------------------------------------------------------------------

    /// <summary>
    /// Handles <see cref="CreateCompanyCommand"/> by validating input, constructing the
    /// Company aggregate root, persisting it through the repository, and committing via Unit-of-Work.
    /// </summary>
    internal sealed class CreateCompanyCommandHandler
        : IRequestHandler<CreateCompanyCommand, CreateCompanyResult>
    {
        private readonly ICompanyRepository _companyRepository;
        private readonly IUnitOfWork _unitOfWork;
        private readonly ICurrencyConversionService _currencyConversion;
        private readonly ILogger<CreateCompanyCommandHandler> _logger;

        public CreateCompanyCommandHandler(
            ICompanyRepository companyRepository,
            IUnitOfWork unitOfWork,
            ICurrencyConversionService currencyConversion,
            ILogger<CreateCompanyCommandHandler> logger)
        {
            _companyRepository = companyRepository ?? throw new ArgumentNullException(nameof(companyRepository));
            _unitOfWork = unitOfWork ?? throw new ArgumentNullException(nameof(unitOfWork));
            _currencyConversion = currencyConversion ?? throw new ArgumentNullException(nameof(currencyConversion));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        public async Task<CreateCompanyResult> Handle(
            CreateCompanyCommand request,
            CancellationToken cancellationToken)
        {
            // Step ‑1: Defensive checks ------------------------------------------------------
            if (string.IsNullOrWhiteSpace(request.Name))
                throw new ValidationException("Company name must be provided.");

            if (request.InitialCapital < 10_000)
                throw new ValidationException("Initial capital must be at least 10 000 in-game credits.");

            if (!RegionInfo.CurrentRegion.TwoLetterISORegionName.Equals(
                    request.CountryIsoCode, StringComparison.OrdinalIgnoreCase)
                && request.CountryIsoCode.Length != 2)
            {
                throw new ValidationException("Country ISO code must be a valid two-letter ISO 3166-1 value.");
            }

            // Step 0: Ensure player does not already own a company with the same name ------
            bool duplicateExists = await _companyRepository.ExistsAsync(
                request.Name, request.RequestedByPlayerId, cancellationToken);

            if (duplicateExists)
                throw new BusinessRuleException($"A company named '{request.Name}' already exists for this player.");

            // Step 1: Convert the initial capital into the internal accounting currency ----
            // The game operates with "G-Credits" internally, but players can seed with local currencies.
            Money seedCapital = await _currencyConversion.ConvertAsync(
                new Money(request.InitialCapital, CurrencyCode.GCredits),  // assuming already in credits
                cancellationToken);

            // Step 2: Create the domain entity (aggregate root) -----------------------------
            var company = Company.Create(
                name: request.Name,
                industry: request.Industry,
                initialCapital: seedCapital,
                regionIsoCode: request.CountryIsoCode,
                foundedByPlayerId: request.RequestedByPlayerId);

            // Step 3: Persist the aggregate through repository + commit ---------------------
            await _companyRepository.AddAsync(company, cancellationToken);
            await _unitOfWork.SaveChangesAsync(cancellationToken);

            _logger.LogInformation(
                "Player {PlayerId} created company {CompanyName} (Id: {CompanyId})",
                request.RequestedByPlayerId,
                company.Name,
                company.Id);

            // Step 4: Return DTO ------------------------------------------------------------
            return new CreateCompanyResult(company.Id, company.CreatedAtUtc);
        }
    }

    #endregion
}

/* -------------------------------------------------------------------------------------------
 * Supporting abstractions & domain types referenced above.
 * In the real codebase these exist in their own files/namespaces; they are included here
 * to keep the snippet self-contained for the purposes of this exercise.
 * ---------------------------------------------------------------------------------------- */

namespace TycoonVerse.Domain.CompanyAggregate
{
    using System;
    using TycoonVerse.Domain.SharedKernel;

    public enum Industry
    {
        Agriculture,
        Manufacturing,
        Technology,
        Retail,
        Logistics,
        Energy,
        Entertainment
    }

    /// <summary>
    /// Company aggregate root.  Only a subset of the real properties is included here.
    /// </summary>
    public sealed class Company
    {
        private Company() { }

        public Guid Id { get; private set; } = Guid.NewGuid();
        public string Name { get; private set; } = default!;
        public Industry Industry { get; private set; }
        public Money Cash { get; private set; } = default!;
        public string RegionIsoCode { get; private set; } = default!;
        public Guid FoundedByPlayerId { get; private set; }
        public DateTime CreatedAtUtc { get; private set; }

        public static Company Create(
            string name,
            Industry industry,
            Money initialCapital,
            string regionIsoCode,
            Guid foundedByPlayerId)
        {
            if (initialCapital.Amount <= 0)
                throw new ArgumentException("Initial capital must be greater than zero.", nameof(initialCapital));

            var company = new Company
            {
                Name = name,
                Industry = industry,
                Cash = initialCapital,
                RegionIsoCode = regionIsoCode,
                FoundedByPlayerId = foundedByPlayerId,
                CreatedAtUtc = DateTime.UtcNow
            };

            // Domain events like CompanyCreatedDomainEvent could be added here.

            return company;
        }
    }
}

namespace TycoonVerse.Domain.SharedKernel
{
    /// <summary>
    /// Immutable value object representing money in a given currency.
    /// </summary>
    public readonly struct Money : IEquatable<Money>
    {
        public decimal Amount { get; }
        public CurrencyCode Currency { get; }

        public Money(decimal amount, CurrencyCode currency)
        {
            if (amount < 0) throw new ArgumentOutOfRangeException(nameof(amount));
            Amount = amount;
            Currency = currency;
        }

        public override string ToString() => $"{Amount:n2} {Currency}";
        public bool Equals(Money other) => Amount == other.Amount && Currency == other.Currency;
        public override bool Equals(object? obj) => obj is Money other && Equals(other);
        public override int GetHashCode() => HashCode.Combine(Amount, Currency);
    }

    public enum CurrencyCode
    {
        GCredits, // In-game virtual currency
        USD,
        EUR,
        JPY,
        GBP
    }
}

namespace TycoonVerse.Application.Abstractions.Persistence
{
    using System;
    using System.Threading;
    using System.Threading.Tasks;
    using TycoonVerse.Domain.CompanyAggregate;

    public interface ICompanyRepository
    {
        Task AddAsync(Company company, CancellationToken ct);
        Task<bool> ExistsAsync(string companyName, Guid playerId, CancellationToken ct);
        // Additional read/query methods omitted for brevity
    }

    public interface IUnitOfWork : IDisposable
    {
        /// <summary>
        /// Persists all tracked changes atomically.
        /// </summary>
        Task<int> SaveChangesAsync(CancellationToken ct);
    }
}

namespace TycoonVerse.Application.Abstractions.Services
{
    using System.Threading;
    using System.Threading.Tasks;
    using TycoonVerse.Domain.SharedKernel;

    /// <summary>
    /// Converts monetary values between various in-game and real currencies.
    /// </summary>
    public interface ICurrencyConversionService
    {
        Task<Money> ConvertAsync(Money from, CancellationToken ct);
    }
}

namespace TycoonVerse.Application.Common.Exceptions
{
    using System;
    using System.Runtime.Serialization;

    [Serializable]
    public sealed class ValidationException : Exception
    {
        public ValidationException(string message) : base(message) { }
        private ValidationException(SerializationInfo info, StreamingContext context) : base(info, context) { }
    }

    [Serializable]
    public sealed class BusinessRuleException : Exception
    {
        public BusinessRuleException(string message) : base(message) { }
        private BusinessRuleException(SerializationInfo info, StreamingContext context) : base(info, context) { }
    }
}
```