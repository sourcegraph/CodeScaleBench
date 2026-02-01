using System;
using System.Collections.Generic;
using System.Linq;
using System.Linq.Expressions;
using System.Threading;
using System.Threading.Tasks;

namespace CanvasCraft.Core.Interfaces.Repositories
{
    /// <summary>
    /// Generic repository abstraction used by CanvasCraft ML Studio.
    /// The repository isolates the domain layer from any specific data-access concerns
    /// and offers first-class support for asynchronous I/O, Specifications, paging,
    /// soft-deletes, and optimistic concurrency control.
    /// </summary>
    /// <typeparam name="TEntity">Aggregate root type.</typeparam>
    /// <typeparam name="TKey">Primary-key type (e.g., <see cref="Guid"/>).</typeparam>
    public interface IRepository<TEntity, in TKey>
        where TEntity : class
    {
        #region Retrieval

        /// <summary>
        /// Gets an entity by its primary key. Returns <c>null</c> when not found.
        /// </summary>
        Task<TEntity?> GetByIdAsync(
            TKey id,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Returns a single entity that matches the supplied <paramref name="specification"/>.
        /// Returns <c>null</c> when no match is found, throws when multiple matches exist.
        /// </summary>
        Task<TEntity?> SingleOrDefaultAsync(
            ISpecification<TEntity>? specification = null,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Returns the first entity that matches <paramref name="predicate"/> or <c>null</c>.
        /// </summary>
        Task<TEntity?> FirstOrDefaultAsync(
            Expression<Func<TEntity, bool>> predicate,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Lists entities that satisfy the given <paramref name="specification"/>.
        /// When <paramref name="specification"/> is <c>null</c>, all entities are returned.
        /// </summary>
        Task<IReadOnlyList<TEntity>> ListAsync(
            ISpecification<TEntity>? specification = null,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Lists entities using page/offset semantics.
        /// </summary>
        Task<PagedResult<TEntity>> ListPagedAsync(
            int pageNumber,
            int pageSize,
            ISpecification<TEntity>? specification = null,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Counts entities that satisfy the given <paramref name="specification"/>.
        /// </summary>
        Task<long> CountAsync(
            ISpecification<TEntity>? specification = null,
            CancellationToken cancellationToken = default);

        #endregion

        #region Persistence

        /// <summary>
        /// Adds a new entity instance to the underlying store and returns the tracked entity.
        /// </summary>
        Task<TEntity> AddAsync(
            TEntity entity,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Persists modifications to an existing entity.
        /// Implementations must guard against optimistic concurrency conflicts and
        /// throw <see cref="ConcurrencyException"/> when detected.
        /// </summary>
        Task UpdateAsync(
            TEntity entity,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Physically removes the entity from the store.
        /// </summary>
        Task DeleteAsync(
            TEntity entity,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Performs a logical (soft) delete by marking the entity as removed while retaining data.
        /// </summary>
        Task SoftDeleteAsync(
            TEntity entity,
            CancellationToken cancellationToken = default);

        #endregion
    }

    #region Helper Types

    /// <summary>
    /// Immutable paged result used by <see cref="IRepository{TEntity,TKey}.ListPagedAsync"/>.
    /// </summary>
    /// <typeparam name="T">Entity type.</typeparam>
    public sealed class PagedResult<T>
    {
        public PagedResult(
            IReadOnlyList<T> items,
            int pageNumber,
            int pageSize,
            long totalCount)
        {
            Items      = items     ?? throw new ArgumentNullException(nameof(items));
            PageNumber = pageNumber > 0 ? pageNumber
                                        : throw new ArgumentOutOfRangeException(nameof(pageNumber));
            PageSize   = pageSize   > 0 ? pageSize
                                        : throw new ArgumentOutOfRangeException(nameof(pageSize));
            TotalCount = totalCount >= 0 ? totalCount
                                         : throw new ArgumentOutOfRangeException(nameof(totalCount));
        }

        public IReadOnlyList<T> Items { get; }
        public int              PageNumber  { get; }
        public int              PageSize    { get; }
        public long             TotalCount  { get; }
        public int              TotalPages  => (int)Math.Ceiling(TotalCount / (double)PageSize);
        public bool             HasPrevious => PageNumber > 1;
        public bool             HasNext     => PageNumber < TotalPages;
    }

    /// <summary>
    /// Conveys query logic via the Specification pattern.
    /// </summary>
    /// <typeparam name="TEntity">Entity type the specification applies to.</typeparam>
    public interface ISpecification<TEntity>
    {
        /// <summary>Base criteria expression.</summary>
        Expression<Func<TEntity, bool>> Criteria { get; }

        /// <summary>Includes expressed as lambda expressions.</summary>
        IReadOnlyCollection<Expression<Func<TEntity, object>>> Includes { get; }

        /// <summary>Includes expressed as strings (navigation-property paths).</summary>
        IReadOnlyCollection<string> IncludeStrings { get; }

        /// <summary>Ordering function (ascending/descending).</summary>
        Func<IQueryable<TEntity>, IOrderedQueryable<TEntity>>? OrderBy { get; }

        /// <summary>Number of items to skip (offset).</summary>
        int? Skip { get; }

        /// <summary>Number of items to take (limit).</summary>
        int? Take { get; }

        /// <summary>Indicates whether paging is enabled for this specification.</summary>
        bool IsPagingEnabled => Skip.HasValue || Take.HasValue;
    }

    /// <summary>
    /// Thrown when an optimistic concurrency violation is detected.
    /// </summary>
    [Serializable]
    public class ConcurrencyException : Exception
    {
        public ConcurrencyException() { }
        public ConcurrencyException(string message)                : base(message) { }
        public ConcurrencyException(string message, Exception? ex) : base(message, ex) { }

        protected ConcurrencyException(
            System.Runtime.Serialization.SerializationInfo info,
            System.Runtime.Serialization.StreamingContext   context)
            : base(info, context) { }
    }

    #endregion
}