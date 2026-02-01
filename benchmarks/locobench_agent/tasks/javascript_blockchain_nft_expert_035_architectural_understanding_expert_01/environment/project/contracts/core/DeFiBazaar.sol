```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title DeFiBazaar
 * @notice A lightweight, upgrade-safe Automated Market Maker (AMM) powering the
 *         StellarStage Carnival in-world perk economy.  Fans can permissionlessly
 *         swap ERC-20 show tokens & loot credits, or seed new liquidity pools
 *         while the contract enforces creator royalties and treasury fees.
 *
 *         The contract is upgradeable via UUPS, hardened with ReentrancyGuard and
 *         governed through Role-Based Access Control.
 *
 * @dev    IMPORTANT: This contract purposefully skips flash-loan mitigation and
 *         oracle integration to stay lean for in-game micro-transactions.  DO
 *         NOT use in production environments that secure material TVL without
 *         additional auditing.
 */

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/security/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

import "@openzeppelin/contracts-upgradeable/token/ERC20/IERC20Upgradeable.sol";
import "@openzeppelin/contracts-upgradeable/token/ERC20/utils/SafeERC20Upgradeable.sol";

import "@openzeppelin/contracts-upgradeable/utils/math/MathUpgradeable.sol";

contract DeFiBazaar is
    Initializable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable,
    UUPSUpgradeable
{
    using SafeERC20Upgradeable for IERC20Upgradeable;

    // ---------------------------------- Roles ---------------------------------
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // --------------------------------- Events ---------------------------------
    event PoolCreated(bytes32 indexed pid, address indexed tokenA, address indexed tokenB);
    event LiquidityAdded(
        bytes32 indexed pid,
        address indexed provider,
        uint256 amountA,
        uint256 amountB,
        uint256 lpMinted
    );
    event LiquidityRemoved(
        bytes32 indexed pid,
        address indexed provider,
        uint256 amountA,
        uint256 amountB,
        uint256 lpBurned
    );
    event Swapped(
        bytes32 indexed pid,
        address indexed trader,
        address tokenIn,
        uint256 amountIn,
        address tokenOut,
        uint256 amountOut
    );

    // --------------------------- Configuration vars ---------------------------
    uint16 public constant FEE_DIVISOR = 10_000; // basis-point divisor
    uint16 public tradeFeeBps; // e.g. 30  => 0.30%
    uint16 public royaltyBps;  // e.g. 25  => 0.25%
    address public treasury;   // receives fees

    // -------------------------- Liquidity pool state --------------------------
    struct Pool {
        IERC20Upgradeable tokenA;
        IERC20Upgradeable tokenB;
        uint112 reserveA; // uses uint112 to fit tightly into one storage slot
        uint112 reserveB;
        uint32  blockTimestampLast; // for TWAP upgrades (not used yet)
        uint256 totalSupply; // total LP tokens minted (virtual, non-ERC20)
    }

    // Mapping: pid => Pool
    mapping(bytes32 => Pool) private pools;
    // Mapping: pid => provider => LP balance
    mapping(bytes32 => mapping(address => uint256)) private lpBalances;

    // -------------------------------- Modifiers -------------------------------
    modifier poolExists(bytes32 pid) {
        require(pools[pid].totalSupply != 0, "Bazaar: pool not found");
        _;
    }

    // ----------------------------- Initialization -----------------------------
    function initialize(
        address _admin,
        address _treasury,
        uint16 _tradeFeeBps,
        uint16 _royaltyBps
    ) external initializer {
        require(_admin != address(0) && _treasury != address(0), "Bazaar: zero addr");
        require(
            _tradeFeeBps + _royaltyBps < FEE_DIVISOR,
            "Bazaar: invalid fee configuration"
        );

        __AccessControl_init();
        __ReentrancyGuard_init();
        __UUPSUpgradeable_init();

        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(UPGRADER_ROLE, _admin);

        treasury      = _treasury;
        tradeFeeBps   = _tradeFeeBps;
        royaltyBps    = _royaltyBps;
    }

    // ------------------------- Liquidity pool helpers -------------------------
    /**
     * @notice Computes pool identifier from two token addresses, ordering them
     *         lexicographically to guarantee uniqueness.
     */
    function getPoolId(address tokenA, address tokenB) public pure returns (bytes32 pid) {
        (address t0, address t1) = tokenA < tokenB ? (tokenA, tokenB) : (tokenB, tokenA);
        pid = keccak256(abi.encodePacked(t0, t1));
    }

    function getPool(address tokenA, address tokenB)
        external
        view
        returns (Pool memory)
    {
        return pools[getPoolId(tokenA, tokenB)];
    }

    function getReserves(address tokenA, address tokenB)
        external
        view
        returns (uint112 reserveA, uint112 reserveB)
    {
        Pool storage p = pools[getPoolId(tokenA, tokenB)];
        (reserveA, reserveB) = (p.reserveA, p.reserveB);
    }

    // --------------------------- Pool Create / Add ----------------------------
    /**
     * @notice Creates a brand-new liquidity pool or adds liquidity when it
     *         already exists. Returns amount of LP tokens minted.
     */
    function addLiquidity(
        address tokenA,
        address tokenB,
        uint256 amountADesired,
        uint256 amountBDesired
    )
        external
        nonReentrant
        returns (bytes32 pid, uint256 lpMinted)
    {
        require(tokenA != tokenB, "Bazaar: identical tokens");
        require(amountADesired > 0 && amountBDesired > 0, "Bazaar: zero amount");

        (address t0, address t1, uint256 amt0, uint256 amt1) =
            tokenA < tokenB
                ? (tokenA, tokenB, amountADesired, amountBDesired)
                : (tokenB, tokenA, amountBDesired, amountADesired);

        pid = getPoolId(t0, t1);
        Pool storage p = pools[pid];

        if (p.totalSupply == 0) {
            // Initialize pool
            p.tokenA = IERC20Upgradeable(t0);
            p.tokenB = IERC20Upgradeable(t1);
            p.reserveA = uint112(amt0);
            p.reserveB = uint112(amt1);
            p.totalSupply = MathUpgradeable.sqrt(amt0 * amt1);
            lpMinted = p.totalSupply;
            emit PoolCreated(pid, t0, t1);
        } else {
            // Slippage check: maintain price ratio
            require(
                p.reserveA * amt1 == p.reserveB * amt0,
                "Bazaar: price discrepancy"
            );
            lpMinted = MathUpgradeable.min(
                (amt0 * p.totalSupply) / p.reserveA,
                (amt1 * p.totalSupply) / p.reserveB
            );

            p.reserveA += uint112(amt0);
            p.reserveB += uint112(amt1);
            p.totalSupply += lpMinted;
        }

        // Update provider LP balance
        lpBalances[pid][msg.sender] += lpMinted;

        // Transfer tokens in
        IERC20Upgradeable(t0).safeTransferFrom(msg.sender, address(this), amt0);
        IERC20Upgradeable(t1).safeTransferFrom(msg.sender, address(this), amt1);

        emit LiquidityAdded(pid, msg.sender, amt0, amt1, lpMinted);
    }

    // ---------------------------- Remove liquidity ----------------------------
    function removeLiquidity(
        address tokenA,
        address tokenB,
        uint256 lpAmount
    )
        external
        nonReentrant
        poolExists(getPoolId(tokenA, tokenB))
        returns (uint256 amountA, uint256 amountB)
    {
        bytes32 pid = getPoolId(tokenA, tokenB);
        Pool storage p = pools[pid];
        require(lpAmount > 0, "Bazaar: zero LP");
        require(lpBalances[pid][msg.sender] >= lpAmount, "Bazaar: insufficient LP");

        amountA = (lpAmount * p.reserveA) / p.totalSupply;
        amountB = (lpAmount * p.reserveB) / p.totalSupply;

        // Burn LP
        lpBalances[pid][msg.sender] -= lpAmount;
        p.totalSupply -= lpAmount;
        p.reserveA -= uint112(amountA);
        p.reserveB -= uint112(amountB);

        // Payout tokens
        p.tokenA.safeTransfer(msg.sender, amountA);
        p.tokenB.safeTransfer(msg.sender, amountB);

        emit LiquidityRemoved(pid, msg.sender, amountA, amountB, lpAmount);
    }

    // --------------------------------- Swaps ----------------------------------
    /**
     * @notice Swap a fixed `amountIn` of `tokenIn` for at least `minAmountOut` of
     *         the opposite pool token, minus fees and royalties.
     *
     * @dev    The implementation uses the constant-product formula:
     *         reserveIn * reserveOut = k
     *         Fees are collected on the input amount.
     */
    function swap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut
    )
        external
        nonReentrant
        returns (uint256 amountOut)
    {
        bytes32 pid = getPoolId(tokenIn, tokenOut);
        Pool storage p = pools[pid];
        require(p.totalSupply != 0, "Bazaar: pool not found");
        require(amountIn > 0, "Bazaar: zero input");

        bool inIsA = tokenIn == address(p.tokenA);

        (uint112 reserveIn, uint112 reserveOut) = inIsA
            ? (p.reserveA, p.reserveB)
            : (p.reserveB, p.reserveA);

        // Apply fees
        uint256 fee = (amountIn * tradeFeeBps) / FEE_DIVISOR;
        uint256 royalty = (amountIn * royaltyBps) / FEE_DIVISOR;
        uint256 amountInAfterFee = amountIn - fee - royalty;

        // Constant product formula: amountOut = (reserveOut * amountInAfterFee) / (reserveIn + amountInAfterFee)
        amountOut =
            (uint256(reserveOut) * amountInAfterFee) /
            (uint256(reserveIn) + amountInAfterFee);

        require(amountOut >= minAmountOut, "Bazaar: slippage");

        // Update reserves
        if (inIsA) {
            p.reserveA = uint112(reserveIn + amountInAfterFee);
            p.reserveB = uint112(reserveOut - amountOut);
        } else {
            p.reserveB = uint112(reserveIn + amountInAfterFee);
            p.reserveA = uint112(reserveOut - amountOut);
        }

        // Pull input tokens and push output
        IERC20Upgradeable(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
        IERC20Upgradeable(tokenOut).safeTransfer(msg.sender, amountOut);

        // Route fees
        if (fee + royalty > 0) {
            IERC20Upgradeable(tokenIn).safeTransferFrom(
                msg.sender,
                treasury,
                fee + royalty
            );
        }

        emit Swapped(pid, msg.sender, tokenIn, amountIn, tokenOut, amountOut);
    }

    // ------------------------- LP balance view helper -------------------------
    function balanceOfLP(
        address account,
        address tokenA,
        address tokenB
    ) external view returns (uint256) {
        return lpBalances[getPoolId(tokenA, tokenB)][account];
    }

    // ------------------------------ Admin ops ---------------------------------
    /**
     * @dev Reconfigures fee structure. Must keep combined bps < FEE_DIVISOR.
     */
    function setFees(uint16 _tradeFeeBps, uint16 _royaltyBps)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        require(
            _tradeFeeBps + _royaltyBps < FEE_DIVISOR,
            "Bazaar: bad fees"
        );
        tradeFeeBps = _tradeFeeBps;
        royaltyBps = _royaltyBps;
    }

    function setTreasury(address _treasury)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        require(_treasury != address(0), "Bazaar: zero addr");
        treasury = _treasury;
    }

    // ------------------------- UUPS upgradeability ---------------------------
    function _authorizeUpgrade(address newImplementation)
        internal
        override
        onlyRole(UPGRADER_ROLE)
    {}
}
```