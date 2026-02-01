```typescript
/* eslint-disable @typescript-eslint/no-use-before-define */
/*  StellarStage Carnival – User store slice
 *
 *  This slice is responsible for all user–related client-state:
 *  – Wallet connection & chain metadata
 *  – Owned Show-Pass NFTs
 *  – Pass staking workflow
 *  – Local UI preferences
 *
 *  It leverages Redux-Toolkit for ergonomics while staying framework-agnostic.
 *  Business rules (minting, staking, etc.) remain in dedicated
 *  ‘use-case’ services inside the domain layer; the slice only orchestrates
 *  front-end concerns and invokes those services through adapters.
 */

import {
  createAsyncThunk,
  createSlice,
  PayloadAction,
} from '@reduxjs/toolkit';
import type { RootState, AppDispatch } from '../store';
import walletAdapter from '../adapters/wallet.adapter';
import userApi from '../adapters/user.api';
import blockchainAdapter from '../adapters/blockchain.adapter';

/* ------------------------------------------------------------------------
 * Type definitions
 * --------------------------------------------------------------------- */

export interface WalletState {
  address: string | null;
  networkId: number | null;
  isConnected: boolean;
  // Non-critical chain metadata for UX purposes
  ensName?: string | null;
}

export interface Pass {
  tokenId: string;
  showId: string;
  level: number;
  image: string;
  staked: boolean;
  lastUpdated: string; // ISO-date
}

export interface PreferenceState {
  audioEnabled: boolean;
  quality: 'low' | 'medium' | 'high' | 'ultra';
  theme: 'light' | 'dark' | 'system';
}

export interface LoadingState {
  connectWallet: boolean;
  fetchPasses: boolean;
  stakePass: Record<string, boolean>; // keyed by tokenId
}

export interface UserState {
  wallet: WalletState;
  passes: Pass[];
  preferences: PreferenceState;
  loading: LoadingState;
  error: string | null;
}

/* ------------------------------------------------------------------------
 * Async thunks
 * --------------------------------------------------------------------- */

/**
 * Connects an injected wallet (e.g. Metamask, WalletConnect),
 * returning the user address & network id. Aborts when user rejects.
 */
export const connectWallet = createAsyncThunk<
  { address: string; networkId: number; ensName?: string | null },
  void,
  { rejectValue: string }
>('user/connectWallet', async (_, { rejectWithValue }) => {
  try {
    const res = await walletAdapter.connect();
    return res;
  } catch (err) {
    return rejectWithValue((err as Error).message);
  }
});

/**
 * Retrieves all Show-Pass NFTs owned by the connected wallet.
 */
export const fetchUserPasses = createAsyncThunk<
  Pass[],
  void,
  { state: RootState; rejectValue: string }
>('user/fetchUserPasses', async (_, { getState, rejectWithValue }) => {
  try {
    const { address } = getState().user.wallet;
    if (!address) throw new Error('Wallet not connected');
    const passes = await userApi.getPassesByOwner(address);
    return passes;
  } catch (err) {
    return rejectWithValue((err as Error).message);
  }
});

/**
 * Stakes a single pass so the owner can participate in on-chain governance
 * & yield farming. Updates both blockchain and backend indexer.
 */
export const stakePass = createAsyncThunk<
  { tokenId: string },
  string, // tokenId
  { state: RootState; rejectValue: string }
>('user/stakePass', async (tokenId, { getState, rejectWithValue }) => {
  try {
    const { address } = getState().user.wallet;
    if (!address) throw new Error('Wallet not connected');

    await blockchainAdapter.stakePass({ tokenId, from: address });

    // Optimistic backend acknowledgement (non-blocking)
    userApi
      .markPassStaked(tokenId)
      .catch((e) => console.warn('Failed to mark pass staked', e));

    return { tokenId };
  } catch (err) {
    return rejectWithValue((err as Error).message);
  }
});

/* ------------------------------------------------------------------------
 * Initial state
 * --------------------------------------------------------------------- */

const initialState = (): UserState => ({
  wallet: {
    address: null,
    networkId: null,
    isConnected: false,
    ensName: null,
  },
  passes: [],
  preferences: loadPreferences(),
  loading: {
    connectWallet: false,
    fetchPasses: false,
    stakePass: {},
  },
  error: null,
});

/* ------------------------------------------------------------------------
 * Slice definition
 * --------------------------------------------------------------------- */

const userSlice = createSlice({
  name: 'user',
  initialState: initialState(),
  reducers: {
    resetUserState: () => initialState(),
    updatePreference: (
      state,
      action: PayloadAction<Partial<PreferenceState>>,
    ) => {
      state.preferences = { ...state.preferences, ...action.payload };
      persistPreferences(state.preferences);
    },
    signOut: (state) => {
      // Soft-sign-out keeps prefs but wipes sensitive data
      state.wallet = initialState().wallet;
      state.passes = [];
    },
  },
  extraReducers: (builder) => {
    /* ---- connectWallet ------------------------------------------------ */
    builder
      .addCase(connectWallet.pending, (state) => {
        state.loading.connectWallet = true;
        state.error = null;
      })
      .addCase(connectWallet.fulfilled, (state, action) => {
        state.loading.connectWallet = false;
        state.wallet = {
          ...action.payload,
          isConnected: true,
        };
      })
      .addCase(connectWallet.rejected, (state, action) => {
        state.loading.connectWallet = false;
        state.error = action.payload ?? 'Unknown wallet error';
      });

    /* ---- fetchUserPasses ---------------------------------------------- */
    builder
      .addCase(fetchUserPasses.pending, (state) => {
        state.loading.fetchPasses = true;
        state.error = null;
      })
      .addCase(fetchUserPasses.fulfilled, (state, action) => {
        state.loading.fetchPasses = false;
        state.passes = action.payload;
      })
      .addCase(fetchUserPasses.rejected, (state, action) => {
        state.loading.fetchPasses = false;
        state.error = action.payload ?? 'Unable to fetch passes';
      });

    /* ---- stakePass ----------------------------------------------------- */
    builder
      .addCase(stakePass.pending, (state, action) => {
        const tokenId = action.meta.arg;
        state.loading.stakePass[tokenId] = true;
        state.error = null;
      })
      .addCase(stakePass.fulfilled, (state, action) => {
        const { tokenId } = action.payload;
        state.loading.stakePass[tokenId] = false;
        const pass = state.passes.find((p) => p.tokenId === tokenId);
        if (pass) pass.staked = true;
      })
      .addCase(stakePass.rejected, (state, action) => {
        const tokenId = action.meta.arg;
        state.loading.stakePass[tokenId] = false;
        state.error = action.payload ?? `Failed to stake pass #${tokenId}`;
      });
  },
});

