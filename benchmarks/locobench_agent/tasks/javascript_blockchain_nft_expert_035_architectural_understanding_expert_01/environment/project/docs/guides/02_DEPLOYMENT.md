```markdown
<!--
  StellarStage Carnival
  Deployment Guide · docs/guides/02_DEPLOYMENT.md

  This document describes the canonical procedure for shipping a new
  version of StellarStage Carnival—from smart-contract compilation all
  the way to front-end delivery and canary monitoring.

  Last updated: 2024-06-15
-->
# 02 · Deployment

> 🛠️  Every commit that reaches `main` **must** be deploy-ready.  
> 🔒  All secrets live in 1Password + GitHub Encrypted Secrets.  
> 🚦  Releases cannot bypass CI checks.

---

## 1. High-Level Overview

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                         GitHub → Actions → Hardhat → L2                      │
│                                                                               │
│  1. Pull Request → CI lint/test → Merge → Tag (`vX.Y.Z`)                      │
│  2. GitHub Action `deploy.yml` fires on tag                                   │
│  3. Contracts are compiled & audited lint                                     │
│  4. Hardhat deploys via Safe transaction to                                   │
│         - Ethereum Mainnet (ProxyAdmin + Implementation)                      │
│         - Polygon zkEVM (mirror)                                              │
│  5. Bytecode is auto-verified on Etherscan / Polygonscan                      │
│  6. Subgraph schema auto-migrates -> The Graph Hosted Svc                     │
│  7. React-Three build → IPFS → Cloudflare R2 CDN → gateway.stellarcarnival.io │
│  8. Canary tests ping GraphQL, WS and contract read routes                    │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Prerequisites

1. **Node ≥ 18** & **pnpm ≥ 8**
2. **Hardhat** (`pnpm dlx hardhat --version`)
3. **Foundry** for cross-toolchain fuzzing  
   `brew install foundry` → `foundryup`
4. **Docker** & `docker compose` (required for local *subgraph* runner)
5. Funding wallets:
   * `DEPLOYER_PK_MAINNET` (0.2 ETH buffer)
   * `DEPLOYER_PK_L2` (3 MATIC buffer)
6. 1Password CLI (`op`) for secret injection

---

## 3. Local Environment Setup

```bash
# 1️⃣  Clone
git clone git@github.com:StellarStage/carnival.git && cd carnival

# 2️⃣  Bootstrap repo
pnpm i

# 3️⃣  Copy & edit environment template
cp .env.example .env.local
op read "op://StellarStage/DEPLOYMENT/.env.local" > .env.local

# 4️⃣  Spin up private chain + subgraph + IPFS
pnpm dev:stack         # docker compose wrapper
```

The wrapper script lives in `scripts/dev/stack.ts` and multiplexes logs with [@nadeesha/logger-tap](https://github.com/nadeesha/logger-tap) for clearer splits.

---

## 4. Smart-Contract Deployment Workflow

### 4.1 Compile & Static-Analyze

```bash
pnpm contracts:clean
pnpm contracts:build            # typechain + hardhat compile
pnpm contracts:slither          # Slither static analysis
pnpm contracts:forge:tests      # Foundry invariant & fuzz tests
```

Any **Slither HIGH** findings block the pipeline. MEDIUM is allowed only with a Jira ticket (`SEC-XXX`).

### 4.2 Dry-Run to Anvil

```bash
pnpm contracts:deploy:dry-run
# ➜ prints gas report, storage layout & emits event table
```

### 4.3 Deploy via Safe TX Service

Production rollouts are executed by the Gnosis Safe *Core Team* multisig (`3/5`) through the **Safe Transaction Service**:

```bash
pnpm contracts:deploy --network mainnet \
  --safe 0x7AFe...C131 \
  --verify            \
  --broadcast
```

Flags:
* `--safe`: pushes a *prepared* transaction requiring quorum (no hot-wallet risk)
* `--verify`: auto-submits source to block-explorer
* `--broadcast`: sends to RPC once Safe approves

Hardhat task implemented at `packages/contracts/tasks/deploy.ts`.

### 4.4 Post-Deploy Hooks

Upon success:

1. Script writes `deployment.{chainId}.json` to `packages/contracts/deployments/`.
2. GitHub Action commits the artifact back to `main`.
3. Web app reads address via `@stellarcarnival/addresses` package (generated).

---

## 5. Front-End & Subgraph

### 5.1 Build Static Assets

```bash
pnpm web:build          # Next.js + React-Three, outputs to .next
```

### 5.2 Pin to IPFS

We pin both to **Pinata** and an internal Cluster using [`ipfs-deploy`](https://github.com/ipfs-shipyard/ipfs-deploy):

```bash
pnpm web:ipfs
# CID -> e.g. QmT5Nv...z7Tg

