```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title RoyaltyEnforcer
 * @notice Stand-alone royalty registry & operator-filter that can be composed
 *         with any ERC-721/1155 contract. Implements ERC-2981 while giving the
 *         collection owner fine-grained control over per-token royalties and
 *         marketplaces that are authorised to interact with the asset.
 *
 *         Rationale:
 *         1. Some marketplaces ignore on-chain royalty data.  By gating
 *            `transfer`, `approve`, `setApprovalForAll`, etc. through the
 *            `onlyPermittedOperator` modifier, an NFT contract can hard-block
 *            non-compliant venues.
 *         2. Keeping royalty logic in an isolated contract lets future
 *            collections share a single source of truth (proxy-friendly) and
 *            keeps storage layouts clean.
 *
 *         Usage Pattern (in an ERC-721 contract):
 *
 *            contract ShowPass is ERC721, RoyaltyEnforcer {
 *                constructor() ERC721("ShowPass", "SHOW") RoyaltyEnforcer(msg.sender, 750) {}
 *
 *                function setApprovalForAll(address operator, bool approved)
 *                    public
 *                    override
 *                    onlyPermittedOperator(operator)
 *                {
 *                    super.setApprovalForAll(operator, approved);
 *                }
 *
 *                function _beforeTokenTransfer(address from, address to, uint256 id, uint256 batchSize)
 *                    internal
 *                    override
 *                    onlyPermittedOperator(msg.sender)
 *                {
 *                    super._beforeTokenTransfer(from, to, id, batchSize);
 *                }
 *            }
 *
 *         –––––––––––––
 *         Developed for the StellarStage Carnival codebase.
 */

import "@openzeppelin/contracts/interfaces/IERC2981.sol";
import "@openzeppelin/contracts/utils/introspection/ERC165.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract RoyaltyEnforcer is IERC2981, ERC165, Ownable {
    /*//////////////////////////////////////////////////////////////
                               CONSTRUCTOR
    //////////////////////////////////////////////////////////////*/

    /**
     * @param defaultReceiver   Initial address that should receive royalty funds
     * @param defaultBps        Basis-points royalty fee (1% = 100, max = 10_000)
     */
    constructor(address defaultReceiver, uint96 defaultBps) {
        _setDefaultRoyalty(defaultReceiver, defaultBps);
    }

    /*//////////////////////////////////////////////////////////////
                               EVENTS
    //////////////////////////////////////////////////////////////*/

    event DefaultRoyaltySet(address indexed receiver, uint96 feeBps);
    event TokenRoyaltySet(uint256 indexed tokenId, address indexed receiver, uint96 feeBps);
    event OperatorAllowed(address indexed operator, bool isAllowed);

    /*//////////////////////////////////////////////////////////////
                               ROYALTY STATE
    //////////////////////////////////////////////////////////////*/

    uint96 private constant _FEE_DENOMINATOR = 10_000;

    struct RoyaltyInfo {
        address receiver;
        uint96  royaltyFraction; // out of _FEE_DENOMINATOR
    }

    // Global royalty (fallback)
    RoyaltyInfo private _defaultRoyalty;

    // Optional per-token override
    mapping(uint256 tokenId => RoyaltyInfo) private _tokenRoyalty;

    /*//////////////////////////////////////////////////////////////
                           MARKETPLACE FILTERS
    //////////////////////////////////////////////////////////////*/

    mapping(address operator => bool) private _allowedOperators;

    /*//////////////////////////////////////////////////////////////
                         ROYALTY ADMIN FUNCTIONS
    //////////////////////////////////////////////////////////////*/

    /**
     * @notice Update the global royalty settings.
     */
    function setDefaultRoyalty(address receiver, uint96 feeBps) external onlyOwner {
        _setDefaultRoyalty(receiver, feeBps);
    }

    /**
     * @notice Define a unique royalty for a specific tokenId.
     *         Pass `address(0)` or `feeBps = 0` to remove override.
     */
    function setTokenRoyalty(
        uint256 tokenId,
        address receiver,
        uint96  feeBps
    ) external onlyOwner {
        if (receiver == address(0) || feeBps == 0) {
            delete _tokenRoyalty[tokenId];
            emit TokenRoyaltySet(tokenId, address(0), 0);
            return;
        }

        _validateRoyaltyParams(receiver, feeBps);
        _tokenRoyalty[tokenId] = RoyaltyInfo(receiver, feeBps);
        emit TokenRoyaltySet(tokenId, receiver, feeBps);
    }

    /*//////////////////////////////////////////////////////////////
                        OPERATOR-FILTER FUNCTIONS
    //////////////////////////////////////////////////////////////*/

    /**
     * @notice Allow or block a marketplace / operator contract.
     *         NFT contracts can then gate sensitive state-changing
     *         functions with `onlyPermittedOperator`.
     */
    function allowOperator(address operator, bool isAllowed) external onlyOwner {
        _allowedOperators[operator] = isAllowed;
        emit OperatorAllowed(operator, isAllowed);
    }

    /**
     * @return true if the operator is explicitly permitted
     */
    function isOperatorAllowed(address operator) public view returns (bool) {
        return _allowedOperators[operator];
    }

    /**
     * @dev Transfer-gate modifier.  Place this on public/external functions
     *      that grant token approvals or move tokens.
     *
     *      Example:
     *          function approve(address to, uint256 id)
     *              public
     *              onlyPermittedOperator(to)
     *          { … }
     */
    modifier onlyPermittedOperator(address operator) {
        require(
            isOperatorAllowed(operator),
            "RoyaltyEnforcer: operator not permitted"
        );
        _;
    }

    /*//////////////////////////////////////////////////////////////
                       ERC-2981 IMPLEMENTATION
    //////////////////////////////////////////////////////////////*/

    /**
     * @inheritdoc IERC2981
     */
    function royaltyInfo(
        uint256 tokenId,
        uint256 salePrice
    ) external view override returns (address receiver, uint256 royaltyAmount) {
        RoyaltyInfo memory royalty = _tokenRoyalty[tokenId];

        // Fallback to default if no per-token override
        if (royalty.receiver == address(0)) {
            royalty = _defaultRoyalty;
        }

        royaltyAmount = (salePrice * royalty.royaltyFraction) / _FEE_DENOMINATOR;
        receiver       = royalty.receiver;
    }

    /*//////////////////////////////////////////////////////////////
                          INTERNAL UTILITIES
    //////////////////////////////////////////////////////////////*/

    function _setDefaultRoyalty(address receiver, uint96 feeBps) internal {
        _validateRoyaltyParams(receiver, feeBps);
        _defaultRoyalty = RoyaltyInfo(receiver, feeBps);
        emit DefaultRoyaltySet(receiver, feeBps);
    }

    function _validateRoyaltyParams(address receiver, uint96 feeBps) private pure {
        require(receiver != address(0), "RoyaltyEnforcer: zero receiver");
        require(feeBps <= _FEE_DENOMINATOR, "RoyaltyEnforcer: fee too high");
    }

    /*//////////////////////////////////////////////////////////////
                           ERC165 SUPPORT
    //////////////////////////////////////////////////////////////*/

    function supportsInterface(bytes4 interfaceId)
        public
        view
        virtual
        override(ERC165, IERC165)
        returns (bool)
    {
        return
            interfaceId == type(IERC2981).interfaceId ||
            super.supportsInterface(interfaceId);
    }
}
```