```typescript
/**
 * StellarStage Carnival – Hardhat Configuration
 * ----------------------------------------------
 * This file wires together Solidity compiler versions, common Hardhat plugins,
 * network endpoints (Ethereum / L2 roll-ups), named accounts, Etherscan APIs,
 * forked–mainnet testing, gas reporting and custom tasks.  It adheres to Clean
 * Architecture by remaining strictly in the infrastructure layer: no business
 * logic from the domain/use-case tiers leaks in here.
 *
 * ENVIRONMENT VARIABLES
 * ---------------------
 * • PRIVATE_KEYS               Comma-separated list of private keys used for deployments
 * • MNEMONIC                   12/24-word mnemonic as an alternative to PRIVATE_KEYS
 * • INFURA_API_KEY             Infura project id
 * • ALCHEMY_API_KEY            Alchemy key (used if INFURA_API_KEY not supplied)
 * • ETHERSCAN_API_KEY          Mainnet / Goerli explorers
 * • POLYGONSCAN_API_KEY        Polygon / Mumbai explorers
 * • OP_ETHERSCAN_API_KEY       Optimism / Optimism Goerli explorers
 * • MAINNET_FORK_URL           Custom RPC URL for mainnet forking (defaults to Infura)
 * • REPORT_GAS=true            Enable gas reporter
 */

import * as dotenv from 'dotenv';
import { HardhatUserConfig, task } from 'hardhat/config';
import { NetworkUserConfig } from 'hardhat/types';

import '@nomiclabs/hardhat-ethers';
import '@nomiclabs/hardhat-waffle';
import '@nomiclabs/hardhat-etherscan';
import '@typechain/hardhat';
import 'hardhat-gas-reporter';
import 'hardhat-contract-sizer';
import 'hardhat-deploy';
import 'hardhat-abi-exporter';
import '@openzeppelin/hardhat-upgrades';
import 'solidity-coverage';

dotenv.config();

/* -------------------------------------------------------------------------- */
/*                               Helper Utilities                             */
/* -------------------------------------------------------------------------- */

/**
 * Safely fetches an environment variable.
 */
const env = (key: string, def?: string, required = false): string | undefined => {
  const value = process.env[key] || def;
  if (required && (value === undefined || value === '')) {
    throw new Error(`Environment variable ${key} is required but missing`);
  }
  return value;
};

/**
 * Builds the accounts array for the network configuration. Priority:
 * PRIVATE_KEYS > MNEMONIC > Hardhat in-memory accounts.
 */
const getAccounts = (): string[] | { mnemonic: string } | undefined => {
  const keys = env('PRIVATE_KEYS');
  if (keys && keys.trim() !== '') {
    return keys.split(',').map((k) => k.trim());
  }
  const mnemonic = env('MNEMONIC');
  if (mnemonic && mnemonic.trim() !== '') {
    return { mnemonic: mnemonic.trim() };
  }
  return undefined; // Explicitly undefined lets Hardhat generate accounts
};

/**
 * Constructs a network object with sensible defaults.
 */
const buildNetwork = (
  network: string,
  chainId: number,
  urlSuffix = network
): NetworkUserConfig => ({
  chainId,
  url: `https://${urlSuffix}.infura.io/v3/${env('INFURA_API_KEY', env('ALCHEMY_API_KEY'))}`,
  accounts: getAccounts(),
  // Deployment-related Hardhat Deploy options
  live: network !== 'hardhat' && network !== 'localhost',
  saveDeployments: network !== 'hardhat',
  tags: [network],
});

/* -------------------------------------------------------------------------- */
/*                                Custom Tasks                                */
/* -------------------------------------------------------------------------- */

// Prints the list of available accounts (derives them at runtime)
task('accounts', 'Prints the list of accounts', async (args, hre) => {
  const signers = await hre.ethers.getSigners();
  signers.forEach((s, idx) => console.log(`Account #${idx}: ${s.address}`));
});

