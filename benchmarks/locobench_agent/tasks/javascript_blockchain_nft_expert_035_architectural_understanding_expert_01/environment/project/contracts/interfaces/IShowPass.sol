```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title IShowPass
 * @notice Interface for the StellarStage Carnival “Show Pass” NFT.
 *
 *         A Show Pass is an ERC-721 compliant, up-gradable ticket that can:
 *           • evolve its metadata/traits through authorised upgrades;
 *           • be staked to accrue on-chain governance weight; and
 *           • distribute secondary-sale royalties to the show creator.
 *
 *         The interface purposefully inherits from OpenZeppelin’s IERC721
 *         and IERC2981 to guarantee compatibility with the wider ecosystem.
 *
 * @dev    Implementations MUST gate state-changing functions with the proper
 *         access-control modifiers (e.g., onlyMinter, onlyOwner, onlyDAO).
 */

import "@openzeppelin/contracts/interfaces/IERC721.sol";
import "@openzeppelin/contracts/interfaces/IERC2981.sol";

interface IShowPass is IERC721, IERC2981 {
    /* --------------------------------------------------------------------- */
    /*                                Errors                                 */
    /* --------------------------------------------------------------------- */

    /// Thrown when an operation is tried on a token that is not minted.
    error ShowPass_NotExists(uint256 tokenId);

    /// Thrown when the caller does not own the required token.
    error ShowPass_NotOwner(uint256 tokenId);

    /// Thrown when attempting to move or upgrade a staked pass.
    error ShowPass_Staked(uint256 tokenId);

    /// Thrown when a provided signature for upgrading is invalid or expired.
    error ShowPass_BadUpgradeSignature();

    /* --------------------------------------------------------------------- */
    /*                                Events                                 */
    /* --------------------------------------------------------------------- */

    /**
     * @notice Emitted once a new Show Pass has been minted.
     * @param to      receiver of the freshly-minted pass
     * @param tokenId id of the pass
     * @param showId  id of the show this pass grants access to
     */
    event PassMinted(address indexed to, uint256 indexed tokenId, uint256 indexed showId);

    /**
     * @notice Emitted every time a pass upgrades to a new level / trait set.
     * @param tokenId   id of the upgraded pass
     * @param newLevel  resulting level after the upgrade
     * @param traitHash keccak256 hash of the new trait JSON blob
     */
    event PassUpgraded(uint256 indexed tokenId, uint8 newLevel, bytes32 traitHash);

    /**
     * @notice Emitted when a pass is staked to a specific governance proposal.
     * @param owner      address that performed the stake
     * @param tokenId    id of the staked pass
     * @param proposalId governance proposal the pass has been locked into
     */
    event PassStaked(address indexed owner, uint256 indexed tokenId, uint256 indexed proposalId);

    /**
     * @notice Emitted when a previously-staked pass is unlocked.
     * @param owner   address that performed the unstake
     * @param tokenId id of the unstaked pass
     */
    event PassUnstaked(address indexed owner, uint256 indexed tokenId);

    /**
     * @dev See EIP-4906. Signals dApps that metadata/traits have changed.
     */
    event MetadataUpdate(uint256 indexed tokenId);

    /* --------------------------------------------------------------------- */
    /*                        Minting & Core Getters                         */
    /* --------------------------------------------------------------------- */

    /**
     * @notice Mint a brand-new Show Pass.
     *
     * @param to      address that will own the pass
     * @param showId  associated show identifier
     * @param uri     initial metadata URI (IPFS/Arweave/HTTPS)
     *
     * @return tokenId id of the freshly-minted NFT
     *
     * Requirements:
     *  – Caller MUST possess the MINTER role or equivalent authorisation.
     */
    function mintPass(
        address to,
        uint256 showId,
        string calldata uri
    ) external returns (uint256 tokenId);

    /**
     * @notice Returns the show identifier a pass belongs to.
     * @param tokenId target pass
     */
    function showOf(uint256 tokenId) external view returns (uint256);

    /**
     * @notice Returns the current level of a pass (e.g., 1-255).
     * @param tokenId target pass
     */
    function levelOf(uint256 tokenId) external view returns (uint8);

    /**
     * @notice Returns the keccak256 hash of the traits JSON blob.
     * @param tokenId target pass
     */
    function traitsHashOf(uint256 tokenId) external view returns (bytes32);

    /* --------------------------------------------------------------------- */
    /*                         Upgrading / Evolution                         */
    /* --------------------------------------------------------------------- */

    /**
     * @notice Upgrade a pass to a new level, refreshing its metadata.
     *
     * @dev    The upgrade must be authorised via an off-chain signature issued
     *         by a trusted “Trait Oracle” (e.g., the performer’s server).
     *
     * @param tokenId   pass to upgrade
     * @param newLevel  new level the pass should reach
     * @param traitHash hash of the full trait JSON defining the new metadata
     * @param deadline  UNIX timestamp after which the signature is invalid
     * @param sig       ECDSA signature of the payload:
     *                    keccak256(abi.encodePacked(
     *                        tokenId,
     *                        newLevel,
     *                        traitHash,
     *                        deadline
     *                    ))
     *
     * Emits a {PassUpgraded} and {MetadataUpdate} event.
     */
    function upgradePass(
        uint256 tokenId,
        uint8 newLevel,
        bytes32 traitHash,
        uint256 deadline,
        bytes calldata sig
    ) external;

    /* --------------------------------------------------------------------- */
    /*                             Governance                                */
    /* --------------------------------------------------------------------- */

    /**
     * @notice Stakes a pass into a governance proposal, locking transferability
     *         until the proposal is resolved.
     *
     * @param tokenId    pass to be staked
     * @param proposalId identifier of the governance proposal
     *
     * Emits a {PassStaked} event.
     */
    function stake(uint256 tokenId, uint256 proposalId) external;

    /**
     * @notice Unstakes a pass from its governance proposal. Can only be called
     *         after the governing DAO marks the proposal as final.
     *
     * @param tokenId pass to be unstaked
     *
     * Emits a {PassUnstaked} event.
     */
    function unstake(uint256 tokenId) external;

    /**
     * @notice Checks whether a pass is currently staked.
     * @param tokenId target pass
     */
    function isStaked(uint256 tokenId) external view returns (bool);
}
```