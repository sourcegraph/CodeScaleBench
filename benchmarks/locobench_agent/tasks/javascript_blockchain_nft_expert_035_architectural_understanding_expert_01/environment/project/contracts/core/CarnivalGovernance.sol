```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * CarnivalGovernance.sol
 * -------------------------------------------
 * Core on-chain governance for the StellarStage Carnival platform.
 *
 * Built on OpenZeppelin’s modular Governor implementation to leverage
 * battle-tested logic while keeping the contract upgradeable through
 * Transparent Proxies (UUPS). Voting power is derived from a
 * “Carnival Pass” ERC20Votes token that users receive by staking their
 * underlying ERC721 show-passes off-chain. The contract also integrates
 * a Timelock controller to allow for queued, delay-based execution of
 * approved proposals—giving the community time to audit and, if needed,
 * cancel malicious actions via the Guardian.
 *
 * Clean-architecture note: this smart-contract represents a boundary
 * adapter to the blockchain. Higher-level domain logic (e.g. Pass
 * staking, loot distribution) lives in their own contracts and call
 * into governance only to read proposal state.
 */

import "@openzeppelin/contracts-upgradeable/governance/extensions/GovernorSettingsUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/governance/extensions/GovernorCountingSimpleUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/governance/extensions/GovernorVotesUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/governance/extensions/GovernorVotesQuorumFractionUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/governance/extensions/GovernorTimelockControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/utils/AddressUpgradeable.sol";

contract CarnivalGovernance is
    Initializable,
    GovernorSettingsUpgradeable,
    GovernorCountingSimpleUpgradeable,
    GovernorVotesUpgradeable,
    GovernorVotesQuorumFractionUpgradeable,
    GovernorTimelockControlUpgradeable
{
    using AddressUpgradeable for address;

    // ------------------------------------------------------------------------------------------
    // Constants & immutable-like storage
    // ------------------------------------------------------------------------------------------

    string private constant _NAME = "StellarStage Carnival ‑ Governance";

    // Emergency guardian address (multisig) that can cancel proposals in case of critical bugs.
    address public guardian;

    // Mapping to store cancellation reasons for transparency.
    mapping(uint256 proposalId => string reason) public cancellationReason;

    // ------------------------------------------------------------------------------------------
    // Events
    // ------------------------------------------------------------------------------------------

    event GuardianUpdated(address indexed oldGuardian, address indexed newGuardian);
    event ProposalCancelledByGuardian(uint256 indexed proposalId, string reason);

    // ------------------------------------------------------------------------------------------
    // Errors (custom revert reasons to save gas)
    // ------------------------------------------------------------------------------------------

    error Unauthorized();
    error InvalidAddress();
    error GuardianCannotBeZero();
    error InvalidProposalState();

    // ------------------------------------------------------------------------------------------
    // Initializer (replaces constructor for proxy deployment)
    // ------------------------------------------------------------------------------------------

    /**
     * initialize
     *
     * Params:
     *  token                IVotes compliant token used for voting weight (CarnivalPass ERC20Votes)
     *  timelock             TimelockController instance governing queued proposal execution
     *  guardian_            Multisig/EOA authorized for emergency actions
     *  votingDelayBlocks    How many blocks after proposal submission voting starts
     *  votingPeriodBlocks   How many blocks the vote is open
     *  proposalThreshold    Minimum voting power required to create a proposal (in token units)
     *  quorumPercentage     % of total supply required for quorum
     */
    function initialize(
        IVotes token,
        TimelockControllerUpgradeable timelock,
        address guardian_,
        uint256 votingDelayBlocks,
        uint256 votingPeriodBlocks,
        uint256 proposalThreshold,
        uint256 quorumPercentage
    ) external initializer {
        if (guardian_ == address(0)) revert GuardianCannotBeZero();

        __Governor_init(_NAME);
        __GovernorSettings_init(votingDelayBlocks, votingPeriodBlocks, proposalThreshold);
        __GovernorVotes_init(token);
        __GovernorVotesQuorumFraction_init(quorumPercentage);
        __GovernorTimelockControl_init(timelock);

        guardian = guardian_;
    }

    // ------------------------------------------------------------------------------------------
    // Guardian management
    // ------------------------------------------------------------------------------------------

    /**
     * updateGuardian
     * Allows governance itself (through a successful proposal) to change the guardian.
     */
    function updateGuardian(address newGuardian) external onlyGovernance {
        if (newGuardian == address(0)) revert GuardianCannotBeZero();

        address oldGuardian = guardian;
        guardian = newGuardian;

        emit GuardianUpdated(oldGuardian, newGuardian);
    }

    /**
     * cancelByGuardian
     * Emergency cancellation of a proposal if malicious or buggy.
     * Guardian can only act BEFORE the proposal is executed.
     */
    function cancelByGuardian(uint256 proposalId, string calldata reason_)
        external
    {
        if (msg.sender != guardian) revert Unauthorized();

        GovernorTimelockControlUpgradeable.ProposalState state = state(proposalId);

        // Only Pending, Active or Queued proposals can be cancelled
        if (
            state != GovernorTimelockControlUpgradeable.ProposalState.Pending &&
            state != GovernorTimelockControlUpgradeable.ProposalState.Active &&
            state != GovernorTimelockControlUpgradeable.ProposalState.Queued
        ) {
            revert InvalidProposalState();
        }

        _cancel(
            _proposalTargets[proposalId],
            _proposalValues[proposalId],
            _proposalCalldatas[proposalId],
            _proposalDescriptionHashes[proposalId]
        );

        cancellationReason[proposalId] = reason_;
        emit ProposalCancelledByGuardian(proposalId, reason_);
    }

    // ------------------------------------------------------------------------------------------
    // Override hooks (OpenZeppelin governor plumbing)
    // ------------------------------------------------------------------------------------------

    // The following overrides are required by Solidity due to multiple inheritance.

    function votingDelay() public view override(IGovernor, GovernorSettingsUpgradeable) returns (uint256) {
        return super.votingDelay();
    }

    function votingPeriod() public view override(IGovernor, GovernorSettingsUpgradeable) returns (uint256) {
        return super.votingPeriod();
    }

    function proposalThreshold() public view override(GovernorSettingsUpgradeable, GovernorUpgradeable) returns (uint256) {
        return super.proposalThreshold();
    }

    function quorum(uint256 blockNumber)
        public
        view
        override(IGovernor, GovernorVotesQuorumFractionUpgradeable)
        returns (uint256)
    {
        return super.quorum(blockNumber);
    }

    function state(uint256 proposalId)
        public
        view
        override(GovernorUpgradeable, GovernorTimelockControlUpgradeable)
        returns (ProposalState)
    {
        return super.state(proposalId);
    }

    function propose(
        address[] memory targets,
        uint256[] memory values,
        bytes[] memory calldatas,
        string memory description
    )
        public
        override(GovernorUpgradeable, IGovernor)
        returns (uint256)
    {
        // Restrict contract-based spam proposals
        if (msg.sender.isContract()) {
            // Only registrered adapter contracts can propose
            // (front-end uses off-chain vote-signing to call propose via proxy)
            // For simplicity this sample denies all contracts.
            revert Unauthorized();
        }

        return super.propose(targets, values, calldatas, description);
    }

    function _execute(
        uint256 proposalId,
        address[] memory targets,
        uint256[] memory values,
        bytes[] memory calldatas,
        bytes32 descriptionHash
    ) internal override(GovernorUpgradeable, GovernorTimelockControlUpgradeable) {
        super._execute(proposalId, targets, values, calldatas, descriptionHash);
    }

    function _cancel(
        address[] memory targets,
        uint256[] memory values,
        bytes[] memory calldatas,
        bytes32 descriptionHash
    )
        internal
        override(GovernorUpgradeable, GovernorTimelockControlUpgradeable)
        returns (uint256)
    {
        return super._cancel(targets, values, calldatas, descriptionHash);
    }

    function _executor()
        internal
        view
        override(GovernorUpgradeable, GovernorTimelockControlUpgradeable)
        returns (address)
    {
        return super._executor();
    }

    // Support ERC165 interface detection
    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(GovernorUpgradeable, GovernorTimelockControlUpgradeable)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }

    // ------------------------------------------------------------------------------------------
    // Storage gap for upgradeability
    // ------------------------------------------------------------------------------------------

    uint256[48] private __gap;
}
```