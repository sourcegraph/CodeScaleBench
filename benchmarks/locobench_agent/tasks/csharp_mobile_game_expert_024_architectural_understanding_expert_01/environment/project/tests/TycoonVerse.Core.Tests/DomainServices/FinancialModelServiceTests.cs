```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using Moq;
using TycoonVerse.Core.Domain.Events;
using TycoonVerse.Core.Domain.Models;
using TycoonVerse.Core.Domain.Services;
using TycoonVerse.Core.Domain.ValueObjects;
using TycoonVerse.Core.Infrastructure.Repositories;
using Xunit;

namespace TycoonVerse.Core.Tests.DomainServices
{
    /// <summary>
    ///     Unit-tests for <see cref="FinancialModelService" />.
    ///     The service is the canonical source of truth for a company’s real-time
    ///     P&L, Balance-Sheet, and Cash-Flow statements.  All in-game financial
    ///     transactions must flow through this service.
    /// </summary>
    public sealed class FinancialModelServiceTests
    {
        private readonly Mock<IRepository<FinancialSnapshot>> _snapshotRepositoryMock;
        private readonly Mock<ITaxCalculator>                _taxCalculatorMock;
        private readonly Mock<IDomainEventPublisher>          _domainEventPublisherMock;
        private readonly FinancialModelService                _sut; // System-Under-Test

        private readonly CompanyId _companyId = CompanyId.New();

        public FinancialModelServiceTests()
        {
            _snapshotRepositoryMock  = new Mock<IRepository<FinancialSnapshot>>(MockBehavior.Strict);
            _taxCalculatorMock       = new Mock<ITaxCalculator>(MockBehavior.Strict);
            _domainEventPublisherMock = new Mock<IDomainEventPublisher>(MockBehavior.Strict);

            _sut = new FinancialModelService(
                _snapshotRepositoryMock.Object,
                _taxCalculatorMock.Object,
                _domainEventPublisherMock.Object
            );
        }

        #region RecordInventoryPurchase

        [Fact]
        public async Task RecordInventoryPurchase_ShouldDecreaseCash_AndIncreaseInventory_AndPersistSnapshot()
        {
            // Arrange
            const decimal startingCash      = 250_000m;
            const decimal startingInventory = 10_000m;
            const decimal purchaseCost      = 40_000m;

            var snapshot = TestData.FinancialSnapshot(_companyId, startingCash, startingInventory);

            _snapshotRepositoryMock
                .Setup(r => r.GetAsync(
                    It.Is<SnapshotId>(id => id.CompanyId == _companyId),
                    It.IsAny<CancellationToken>()))
                .ReturnsAsync(snapshot);

            _snapshotRepositoryMock
                .Setup(r => r.UpdateAsync(snapshot, It.IsAny<CancellationToken>()))
                .Returns(Task.CompletedTask);

            _domainEventPublisherMock
                .Setup(p => p.PublishAsync(
                    It.Is<DomainEvent>(e =>
                        e is CashFlowChangedEvent cf &&
                        cf.CompanyId == _companyId &&
                        cf.Amount == -purchaseCost),
                    It.IsAny<CancellationToken>()))
                .Returns(Task.CompletedTask);

            // Act
            await _sut.RecordInventoryPurchaseAsync(
                _companyId,
                new Money(purchaseCost),
                "Bulk steel",
                CancellationToken.None);

            // Assert
            snapshot.Cash.Should().Be(startingCash - purchaseCost);
            snapshot.InventoryValue.Should().Be(startingInventory + purchaseCost);

            _snapshotRepositoryMock.VerifyAll();
            _domainEventPublisherMock.VerifyAll();
        }

        [Fact]
        public async Task RecordInventoryPurchase_WithInsufficientCash_ShouldThrowInvalidOperationException()
        {
            // Arrange
            var snapshot = TestData.FinancialSnapshot(_companyId, startingCash: 1_000m);

            _snapshotRepositoryMock
                .Setup(r => r.GetAsync(It.IsAny<SnapshotId>(), It.IsAny<CancellationToken>()))
                .ReturnsAsync(snapshot);

            // Act
            Func<Task> act = () => _sut.RecordInventoryPurchaseAsync(
                _companyId,
                new Money(10_000m),
                "CPU chips",
                CancellationToken.None);

            // Assert
            await act.Should().ThrowAsync<InvalidOperationException>()
               .WithMessage("*insufficient*cash*");
        }

        #endregion

        #region Calculate End-Of-Month EBITDA

        [Theory]
        [InlineData(500_000, 200_000,  75_000, 225_000)]
        [InlineData(750_000, 400_000, 125_000, 225_000)]
        public async Task CloseMonth_ShouldCalculateCorrectEBITDA(
            decimal revenue,
            decimal cogs,
            decimal overhead,
            decimal expectedEbitda)
        {
            // Arrange
            var snapshot = TestData.FinancialSnapshot(_companyId);
            snapshot.Revenue   = revenue;
            snapshot.Cogs      = cogs;
            snapshot.Overhead  = overhead;

            _snapshotRepositoryMock
                .Setup(r => r.GetAsync(It.IsAny<SnapshotId>(), It.IsAny<CancellationToken>()))
                .ReturnsAsync(snapshot);

            _taxCalculatorMock
                .Setup(t => t.CalculateEbitdaTax(snapshot))
                .Returns(0m); // tax is not part of EBITDA

            _snapshotRepositoryMock
                .Setup(r => r.UpdateAsync(snapshot, It.IsAny<CancellationToken>()))
                .Returns(Task.CompletedTask);

            // Act
            await _sut.CloseMonthAsync(_companyId, CancellationToken.None);

            // Assert
            snapshot.Ebitda.Should().Be(expectedEbitda);
            _snapshotRepositoryMock.VerifyAll();
            _taxCalculatorMock.VerifyAll();
        }

        #endregion

        #region ApplyLoanInterest

        [Fact]
        public async Task ApplyLoanInterest_WithValidLoan_ShouldDecreaseCashAndPublishEvent()
        {
            // Arrange
            var loan       = TestData.Loan(principal: 1_000_000m, annualInterestRate: 0.12m); // 12%
            var snapshot   = TestData.FinancialSnapshot(_companyId, startingCash: 200_000m);
            snapshot.Loans.Add(loan);

            _snapshotRepositoryMock
                .Setup(r => r.GetAsync(It.IsAny<SnapshotId>(), It.IsAny<CancellationToken>()))
                .ReturnsAsync(snapshot);

            _snapshotRepositoryMock
                .Setup(r => r.UpdateAsync(snapshot, It.IsAny<CancellationToken>()))
                .Returns(Task.CompletedTask);

            var expectedInterestExpense = 1_000_000m * 0.12m / 12m; // One month

            _domainEventPublisherMock
                .Setup(p => p.PublishAsync(
                    It.Is<DomainEvent>(e =>
                        e is InterestAccruedEvent ie &&
                        ie.CompanyId == _companyId &&
                        ie.LoanId == loan.Id &&
                        ie.Amount == expectedInterestExpense),
                    It.IsAny<CancellationToken>()))
                .Returns(Task.CompletedTask);

            // Act
            await _sut.ApplyMonthlyLoanInterestAsync(
                _companyId,
                loan.Id,
                CancellationToken.None);

            // Assert
            snapshot.Cash.Should().Be(200_000m - expectedInterestExpense);
            loan.Principal.Should().Be(1_000_000m + expectedInterestExpense);

            _snapshotRepositoryMock.VerifyAll();
            _domainEventPublisherMock.VerifyAll();
        }

        [Fact]
        public async Task ApplyLoanInterest_ForMissingLoan_ShouldThrowArgumentException()
        {
            // Arrange
            var snapshot = TestData.FinancialSnapshot(_companyId);

            _snapshotRepositoryMock
                .Setup(r => r.GetAsync(It.IsAny<SnapshotId>(), It.IsAny<CancellationToken>()))
                .ReturnsAsync(snapshot);

            // Act
            Func<Task> act = () => _sut.ApplyMonthlyLoanInterestAsync(
                _companyId,
                loanId: Guid.NewGuid(),
                CancellationToken.None);

            // Assert
            await act.Should().ThrowAsync<ArgumentException>()
               .WithMessage("*loan*not*found*");
        }

        #endregion
    }

    #region ----- Test Data Builders ---------------------------------------------------------

    /// <summary>
    ///     Lightweight builder methods used exclusively by the unit-tests.
    /// </summary>
    internal static class TestData
    {
        public static FinancialSnapshot FinancialSnapshot(
            CompanyId companyId,
            decimal   startingCash      = 100_000m,
            decimal   startingInventory = 0m)
        {
            return new FinancialSnapshot
            (
                snapshotId : SnapshotId.For(companyId, GameClock.UtcNow.Date),
                cash       : startingCash,
                inventory  : startingInventory
            );
        }

        public static Loan Loan(
            decimal principal,
            decimal annualInterestRate)
        {
            return new Loan
            (
                id                  : Guid.NewGuid(),
                principal           : principal,
                annualInterestRate  : annualInterestRate
            );
        }
    }

    #endregion
}
```