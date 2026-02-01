```csharp
using System;
using System.Linq;
using AutoFixture;
using FluentAssertions;
using TycoonVerse.Core.Domain.Events;
using TycoonVerse.Core.Entities;
using TycoonVerse.Core.Exceptions;
using Xunit;

namespace TycoonVerse.Core.Tests.Entities
{
    /// <summary>
    /// Unit-tests for the <see cref="Company"/> aggregate-root.
    /// </summary>
    public sealed class CompanyTests
    {
        #region Ctor

        [Fact]
        public void Ctor_Should_Create_Valid_Company_When_Arguments_Are_Correct()
        {
            // Arrange
            var fixture = new Fixture();
            var name     = fixture.Create<string>();
            var seedCash = fixture.Create<decimal>() + 10_000m; // guarantee positive

            // Act
            var company = new Company(name, seedCash);

            // Assert
            company.Id.Should().NotBe(Guid.Empty);
            company.Name.Should().Be(name);
            company.CashBalance.Should().Be(seedCash);
        }

        [Theory]
        [InlineData(null)]
        [InlineData("")]
        [InlineData("   ")]
        public void Ctor_Should_Throw_DomainException_When_Name_Is_Invalid(string? invalidName)
        {
            // Arrange
            var seedCash = 1_000m;

            // Act
            var act = () => new Company(invalidName!, seedCash);

            // Assert
            act.Should().ThrowExactly<DomainException>()
               .WithMessage("*name*");
        }

        [Fact]
        public void Ctor_Should_Throw_DomainException_When_SeedCash_Is_Negative()
        {
            // Arrange
            const decimal negativeCash = -1m;

            // Act
            var act = () => new Company("Bad Cash Inc.", negativeCash);

            // Assert
            act.Should().ThrowExactly<DomainException>()
               .WithMessage("*cash*");
        }

        #endregion

        #region Cash Management

        [Fact]
        public void AddCash_Should_Increase_CashBalance()
        {
            // Arrange
            var company = CompanyMother.CreateDefault();
            var original = company.CashBalance;
            const decimal increment = 2_500m;

            // Act
            company.AddCash(increment);

            // Assert
            company.CashBalance.Should().Be(original + increment);
        }

        [Fact]
        public void AddCash_Should_Throw_When_Amount_Is_Negative()
        {
            // Arrange
            var company = CompanyMother.CreateDefault();

            // Act
            var act = () => company.AddCash(-10m);

            // Assert
            act.Should().ThrowExactly<DomainException>()
               .WithMessage("*positive*");
        }

        [Fact]
        public void WithdrawCash_Should_Decrease_CashBalance_When_Funds_Are_Sufficient()
        {
            // Arrange
            var company = CompanyMother.CreateDefault();
            var original = company.CashBalance;
            var amount = company.CashBalance / 2;

            // Act
            company.WithdrawCash(amount);

            // Assert
            company.CashBalance.Should().Be(original - amount);
        }

        [Fact]
        public void WithdrawCash_Should_Throw_When_Funds_Are_Insufficient()
        {
            // Arrange
            var company = CompanyMother.CreateDefault();
            var amount = company.CashBalance + 1m;

            // Act
            var act = () => company.WithdrawCash(amount);

            // Assert
            act.Should().ThrowExactly<InsufficientFundsException>();
        }

        #endregion

        #region Workforce

        [Fact]
        public void HireEmployee_Should_Add_To_Employees_Collection_And_Raise_Event()
        {
            // Arrange
            var company = CompanyMother.CreateDefault();
            var employee = new Employee(
                id: Guid.NewGuid(),
                fullName: "John Doe",
                salary: 50_000m);

            // Act
            company.HireEmployee(employee);

            // Assert
            company.Employees.Should().Contain(employee);

            var events = company.DequeueDomainEvents();
            events.Should().ContainSingle()
                  .Which.Should().BeOfType<EmployeeHiredEvent>()
                  .Subject.As<EmployeeHiredEvent>()
                  .EmployeeId.Should().Be(employee.Id);
        }

        [Fact]
        public void FireEmployee_Should_Remove_From_Employees_Collection_And_Raise_Event()
        {
            // Arrange
            var company = CompanyMother.CreateDefaultWithEmployees(2);
            var employee = company.Employees.First();

            // Act
            company.FireEmployee(employee.Id);

            // Assert
            company.Employees.Should().NotContain(employee);

            var events = company.DequeueDomainEvents();
            events.Should().ContainSingle(e => e is EmployeeFiredEvent fired && fired.EmployeeId == employee.Id);
        }

        #endregion

        #region M&A

        [Fact]
        public void AcquireCompany_Should_Merge_Cash_And_Employees_And_Raise_Event()
        {
            // Arrange
            var acquirer = CompanyMother.CreateDefaultWithEmployees(3);
            var target   = CompanyMother.CreateDefaultWithEmployees(4);

            var expectedCash = acquirer.CashBalance + target.CashBalance;
            var expectedEmployeeCount = acquirer.Employees.Count + target.Employees.Count;

            // Act
            acquirer.AcquireCompany(target);

            // Assert
            acquirer.CashBalance.Should().Be(expectedCash);
            acquirer.Employees.Count.Should().Be(expectedEmployeeCount);

            var events = acquirer.DequeueDomainEvents();
            events.Should().ContainSingle(e => e is CompanyAcquiredEvent acquired &&
                                               acquired.TargetCompanyId == target.Id);
        }

        #endregion
    }

    /// <summary>
    /// Mother-object (test-data builder) for <see cref="Company"/> aggregates.
    /// </summary>
    internal static class CompanyMother
    {
        private static readonly Fixture _fixture = new();

        internal static Company CreateDefault()
        {
            var name  = $"Company {_fixture.Create<string>().Substring(0, 8)}";
            var cash  = _fixture.Create<decimal>() % 10_000m + 5_000m; // keep amounts reasonable
            return new Company(name, cash);
        }

        internal static Company CreateDefaultWithEmployees(int numberOfEmployees)
        {
            var company = CreateDefault();
            for (var i = 0; i < numberOfEmployees; i++)
            {
                var employee = new Employee(
                    id: Guid.NewGuid(),
                    fullName: _fixture.Create<string>(),
                    salary: (decimal)(_fixture.Create<double>() % 90_000 + 30_000));
                company.HireEmployee(employee);
            }
            // flush any events emitted during setup, so tests only care about events from Act phase
            company.DequeueDomainEvents();
            return company;
        }
    }
}
```
