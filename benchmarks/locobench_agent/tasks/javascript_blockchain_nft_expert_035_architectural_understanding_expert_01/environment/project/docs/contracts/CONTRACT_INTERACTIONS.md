```markdown
# StellarStage Carnival – Smart-Contract Interaction Guide
Interact with the on-chain backbone of the Carnival from a Node.js service, a React dApp, or even a serverless function. All snippets use TypeScript flavored JavaScript and `ethers@6.x`, but are easily portable to web3.js, viem, Foundry scripts, or Hardhat tasks.

---

## Table of Contents
1. Prerequisites
2. Contracts & ABIs
3. Bootstrapping a Provider & Signer
4. Read-Only Queries
5. Stateful Transactions
6. Event Subscriptions
7. Error Handling Patterns
8. Gas & Fee Optimisations
9. Advanced: Meta-Tx & Permit2
10. Reference Utilities

---

## 1. Prerequisites
```bash
npm i ethers@^6.10 dotenv@^16.4 zod@^3.22
# For node < 20 add: npm i --save-dev @types/node
```
Create a `.env` file containing:
```env
RPC_URL=https://mainnet.infura.io/v3/<PROJECT_ID>
PRIVATE_KEY=0xabc123...              # For backend/bot wallets
CHAIN_ID=1                           # 1 Mainnet, 5 Goerli, 8453 Base, etc.
```

---

## 2. Contracts & ABIs
| Alias             | Proxy Address                                | Domain Entity | Upgrade Admin |
|-------------------|----------------------------------------------|---------------|---------------|
| ShowPassProxy     | `0x1cA5…BEEF`                                | `Pass`        | `0x7F0…135`   |
| LootChestProxy    | `0xDeaD…CAFE`                                | `Loot`        | `0x7F0…135`   |
| CarnivalGovernor  | `0xFabC…A11A`                                | Governance    | `–`           |
| VotingEscrow      | `0xEscR…0LL`                                 | `Stake`       | `–`           |

All production ABIs are collated under `@/contracts/abi/`. Example import:

```ts
import ShowPassABI from '@/contracts/abi/ShowPassProxy.json' assert { type: 'json' };
```

---

## 3. Bootstrapping a Provider & Signer
```ts
// src/lib/blockchain.ts
import { JsonRpcProvider, Wallet } from 'ethers';
import { config } from 'dotenv';
import { z } from 'zod';

config();

const EnvSchema = z.object({
  RPC_URL: z.string().url(),
  PRIVATE_KEY: z.string().regex(/^0x[a-fA-F0-9]{64}$/),
  CHAIN_ID: z.coerce.number().positive()
});

const { RPC_URL, PRIVATE_KEY, CHAIN_ID } = EnvSchema.parse(process.env);

export const provider = new JsonRpcProvider(RPC_URL, CHAIN_ID);

// A signer is _only_ required for state-changing transactions.
export const signer = new Wallet(PRIVATE_KEY, provider);
```

---

## 4. Read-Only Queries
```ts
// src/queries/isPassUpgradable.ts
import { Contract } from 'ethers';
import { provider } from '@/lib/blockchain';
import ShowPassABI from '@/contracts/abi/ShowPassProxy.json' assert { type: 'json' };

const SHOW_PASS_ADDRESS = '0x1cA5…BEEF';

/**
 * Check whether a given tokenId can still evolve.
 */
export async function isPassUpgradable(tokenId: bigint): Promise<boolean> {
  const contract = new Contract(SHOW_PASS_ADDRESS, ShowPassABI, provider);
  try {
    const level = await contract.currentLevel(tokenId);
    const maxLevel = await contract.MAX_LEVEL();
    return level < maxLevel;
  } catch (error) {
    console.error('Read error in isPassUpgradable ➜', error);
    return false;
  }
}
```

---

## 5. Stateful Transactions
### 5.1 Mint a ShowPass
```ts
// src/tx/mintShowPass.ts
import { Contract } from 'ethers';
import { signer } from '@/lib/blockchain';
import ShowPassABI from '@/contracts/abi/ShowPassProxy.json' assert { type: 'json' };

const SHOW_PASS_ADDRESS = '0x1cA5…BEEF';

/**
 * Mints a new ShowPass for the connected wallet.
 * @param tier 0 = GA, 1 = VIP, 2 = Ultra
 * @param referralCode Optional bytes32 affiliate code
 */
