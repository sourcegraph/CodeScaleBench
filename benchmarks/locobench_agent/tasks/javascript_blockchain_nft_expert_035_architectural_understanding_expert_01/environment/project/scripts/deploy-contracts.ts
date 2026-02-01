```typescript
/**
 * scripts/deploy-contracts.ts
 *
 * Deployment entry-point for StellarStage Carnival smart-contracts.
 * The script bootstraps upgradeable proxies, persists addresses per-network,
 * and optionally verifies source on Etherscan / Blockscout.
 *
 * Usage:
 *  npx ts-node --transpile-only scripts/deploy-contracts.ts --network=<network>
 *
 * Environment variables (see `.env.example`):
 *  - ETHERSCAN_API_KEY=<apikey>       // Optional, for contract verification
 *  - DEPLOYER_PK=<hex-private-key>    // Deployer signer
 *  - IPFS_API=<url>                   // Optional, for metadata uploads
 */

import 'dotenv/config';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import { join } from 'path';
import chalk from 'chalk';
import yargs from 'yargs/yargs';
import { hideBin } from 'yargs/helpers';
import { ethers, upgrades, run, network } from 'hardhat';

/* ---------- Types & Constants ------------------------------------------------ */

type DeploymentRecord = Record<
  string, // Contract name
  {
    proxy: string;           // Proxy address
    implementation: string;  // Implementation logic address
    txHash: string;          // Deployment transaction hash
    block: number;           // Deployment block
  }
>;

const DEPLOYMENTS_DIR = join(__dirname, '../deployments');

/* ---------- Helpers ---------------------------------------------------------- */

/**
 * Persist deployed contract addresses to /deployments/<chainId>.json
 */
function saveDeployment(
  chainId: number | string,
  contractName: string,
  details: DeploymentRecord[string],
): void {
  const filePath = join(DEPLOYMENTS_DIR, `${chainId}.json`);

  let records: DeploymentRecord = {};
  if (existsSync(filePath)) {
    records = JSON.parse(readFileSync(filePath, 'utf-8'));
  } else if (!existsSync(DEPLOYMENTS_DIR)) {
    mkdirSync(DEPLOYMENTS_DIR);
  }

  records[contractName] = details;
  writeFileSync(filePath, JSON.stringify(records, null, 2));
  console.log(chalk.green(`📒  Saved deployment: ${filePath}`));
}

/**
 * Attempt to verify contract source on Etherscan / Blockscout.
 */
async function verifyContract(address: string, constructorArgs: any[]): Promise<void> {
  if (!process.env.ETHERSCAN_API_KEY) {
    console.log(chalk.yellow('⚠️  Skipping verification – ETHERSCAN_API_KEY not set'));
    return;
  }

  try {
    await run('verify:verify', { address, constructorArguments: constructorArgs });
    console.log(chalk.green(`🔍  Verified: ${address}`));
  } catch (err: any) {
    // Already verified or other non-critical error
    if (err.message?.toLowerCase().includes('already verified')) {
      console.log(chalk.cyan('ℹ️   Already verified'));
    } else {
      console.error(chalk.red(`Verification failed: ${err.message}`));
    }
  }
}

/**
 * Deploy an upgradeable proxy + implementation pair using the OpenZeppelin plugin.
 */
async function deployProxy(
  contractName: string,
  constructorArgs: any[] = [],
  initializer = 'initialize',
) {
  console.log(chalk.blue(`🚀  Deploying ${contractName} Proxy…`));

  const Factory = await ethers.getContractFactory(contractName);
  const instance = await upgrades.deployProxy(Factory, constructorArgs, {
    initializer,
    kind: 'uups',
  });

  await instance.deployed();
  const proxyAddress = instance.address;

  // Fetch implementation address for records
  const implAddress = await upgrades.erc1967.getImplementationAddress(proxyAddress);
  const receipt = await instance.deployTransaction.wait();

  console.log(
    chalk.green(`✅  ${contractName} deployed`),
    '\n   ↳ proxy          :', proxyAddress,
    '\n   ↳ implementation :', implAddress,
    '\n   ↳ tx hash        :', receipt.transactionHash,
  );

  // Persist to filesystem
  saveDeployment(receipt.network.chainId, contractName, {
    proxy: proxyAddress,
    implementation: implAddress,
    txHash: receipt.transactionHash,
    block: receipt.blockNumber,
  });

  // Verify implementation (proxy has no source)
  await verifyContract(implAddress, []);

  return instance;
}

/* ---------- Main ---------------------------------------------------------------- */

async function main(): Promise<void> {
  /* 1. CLI & network sanity checks ------------------------------------------------*/
  const argv = yargs(hideBin(process.argv))
    .option('verify', {
      type: 'boolean',
      default: true,
      description: 'Verify contracts after deployment',
    })
    .parseSync();

  const [deployer] = await ethers.getSigners();

  console.log(chalk.magenta('🏗  StellarStage Carnival — Contract Deployment'));
  console.log(`\nNetwork     : ${network.name} (${await deployer.getChainId()})`);
  console.log(`Deployer    : ${deployer.address}`);
  console.log(`Balance     : ${ethers.utils.formatEther(await deployer.getBalance())} ETH\n`);

  /* 2. Deploy contracts ----------------------------------------------------------*/
  // a) ShowPass (ERC-721 upgradable)
  const showPass = await deployProxy('ShowPass', [
    'StellarStage Show Pass',  // name
    'SSC',                     // symbol
    'ipfs://base-uri',         // base tokenURI
  ]);

  // b) LootVault (ERC-1155 loot drops)
  const lootVault = await deployProxy('LootVault', []);

  // c) CarnivalGovernor (Governor & Timelock compound)
  const timelockDelay = 60 * 60 * 24; // 24h
  const governor = await deployProxy('CarnivalGovernor', [
    showPass.address,
    timelockDelay,
  ]);

  // d) Registry (ties everything together)
  const registry = await deployProxy('ShowRegistry', [
    showPass.address,
    lootVault.address,
    governor.address,
  ]);

  /* 3. Post-deployment hooks -----------------------------------------------------*/
  console.log(chalk.cyan('\n🔗  Wiring contract references…'));
  await (await showPass.setRegistry(registry.address)).wait();
  await (await lootVault.setRegistry(registry.address)).wait();

  console.log(chalk.green('🎉  Deployment complete!'));
}

/* ---------- Bootstrap -----------------------------------------------------------*/

main().catch((err) => {
  console.error(chalk.red('Fatal deployment error:\n'), err);
  process.exitCode = 1;
});
```
