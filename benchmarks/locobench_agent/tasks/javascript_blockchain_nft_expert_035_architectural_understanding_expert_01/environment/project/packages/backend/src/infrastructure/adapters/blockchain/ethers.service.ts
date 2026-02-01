```typescript
/******************************************************************************************
 * StellarStage Carnival – Ethers infrastructure adapter
 *
 * This module provides a thin but production-ready wrapper around ethers.js that is used
 * by application-level use-cases (MintShowPass, StakePass, DistributeLoot, …) via an
 * abstract “BlockchainPort”.  The class takes care of
 *   • provider / signer boot-strapping
 *   • safe gas-estimation & automatic gas-margin padding
 *   • common transaction life-cycle helpers (waitForTx, getReceipt, …)
 *   • minimal proxy-deployment helper for upgradeable contracts
 *   • typed contract factory / loader
 *   • basic event-listening utilities
 *
 * NOTE: All domain logic is intentionally kept out of this file – this is *purely* an
 *       infrastructure concern in accordance with Clean Architecture guidelines.
 ******************************************************************************************/

import * as dotenv from 'dotenv';
import { ethers, providers, Wallet, Contract, ContractFactory, BigNumberish } from 'ethers';
import { Typed } from '@ethersproject/abi'; // handy helper for typed event args (optional)
import assert from 'assert';

dotenv.config();

/* -------------------------------------------------------------------------- */
/*                                 Interfaces                                 */
/* -------------------------------------------------------------------------- */

export interface ContractArtifact {
    abi: any;
    bytecode: string;
    /* Optional:  metadata / source map, etc. are ignored by this adapter   */
}

export interface EthersServiceOptions {
    rpcUrl: string;
    privateKey: string;
    chainId: number;
    defaultConfirmations: number;
    gasLimitBuffer: number;   // e.g. 1.2 => +20 %
    gasPriceMultiplier: number;
}

/**
 * Interface describing the publicly consumed surface of the service.
 * (“BlockchainPort” in domain language)
 */
export interface IEthersService {
    getProvider(): providers.Provider;
    getSigner(): Wallet;

    loadContract<T extends Contract = Contract>(
        address: string,
        abi: any,
        signerOrProvider?: Wallet | providers.Provider
    ): T;

    deployProxy(
        implementationArtifact: ContractArtifact,
        initializeArgs?: readonly any[]
    ): Promise<Contract>;

    sendTransaction(
        tx: providers.TransactionRequest,
        confirmations?: number
    ): Promise<providers.TransactionReceipt>;

    waitForTx(
        txHash: string,
        confirmations?: number
    ): Promise<providers.TransactionReceipt>;

    estimateGas(tx: providers.TransactionRequest): Promise<ethers.BigNumber>;

    on<E extends readonly unknown[]>(
        contract: Contract,
        event: string,
        cb: (...args: E) => void
    ): void;

    removeListener(
        contract: Contract,
        event: string,
        cb: (...args: any[]) => void
    ): void;
}

/* -------------------------------------------------------------------------- */
/*                                  Service                                   */
/* -------------------------------------------------------------------------- */

export class EthersService implements IEthersService {
    /* Singleton holder – prevents multiple providers in serverless contexts */
    private static _instance: EthersService;

    public static get instance(): EthersService {
        if (!EthersService._instance) {
            EthersService._instance = new EthersService();
        }
        return EthersService._instance;
    }

    /* ---------------------------------------------------------------------- */

    private readonly provider: providers.JsonRpcProvider;
    private readonly signer: Wallet;
    private readonly options: EthersServiceOptions;

    private constructor(customOptions?: Partial<EthersServiceOptions>) {
        /* 1️⃣  Assemble effective options (env ▶ default ▶ overrides) */
        const defaults: EthersServiceOptions = {
            rpcUrl: process.env.BLOCKCHAIN_RPC_URL || 'http://127.0.0.1:8545',
            privateKey: process.env.BLOCKCHAIN_PRIVATE_KEY || '',
            chainId: +(process.env.BLOCKCHAIN_CHAIN_ID || 1337),
            defaultConfirmations: parseInt(process.env.BLOCKCHAIN_CONFIRMATIONS || '1', 10),
            gasLimitBuffer: 1.2,
            gasPriceMultiplier: 1.1
        };
        this.options = { ...defaults, ...(customOptions || {}) };

        /* 2️⃣  Provider / signer boot-strap with runtime validations          */
        assert.ok(this.options.privateKey, 'Missing private key for signer');
        this.provider = new ethers.providers.JsonRpcProvider(
            this.options.rpcUrl,
            this.options.chainId
        );
        this.signer = new Wallet(this.options.privateKey, this.provider);
    }

    /* ---------------------------------------------------------------------- */
    /*                                Getters                                 */
    /* ---------------------------------------------------------------------- */

    public getProvider(): providers.Provider {
        return this.provider;
    }

    public getSigner(): Wallet {
        return this.signer;
    }

    /* ---------------------------------------------------------------------- */
    /*                              Tx helpers                                */
    /* ---------------------------------------------------------------------- */

    /**
     * Estimate gas, apply buffer, fetch gasPrice (EIP-1559 aware), then sign+send
     */
    public async sendTransaction(
        tx: providers.TransactionRequest,
        confirmations = this.options.defaultConfirmations
    ): Promise<providers.TransactionReceipt> {
        const populated: providers.TransactionRequest = await this.populateTx(tx);
        const response = await this.signer.sendTransaction(populated);
        return await response.wait(confirmations);
    }

    /**
     * Wait for an already-submitted tx-hash
     */
    public async waitForTx(txHash: string, confirmations = this.options.defaultConfirmations) {
        return await this.provider.waitForTransaction(txHash, confirmations);
    }

    /**
     * Populates missing transaction parameters (gas, gasPrice, nonce, …)
     */
    private async populateTx(
        tx: providers.TransactionRequest
    ): Promise<providers.TransactionRequest> {
        // gas limit
        if (!tx.gasLimit) {
            const est = await this.estimateGas(tx);
            tx.gasLimit = est;
        }

        // gasPrice or EIP-1559 fees
        if (!tx.gasPrice && (!tx.maxFeePerGas || !tx.maxPriorityFeePerGas)) {
            const feeData = await this.provider.getFeeData();
            if (feeData.maxFeePerGas && feeData.maxPriorityFeePerGas) {
                // Prefer EIP-1559 when available
                tx.maxFeePerGas = feeData.maxFeePerGas
                    .mul(Math.round(this.options.gasPriceMultiplier * 100))
                    .div(100);
                tx.maxPriorityFeePerGas = feeData.maxPriorityFeePerGas
                    .mul(Math.round(this.options.gasPriceMultiplier * 100))
                    .div(100);
            } else if (feeData.gasPrice) {
                tx.gasPrice = feeData.gasPrice
                    .mul(Math.round(this.options.gasPriceMultiplier * 100))
                    .div(100);
            }
        }

        // chainId, nonce
        tx.chainId = tx.chainId ?? this.options.chainId;
        tx.nonce = tx.nonce ?? (await this.signer.getTransactionCount('pending'));

        return tx;
    }

    /**
     * Estimate gas w/ buffer to reduce out-of‐gas (defaults to +20 %)
     */
    public async estimateGas(
        tx: providers.TransactionRequest | Contract
    ): Promise<ethers.BigNumber> {
        let estimate: ethers.BigNumber;
        if (tx instanceof Contract) {
            throw new Error('Cannot estimate gas for raw contract; call method estimateGas.*');
        } else {
            estimate = await this.provider.estimateGas(tx);
        }

        return estimate
            .mul(Math.round(this.options.gasLimitBuffer * 100))
            .div(100);
    }

    /* ---------------------------------------------------------------------- */
    /*                       Contract deployment / proxies                    */
    /* ---------------------------------------------------------------------- */

    /**
     * Deploy an implementation contract and wrap it with an OpenZeppelin Transparent
     * Upgradeable Proxy.  Returns a contract instance that is already connected to the
     * signer and uses the implementation’s ABI.  Only *very* light-weight: for truly
     * complex deployments use Hardhat upgrades-plugin in scripts.
     */
    public async deployProxy(
        implementationArtifact: ContractArtifact,
        initializeArgs: readonly any[] = []
    ): Promise<Contract> {
        // 1) Deploy implementation
        const implFactory = new ContractFactory(
            implementationArtifact.abi,
            implementationArtifact.bytecode,
            this.signer
        );

        const implContract = await implFactory.deploy();
        await implContract.deployed();

        // 2) Encode initializer data
        const initCalldata = implContract.interface.encodeFunctionData(
            'initialize',
            initializeArgs
        );

        // 3) Deploy proxy (using OpenZeppelin factory artefact shipped with NPM)
        //    We inline ABI for tiny footprint, bytecode pulled from env/artefacts.
        const PROXY_ABI = [
            'constructor(address _logic,address admin,bytes memory _data)',
            'function implementation() public view returns (address)'
        ];
        const PROXY_BYTECODE =
            process.env.OZ_TRANSPARENT_PROXY_BYTECODE || // optionally injected at build-time
            '0x'; // ⚠ placeholder – should be replaced with compiled bytecode

        assert.ok(
            PROXY_BYTECODE !== '0x',
            'TransparentUpgradeableProxy bytecode missing. ' +
                'Provide via env OZ_TRANSPARENT_PROXY_BYTECODE.'
        );

        const proxyFactory = new ContractFactory(PROXY_ABI, PROXY_BYTECODE, this.signer);

        const proxy = await proxyFactory.deploy(
            implContract.address,
            this.signer.address,
            initCalldata
        );
        await proxy.deployed();

        return new Contract(proxy.address, implementationArtifact.abi, this.signer);
    }

    /* ---------------------------------------------------------------------- */
    /*                                Contracts                               */
    /* ---------------------------------------------------------------------- */

    public loadContract<T extends Contract = Contract>(
        address: string,
        abi: any,
        signerOrProvider: Wallet | providers.Provider = this.signer
    ): T {
        return new Contract(address, abi, signerOrProvider) as T;
    }

    /* ---------------------------------------------------------------------- */
    /*                              Event helpers                             */
    /* ---------------------------------------------------------------------- */

    public on<E extends readonly unknown[]>(
        contract: Contract,
        event: string,
        cb: (...args: E) => void
    ): void {
        contract.on(event, (...args) => {
            /* Last argument is Event Object with tx data – we keep API small */
            // eslint-disable-next-line @typescript-eslint/no-unsafe-argument
            cb(...(args as unknown as E));
        });
    }

    public removeListener(contract: Contract, event: string, cb: (...args: any[]) => void): void {
        contract.off(event, cb);
    }
}

/* -------------------------------------------------------------------------- */
/*                              Helper functions                              */
/* -------------------------------------------------------------------------- */

/**
 * Parse a VM revert reason (EIP-838).  ethers v5 already decodes many errors but
 * sometimes we need manual fall-back for old nodes.
 */
export function parseRevertReason(error: any): string | null {
    try {
        if (error?.data?.message) return error.data.message;
        if (typeof error === 'string') return error;
        if (error?.error?.message) return error.error.message;
        return null;
    } catch {
        return null;
    }
}

/* -------------------------------------------------------------------------- */
/*                               Module exports                               */
/* -------------------------------------------------------------------------- */

export default EthersService.instance;
```