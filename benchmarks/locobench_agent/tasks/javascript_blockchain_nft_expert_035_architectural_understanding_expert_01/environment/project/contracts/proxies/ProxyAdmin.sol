```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/*
 *  StellarStage Carnival
 *  ---------------------
 *  ProxyAdmin.sol
 *
 *  A hardened admin contract used to control upgradeable proxy instances
 *  deployed throughout the StellarStage Carnival ecosystem. The contract is
 *  inspired by OpenZeppelin’s ProxyAdmin implementation, but extends it with:
 *
 *    • Two-step ownership (via Ownable2Step) for safer role transfers
 *    • Permanent proxy-locking to freeze royalty-critical logic
 *    • Custom errors for cheaper & cleaner revert messages
 *    • Basic proxy-type validation guard rails
 */

import "@openzeppelin/contracts/proxy/transparent/TransparentUpgradeableProxy.sol";
import "@openzeppelin/contracts/access/Ownable2Step.sol";

contract ProxyAdmin is Ownable2Step {
    /* ──────────────────────────────────────────────────────────────────────────
        Errors
    ───────────────────────────────────────────────────────────────────────── */
    error InvalidProxy(address proxy);
    error ProxyLocked(address proxy);
    error UnauthorizedFallback(address caller);

    /* ──────────────────────────────────────────────────────────────────────────
        Storage
    ───────────────────────────────────────────────────────────────────────── */
    // Tracks whether a proxy has been irreversibly locked.
    mapping(address => bool) private _locked;

    /* ──────────────────────────────────────────────────────────────────────────
        Modifiers
    ───────────────────────────────────────────────────────────────────────── */
    modifier onlyProxy(address proxy) {
        if (!_looksLikeProxy(proxy)) revert InvalidProxy(proxy);
        _;
    }

    modifier notLocked(address proxy) {
        if (_locked[proxy]) revert ProxyLocked(proxy);
        _;
    }

    /* ──────────────────────────────────────────────────────────────────────────
        View helpers
    ───────────────────────────────────────────────────────────────────────── */
    /**
     * @notice Returns the current admin of a TransparentUpgradeableProxy.
     */
    function getProxyAdmin(address proxy)
        public
        view
        onlyProxy(proxy)
        returns (address)
    {
        return TransparentUpgradeableProxy(payable(proxy)).admin();
    }

    /**
     * @notice Returns a proxy’s active implementation address.
     */
    function getProxyImplementation(address proxy)
        public
        view
        onlyProxy(proxy)
        returns (address)
    {
        return TransparentUpgradeableProxy(payable(proxy)).implementation();
    }

    /**
     * @notice Checks whether a proxy has been permanently locked.
     */
    function isProxyLocked(address proxy) external view returns (bool) {
        return _locked[proxy];
    }

    /* ──────────────────────────────────────────────────────────────────────────
        Admin actions
    ───────────────────────────────────────────────────────────────────────── */
    /**
     * @notice Changes the admin of a given proxy.
     */
    function changeProxyAdmin(
        address proxy,
        address newAdmin
    )
        external
        onlyOwner
        onlyProxy(proxy)
        notLocked(proxy)
    {
        TransparentUpgradeableProxy(payable(proxy)).changeAdmin(newAdmin);
    }

    /**
     * @notice Upgrades a proxy to a new implementation without calling it.
     */
    function upgrade(
        address proxy,
        address newImplementation
    )
        external
        onlyOwner
        onlyProxy(proxy)
        notLocked(proxy)
    {
        TransparentUpgradeableProxy(payable(proxy)).upgradeTo(newImplementation);
    }

    /**
     * @notice Upgrades a proxy to a new implementation and executes a function
     *         on the new logic contract in a single transaction.
     */
    function upgradeAndCall(
        address proxy,
        address newImplementation,
        bytes calldata data
    )
        external
        payable
        onlyOwner
        onlyProxy(proxy)
        notLocked(proxy)
    {
        TransparentUpgradeableProxy(payable(proxy))
            .upgradeToAndCall{ value: msg.value }(newImplementation, data);
    }

    /**
     * @notice Permanently locks a proxy against any future upgrades or admin
     *         changes. This operation is irreversible.
     */
    function lockProxy(address proxy)
        external
        onlyOwner
        onlyProxy(proxy)
        notLocked(proxy)
    {
        _locked[proxy] = true;
    }

    /* ──────────────────────────────────────────────────────────────────────────
        Internal utilities
    ───────────────────────────────────────────────────────────────────────── */
    /**
     * @dev Attempts to determine whether a given address is a
     *      TransparentUpgradeableProxy by checking for the existence of
     *      the `admin()` view function via `staticcall`.
     *
     *      This is not an absolute guarantee, but is sufficient to protect
     *      against common mis-configurations (e.g., passing a non-proxy
     *      contract or EOA by accident).
     */
    function _looksLikeProxy(address proxy) private view returns (bool ok) {
        (ok, ) = proxy.staticcall(
            abi.encodeWithSignature("admin()")
        );
    }

    /* ──────────────────────────────────────────────────────────────────────────
        Fallback safeties
    ───────────────────────────────────────────────────────────────────────── */
    receive() external payable {
        revert UnauthorizedFallback(msg.sender);
    }

    fallback() external payable {
        revert UnauthorizedFallback(msg.sender);
    }
}
```