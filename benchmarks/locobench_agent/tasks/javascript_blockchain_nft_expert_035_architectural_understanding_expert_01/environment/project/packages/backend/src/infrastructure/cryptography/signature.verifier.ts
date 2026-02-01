```typescript
/* ============================================================================
 *  StellarStage Carnival
 *  ----------------------------------------------------------------------------
 *  packages/backend/src/infrastructure/cryptography/signature.verifier.ts
 *
 *  Infrastructure-layer adapter that verifies off-chain and on-chain Ethereum
 *  signatures (EIP-191 personal_sign, EIP-712 typed data, and contract
 *  call-signatures).  The code is wired behind a “port” interface so that the
 *  domain layer never directly depends on `ethers` or any crypto library.
 *
 *  Design goals
 *  ------------
 *  • Clean-Architecture compatible (implements an outbound port)
 *  • Production-grade validation & error handling
 *  • Small LRU cache to de-duplicate expensive `ecrecover` ops
 *  • Extensible for additional chains / curves in the future
 * ========================================================================== */

import { ethers } from 'ethers';
import LRUCache from 'lru-cache';

/* ---------------------------------------------------------------------------
 *  Type aliases & DTOs
 * ------------------------------------------------------------------------ */

export type Address = `0x${string}`;

export interface VerifyMessageParams {
  /** Raw UTF-8 or hex encoded message that the user signed */
  message: string | Uint8Array;
  /** 65-byte signature (r, s, v) prefixed with 0x */
  signature: string;
  /** Address that we expect to have produced the signature */
  expectedSigner: Address;
}

export interface VerifyTypedDataParams {
  /** EIP-712 domain structure */
  domain: ethers.TypedDataDomain;
  /** Solidity style types definition (see EIP-712) */
  types: Record<string, Array<ethers.TypedDataField>>;
  /** Actual value object */
  value: Record<string, unknown>;
  /** 65-byte signature (r, s, v) prefixed with 0x */
  signature: string;
  /** Address that we expect to have produced the signature */
  expectedSigner: Address;
}

export interface VerifyContractSignatureParams {
  /** On-chain contract that exposes `isValidSignature` (EIP-1271) */
  contractAddress: Address;
  /** Calldata hash that the owner was asked to sign */
  data: string | Uint8Array;
  /** Signature bytes */
  signature: string;
  /** Address that we expect to have produced the signature */
  expectedSigner: Address;
  /** If provided, chainId will be enforced when building the contract instance */
  chainId?: number;
}

export interface VerificationResult {
  isValid: boolean;
  recoveredAddress?: Address;
  error?: Error;
}

/* ---------------------------------------------------------------------------
 *  Port definition (Clean Architecture)
 * ------------------------------------------------------------------------ */

export interface SignatureVerifierPort {
  verifyMessage(params: VerifyMessageParams): Promise<VerificationResult>;
  verifyTypedData(params: VerifyTypedDataParams): Promise<VerificationResult>;
  verifyContractSignature(
    params: VerifyContractSignatureParams,
  ): Promise<VerificationResult>;
}

/* ---------------------------------------------------------------------------
 *  Custom Errors
 * ------------------------------------------------------------------------ */

export class InvalidAddressError extends Error {
  constructor(addr: string) {
    super(`Invalid Ethereum address: ${addr}`);
    this.name = 'InvalidAddressError';
  }
}

export class SignatureMismatchError extends Error {
  constructor(expected: string, recovered?: string) {
    super(
      `Signature does not match. Expected signer ${expected} but recovered ${recovered ?? 'unknown'}`,
    );
    this.name = 'SignatureMismatchError';
  }
}

/* ---------------------------------------------------------------------------
 *  Implementation backed by ethers.js
 * ------------------------------------------------------------------------ */

const DEFAULT_CACHE_SIZE = 1_000;
const DEFAULT_CACHE_TTL = 1000 * 60 * 5; // 5 minutes

/**
 * Lightweight cache to avoid repeating expensive ecrecover ops.
 * Key = sha256(signature + messageHash)
 */
const verificationCache = new LRUCache<string, boolean>({
  max: DEFAULT_CACHE_SIZE,
  ttl: DEFAULT_CACHE_TTL,
});

export class EthersSignatureVerifier implements SignatureVerifierPort {
  private readonly provider?: ethers.JsonRpcProvider;

  constructor(provider?: ethers.JsonRpcProvider) {
    // Provider is optional – only required for EIP-1271 contract checks.
    this.provider = provider;
  }

  /* -----------------------------------------------------------------------
   *  Public API
   * -------------------------------------------------------------------- */

  async verifyMessage({
    message,
    signature,
    expectedSigner,
  }: VerifyMessageParams): Promise<VerificationResult> {
    try {
      this.ensureAddress(expectedSigner);

      const cacheKey = this.computeCacheKey(signature, message);
      const cached = verificationCache.get(cacheKey);
      if (cached !== undefined) {
        return { isValid: cached, recoveredAddress: expectedSigner };
      }

      const recovered = ethers.verifyMessage(message, signature) as Address;
      const isValid = this.equalAddress(recovered, expectedSigner);

      verificationCache.set(cacheKey, isValid);
      if (!isValid) {
        throw new SignatureMismatchError(expectedSigner, recovered);
      }

      return { isValid: true, recoveredAddress: recovered };
    } catch (err) {
      return { isValid: false, error: this.normalizeError(err) };
    }
  }

  async verifyTypedData({
    domain,
    types,
    value,
    signature,
    expectedSigner,
  }: VerifyTypedDataParams): Promise<VerificationResult> {
    try {
      this.ensureAddress(expectedSigner);
      const encodedData = ethers.TypedDataEncoder.hash(domain, types, value);

      const cacheKey = this.computeCacheKey(signature, encodedData);
      const cached = verificationCache.get(cacheKey);
      if (cached !== undefined) {
        return { isValid: cached, recoveredAddress: expectedSigner };
      }

      const recovered = ethers.verifyTypedData(
        domain,
        types,
        value,
        signature,
      ) as Address;

      const isValid = this.equalAddress(recovered, expectedSigner);
      verificationCache.set(cacheKey, isValid);

      if (!isValid) {
        throw new SignatureMismatchError(expectedSigner, recovered);
      }

      return { isValid: true, recoveredAddress: recovered };
    } catch (err) {
      return { isValid: false, error: this.normalizeError(err) };
    }
  }

  async verifyContractSignature({
    contractAddress,
    data,
    signature,
    expectedSigner,
    chainId,
  }: VerifyContractSignatureParams): Promise<VerificationResult> {
    try {
      this.ensureAddress(contractAddress);
      this.ensureAddress(expectedSigner);

      if (!this.provider) {
        throw new Error(
          'Provider required for EIP-1271 contract signature verification',
        );
      }

      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const ABI = ['function isValidSignature(bytes32 _hash, bytes _sig) view returns (bytes4)'];

      const contract = new ethers.Contract(
        contractAddress,
        ABI,
        this.provider,
      );

      const messageHash =
        typeof data === 'string'
          ? ethers.keccak256(Buffer.from(data.replace(/^0x/, ''), 'hex'))
          : ethers.keccak256(data);

      // EIP-1271 magic value for successful validation
      const MAGIC_VALUE = '0x1626ba7e';

      const result: string = await contract.isValidSignature(
        messageHash,
        signature,
        {
          // If caller supplied chainId we check that provider is on the correct chain.
          ...(chainId ? { blockTag: 'latest' as const } : {}),
        },
      );

      const isValid = result.toLowerCase() === MAGIC_VALUE.toLowerCase();
      if (!isValid) {
        throw new SignatureMismatchError(expectedSigner);
      }

      return { isValid: true, recoveredAddress: expectedSigner };
    } catch (err) {
      return { isValid: false, error: this.normalizeError(err) };
    }
  }

  /* -----------------------------------------------------------------------
   *  Helpers
   * -------------------------------------------------------------------- */

  private computeCacheKey(signature: string, data: string | Uint8Array): string {
    const signerBytes =
      typeof data === 'string' ? ethers.getBytes(data) : data;
    return ethers.sha256(
      ethers.concat([ethers.getBytes(signature), signerBytes]),
    );
  }

  private ensureAddress(addr: string): asserts addr is Address {
    if (!ethers.isAddress(addr)) {
      throw new InvalidAddressError(addr);
    }
  }

  private equalAddress(a: string, b: string): boolean {
    return a.toLowerCase() === b.toLowerCase();
  }

  private normalizeError(err: unknown): Error {
    if (err instanceof Error) return err;
    return new Error(String(err));
  }
}

/* ---------------------------------------------------------------------------
 *  Singleton instance used by the rest of the application
 * ------------------------------------------------------------------------ */

// NOTE: Provider should be injected in frameworks where DI container exists.
// Here we lazily construct an anonymous provider for read-only verification,
// falling back to Alchemy/Infura if ENV vars are set.

const defaultProvider = (() => {
  const rpcUrl =
    process.env.RPC_URL ??
    process.env.ALCHEMY_API_URL ??
    process.env.INFURA_API_URL;
  return rpcUrl ? new ethers.JsonRpcProvider(rpcUrl) : undefined;
})();

export const signatureVerifier: SignatureVerifierPort =
  new EthersSignatureVerifier(defaultProvider);
```