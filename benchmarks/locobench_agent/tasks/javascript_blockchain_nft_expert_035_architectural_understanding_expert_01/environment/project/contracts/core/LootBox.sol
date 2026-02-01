```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 *  ███████╗████████╗████████╗██╗     ███████╗████████╗
 *  ██╔════╝╚══██╔══╝╚══██╔══╝██║     ██╔════╝╚══██╔══╝
 *  █████╗     ██║      ██║   ██║     █████╗     ██║
 *  ██╔══╝     ██║      ██║   ██║     ██╔══╝     ██║
 *  ██║        ██║      ██║   ███████╗███████╗   ██║
 *  ╚═╝        ╚═╝      ╚═╝   ╚══════╝╚══════╝   ╚═╝
 *
 *  StellarStage Carnival – Interactive NFT Showrunner
 *  Core Contract: LootBox
 *
 *  A LootBox represents a container that can be opened by a Pass holder
 *  to receive a random set of ERC-721/1155 rewards.  The contract uses
 *  Chainlink VRF for provable randomness and is upgradeable via UUPS.
 */

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/token/ERC721/extensions/ERC721URIStorageUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/token/ERC721/extensions/ERC721BurnableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/security/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/security/PausableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/structs/EnumerableSetUpgradeable.sol";
import "@openzeppelin/contracts/utils/Address.sol";
import "@openzeppelin/contracts/token/ERC1155/IERC1155.sol";

/// @dev Minimal interface for the Pass contract used for access-checks.
interface IShowPass {
    function ownerOf(uint256 passId) external view returns (address);
}

/// @dev Interface for Chainlink VRF (v2 coordinator)
interface IVRFCoordinator {
    function requestRandomWords(
        bytes32 keyHash,
        uint64  subId,
        uint16  minConfirmations,
        uint32  callbackGasLimit,
        uint32  numWords
    ) external returns (uint256 requestId);
}

/**
 * @title LootBox
 * @author StellarStage
 *
 * LootBox NFTs are minted to concert-goers as part of live events.
 * Owners can call `open` to burn the LootBox and receive random
 * on-chain rewards (ERC-721 or ERC-1155 assets).
 *
 * SECURITY:
 *  – Upgradeable via UUPS.  Only accounts with UPGRADER_ROLE can upgrade.
 *  – Pausable by PAUSER_ROLE to mitigate emergencies.
 *  – ReentrancyGuard protects against re-entrancy attacks.
 *  – Uses Chainlink VRF v2 for unmanipulable randomness.
 */
contract LootBox is
    Initializable,
    AccessControlUpgradeable,
    PausableUpgradeable,
    ReentrancyGuardUpgradeable,
    ERC721URIStorageUpgradeable,
    ERC721BurnableUpgradeable,
    UUPSUpgradeable
{
    using EnumerableSetUpgradeable for EnumerableSetUpgradeable.UintSet;
    using Address for address;

    /* ────────────────────────────────────────────────────────────────
     *  Roles
     * ────────────────────────────────────────────────────────────── */
    bytes32 public constant MINTER_ROLE   = keccak256("MINTER_ROLE");
    bytes32 public constant PAUSER_ROLE   = keccak256("PAUSER_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    /* ────────────────────────────────────────────────────────────────
     *  Immutable / Upgradeable Storage
     * ────────────────────────────────────────────────────────────── */

    // Pass contract (for ownership checks)
    IShowPass public pass;

    // Chainlink VRF variables
    IVRFCoordinator public vrfCoordinator;
    bytes32          public vrfKeyHash;
    uint64           public vrfSubId;
    uint32           public vrfCallbackGas;

    // Reward pool definition
    struct Reward {
        address nft;      // Contract address of reward token (ERC721 or ERC1155)
        uint256 id;       // TokenId (for ERC1155) or the single ERC721 Id
        uint256 amount;   // Amount for ERC1155. For ERC721 must be 1
        bool    is1155;   // True → ERC1155, False → ERC721
    }

    Reward[] public rewards;                         // All possible rewards
    uint256  public totalRewardWeight;               // Sum of all weights
    mapping(uint256 => uint256) public rewardWeight; // index → weight

    // Request tracking
    struct Request {
        address opener;
        uint256 lootId;
    }
    mapping(uint256 => Request) public vrfRequests; // requestId → Request

    // LootBox token counter
    uint256 private _nextTokenId;

    // Emitted when a new LootBox is minted
    event LootBoxMinted(address indexed to, uint256 indexed tokenId);

    // Emitted when randomness is fulfilled
    event LootBoxOpened(
        address indexed opener,
        uint256 indexed tokenId,
        uint256 indexed rewardIndex,
        Reward  reward
    );

    /* ────────────────────────────────────────────────────────────────
     *  Initialization
     * ────────────────────────────────────────────────────────────── */

    /// @notice Initializer (replaces constructor for upgradeable contract)
    function initialize(
        string memory name_,
        string memory symbol_,
        address passAddress_,
        address vrfCoordinator_,
        bytes32 vrfKeyHash_,
        uint64  vrfSubId_,
        uint32  vrfCallbackGas_
    ) external initializer {
        __AccessControl_init();
        __Pausable_init();
        __ReentrancyGuard_init();
        __ERC721_init(name_, symbol_);
        __ERC721URIStorage_init();
        __ERC721Burnable_init();
        __UUPSUpgradeable_init();

        // Role setup
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(MINTER_ROLE,          msg.sender);
        _grantRole(PAUSER_ROLE,          msg.sender);
        _grantRole(UPGRADER_ROLE,        msg.sender);

        pass             = IShowPass(passAddress_);
        vrfCoordinator   = IVRFCoordinator(vrfCoordinator_);
        vrfKeyHash       = vrfKeyHash_;
        vrfSubId         = vrfSubId_;
        vrfCallbackGas   = vrfCallbackGas_;
        _nextTokenId     = 1;
    }

    /* ────────────────────────────────────────────────────────────────
     *  Minting
     * ────────────────────────────────────────────────────────────── */

    /**
     * @notice Mint a new LootBox NFT to `to`.
     * @dev    Only accounts with MINTER_ROLE may call.
     */
    function safeMint(address to, string calldata uri)
        external
        whenNotPaused
        onlyRole(MINTER_ROLE)
    {
        uint256 tokenId = _nextTokenId++;
        _safeMint(to, tokenId);
        _setTokenURI(tokenId, uri);

        emit LootBoxMinted(to, tokenId);
    }

    /* ────────────────────────────────────────────────────────────────
     *  Reward Pool Management
     * ────────────────────────────────────────────────────────────── */

    /**
     * @notice Add a new reward type to the pool.
     *
     * @param nft       Address of NFT contract
     * @param id        Token Id (0 for ERC721 collections where id is dynamic)
     * @param amount    Amount (must be 1 for ERC721)
     * @param is1155    True if `nft` is ERC1155
     * @param weight    Probability weight (relative to other rewards)
     */
    function addReward(
        address nft,
        uint256 id,
        uint256 amount,
        bool    is1155,
        uint256 weight
    ) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(nft != address(0), "LootBox: invalid nft");
        require(weight > 0,         "LootBox: zero weight");

        if (!is1155) {
            require(amount == 1, "LootBox: ERC721 amount must be 1");
        }

        rewards.push(Reward(nft, id, amount, is1155));
        rewardWeight[rewards.length - 1] = weight;
        totalRewardWeight += weight;
    }

    /**
     * @notice Update callback gas limit for VRF fulfillment.
     */
    function updateVrfCallbackGas(uint32 gasLimit)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        vrfCallbackGas = gasLimit;
    }

    /* ────────────────────────────────────────────────────────────────
     *  Opening LootBoxes
     * ────────────────────────────────────────────────────────────── */

    /**
     * @notice Opens a LootBox NFT. The token is burned and
     *         a randomness request is sent to Chainlink VRF.
     *
     * @param lootId  Token Id of the LootBox
     * @param passId  Caller must own this Pass as proof of participation.
     */
    function open(uint256 lootId, uint256 passId)
        external
        whenNotPaused
        nonReentrant
    {
        // Ownership checks
        require(ownerOf(lootId) == msg.sender, "LootBox: not owner");
        require(pass.ownerOf(passId) == msg.sender, "LootBox: not pass owner");

        // Burn the LootBox NFT
        _burn(lootId);

        // Request randomness
        uint256 requestId = vrfCoordinator.requestRandomWords(
            vrfKeyHash,
            vrfSubId,
            3,                  // min confirmations
            vrfCallbackGas,
            1                   // numWords
        );

        vrfRequests[requestId] = Request({
            opener : msg.sender,
            lootId : lootId
        });
    }

    /* ────────────────────────────────────────────────────────────────
     *  Chainlink VRF Callback
     * ────────────────────────────────────────────────────────────── */

    /**
     * @dev Chainlink VRF fulfills randomness via this function.
     *      The VRF Coordinator calls it directly.
     */
    function fulfillRandomWords(
        uint256 requestId,
        uint256[] calldata randomWords
    ) external {
        require(
            msg.sender == address(vrfCoordinator),
            "LootBox: only coordinator"
        );

        Request memory req = vrfRequests[requestId];
        require(req.opener != address(0), "LootBox: unknown request");

        // Calculate reward index using random number
        uint256 rand = randomWords[0] % totalRewardWeight;
        uint256 cumulative = 0;
        uint256 rewardIdx;

        for (uint256 i = 0; i < rewards.length; ++i) {
            cumulative += rewardWeight[i];
            if (rand < cumulative) {
                rewardIdx = i;
                break;
            }
        }

        Reward memory reward = rewards[rewardIdx];
        _deliverReward(req.opener, reward);

        emit LootBoxOpened(req.opener, req.lootId, rewardIdx, reward);

        delete vrfRequests[requestId];
    }

    /* ────────────────────────────────────────────────────────────────
     *  Internal Helpers
     * ────────────────────────────────────────────────────────────── */
    function _deliverReward(address to, Reward memory reward) internal {
        if (reward.is1155) {
            IERC1155(reward.nft).safeTransferFrom(
                address(this),
                to,
                reward.id,
                reward.amount,
                ""
            );
        } else {
            // ERC721 – assume tokenId is pre-owned by this contract
            IERC721(reward.nft).safeTransferFrom(address(this), to, reward.id);
        }
    }

    /* ────────────────────────────────────────────────────────────────
     *  Pause / Unpause
     * ────────────────────────────────────────────────────────────── */
    function pause() external onlyRole(PAUSER_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(PAUSER_ROLE) {
        _unpause();
    }

    /* ────────────────────────────────────────────────────────────────
     *  UUPS Upgrade Authorization
     * ────────────────────────────────────────────────────────────── */
    function _authorizeUpgrade(address newImplementation)
        internal
        override
        onlyRole(UPGRADER_ROLE)
    {}

    /* ────────────────────────────────────────────────────────────────
     *  Overrides
     * ────────────────────────────────────────────────────────────── */
    function _beforeTokenTransfer(
        address from,
        address to,
        uint256 tokenId,
        uint256 batchSize
    )
        internal
        override
        whenNotPaused
    {
        super._beforeTokenTransfer(from, to, tokenId, batchSize);
    }

    /* ────────────────────────────────────────────────────────────────
     *  ERC-165 Support
     * ────────────────────────────────────────────────────────────── */
    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721Upgradeable, AccessControlUpgradeable)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }

    /* ────────────────────────────────────────────────────────────────
     *  Fallbacks
     * ────────────────────────────────────────────────────────────── */
    receive() external payable {}
    fallback() external payable {}
}
```