// Quick check helper to confirm proxy implementation addresses
task(
  'proxy:impl',
  'Returns current implementation for a proxy',
  async ({ proxyAddress }, hre) => {
    if (!proxyAddress) {
      throw new Error('Please provide --proxy-address argument');
    }
    const implSlot =
      '0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc';

    const implAddr = await hre.ethers.provider.getStorageAt(proxyAddress, implSlot);
    console.log(
      `Implementation for proxy ${proxyAddress} is ${hre.ethers.utils.getAddress(
        `0x${implAddr.slice(26)}`
      )}`
    );
  }
).addParam('proxyAddress', 'Proxy contract address');

/* -------------------------------------------------------------------------- */
/*                              Hardhat Config                                */
/* -------------------------------------------------------------------------- */

const config: HardhatUserConfig = {
  defaultNetwork: 'hardhat',

  networks: {
    // In-memory network with mainnet forking for realistic integration tests
    hardhat: {
      chainId: 31337,
      forking: env('MAINNET_FORK_URL')
        ? { url: env('MAINNET_FORK_URL', '', true)! }
        : {
            url: `https://mainnet.infura.io/v3/${env(
              'INFURA_API_KEY',
              env('ALCHEMY_API_KEY'),
              true
            )}`,
            blockNumber: 18_000_000, // deterministic snapshot
          },
      accounts: getAccounts(),
    },

    localhost: {
      url: 'http://127.0.0.1:8545',
      chainId: 31337,
      accounts: getAccounts(),
    },

    goerli: buildNetwork('goerli', 5),
    mainnet: buildNetwork('mainnet', 1, 'mainnet'),

    // Polygon
    mumbai: {
      chainId: 80001,
      url: `https://polygon-mumbai.infura.io/v3/${env('INFURA_API_KEY')}`,
      accounts: getAccounts(),
      tags: ['mumbai'],
    },
    polygon: {
      chainId: 137,
      url: `https://polygon-mainnet.infura.io/v3/${env('INFURA_API_KEY')}`,
      accounts: getAccounts(),
      tags: ['polygon'],
    },

    // Optimism
    'optimism-goerli': {
      chainId: 420,
      url: `https://optimism-goerli.infura.io/v3/${env('INFURA_API_KEY')}`,
      accounts: getAccounts(),
      tags: ['optimism-goerli'],
    },
    optimism: {
      chainId: 10,
      url: `https://optimism-mainnet.infura.io/v3/${env('INFURA_API_KEY')}`,
      accounts: getAccounts(),
      tags: ['optimism'],
    },
  },

  solidity: {
    compilers: [
      {
        version: '0.8.19',
        settings: {
          optimizer: {
            enabled: true,
            runs: 800,
          },
          outputSelection: {
            '*': {
              '*': ['storageLayout'], // needed for proxy upgrades
            },
          },
        },
      },
      {
        version: '0.7.6',
        settings: {
          optimizer: { enabled: true, runs: 800 },
        },
      },
    ],
  },

  etherscan: {
    apiKey: {
      mainnet: env('ETHERSCAN_API_KEY'),
      goerli: env('ETHERSCAN_API_KEY'),
      polygon: env('POLYGONSCAN_API_KEY'),
      polygonMumbai: env('POLYGONSCAN_API_KEY'),
      optimisticEthereum: env('OP_ETHERSCAN_API_KEY'),
      optimisticGoerli: env('OP_ETHERSCAN_API_KEY'),
    },
  },

  namedAccounts: {
    deployer: {
      default: 0, // first account
    },
    performer: {
      default: 1,
    },
    governor: {
      default: 2,
    },
  },

  gasReporter: {
    enabled: env('REPORT_GAS') === 'true',
    currency: 'USD',
    coinmarketcap: env('COINMARKETCAP_API_KEY'),
    showTimeSpent: true,
    excludeContracts: ['mocks', 'test'],
  },

  abiExporter: {
    path: './abi',
    runOnCompile: false,
    flat: true,
    spacing: 2,
  },

  typechain: {
    outDir: 'typechain',
    target: 'ethers-v5',
  },

  contractSizer: {
    alphaSort: false,
    runOnCompile: true,
    strict: false,
  },

  paths: {
    sources: './src/contracts',
    tests: './src/tests',
    deploy: './src/deploy',
    cache: './cache',
    artifacts: './artifacts',
  },

  mocha: {
    timeout: 400_000,
  },
};

export default config;
```