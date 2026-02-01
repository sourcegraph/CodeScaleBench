#pragma once
/**********************************************************************************************************************
 *  MosaicBoard Studio
 *  File:    src/interfaces/IRepository.h
 *
 *  Description:
 *      Generic, type-safe repository interface that abstracts persistence concerns from the rest of the application.
 *      Every concrete repository (SQL, NoSQL, in-memory, remote REST, etc.) must implement this contract to ensure
 *      uniform data-access semantics across the service layer, business logic, and plug-in ecosystem.
 *
 *      The interface embraces modern C++ idioms:
 *          • Value/RAII semantics, exception-safe, noexcept where feasible.
 *          • Optional/Expected-style error handling (std::optional for “not found”, exceptions for unrecoverable errors).
 *          • Asynchronous overloads powered by std::future for non-blocking coroutines/executor integration.
 *          • Transactional boundary hooks for ACID-compliant back-ends.
 *
 *      NOTE:
 *          ‑ The interface purposefully refrains from imposing a specific ORM or serialization layer. Concrete
 *            providers can leverage anything from raw ODBC/PG APIs to nlohmann::json or bespoke graph stores.
 *          ‑ Thread-safety is delegated to the implementation; however, immutable const operations MUST be safe
 *            to call concurrently.
 *
 *  Copyright:
 *      Copyright (c) 2024 MosaicBoard Studio.
 *
 *  SPDX-License-Identifier: MIT
 *********************************************************************************************************************/

#include <future>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace mosaic::data
{

/*==================================================================================================
 *  Forward Declarations
 *=================================================================================================*/
class ITransaction;

/*==================================================================================================
 *  Repository Interface
 *=================================================================================================*/

/**
 *  \brief Generic repository interface inspired by Domain-Driven Design and the Repository Pattern.
 *
 *  \tparam TEntity     Domain / DTO type persisted by this repository.
 *  \tparam TId         Primary-key type (defaults to std::string to facilitate UUIDs, ULIDs, etc.).
 *
 *  Implementations are expected to:
 *      • Throw std::runtime_error (or subclass) for connectivity / constraint violations.
 *      • Return std::optional<TEntity>{} for “not found” scenarios instead of throwing.
 *      • Use UTF-8 encoded strings for all textual data.
 */
template <typename TEntity, typename TId = std::string>
class IRepository
{
public:
    using entity_type   = TEntity;
    using id_type       = TId;
    using list_type     = std::vector<entity_type>;

    virtual ~IRepository() = default;

    // ———————————————————————————————————————————————————————————— Synchronous API ————————————————————————————————————————————————————————————

    /**
     *  Retrieve the full set of entities managed by this repository.
     *  \return Vector of entity values. Empty if none exist. Must not return null.
     */
    [[nodiscard]] virtual list_type getAll() = 0;

    /**
     *  Fetch an entity by its primary key.
     *  \param id Primary key to search for.
     *  \return A populated optional if found; std::nullopt otherwise.
     */
    [[nodiscard]] virtual std::optional<entity_type> getById(const id_type& id) = 0;

    /**
     *  Persist a new entity.
     *  \param entity Object to be inserted (implementation may perform validation).
     *  \return Generated or assigned primary key.
     *  \throws std::runtime_error on constraint violation or I/O failure.
     */
    virtual id_type add(const entity_type& entity) = 0;

    /**
     *  Update an existing entity.
     *  \param id      Primary key of the entity being updated.
     *  \param entity  New state of the entity.
     *  \throws std::runtime_error if the entity does not exist or on I/O failure.
     */
    virtual void update(const id_type& id, const entity_type& entity) = 0;

    /**
     *  Remove an entity.
     *  \param id Primary key to delete.
     *  \throws std::runtime_error if the entity does not exist or on I/O failure.
     */
    virtual void remove(const id_type& id) = 0;

    // ———————————————————————————————————————————————————————————— Asynchronous API ——————————————————————————————————————————————————————————­

    /**
     *  Asynchronous variants mirror the synchronous behavior but return std::future<T>.
     *  They enable non-blocking use in event-loops / thread pools without enforcing a specific executor.
     */
    [[nodiscard]] virtual std::future<list_type>                getAllAsync()                     = 0;
    [[nodiscard]] virtual std::future<std::optional<entity_type>> getByIdAsync(const id_type& id) = 0;
    [[nodiscard]] virtual std::future<id_type>                  addAsync(const entity_type& entity)         = 0;
    [[nodiscard]] virtual std::future<void>                     updateAsync(const id_type& id, const entity_type& entity) = 0;
    [[nodiscard]] virtual std::future<void>                     removeAsync(const id_type& id)              = 0;

    // ———————————————————————————————————————————————————————————— Transactional Support ————————————————————————————————————————————————————

    /**
     *  Start a new transaction scope.
     *  Implementations may return nullptr if transactions are unsupported.
     */
    [[nodiscard]] virtual std::unique_ptr<ITransaction> beginTransaction() = 0;

    /**
     *  Convenience helper that indicates whether the underlying persistence provider supports
     *  transactional semantics (commit/rollback).
     */
    [[nodiscard]] virtual bool supportsTransactions() const noexcept = 0;

    // Disallow copying to prevent slicing & accidental sharing of repository state.
    IRepository(const IRepository&)            = delete;
    IRepository& operator=(const IRepository&) = delete;
    IRepository(IRepository&&)                 = default;
    IRepository& operator=(IRepository&&)      = default;

protected:
    // Protected default ctor: prevent direct instantiation while allowing derived classes.
    IRepository() = default;
};

/*==================================================================================================
 *  Transaction Interface
 *=================================================================================================*/

/**
 *  \brief ACID transaction handle.
 *
 *  RAII wrappers are strongly encouraged to ensure deterministic commit/rollback if an exception
 *  propagates. This interface only models the low-level operations; higher-level abstractions are
 *  free to wrap it in scoped_transaction, etc.
 */
class ITransaction
{
public:
    virtual ~ITransaction() = default;

    /**
     *  Commit the transaction. After calling commit(), the transaction object is considered inert
     *  and further calls are undefined behavior.
     */
    virtual void commit()   = 0;

    /**
     *  Rollback all changes made during the transaction.
     *  Must be safe to call multiple times; subsequent calls should no-op.
     */
    virtual void rollback() = 0;

    // No copy semantics.
    ITransaction(const ITransaction&)            = delete;
    ITransaction& operator=(const ITransaction&) = delete;
    ITransaction(ITransaction&&)                 = default;
    ITransaction& operator=(ITransaction&&)      = default;

protected:
    ITransaction() = default;
};

}   // namespace mosaic::data