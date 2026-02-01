```typescript
// File: packages/frontend/src/hooks/useWallet.ts
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ethers, providers, Contract, BigNumber } from 'ethers';
import { toast } from 'react-toastify';

import { SHOWPASS_ABI } from '../abi/ShowPass';
import { getRpcUrl, getExplorerUrl } from '../utils/network';
import { trackAnalytics } from '../utils/analytics';
import { getReadableError } from '../utils/errors';

////////////////////////////////////////////////////////////////////////////////
// Types & Interfaces
////////////////////////////////////////////////////////////////////////////////

interface WalletState {
  provider: providers.Web3Provider | null;
  signer: providers.JsonRpcSigner | null;
  address: string | null;
  chainId: number | null;
  connected: boolean;
  balance: BigNumber | null;
  isCorrectNetwork: boolean;
}

interface UseWallet {
  // State
  provider: providers.Web3Provider | null;
  signer: providers.JsonRpcSigner | null;
  address: string | null;
  chainId: number | null;
  connected: boolean;
  balance: BigNumber | null;
  isCorrectNetwork: boolean;

  // Actions
  connect: () => Promise<void>;
  disconnect: () => void;
  switchNetwork: (targetChainId?: number) => Promise<void>;
  signMessage: (message: string) => Promise<string>;
  sendTransaction: (tx: providers.TransactionRequest) => Promise<providers.TransactionResponse>;
  mintShowPass: (showId: string, quantity?: number) => Promise<providers.TransactionResponse>;
}

////////////////////////////////////////////////////////////////////////////////
// Constants
////////////////////////////////////////////////////////////////////////////////

//  The chain your dApp primarily lives on
const DEFAULT_CHAIN_ID = Number(process.env.REACT_APP_CHAIN_ID) || 1; // Fall back to Ethereum Mainnet

//  The on-chain address of the ShowPass factory / minter contract
const SHOW_PASS_ADDRESS = process.env.REACT_APP_SHOWPASS_ADDRESS as string;

////////////////////////////////////////////////////////////////////////////////
// Hook
////////////////////////////////////////////////////////////////////////////////

export const useWallet = (): UseWallet => {
  ////////////////////////////////////////////////////////////////////////////
  // State
  ////////////////////////////////////////////////////////////////////////////

  const [{ provider, signer, address, chainId, connected, balance, isCorrectNetwork }, setState] =
    useState<WalletState>({
      provider: null,
      signer: null,
      address: null,
      chainId: null,
      connected: false,
      balance: null,
      isCorrectNetwork: false,
    });

  // React keeps stale closures around; store listeners in refs to remove them later
  const listenersAttached = useRef(false);

  ////////////////////////////////////////////////////////////////////////////
  // Helpers
  ////////////////////////////////////////////////////////////////////////////

  /** Mutate only the specific keys you pass in to avoid unwanted resets */
  const patchState = (partial: Partial<WalletState>) =>
    setState((prev) => ({ ...prev, ...partial }));

  /** Prepare an ethers.js Web3Provider from the injected provider */
  const createProvider = (): providers.Web3Provider | null => {
    if ((window as any).ethereum == null) {
      toast.error('No Ethereum provider detected. Install MetaMask or another wallet.');
      return null;
    }
    return new ethers.providers.Web3Provider((window as any).ethereum, 'any');
  };

  /** Attach MetaMask / injected event listeners for reactive UI updates */
  const attachListeners = useCallback(
    (eth: any) => {
      if (listenersAttached.current || eth == null) return;

      // Account changes
      eth.on('accountsChanged', async (accounts: string[]) => {
        patchState({ address: accounts[0] ?? null, connected: accounts.length > 0 });
        if (accounts.length > 0) {
          await updateBalance();
        }
      });

      // Chain changes
      eth.on('chainChanged', async (hexChainId: string) => {
        const numericChainId = Number(BigInt(hexChainId));
        patchState({ chainId: numericChainId, isCorrectNetwork: numericChainId === DEFAULT_CHAIN_ID });
        await updateBalance();
      });

      // Disconnect (MetaMask currently fires only on certain providers)
      eth.on('disconnect', () => {
        resetState();
      });

      listenersAttached.current = true;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  /** Reset local wallet state */
  const resetState = () => {
    setState({
      provider: null,
      signer: null,
      address: null,
      chainId: null,
      connected: false,
      balance: null,
      isCorrectNetwork: false,
    });
    listenersAttached.current = false;
  };

  /** Update ETH/WETH balance for the current signer */
  const updateBalance = async () => {
    try {
      if (!signer) return;
      const newBalance = await signer.getBalance();
      patchState({ balance: newBalance });
    } catch (err) {
      console.error('Failed to update balance', err);
    }
  };

  ////////////////////////////////////////////////////////////////////////////
  // Public wallet actions
  ////////////////////////////////////////////////////////////////////////////

  /**
   * Prompt the user’s wallet to connect & initialise the provider.
   */
  const connect = useCallback(async () => {
    try {
      let injectedProvider = createProvider();
      if (!injectedProvider) return;

      // Request account access
      const accounts: string[] = await injectedProvider.send('eth_requestAccounts', []);
      if (accounts.length === 0) {
        toast.error('No account returned by wallet.');
        return;
      }

      // Determine the active network
      const { chainId: networkChainId } = await injectedProvider.getNetwork();
      const signer = injectedProvider.getSigner();

      patchState({
        provider: injectedProvider,
        signer,
        address: ethers.utils.getAddress(accounts[0]),
        chainId: networkChainId,
        connected: true,
        isCorrectNetwork: networkChainId === DEFAULT_CHAIN_ID,
      });

      // Subscribe to wallet updates
      attachListeners((window as any).ethereum);

      // Preload balance
      await updateBalance();

      trackAnalytics('wallet_connected', { address: accounts[0], chainId: networkChainId });
    } catch (err) {
      const readable = getReadableError(err);
      toast.error(readable);
      trackAnalytics('wallet_connection_error', { error: readable });
      console.error('Wallet connect error', err);
    }
  }, [attachListeners, updateBalance]);

  /**
   * Disconnect the wallet from the dApp UI (cannot always disconnect provider on MetaMask side).
   */
  const disconnect = () => {
    resetState();
    trackAnalytics('wallet_disconnected');
  };

  /**
   * Ask wallet to switch to a supported network (and optionally add it if missing).
   */
  const switchNetwork = useCallback(
    async (targetChainId: number = DEFAULT_CHAIN_ID) => {
      if (!provider) {
        toast.error('Wallet not connected');
        return;
      }

      const eth = (provider.provider as any) ?? (window as any).ethereum;
      if (!eth?.request) {
        toast.error('Switch network is not supported by your provider');
        return;
      }

      const hexChainId = '0x' + targetChainId.toString(16);

      try {
        await eth.request({
          method: 'wallet_switchEthereumChain',
          params: [{ chainId: hexChainId }],
        });
        patchState({ chainId: targetChainId, isCorrectNetwork: targetChainId === DEFAULT_CHAIN_ID });
        toast.success('Network switched');
      } catch (err: any) {
        // If the chain has not been added to MetaMask, we attempt to add it
        if (err.code === 4902) {
          try {
            await eth.request({
              method: 'wallet_addEthereumChain',
              params: [
                {
                  chainId: hexChainId,
                  rpcUrls: [getRpcUrl(targetChainId)],
                  nativeCurrency: { name: 'ETH', symbol: 'ETH', decimals: 18 },
                  blockExplorerUrls: [getExplorerUrl(targetChainId)],
                  chainName: `Chain ${targetChainId}`,
                },
              ],
            });
            toast.success('Network added & switched');
          } catch (addError) {
            toast.error(getReadableError(addError));
          }
        } else {
          toast.error(getReadableError(err));
        }
      }
    },
    [provider],
  );

  /**
   * Sign an arbitrary message with the user’s wallet (for auth, etc.).
   */
  const signMessage = async (message: string): Promise<string> => {
    if (!signer) throw new Error('Wallet not connected');
    try {
      const signature = await signer.signMessage(message);
      return signature;
    } catch (err) {
      toast.error(getReadableError(err));
      throw err;
    }
  };

  /**
   * Send a raw transaction to the network.
   */
  const sendTransaction = async (
    tx: providers.TransactionRequest,
  ): Promise<providers.TransactionResponse> => {
    if (!signer) throw new Error('Wallet not connected');
    try {
      const txResponse = await signer.sendTransaction(tx);
      toast.info(`Transaction submitted: ${txResponse.hash}`);
      return txResponse;
    } catch (err) {
      toast.error(getReadableError(err));
      throw err;
    }
  };

  /**
   * Business-specific convenience wrapper around the ShowPass contract to mint tickets.
   */
  const mintShowPass = async (
    showId: string,
    quantity: number = 1,
  ): Promise<providers.TransactionResponse> => {
    if (!signer) throw new Error('Wallet not connected');
    if (!SHOW_PASS_ADDRESS) throw new Error('ShowPass contract address not configured');

    try {
      const contract = new Contract(SHOW_PASS_ADDRESS, SHOWPASS_ABI, signer);
      const gasEstimate = await contract.estimateGas.mint(showId, quantity);
      const tx = await contract.mint(showId, quantity, { gasLimit: gasEstimate.mul(120).div(100) }); // add 20% buffer
      toast.success(`Minting transaction submitted: ${tx.hash}`);

      trackAnalytics('mint_show_pass_submitted', {
        address,
        showId,
        quantity,
        txHash: tx.hash,
      });

      return tx;
    } catch (err) {
      const readable = getReadableError(err);
      toast.error(readable);
      trackAnalytics('mint_show_pass_failed', { error: readable });
      throw err;
    }
  };

  ////////////////////////////////////////////////////////////////////////////
  // Lifecycle: attempt eager connection on page load for UX
  ////////////////////////////////////////////////////////////////////////////

  useEffect(() => {
    const eagerConnect = async () => {
      try {
        const inject = createProvider();
        if (!inject) return;

        const accounts: string[] = await inject.listAccounts();
        if (accounts.length === 0) return;

        // Already authorised, populate state silently
        const { chainId: networkChainId } = await inject.getNetwork();
        const signer = inject.getSigner();

        setState({
          provider: inject,
          signer,
          address: ethers.utils.getAddress(accounts[0]),
          chainId: networkChainId,
          connected: true,
          isCorrectNetwork: networkChainId === DEFAULT_CHAIN_ID,
          balance: await signer.getBalance(),
        });

        attachListeners((window as any).ethereum);
      } catch (err) {
        // Eager connect errors should be silent to not annoy the user
        console.debug('Eager connect skipped:', err);
      }
    };

    eagerConnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  ////////////////////////////////////////////////////////////////////////////
  // Return the public API of the hook
  ////////////////////////////////////////////////////////////////////////////

  return {
    // state
    provider,
    signer,
    address,
    chainId,
    connected,
    balance,
    isCorrectNetwork,

    // actions
    connect,
    disconnect,
    switchNetwork,
    signMessage,
    sendTransaction,
    mintShowPass,
  };
};
```
