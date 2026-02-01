```tsx
/* eslint-disable @typescript-eslint/no-misused-promises */
/* ──────────────────────────────────────────────────────────────────────────────
 File:       packages/frontend/src/components/ui/WalletConnector.tsx
 Author:     StellarStage Carnival Front-End Guild
 Summary:    Universal wallet connector UI that integrates Wagmi, ethers.js and
             the app-wide event bus. Allows users to connect via any injected
             EIP-1193 provider (MetaMask, WalletConnect, Coinbase Wallet, etc.),
             displays the active address & network, and propagates connection
             state to the rest of the front-end through Clean-Architecture
             boundaries.
 ────────────────────────────────────────────────────────────────────────────── */

import React, {
  Fragment,
  memo,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { ethers } from 'ethers';
import {
  useAccount,
  useConnect,
  useDisconnect,
  useNetwork,
  useSwitchNetwork,
  Connector,
} from 'wagmi';
import { InjectedConnector } from 'wagmi/connectors/injected';
import { MetaMaskConnector } from 'wagmi/connectors/metaMask';
import { CoinbaseWalletConnector } from 'wagmi/connectors/coinbaseWallet';
import { WalletConnectConnector } from 'wagmi/connectors/walletConnect';
import styled from 'styled-components';
import { toast } from 'react-toastify';

import { EventBus } from '../../services/EventBus'; // <- Domain-agnostic pub/sub layer
import { ReactComponent as DisconnectIcon } from '../../assets/icons/logout.svg';
import { ReactComponent as CopyIcon } from '../../assets/icons/copy.svg';
import { ReactComponent as ChevronDownIcon } from '../../assets/icons/chevron-down.svg';
import { COLORS } from '../../theme/colors';

////////////////////////////////////////////////////////////////////////////////
// Constants
////////////////////////////////////////////////////////////////////////////////

const SUPPORTED_CHAINS: Record<number, string> = {
  1: 'Ethereum',
  5: 'Goerli',
  137: 'Polygon',
  80001: 'Mumbai',
};

////////////////////////////////////////////////////////////////////////////////
// Styled components
////////////////////////////////////////////////////////////////////////////////

const Button = styled.button<{ $primary?: boolean }>`
  all: unset;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 1rem;
  border-radius: 0.6rem;
  cursor: pointer;
  font-weight: 600;
  color: ${({ $primary }) => ($primary ? '#fff' : COLORS.gray900)};
  background: ${({ $primary }) =>
    $primary ? COLORS.primary600 : COLORS.gray100};
  border: 1px solid
    ${({ $primary }) => ($primary ? COLORS.primary600 : COLORS.gray300)};
  transition: background 200ms ease;

  &:hover {
    background: ${({ $primary }) =>
      $primary ? COLORS.primary700 : COLORS.gray200};
  }
`;

const Dropdown = styled.div`
  position: absolute;
  right: 0;
  top: calc(100% + 0.25rem);
  min-width: 14rem;
  background: #fff;
  border: 1px solid ${COLORS.gray200};
  border-radius: 0.6rem;
  padding: 0.5rem 0;
  box-shadow: rgba(0, 0, 0, 0.08) 0 4px 16px;
  z-index: 100;
`;

const DropdownItem = styled.button`
  all: unset;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  width: 100%;
  cursor: pointer;
  color: ${COLORS.gray900};
  transition: background 200ms ease;

  &:hover {
    background: ${COLORS.gray100};
  }

  svg {
    width: 1rem;
    height: 1rem;
  }
