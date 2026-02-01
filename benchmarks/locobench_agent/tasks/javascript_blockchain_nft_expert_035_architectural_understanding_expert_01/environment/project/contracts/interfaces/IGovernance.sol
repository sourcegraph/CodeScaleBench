```solidity
// SPDX-License-Identifier: MIT
//  ___  _   _ _   _ _____ ___ _        _    ____  _____ _____ ____
// / _ \| | | | \ | |_   _|_ _| |      / \  |  _ \| ____| ____|  _ \
//| | | | | | |  \| | | |  | || |     / _ \ | |_) |  _| |  _| | |_) |
//| |_| | |_| | |\  | | |  | || |___ / ___ \|  __/| |___| |___|  _ <
// \__\_\\___/|_| \_| |_| |___|_____/__/   \_\_|   |_____|_____|_| \_\
//
//  StellarStage Carnival
//  Interactive NFT Showrunner
//
//  Governance Interface
//
//  Author: StellarStage Core Devs
//

pragma solidity ^0.8.19;

/**
 * @title IGovernance
 * @notice Minimal, forward-compatible interface for the StellarStage
 *         on-chain governance module. Extends the core ERC-20/721/1155
 *         voting token patterns with additional staking and multi-media
 *         quorum logic tailored for live entertainment productions.
 *
 *         Implementations SHOULD be upgrade-safe (UUPS or Beacon) and
 *         keep storage layout compatible with OpenZeppelin Governor*
 *         contracts.
 *
 * @dev    The interface purposefully mirrors OZ’s IGovernor while adding
 *         carnival-specific hooks such as `stakePass` and `registerLoot`.
 */
interface IGovernance {
    /*//////////////////////////////////////////////////////////////
                                ENUMS
    //////////////////////////////////////////////////////////////*/

    /// @notice Possible lifecycle states of a proposal.
    enum ProposalState {
        Pending,
        Active,
        Canceled,
        Defeated,
        Succeeded,
        Queued,
        Expired,
        Executed
    }

    /*//////////////////////////////////////////////////////////////
                              STRUCTS
    //////////////////////////////////////////////////////////////*/

    /// @notice Voter receipt storing vote metadata.
    struct Receipt {
        bool hasVoted;
        uint8 support; // 0 = Against, 1 = For, 2 = Abstain
        uint256 votes;
    }

    /// @notice Core metadata emitted when a proposal is created.
    struct Proposal {
        address proposer;
        address[] targets;
        uint256[] values;
        bytes[] calldatas;
        uint256 snapshot;
        uint256 deadline;
    }

    /*//////////////////////////////////////////////////////////////
                               EVENTS
    //////////////////////////////////////////////////////////////*/

    /// @dev Emitted when a new proposal is submitted.
    event ProposalCreated(
        uint256 indexed proposalId,
        address indexed proposer,
        address[] targets,
        uint256[] values,
        bytes[] calldatas,
        uint256 startBlock,
        uint256 endBlock,
        string description
    );

    /// @dev Emitted when a proposal is queued in the timelock.
    event ProposalQueued(uint256 indexed proposalId, uint256 eta);

    /// @dev Emitted when a proposal is executed via the timelock.
    event ProposalExecuted(uint256 indexed proposalId);

    /// @dev Emitted when a proposal is canceled.
    event ProposalCanceled(uint256 indexed proposalId);

    /// @dev Emitted when a vote is cast.
    event VoteCast(
        address indexed voter,
        uint256 indexed proposalId,
        uint8 support,
        uint256 weight,
        string reason
    );

    /// @dev Emitted when a Show-Pass NFT is staked for governance power.
    event PassStaked(address indexed owner, uint256 indexed passId, uint256 weight);

    /// @dev Emitted when a staked Show-Pass NFT is withdrawn.
    event PassUnstaked(address indexed owner, uint256 indexed passId, uint256 weight);

    /*//////////////////////////////////////////////////////////////
                             CUSTOM ERRORS
    //////////////////////////////////////////////////////////////*/

    error InvalidProposal();
    error InvalidSupportValue();
    error VotingClosed();
    error OnlyPassOwner();
    error StakeLocked();
    error NotEnoughQuorum();
    error TimelockNotSet();
    error AlreadyInitialized();

    /*//////////////////////////////////////////////////////////////
                            VIEW FUNCTIONS
    //////////////////////////////////////////////////////////////*/

    /**
     * @notice Retrieve the name of the governor instance.
     */
    function name() external view returns (string memory);

    /**
     * @notice Current number of tokens required for proposal submission.
     */
    function proposalThreshold() external view returns (uint256);

    /**
     * @notice Quorum weight required for proposal success at a specific block.
     * @param blockNumber Block number to calculate against.
     */
    function quorum(uint256 blockNumber) external view returns (uint256);

    /**
     * @notice State of a given proposal id.
     * @param proposalId The id of the proposal.
     */
    function state(uint256 proposalId) external view returns (ProposalState);

    /**
     * @notice Total voting power for an account at a given block.
     * @param account The address to check.
     * @param blockNumber Historical block number.
     */
    function getVotes(address account, uint256 blockNumber) external view returns (uint256);

    /**
     * @notice Retrieve on-chain vote receipt.
     */
    function getReceipt(uint256 proposalId, address voter) external view returns (Receipt memory);

    /**
     * @notice Access full proposal metadata.
     */
    function getProposal(uint256 proposalId) external view returns (Proposal memory);

    /*//////////////////////////////////////////////////////////////
                        MUTATIVE ‑ GOVERNANCE
    //////////////////////////////////////////////////////////////*/

    /**
     * @notice Submit a new governance proposal.
     * @param targets    Execution targets.
     * @param values     ETH values for each call.
     * @param calldatas  Encoded function calls.
     * @param description Human-readable description.
     *
     * @return proposalId Newly created proposal id.
     */
    function propose(
        address[] calldata targets,
        uint256[] calldata values,
        bytes[] calldata calldatas,
        string calldata description
    ) external returns (uint256 proposalId);

    /**
     * @notice Cast a vote on an active proposal.
     * @param proposalId The id of the proposal.
     * @param support    Vote type: 0 = Against, 1 = For, 2 = Abstain.
     */
    function castVote(uint256 proposalId, uint8 support) external;

    /**
     * @notice Cast a vote with a reason string, stored on-chain.
     */
    function castVoteWithReason(
        uint256 proposalId,
        uint8 support,
        string calldata reason
    ) external;

    /**
     * @notice Queue a successful proposal in the timelock.
     */
    function queue(uint256 proposalId) external;

    /**
     * @notice Execute a queued proposal after timelock delay.
     */
    function execute(uint256 proposalId) external payable;

    /**
     * @notice Cancel a proposal that has not executed or been queued.
     */
    function cancel(uint256 proposalId) external;

    /*//////////////////////////////////////////////////////////////
               MUTATIVE ‑ PASS STAKING & GOVERNANCE POWER
    //////////////////////////////////////////////////////////////*/

    /**
     * @notice Stake a Show-Pass NFT to gain governance weight.
     *         Weight algorithm is implementation-specific (e.g., rarity,
     *         on-chain level, or performance score).
     * @param passId  ERC-721 Token id of the Show-Pass.
     */
    function stakePass(uint256 passId) external;

    /**
     * @notice Withdraw a previously staked Show-Pass NFT.
     *         MAY revert if the pass is still locked by an active vote.
     */
    function withdrawPass(uint256 passId) external;

    /**
     * @notice Hook for adding Loot (ERC-1155) boosts to a voter’s weight.
     *         Optional, but part of the carnival governance spec.
     * @param lootContract The ERC-1155 contract address.
     * @param tokenId      The loot id.
     * @param amount       Number of tokens added.
     */
    function registerLoot(
        address lootContract,
        uint256 tokenId,
        uint256 amount
    ) external;
}
```