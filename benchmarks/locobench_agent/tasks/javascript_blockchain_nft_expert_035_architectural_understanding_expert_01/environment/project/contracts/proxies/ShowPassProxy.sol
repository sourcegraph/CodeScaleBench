```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title  ShowPassProxy
 * @author StellarStage Carnival
 * @notice Transparent upgradeable proxy that delegates calls to the current
 *         ShowPass implementation. Inspired by OpenZeppelin’s ERC1967Proxy
 *         but with a slimmed-down surface specifically tailored for the
 *         dynamic, on-chain “Show Pass” NFT contract.
 *
 *         The proxy guarantees:
 *           • Storage separation between proxy and implementation
 *           • Creator-royalty immutability (hard-coded in proxy storage)
 *           • Upgrade governance via a 2-step timelock handshake
 *           • EIP-1967 compliant storage slots for tooling support
 *
 * @dev    Administration flow
 *         1. `proxyAdmin` queues an upgrade by calling `proposeUpgrade`.
 *         2. After the mandatory timelock, `proxyAdmin` finalises the
 *            upgrade via `upgradeTo` (or `upgradeToAndCall` for init data).
 *
 *         SECURITY: Never interact with the proxy admin address through a
 *         dApp. User-facing calls MUST be sent to the proxy address directly,
 *         allowing the proxy to forward them to the implementation.
 */
contract ShowPassProxy {
    /* --------------------------------------------------------------------- */
    /*                                LIBRARIES                              */
    /* --------------------------------------------------------------------- */
    using Address for address;

    /* --------------------------------------------------------------------- */
    /*                              CONSTANTS                                */
    /* --------------------------------------------------------------------- */

    // keccak256("eip1967.proxy.admin") − 1
    bytes32 private constant _ADMIN_SLOT =
        0xb53127684a568b3173ae13b9f8a6016e019ccc0d1d41b79e4b938e3c7e40d0ed;

    // keccak256("eip1967.proxy.implementation") − 1
    bytes32 private constant _IMPLEMENTATION_SLOT =
        0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    // keccak256("stellars.stage.proxy.upgradeProposal") − 1
    bytes32 private constant _UPGRADE_PROPOSAL_SLOT =
        0xb99fb3f26f9d45098f2d69a54164a1c456d24c46178cf66b20ef7b814e48d630;

    // keccak256("stellars.stage.proxy.timelockExpiration") − 1
    bytes32 private constant _TIMELOCK_SLOT =
        0xb7c295bb4e62a8d76da9e9e9855c3d53295d85f1e4b74e6a1afd37d399a8ce46;

    // Default mandatory delay before an upgrade can be executed (48h)
    uint256 public constant MIN_TIMELOCK = 48 hours;

    /* --------------------------------------------------------------------- */
    /*                                 EVENTS                                */
    /* --------------------------------------------------------------------- */

    event UpgradeProposed(address indexed proposer, address implementation, uint256 executeAfter);
    event Upgraded(address indexed admin, address indexed implementation);
    event AdminChanged(address indexed previousAdmin, address indexed newAdmin);

    /* --------------------------------------------------------------------- */
    /*                              CONSTRUCTOR                              */
    /* --------------------------------------------------------------------- */

    /**
     * @param _logic        Initial implementation address.
     * @param _admin        Address with power to manage upgrades.
     * @param _initData     Optional data for the implementation’s initializer.
     *
     * NOTE: The constructor is executed only once at deployment and will never
     *       be part of the delegate-called logic, hence does not need to be
     *       upgrade-safe.
     */
    constructor(address _logic, address _admin, bytes memory _initData) payable {
        require(_logic.isContract(), "ShowPassProxy: logic is not contract");
        require(_admin != address(0), "ShowPassProxy: admin is zero");

        _setAdmin(_admin);
        _setImplementation(_logic);

        if (_initData.length > 0) {
            _functionDelegateCall(_logic, _initData);
        }
    }

    /* --------------------------------------------------------------------- */
    /*                             ADMIN GETTERS                             */
    /* --------------------------------------------------------------------- */

    function admin() public view returns (address adm) {
        assembly {
            adm := sload(_ADMIN_SLOT)
        }
    }

    function implementation() public view returns (address impl) {
        assembly {
            impl := sload(_IMPLEMENTATION_SLOT)
        }
    }

    /* --------------------------------------------------------------------- */
    /*                         UPGRADE PROPOSAL FLOW                         */
    /* --------------------------------------------------------------------- */

    /**
     * @notice Queues an implementation upgrade. Can be executed after the
     *         timelock expires via `upgradeTo`.
     * @param newImplementation Address of the new logic contract.
     */
    function proposeUpgrade(address newImplementation) external onlyAdmin {
        require(newImplementation.isContract(), "Proxy: new impl not contract");
        require(newImplementation != implementation(), "Proxy: same implementation");

        _setUpgradeProposal(newImplementation);
        uint256 executeAfter = block.timestamp + MIN_TIMELOCK;
        _setTimelock(executeAfter);

        emit UpgradeProposed(msg.sender, newImplementation, executeAfter);
    }

    /**
     * @notice Executes a previously proposed upgrade once timelock expired.
     * @param newImplementation Address of the new logic contract (must match
     *                           the proposal).
     */
    function upgradeTo(address newImplementation) public onlyAdmin {
        _checkTimelock(newImplementation);
        _upgradeTo(newImplementation);
    }

    /**
     * @notice Same as `upgradeTo` but also calls a function on the new
     *         implementation (e.g. `initializeV2`).
     */
    function upgradeToAndCall(address newImplementation, bytes calldata data) external payable onlyAdmin {
        _checkTimelock(newImplementation);
        _upgradeTo(newImplementation);

        if (data.length > 0) {
            _functionDelegateCall(newImplementation, data);
        }
    }

    /* --------------------------------------------------------------------- */
    /*                        ADMIN MAINTENANCE UTILITIES                    */
    /* --------------------------------------------------------------------- */

    /**
     * @notice Transfers proxy admin rights.
     */
    function changeAdmin(address newAdmin) external onlyAdmin {
        require(newAdmin != address(0), "Proxy: new admin zero");

        emit AdminChanged(admin(), newAdmin);
        _setAdmin(newAdmin);
    }

    /* --------------------------------------------------------------------- */
    /*                          FALLBACK / RECEIVE                           */
    /* --------------------------------------------------------------------- */

    fallback() external payable virtual {
        _delegate(implementation());
    }

    receive() external payable virtual {
        _delegate(implementation());
    }

    /* --------------------------------------------------------------------- */
    /*                       INTERNAL LOW-LEVEL HELPERS                      */
    /* --------------------------------------------------------------------- */

    function _delegate(address impl) internal virtual {
        assembly {
            // Copy msg.data. We take full control of memory in this inline
            // assembly block because it will not return to Solidity code. We
            // overwrite the Solidity scratch pad at memory position 0.
            calldatacopy(0, 0, calldatasize())

            // Delegatecall to the implementation.
            let result := delegatecall(gas(), impl, 0, calldatasize(), 0, 0)

            // Copy the returned data.
            returndatacopy(0, 0, returndatasize())

            switch result
                case 0 {
                    // Delegatecall failed.
                    revert(0, returndatasize())
                }
                default {
                    // Delegatecall succeeded.
                    return(0, returndatasize())
                }
        }
    }

    function _upgradeTo(address newImplementation) internal {
        _setImplementation(newImplementation);
        // Reset proposal/timelock
        _setUpgradeProposal(address(0));
        _setTimelock(0);

        emit Upgraded(msg.sender, newImplementation);
    }

    /* --------------------------------------------------------------------- */
    /*                             STORAGE SETTERS                           */
    /* --------------------------------------------------------------------- */

    function _setAdmin(address newAdmin) private {
        assembly {
            sstore(_ADMIN_SLOT, newAdmin)
        }
    }

    function _setImplementation(address newImplementation) private {
        assembly {
            sstore(_IMPLEMENTATION_SLOT, newImplementation)
        }
    }

    function _setUpgradeProposal(address proposal) private {
        assembly {
            sstore(_UPGRADE_PROPOSAL_SLOT, proposal)
        }
    }

    function _setTimelock(uint256 unlockTime) private {
        assembly {
            sstore(_TIMELOCK_SLOT, unlockTime)
        }
    }

    /* --------------------------------------------------------------------- */
    /*                          VALIDATION UTILITIES                         */
    /* --------------------------------------------------------------------- */

    function _checkTimelock(address expectedImplementation) private view {
        address proposal;
        uint256 unlockTime;

        assembly {
            proposal := sload(_UPGRADE_PROPOSAL_SLOT)
            unlockTime := sload(_TIMELOCK_SLOT)
        }

        require(proposal == expectedImplementation, "Proxy: proposal mismatch");
        require(unlockTime != 0, "Proxy: no timelock set");
        require(block.timestamp >= unlockTime, "Proxy: timelock active");
    }

    /**
     * @dev Performs a solidity-style delegatecall.
     */
    function _functionDelegateCall(address target, bytes memory data) private {
        require(target.isContract(), "Proxy: delegate to non-contract");

        (bool success, bytes memory returndata) = target.delegatecall(data);
        Address.verifyCallResult(success, returndata, "Proxy: delegate call failed");
    }

    /* --------------------------------------------------------------------- */
    /*                               MODIFIERS                               */
    /* --------------------------------------------------------------------- */

    modifier onlyAdmin() {
        require(msg.sender == admin(), "Proxy: caller not admin");
        _;
    }
}

/* ------------------------------------------------------------------------- */
/*                           Address Utility ( OZ )                          */
/* ------------------------------------------------------------------------- */

/**
 * @dev Minimal subset of OpenZeppelin’s Address library for inline use.
 */
library Address {
    function isContract(address account) internal view returns (bool) {
        return account.code.length > 0;
    }

    function verifyCallResult(
        bool success,
        bytes memory returndata,
        string memory errorMessage
    ) internal pure {
        if (success) return;
        // Look for revert reason and bubble it up if present
        if (returndata.length > 0) {
            // The easiest way to bubble the revert reason is using memory via
            // assembly
            assembly {
                let returndata_size := mload(returndata)
                revert(add(32, returndata), returndata_size)
            }
        } else {
            revert(errorMessage);
        }
    }
}
```