`;

////////////////////////////////////////////////////////////////////////////////
// Helpers
////////////////////////////////////////////////////////////////////////////////

/**
 * Safely shortens a hex string to something like 0x6d…9460 for UI display.
 */
const shortenHex = (hex: string, digits = 4): string => {
  if (!hex) return '';
  return `${hex.substring(0, 2 + digits)}…${hex.slice(-digits)}`;
};

/**
 * Abstraction over navigator.clipboard to handle browser inconsistencies.
 */
const copyToClipboard = async (text: string): Promise<boolean> => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_err) {
    return false;
  }
};

////////////////////////////////////////////////////////////////////////////////
// Component
////////////////////////////////////////////////////////////////////////////////

const WalletConnector: React.FC = () => {
  /* ───── Wagmi hooks ───────────────────────────────────────────────────────*/
  const { connector: activeConnector, address, isConnected } = useAccount();
  const { chain } = useNetwork();
  const { connect, connectors, error: connectError, isLoading: isConnecting } =
    useConnect({
      // We only list EIP-1193 wallets. MagicLink, LedgerLive, etc. live elsewhere.
      connector: new InjectedConnector(),
    });
  const { disconnect } = useDisconnect();
  const {
    switchNetwork,
    error: switchError,
    isLoading: isSwitchingNetwork,
  } = useSwitchNetwork({
    throwForSwitchChainNotSupported: true,
  });

  /* ───── Local UI state ────────────────────────────────────────────────────*/
  const [isDropdownOpen, setDropdownOpen] = useState(false);
  const [isModalOpen, setModalOpen] = useState(false);

  /* ───── Derived helpers ───────────────────────────────────────────────────*/
  const activeNetworkName = useMemo(
    () => (chain ? SUPPORTED_CHAINS[chain.id] || `Chain #${chain.id}` : '—'),
    [chain],
  );

  /* ───── Effects ───────────────────────────────────────────────────────────*/
  useEffect(() => {
    if (isConnected && address) {
      // Propagate through Clean-Architecture boundary.
      EventBus.publish('wallet:connected', { address, chainId: chain?.id });
    } else {
      EventBus.publish('wallet:disconnected', {});
    }
  }, [isConnected, address, chain?.id]);

  useEffect(() => {
    if (connectError) toast.error(connectError.message);
  }, [connectError]);

  useEffect(() => {
    if (switchError) toast.error(switchError.message);
  }, [switchError]);

  /* ───── Handlers ──────────────────────────────────────────────────────────*/
  const handleConnect = useCallback(
    async (c: Connector) => {
      try {
        await connect({ connector: c });
        setModalOpen(false);
        toast.success('Wallet connected 🎉');
      } catch (err) {
        /* swallow, wagmi sets error state */
      }
    },
    [connect],
  );

  const handleDisconnect = useCallback(() => {
    disconnect();
    toast.info('Wallet disconnected');
  }, [disconnect]);

  const handleCopyAddress = useCallback(async () => {
    if (!address) return;
    const ok = await copyToClipboard(address);
    toast[ok ? 'success' : 'warning'](
      ok ? 'Address copied to clipboard' : 'Failed to copy',
    );
    setDropdownOpen(false);
  }, [address]);

  const handleSwitchNetwork = useCallback(
    async (targetChainId: number) => {
      if (!switchNetwork) {
        toast.error('Your wallet does not support switching networks.');
        return;
      }
      await switchNetwork(targetChainId);
      setDropdownOpen(false);
    },
    [switchNetwork],
  );

  /* ───── Render connector list modal ───────────────────────────────────────*/
  const renderModal = () => {
    if (!isModalOpen) return null;

    const modalRoot = document.getElementById('modal-root');
    const modal = (
      <ModalOverlay onClick={() => setModalOpen(false)}>
        <ModalBody onClick={(e) => e.stopPropagation()}>
          <h3>Select a wallet</h3>
          {connectors.map((c) => (
            <ConnectorButton
              key={c.id}
              disabled={!c.ready || isConnecting}
              onClick={() => handleConnect(c)}
            >
              {c.name} {!c.ready && '(Unavailable)'}
            </ConnectorButton>
          ))}
        </ModalBody>
      </ModalOverlay>
    );
    /* Use a portal so we don’t break z-indexes further down the tree. */
    return modalRoot ? createPortal(modal, modalRoot) : modal;
  };

  /* ───── Main render ───────────────────────────────────────────────────────*/
  return (
    <Fragment>
      {!isConnected ? (
        <Button $primary onClick={() => setModalOpen(true)}>
          {isConnecting ? 'Connecting…' : 'Connect Wallet'}
        </Button>
      ) : (
        <div style={{ position: 'relative' }}>
          <Button onClick={() => setDropdownOpen((s) => !s)}>
            {shortenHex(address ?? '')} · {activeNetworkName}
            <ChevronDownIcon />
          </Button>

          {isDropdownOpen && (
            <Dropdown>
              <DropdownItem onClick={handleCopyAddress}>
                <CopyIcon /> Copy address
              </DropdownItem>

              <DropdownItem onClick={handleDisconnect}>
                <DisconnectIcon /> Disconnect
              </DropdownItem>

              {/* Switch network submenu, collapsed behind details/summary */}
              <details>
                <summary
                  style={{
                    all: 'unset',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem',
                    padding: '0.75rem 1rem',
                    cursor: 'pointer',
                    color: COLORS.gray900,
                  }}
                >
                  <ChevronDownIcon /> Switch Network
                </summary>
                <NetworkList>
                  {Object.entries(SUPPORTED_CHAINS).map(
                    ([chainId, name]) =>
                      Number(chainId) !== chain?.id && (
                        <NetworkItem
                          key={chainId}
                          onClick={() => handleSwitchNetwork(Number(chainId))}
                          disabled={isSwitchingNetwork}
                        >
                          {name}
                        </NetworkItem>
                      ),
                  )}
                </NetworkList>
              </details>
            </Dropdown>
          )}
        </div>
      )}

      {renderModal()}
    </Fragment>
  );
};

export default memo(WalletConnector);

////////////////////////////////////////////////////////////////////////////////
// Aux UI Components
////////////////////////////////////////////////////////////////////////////////

const ModalOverlay = styled.div`
  position: fixed;
  inset: 0;
  background: rgba(23, 23, 23, 0.55);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
`;

const ModalBody = styled.div`
  width: 90vw;
  max-width: 420px;
  background: #fff;
  border-radius: 1rem;
  padding: 2rem 2rem 1.5rem;
  box-shadow: rgba(0, 0, 0, 0.1) 0 10px 25px;

  h3 {
    margin: 0 0 1.25rem;
    font-size: 1.25rem;
    font-weight: 700;
  }
`;

const ConnectorButton = styled.button`
  all: unset;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 0.9rem 1rem;
  margin-top: 0.65rem;
  border: 1px solid ${COLORS.gray300};
  border-radius: 0.75rem;
  cursor: pointer;
  font-weight: 600;
  color: ${COLORS.gray900};
  transition: background 200ms ease;

  &:hover:not([disabled]) {
    background: ${COLORS.gray100};
  }

  &[disabled] {
    opacity: 0.55;
    cursor: not-allowed;
  }
`;

const NetworkList = styled.ul`
  list-style: none;
  padding: 0.45rem 0 0.25rem;
  margin: 0;
`;

const NetworkItem = styled.li<{ disabled?: boolean }>`
  all: unset;
  display: block;
  padding: 0.6rem 1.25rem;
  cursor: ${({ disabled }) => (disabled ? 'not-allowed' : 'pointer')};
  color: ${({ disabled }) =>
    disabled ? COLORS.gray400 : COLORS.gray900};
  transition: background 200ms ease;

  &:hover {
    background: ${({ disabled }) =>
      disabled ? 'transparent' : COLORS.gray100};
  }
`;
```
