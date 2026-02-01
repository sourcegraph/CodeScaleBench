```typescript
/****************************************************************************************
 * StellarStage Carnival
 * WalletService – Front-end adapter for browser wallets (MetaMask, WalletConnect, etc.)
 * --------------------------------------------------------------------------------------
 * • Manages connection / disconnection flow
 * • Normalises Ethereum provider events into an internal, strongly-typed event bus
 * • Exposes convenience helpers (getSigner, sendTransaction, signTypedData, switchNetwork)
 * • Persists last-connected wallet in localStorage for seamless page reload UX
 * • Written in a framework-agnostic style; can be consumed by React / Vue / plain JS
 ****************************************************************************************/

import { ethers, Signer, providers } from 'ethers';
import { TypedEmitter } from 'tiny-typed-emitter';
import WalletConnectProvider from '@walletconnect/web3-provider';

//////////////////////////////////////////////////////////////////////////////////////////
// Types & Constants
//////////////////////////////////////////////////////////////////////////////////////////

export enum WalletAdapter {
  MetaMask = 'METAMASK',
  WalletConnect = 'WALLETCONNECT',
}

export type WalletEventMap = {
  connected: { address: string; network: number };
  disconnected: void;
  accountChanged: { address: string | null };
  networkChanged: { network: number };
  transactionSent: { hash: string };
  error: { error: Error };
};

export interface TransactionRequest
  extends Omit<providers.TransactionRequest, 'from'> {
  from?: string;
}

const LOCAL_STORAGE_WALLET_KEY = 'ssc:lastConnectedWallet';
const DEFAULT_CHAIN_ID = 1; // Ethereum Mainnet

// Minimal chain definition required for network switching
export const SUPPORTED_CHAINS: Record<
  number,
  { chainName: string; rpcUrls: string[] }
> = {
  1: { chainName: 'Ethereum Mainnet', rpcUrls: ['https://rpc.ankr.com/eth'] },
  5: { chainName: 'Goerli Testnet', rpcUrls: ['https://rpc.ankr.com/eth_goerli'] },
};

//////////////////////////////////////////////////////////////////////////////////////////
// Custom Errors
//////////////////////////////////////////////////////////////////////////////////////////

export class WalletNotConnectedError extends Error {
  constructor() {
    super('Wallet is not connected');
    this.name = 'WalletNotConnectedError';
  }
}

export class UnsupportedChainError extends Error {
  constructor(chainId: number) {
    super(`Chain "${chainId}" is not supported by StellarStage Carnival`);
    this.name = 'UnsupportedChainError';
  }
}

//////////////////////////////////////////////////////////////////////////////////////////
// WalletService – Singleton
//////////////////////////////////////////////////////////////////////////////////////////

class WalletService extends TypedEmitter<WalletEventMap> {
  private static _instance: WalletService;

  private _provider?: providers.Web3Provider;
  private _rawProvider?: any; // underlying provider (window.ethereum or WalletConnect)
  private _signer?: Signer;
  private _address: string | null = null;
  private _chainId: number = DEFAULT_CHAIN_ID;

  /** ---------------------------------------------------------------------
   * Public API
   * -------------------------------------------------------------------- */

  public static get instance(): WalletService {
    if (!WalletService._instance) {
      WalletService._instance = new WalletService();
    }
    return WalletService._instance;
  }

  /** Returns an ethers.js Web3Provider (throws if not connected) */
  public get provider(): providers.Web3Provider {
    if (!this._provider) throw new WalletNotConnectedError();
    return this._provider;
  }

  /** Returns Signer (throws if not connected) */
  public get signer(): Signer {
    if (!this._signer) throw new WalletNotConnectedError();
    return this._signer;
  }

  /** Address (null when disconnected) */
  public get address(): string | null {
    return this._address;
  }

  /** Current network chainId */
  public get chainId(): number {
    return this._chainId;
  }

  /** True if wallet currently connected */
  public get isConnected(): boolean {
    return !!this._provider && !!this._address;
  }

  /** Initiates connect flow with requested adapter */
  public async connect(adapter: WalletAdapter = WalletAdapter.MetaMask): Promise<void> {
    try {
      switch (adapter) {
        case WalletAdapter.MetaMask:
          await this._connectMetaMask();
          break;
        case WalletAdapter.WalletConnect:
          await this._connectWalletConnect();
          break;
        default:
          throw new Error(`Unknown adapter "${adapter}"`);
      }

      // Persist adapter for auto-reconnect
      window.localStorage.setItem(LOCAL_STORAGE_WALLET_KEY, adapter);
    } catch (err) {
      this.emit('error', { error: err as Error });
      throw err;
    }
  }

  /** Disconnect wallet and clear listeners */
  public async disconnect(): Promise<void> {
    if (this._rawProvider?.disconnect) {
      await this._rawProvider.disconnect();
    }

    this._teardownProviderListeners();

    this._provider = undefined;
    this._signer = undefined;
    this._rawProvider = undefined;
    this._address = null;
    this._chainId = DEFAULT_CHAIN_ID;

    window.localStorage.removeItem(LOCAL_STORAGE_WALLET_KEY);

    this.emit('disconnected');
  }

  /** Switch EVM network */
  public async switchNetwork(targetChainId: number): Promise<void> {
    const hexChainId = ethers.utils.hexValue(targetChainId);

    if (!this.isConnected) throw new WalletNotConnectedError();
    if (this._chainId === targetChainId) return;

    const provider: any = this._rawProvider;
    if (!provider?.request) throw new Error('Provider does not support RPC requests');

    try {
      await provider.request({
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: hexChainId }],
      });
    } catch (error: any) {
      // Chain not added to wallet
      if (error.code === 4902) {
        const chainParams = SUPPORTED_CHAINS[targetChainId];
        if (!chainParams) throw new UnsupportedChainError(targetChainId);

        await provider.request({
          method: 'wallet_addEthereumChain',
          params: [{ chainId: hexChainId, ...chainParams }],
        });
      } else {
        throw error;
      }
    }
  }

  /** Convenience wrapper around provider.sendTransaction */
  public async sendTransaction(
    tx: TransactionRequest,
  ): Promise<providers.TransactionResponse> {
    if (!this.isConnected) throw new WalletNotConnectedError();

    const populated = await this.signer.populateTransaction({
      ...tx,
      from: this.address!,
    });

    const response = await this.signer.sendTransaction(populated);

    this.emit('transactionSent', { hash: response.hash });

    return response;
  }

  /** EIP-712 signing */
  // eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types
  public async signTypedData(domain: any, types: any, value: any): Promise<string> {
    if (!this.isConnected) throw new WalletNotConnectedError();
    // ethers v5 doesn't support _signTypedData on JsonRpcSigner with WalletConnect < v2
    // Workaround: call personal_sign as fallback
    try {
      // @ts-ignore private method
      return await (this.signer as ethers.Signer & { _signTypedData: any })._signTypedData(
        domain,
        types,
        value,
      );
    } catch (err) {
      const data = JSON.stringify({ types, domain, message: value, primaryType: 'Data' });
      return await this.signer.signMessage(ethers.utils.id(data));
    }
  }

  /** Attempt auto-reconnect on page load */
  public async tryAutoReconnect(): Promise<void> {
    const remembered = window.localStorage.getItem(
      LOCAL_STORAGE_WALLET_KEY,
    ) as WalletAdapter | null;

    if (!remembered) return;

    try {
      await this.connect(remembered);
    } catch {
      // silent fail
      window.localStorage.removeItem(LOCAL_STORAGE_WALLET_KEY);
    }
  }

  /** ---------------------------------------------------------------------
   * Internal – Connection Implementations
   * -------------------------------------------------------------------- */

  private async _connectMetaMask(): Promise<void> {
    if (typeof window === 'undefined' || !(window as any).ethereum) {
      throw new Error('MetaMask is not installed');
    }

    const ethereum = (window as any).ethereum;

    const addresses: string[] = await ethereum.request({
      method: 'eth_requestAccounts',
    });

    this._rawProvider = ethereum;
    this._provider = new providers.Web3Provider(ethereum, 'any');
    this._signer = this._provider.getSigner();
    this._address = addresses[0];
    this._chainId = Number(ethereum.chainId || (await this._provider.getNetwork()).chainId);

    this._setupProviderListeners();

    this.emit('connected', { address: this._address, network: this._chainId });
  }

  private async _connectWalletConnect(): Promise<void> {
    const wcProvider = new WalletConnectProvider({
      rpc: Object.fromEntries(
        Object.entries(SUPPORTED_CHAINS).map(([k, v]) => [k, v.rpcUrls[0]]),
      ),
      chainId: DEFAULT_CHAIN_ID,
    });

    await wcProvider.enable();

    this._rawProvider = wcProvider;
    this._provider = new providers.Web3Provider(wcProvider, 'any');
    this._signer = this._provider.getSigner();
    this._address = await this._signer.getAddress();
    this._chainId = Number(wcProvider.chainId || DEFAULT_CHAIN_ID);

    this._setupProviderListeners();

    this.emit('connected', { address: this._address, network: this._chainId });
  }

  /** ---------------------------------------------------------------------
   * Event handler plumbing
   * -------------------------------------------------------------------- */

  private _setupProviderListeners(): void {
    if (!this._rawProvider?.on) return;

    this._rawProvider.on('accountsChanged', this._onAccountsChanged);
    this._rawProvider.on('chainChanged', this._onChainChanged);
    this._rawProvider.on('disconnect', this._onDisconnect);
  }

  private _teardownProviderListeners(): void {
    if (!this._rawProvider?.removeListener) return;

    this._rawProvider.removeListener('accountsChanged', this._onAccountsChanged);
    this._rawProvider.removeListener('chainChanged', this._onChainChanged);
    this._rawProvider.removeListener('disconnect', this._onDisconnect);
  }

  // Bind as arrow functions to preserve `this`
  private _onAccountsChanged = (accounts: string[]): void => {
    this._address = accounts[0] || null;
    this.emit('accountChanged', { address: this._address });
    // If no accounts, treat as disconnected
    if (!this._address) {
      this.disconnect().catch(() => void 0);
    }
  };

  private _onChainChanged = (hexChainId: string): void => {
    this._chainId = Number(hexChainId);
    this.emit('networkChanged', { network: this._chainId });
  };

  private _onDisconnect = (): void => {
    this.disconnect().catch(() => void 0);
  };
}

//////////////////////////////////////////////////////////////////////////////////////////
// Export singleton
//////////////////////////////////////////////////////////////////////////////////////////

export const walletService = WalletService.instance;
export default walletService;
```