echo "ipfs://<CID>" > packages/web/.latest-cid
```

### 5.3 Update Gateway

A Cloudflare Worker resolves `https://gateway.stellarcarnival.io` to the latest CID.  
`infra/workers/update-cid.ts` is triggered by the same GitHub Action.

### 5.4 Subgraph Migration

```bash
pnpm graph:codegen
pnpm graph:deploy --product hosted-service \
  stellarcarnival/carnival-${ENV}
```

The tag `${ENV}` equals `staging` or `prod`.

---

## 6. CI/CD Pipeline (GitHub Actions)

File: `.github/workflows/deploy.yml`

Key Jobs:
1. `lint-test` → ESLint, prettier, domain tests
2. `solidity-check` → compile, slither, forge tests
3. `build-web` → Next.js build, bundle-analyze
4. `deploy-contracts` (tagged only)  
   Needs manual approval `Staging Approvers`
5. `deploy-subgraph`
6. `publish-web`
7. `smoke` → k6 scripts run against staging endpoints

Matrix strategy runs both *Ethereum Mainnet* and *Polygon zkEVM*.

---

## 7. Rollback Strategy

Smart contracts are upgradeable via **Transparent Proxy Pattern**:

```
ProxyAdmin (multisig)
      ↘
       └── ShowRunnerProxy → ShowRunner_v1 (Implementation)
```

1. Emergency found? Pause contract using `CircuitBreaker.toggle()`.
2. Queue downgrade transaction in Safe to previous implementation address.
3. Redeploy front-end pointing at older ABI if needed (rare).

Front-end & subgraph rollbacks are trivial—pin previous CID / graph deployment.

---

## 8. Staging vs Production

| Component        | Staging                              | Production                               |
|------------------|--------------------------------------|------------------------------------------|
| Chain            | `goerli` + `polygon-mumbai`          | `ethereum` + `polygon-zkevm`             |
| Subgraph         | `stellarcarnival/carnival-staging`   | `stellarcarnival/carnival`               |
| Gateway Host     | `staging.stellarcarnival.io`         | `gateway.stellarcarnival.io`             |
| Feature Flags    | `ENABLE_DEV_MINIGAMES=true`          | off                                      |
| Gas Strategy     | fixed 5 GWei                          | EIP-1559 Priority via Blocknative API    |

Switching environments only requires toggling `$ENV` in `.github/workflows/deploy.yml`.

---

## 9. Smoke Test Checklist (manual)

1. `GET /healthz` returns `200 OK`.
2. Mint flow (test credit card) completes & NFT appears in wallet.
3. Live vote WebSocket receives `StagePulse` events.
4. Loot drop triggers ERC-1155 `TransferSingle`.
5. Stake APY calc UI rounds to 2 decimals.

Scripts in `packages/qa/smoke/` automate 1–4 but still require human eye on UI render.

---

## 10. `.env.example`

```dotenv
# RPC
RPC_MAINNET=https://eth-mainnet.g.alchemy.com/v2/___
RPC_POLYGON_ZKEVM=https://polygonzkevm-mainnet.g.alchemy.com/v2/___
RPC_GOERLI=https://eth-goerli.g.alchemy.com/v2/___

# Keys
DEPLOYER_PK_MAINNET=0x____
DEPLOYER_PK_L2=0x____
INFURA_IPFS_PROJECT_ID=___
INFURA_IPFS_PROJECT_SECRET=___

# Front-end
NEXT_PUBLIC_CHAIN_ID=1
NEXT_PUBLIC_SUBGRAPH=https://api.thegraph.com/subgraphs/name/stellarcarnival/carnival
NEXT_PUBLIC_WS_URL=wss://ws.stellarcarnival.io
```

---

## 11. Troubleshooting

| Symptom                              | Fix                                                            |
|--------------------------------------|----------------------------------------------------------------|
| `Nonce too low` on deploy            | Reset Hardhat cache → `pnpm contracts:clean`                   |
| `GraphQL 400` after subgraph update  | Run `graph:codegen` → `graph:deploy` with `--version-label`    |
| CID not resolving on gateway         | Cloudflare cache purge → `wrangler kv:namespace:delete`        |
| Stuck Safe transaction               | Speed up via `eth_gasPrice` bump or cancel & re-submit         |

---

👏 **That’s it!** You’re now fully equipped to ship the next tour-level
upgrade of StellarStage Carnival. If anything here drifts from reality,
open an issue with the `docs 📝` label.

```