export async function mintShowPass(tier: number, referralCode = '0x') {
  const showPass = new Contract(SHOW_PASS_ADDRESS, ShowPassABI, signer);

  // Optional: Estimate for better UX
  const gas = await showPass.mint.estimateGas(signer.address, tier, referralCode);

  const tx = await showPass.mint(signer.address, tier, referralCode, {
    gasLimit: gas + (gas / 10n) // add 10% safety margin
  });

  console.info(`Mint submitted ➜ ${tx.hash}`);
  const receipt = await tx.wait();
  console.info(`Mint confirmed in block ${receipt.blockNumber}`);
  return receipt;
}
```

### 5.2 Stake Pass (Voting Escrow Pattern)
```ts
// src/tx/stakePass.ts
import { Contract } from 'ethers';
import { signer } from '@/lib/blockchain';
import VotingEscrowABI from '@/contracts/abi/VotingEscrow.json' assert { type: 'json' };
import ShowPassABI from '@/contracts/abi/ShowPassProxy.json' assert { type: 'json' };

const ESCROW = '0xEscR…0LL';
const SHOW_PASS = '0x1cA5…BEEF';

export async function stakePass(tokenId: bigint, weeks: number) {
  const escrow = new Contract(ESCROW, VotingEscrowABI, signer);
  const pass   = new Contract(SHOW_PASS, ShowPassABI, signer);

  // Approve once, stake many
  const approved = await pass.isApprovedForAll(signer.address, ESCROW);
  if (!approved) {
    const approveTx = await pass.setApprovalForAll(ESCROW, true);
    await approveTx.wait();
  }

  const lockUntil = BigInt(Math.floor(Date.now() / 1000) + weeks * 7 * 24 * 60 * 60);

  const tx = await escrow.lock(tokenId, lockUntil);
  console.info(`Staking tx ➜ ${tx.hash}`);
  return tx.wait();
}
```

### 5.3 Cast a Live Vote
```ts
// src/tx/castLiveVote.ts
import { Contract } from 'ethers';
import { signer } from '@/lib/blockchain';
import GovernorABI from '@/contracts/abi/CarnivalGovernor.json' assert { type: 'json' };

const GOVERNOR = '0xFabC…A11A';

export async function castLiveVote(proposalId: bigint, support: 0 | 1 | 2) {
  const governor = new Contract(GOVERNOR, GovernorABI, signer);

  const params = await governor.proposalSnapshot(proposalId);
  if (BigInt(Date.now() / 1000) < params.startTime) {
    throw new Error('Voting has not started yet.');
  }

  const tx = await governor.castVote(proposalId, support);
  console.info(`Vote tx ➜ ${tx.hash}`);
  return tx.wait();
}
```

---

## 6. Event Subscriptions
```ts
// src/subscriptions/showPassEvents.ts
import { Contract } from 'ethers';
import { provider } from '@/lib/blockchain';
import ShowPassABI from '@/contracts/abi/ShowPassProxy.json' assert { type: 'json' };

const SHOW_PASS = '0x1cA5…BEEF';

export function subscribeToPassEvolution(cb: (tokenId: bigint, level: number) => void) {
  const pass = new Contract(SHOW_PASS, ShowPassABI, provider);
  pass.on('LevelUp', (tokenId, level, event) => {
    console.debug('Pass evolved:', { tokenId, level, tx: event.transactionHash });
    cb(tokenId, Number(level));
  });
  return () => pass.removeAllListeners('LevelUp');
}
```

---

## 7. Error Handling Patterns
1. Always wrap read calls inside `try/catch` to avoid crashing renders.
2. Decode revert reasons for on-chain failures:
```ts
import { getRpcError } from 'ethers';

try {
  await contract.doSomething();
} catch (e) {
  const reason = getRpcError(e)?.info?.error?.message ?? 'Unknown error';
  toast.error(`Tx failed: ${reason}`);
}
```
3. Apply exponential back-off when polling confirmations in flaky networks.

---

## 8. Gas & Fee Optimisations
• Prefer `staticCall` (aka call-static) to simulate transactions off-chain.  
• Batch multiple mints with `multicall(aggregate)` via `CarnivalMulticaller`.  
• Use EIP-1559 params: `maxFeePerGas`, `maxPriorityFeePerGas`.  
• Monitor `baseFee` with `provider.getFeeData()` and queue non-urgent jobs.

---

## 9. Advanced: Meta-Tx & Permit2
`ShowPassProxy` implements ERC-2771 recipient; you can pay gas on behalf of users.

```ts
import { signTypedData } from '@wagmi/core'; // or viem
// …generate typedData object…
const signature = await signTypedData({ domain, types, value });

await carnivalForwarder.execute({
  target: SHOW_PASS,
  data: pass.interface.encodeFunctionData('levelUp', [tokenId, traitHash]),
  signature
});
```

---

## 10. Reference Utilities
```ts
// src/utils/retry.ts
export async function retry<T>(
  fn: () => Promise<T>,
  attempts = 3,
  delayMs = 1_000
): Promise<T> {
  try {
    return await fn();
  } catch (err) {
    if (attempts <= 1) throw err;
    await new Promise(res => setTimeout(res, delayMs));
    return retry(fn, attempts - 1, delayMs * 2);
  }
}
```

---

Happy building, and see you on the Stellar Stage! 🚀
```