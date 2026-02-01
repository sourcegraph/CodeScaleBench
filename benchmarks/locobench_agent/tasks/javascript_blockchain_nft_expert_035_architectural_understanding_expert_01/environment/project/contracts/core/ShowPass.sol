```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title ShowPass
 * @notice Upgradeable ERC-721 NFT that functions as an interactive ticket for
 *         StellarStage Carnival shows.  The pass levels-up with on-chain
 *         experience, can be staked for governance, and respects creator
 *         royalties (ERC-2981).  The contract is secured behind access-roles
 *         and can be upgraded through the UUPS proxy pattern.
 *
 * Clean-Architecture Considerations
 * ---------------------------------
 * • Domain logic (leveling, staking, governance weight) is contained in this
 *   contract—the “core” layer—while higher-level orchestration lives in
 *   TypeScript services (MintShowPass, StakePass, CastLiveVote, …).
 * • External dependencies are abstracted behind interfaces (e.g. IXPSource)
 *   to keep the contract testable and chain-agnostic.
 */

import {ERC721EnumerableUpgradeable}     from "@openzeppelin/contracts-upgradeable/token/ERC721/extensions/ERC721EnumerableUpgradeable.sol";
import {AccessControlUpgradeable}        from "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import {PausableUpgradeable}             from "@openzeppelin/contracts-upgradeable/security/PausableUpgradeable.sol";
import {ReentrancyGuardUpgradeable}      from "@openzeppelin/contracts-upgradeable/security/ReentrancyGuardUpgradeable.sol";
import {UUPSUpgradeable}                 from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {ERC2981Upgradeable}              from "@openzeppelin/contracts-upgradeable/token/common/ERC2981Upgradeable.sol";
import {Counters}                        from "@openzeppelin/contracts/utils/Counters.sol";

/// -----------------------------------------------------------------------
/// Custom errors (cheaper than revert strings)
/// -----------------------------------------------------------------------
error Unauthorized();
error InvalidToken();
error AlreadyStaked();
error NotStaked();
error ZeroAddress();

contract ShowPass is
    ERC721EnumerableUpgradeable,
    ERC2981Upgradeable,
    AccessControlUpgradeable,
    PausableUpgradeable,
    ReentrancyGuardUpgradeable,
    UUPSUpgradeable
{
    using Counters for Counters.Counter;

    /// -------------------------------------------------------------------
    /// Roles
    /// -------------------------------------------------------------------
    bytes32 public constant ADMIN_ROLE   = keccak256("ADMIN_ROLE");
    bytes32 public constant MINTER_ROLE  = keccak256("MINTER_ROLE");
    bytes32 public constant STAGE_ROLE   = keccak256("STAGE_ROLE"); // show runtime data feeder

    /// -------------------------------------------------------------------
    /// Pass domain model
    /// -------------------------------------------------------------------
    struct PassData {
        uint8   level;          // Player level (1-255)
        uint32  xp;             // Accumulated experience
        bool    staked;         // Is pass currently staked for governance?
        uint64  stakeTimestamp; // When staking started (unix time)
    }

    Counters.Counter private _tokenIds;                 // incremental id counter
    mapping(uint256 => PassData) internal _passData;    // tokenId => data

    string private _baseTokenURI;                       // metadata root
    uint32 private constant _XP_PER_LEVEL = 1_000 ether /* scaled */;

    /// -------------------------------------------------------------------
    /// Events
    /// -------------------------------------------------------------------
    event PassMinted(address indexed to, uint256 indexed tokenId);
    event LevelUp(uint256 indexed tokenId, uint8 newLevel);
    event PassStaked(uint256 indexed tokenId);
    event PassUnstaked(uint256 indexed tokenId, uint64 durationSec);

    /// -------------------------------------------------------------------
    /// Initializer (replaces constructor for proxy pattern)
    /// -------------------------------------------------------------------
    function initialize(
        string memory name_,
        string memory symbol_,
        string memory baseURI_,
        address defaultRoyaltyReceiver,
        uint96  defaultRoyaltyFeeNumerator /* in bps */
    ) external initializer {
        if (defaultRoyaltyReceiver == address(0)) revert ZeroAddress();

        __ERC721_init(name_, symbol_);
        __ERC721Enumerable_init();
        __AccessControl_init();
        __Pausable_init();
        __ReentrancyGuard_init();
        __UUPSUpgradeable_init();
        __ERC2981_init();

        _baseTokenURI = baseURI_;

        // Role configuration
        _grantRole(DEFAULT_ADMIN_ROLE, _msgSender());
        _grantRole(ADMIN_ROLE,           _msgSender());
        _grantRole(MINTER_ROLE,          _msgSender());
        _grantRole(STAGE_ROLE,           _msgSender());

        // Set default royalty (can be overridden per-token)
        _setDefaultRoyalty(defaultRoyaltyReceiver, defaultRoyaltyFeeNumerator);
    }

    /// -------------------------------------------------------------------
    /// Minting
    /// -------------------------------------------------------------------

    /**
     * @notice Mint a new ShowPass to `to`
     * @dev Only callable by accounts with MINTER_ROLE
     */
    function mint(address to) external whenNotPaused onlyRole(MINTER_ROLE) returns (uint256 tokenId) {
        if (to == address(0)) revert ZeroAddress();

        _tokenIds.increment();
        tokenId = _tokenIds.current();

        // Initialize pass data
        _passData[tokenId] = PassData({
            level: 1,
            xp:    0,
            staked: false,
            stakeTimestamp: 0
        });

        _safeMint(to, tokenId);

        emit PassMinted(to, tokenId);
    }

    /// -------------------------------------------------------------------
    /// Experience / Leveling
    /// -------------------------------------------------------------------

    /**
     * @notice Feed experience points to a pass.  Typically called by the
     *         show’s on-chain runtime (oracle or sequencer) via STAGE_ROLE.
     */
    function grantXP(uint256 tokenId, uint32 amount)
        external
        whenNotPaused
        onlyRole(STAGE_ROLE)
    {
        if (!_exists(tokenId)) revert InvalidToken();

        PassData storage pd = _passData[tokenId];
        pd.xp += amount;

        // Auto-level
        uint8 targetLevel = uint8(pd.xp / _XP_PER_LEVEL) + 1; // level starts at 1
        if (targetLevel > pd.level) {
            pd.level = targetLevel;
            emit LevelUp(tokenId, targetLevel);
        }
    }

    /**
     * @notice Returns the current level of a pass.
     */
    function levelOf(uint256 tokenId) external view returns (uint8) {
        if (!_exists(tokenId)) revert InvalidToken();
        return _passData[tokenId].level;
    }

    /**
     * @notice View helper: returns voting power derived from level and stake state.
     *         Formula (example): level * (1 + stakeBoost)
     */
    function votingPower(uint256 tokenId) public view returns (uint256) {
        if (!_exists(tokenId)) revert InvalidToken();
        PassData memory pd = _passData[tokenId];

        uint256 base = pd.level;
        if (pd.staked) {
            uint64 stakedSec = uint64(block.timestamp) - pd.stakeTimestamp;
            uint256 boost = (stakedSec / 1 days) + 1; // +1 power per day staked
            return base * boost;
        }
        return base;
    }

    /// -------------------------------------------------------------------
    /// Staking
    /// -------------------------------------------------------------------

    /**
     * @notice Stake a pass for governance.  Token must be owned by caller.
     */
    function stake(uint256 tokenId) external nonReentrant whenNotPaused {
        if (!_isApprovedOrOwner(_msgSender(), tokenId)) revert Unauthorized();

        PassData storage pd = _passData[tokenId];
        if (pd.staked) revert AlreadyStaked();

        pd.stakeTimestamp = uint64(block.timestamp);
        pd.staked = true;

        emit PassStaked(tokenId);
    }

    /**
     * @notice Unstake a pass, returning it to transferable state.
     */
    function unstake(uint256 tokenId) external nonReentrant whenNotPaused {
        if (!_isApprovedOrOwner(_msgSender(), tokenId)) revert Unauthorized();

        PassData storage pd = _passData[tokenId];
        if (!pd.staked) revert NotStaked();

        uint64 duration = uint64(block.timestamp) - pd.stakeTimestamp;

        pd.staked = false;
        pd.stakeTimestamp = 0;

        emit PassUnstaked(tokenId, duration);
    }

    /// -------------------------------------------------------------------
    /// Admin Utilities
    /// -------------------------------------------------------------------

    function setBaseURI(string memory newBase) external onlyRole(ADMIN_ROLE) {
        _baseTokenURI = newBase;
    }

    function setDefaultRoyalty(address receiver, uint96 feeNumerator)
        external
        onlyRole(ADMIN_ROLE)
    {
        _setDefaultRoyalty(receiver, feeNumerator);
    }

    function pause() external onlyRole(ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(ADMIN_ROLE) {
        _unpause();
    }

    /// -------------------------------------------------------------------
    /// Overrides
    /// -------------------------------------------------------------------

    function _baseURI() internal view override returns (string memory) {
        return _baseTokenURI;
    }

    // Restrict transfers while staked
    function _beforeTokenTransfer(
        address from,
        address to,
        uint256 tokenId,
        uint256 batchSize
    )
        internal
        override(ERC721EnumerableUpgradeable)
        whenNotPaused
    {
        if (_passData[tokenId].staked && from != address(0)) {
            // allow mint but block transfer when staked
            revert("ShowPass: staked");
        }
        super._beforeTokenTransfer(from, to, tokenId, batchSize);
    }

    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721EnumerableUpgradeable, AccessControlUpgradeable, ERC2981Upgradeable)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }

    /// -------------------------------------------------------------------
    /// UUPS upgradability
    /// -------------------------------------------------------------------
    function _authorizeUpgrade(address newImplementation)
        internal
        override
        onlyRole(ADMIN_ROLE)
    {}

    /// -------------------------------------------------------------------
    /// Modifiers
    /// -------------------------------------------------------------------
    modifier onlyRole(bytes32 role) {
        if (!hasRole(role, _msgSender())) revert Unauthorized();
        _;
    }
}
```