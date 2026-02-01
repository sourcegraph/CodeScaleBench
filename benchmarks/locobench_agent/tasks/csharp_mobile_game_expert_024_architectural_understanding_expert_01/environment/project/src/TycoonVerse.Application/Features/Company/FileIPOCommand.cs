```csharp
using System;
using System.Globalization;
using System.Threading;
using System.Threading.Tasks;
using FluentValidation;
using MediatR;
using Microsoft.Extensions.Logging;
using TycoonVerse.Application.Common.Exceptions;
using TycoonVerse.Application.Common.Interfaces;
using TycoonVerse.Application.Common.Models;
using TycoonVerse.Domain.Aggregates.CompanyAggregate;
using TycoonVerse.Domain.Repositories;

namespace TycoonVerse.Application.Features.Company;

/// <summary>
/// Command raised when a player attempts to file an Initial Public Offering (IPO)
/// for one of his/her in-game companies.
/// </summary>
/// <param name="CompanyId">Aggregate identifier of the company that is filing the IPO.</param>
/// <param name="Exchange">The exchange (e.g. “NYSE”, “NASDAQ”) where the company wants to list.</param>
/// <param name="PricePerShare">Expected price per share in the game’s reference currency (USD).</param>
/// <param name="SharesToIssue">Total number of shares the company will issue.</param>
/// <param name="FilingDateUtc">The exact moment the filing is made. Must be in UTC.</param>
public sealed record FileIPOCommand(
    Guid CompanyId,
    string Exchange,
    decimal PricePerShare,
    long SharesToIssue,
    DateTime FilingDateUtc) : IRequest<Result<IPOResponse>>
{
    /// <summary>
    /// Validation rules for <see cref="FileIPOCommand"/>.
    /// </summary>
    public sealed class Validator : AbstractValidator<FileIPOCommand>
    {
        public Validator(IDateTimeProvider clock)
        {
            RuleFor(x => x.CompanyId)
                .NotEmpty();

            RuleFor(x => x.Exchange)
                .NotEmpty()
                .MaximumLength(16)
                .Must(exchange => exchange.Equals(exchange.ToUpper(CultureInfo.InvariantCulture)))
                .WithMessage("Exchange must be in uppercase (e.g. \"NYSE\").");

            RuleFor(x => x.PricePerShare)
                .GreaterThan(0m)
                .LessThanOrEqualTo(10_000m);

            RuleFor(x => x.SharesToIssue)
                .GreaterThan(0);

            RuleFor(x => x.FilingDateUtc)
                .Must(date => date.Kind == DateTimeKind.Utc)
                .WithMessage("FilingDateUtc must be specified in UTC.")
                .Must(date => date <= clock.UtcNow)
                .WithMessage("Filing date cannot be set in the future.");
        }
    }

    /// <summary>
    /// Handles the <see cref="FileIPOCommand"/>.
    /// </summary>
    internal sealed class Handler : IRequestHandler<FileIPOCommand, Result<IPOResponse>>
    {
        private readonly ICompanyRepository          _companyRepository;
        private readonly IUnitOfWork                 _unitOfWork;
        private readonly IDateTimeProvider           _clock;
        private readonly ILogger<Handler>            _logger;

        public Handler(
            ICompanyRepository companyRepository,
            IUnitOfWork unitOfWork,
            IDateTimeProvider clock,
            ILogger<Handler> logger)
        {
            _companyRepository = companyRepository;
            _unitOfWork        = unitOfWork;
            _clock             = clock;
            _logger            = logger;
        }

        public async Task<Result<IPOResponse>> Handle(
            FileIPOCommand request,
            CancellationToken cancellationToken)
        {
            // Acquire aggregate
            Company? company =
                await _companyRepository.GetAsync(request.CompanyId, cancellationToken);

            if (company is null)
            {
                return Result<IPOResponse>.Failure($"Company '{request.CompanyId}' was not found.");
            }

            if (company.IsListed)
            {
                return Result<IPOResponse>.Failure(
                    "The company is already publicly traded and therefore cannot file another IPO.");
            }

            // Domain operation — may throw domain-specific exceptions.
            try
            {
                company.FileInitialPublicOffering(
                    exchange:        request.Exchange,
                    pricePerShare:   request.PricePerShare,
                    sharesToIssue:   request.SharesToIssue,
                    filingDateUtc:   request.FilingDateUtc);

                _companyRepository.Update(company);

                // Persist changes with optimistic concurrency.
                await _unitOfWork.SaveChangesAsync(cancellationToken);

                _logger.LogInformation(
                    "IPO filed successfully for Company {CompanyId} on {Exchange}.",
                    request.CompanyId,
                    request.Exchange);

                return Result<IPOResponse>.Success(new IPOResponse(
                    company.Id,
                    company.TickerSymbol,
                    request.Exchange,
                    request.PricePerShare,
                    request.SharesToIssue,
                    request.FilingDateUtc));
            }
            catch (ConcurrencyException ex)
            {
                _logger.LogWarning(
                    ex,
                    "Concurrency conflict while filing IPO for Company {CompanyId}.",
                    request.CompanyId);

                return Result<IPOResponse>.Failure(
                    "IPO filing failed due to a concurrency conflict. Please try again.");
            }
            catch (DomainValidationException ex)
            {
                _logger.LogDebug(
                    ex,
                    "Domain validation error while filing IPO for Company {CompanyId}.",
                    request.CompanyId);

                return Result<IPOResponse>.Failure(ex.Message);
            }
            catch (Exception ex)
            {
                _logger.LogError(
                    ex,
                    "Unexpected error while filing IPO for Company {CompanyId}.",
                    request.CompanyId);

                return Result<IPOResponse>.Failure(
                    "An unexpected error occurred while filing the IPO.");
            }
        }
    }
}

/// <summary>
/// DTO returned when an IPO filing succeeds.
/// </summary>
public sealed record IPOResponse(
    Guid CompanyId,
    string TickerSymbol,
    string Exchange,
    decimal PricePerShare,
    long SharesIssued,
    DateTime FiledAtUtc);
```