/* ------------------------------------------------------------------------
 * Selectors
 * --------------------------------------------------------------------- */

export const selectWallet = (state: RootState) => state.user.wallet;
export const selectPasses = (state: RootState) => state.user.passes;
export const selectPreferences = (state: RootState) => state.user.preferences;
export const selectIsLoading = (state: RootState) => state.user.loading;
export const selectUserError = (state: RootState) => state.user.error;

/* ------------------------------------------------------------------------
 * Preference persistence helpers
 * --------------------------------------------------------------------- */

const PREF_STORAGE_KEY = 'stellarStagePrefs';

function loadPreferences(): PreferenceState {
  try {
    const raw = localStorage.getItem(PREF_STORAGE_KEY);
    if (!raw) throw new Error('No prefs');
    return JSON.parse(raw) as PreferenceState;
  } catch {
    return {
      audioEnabled: true,
      quality: 'high',
      theme: 'system',
    };
  }
}

function persistPreferences(prefs: PreferenceState): void {
  try {
    localStorage.setItem(PREF_STORAGE_KEY, JSON.stringify(prefs));
  } catch (err) {
    // Storage might be unavailable (Safari private mode etc.)
    console.warn('Failed to persist preferences:', err);
  }
}

/* ------------------------------------------------------------------------
 * Exports
 * --------------------------------------------------------------------- */

export const { resetUserState, updatePreference, signOut } = userSlice.actions;

export default userSlice.reducer;

/* ------------------------------------------------------------------------
 * Typed hooks (optional, can be placed in a separate file)
 * --------------------------------------------------------------------- */

export const fetchUserDataFlow =
  () =>
  async (dispatch: AppDispatch, getState: () => RootState): Promise<void> => {
    // Connect wallet if not already
    const { wallet } = getState().user;
    if (!wallet.isConnected) {
      await dispatch(connectWallet());
    }
    // Hydrate passes
    await dispatch(fetchUserPasses());
  };
```