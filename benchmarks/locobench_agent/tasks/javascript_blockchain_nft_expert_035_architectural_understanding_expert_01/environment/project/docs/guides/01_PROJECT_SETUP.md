```markdown
# StellarStage Carnival – Project Setup Guide
> docs/guides/01_PROJECT_SETUP.md  
> Version: 1.0.0 • Last updated: 2024-05-02

Welcome to the StellarStage Carnival monorepo!  
This guide walks you through installing dependencies, configuring your local blockchain stack, and running all services (smart contracts, back-end, front-end, and real-time infra) in under **10 minutes**.

---

## Table of Contents
1. Prerequisites  
2. Clone & Bootstrap  
3. Environment Variables  
4. Workspace Layout  
5. Common `package.json` Scripts  
6. Run the Full Stack (DEV)  
7. Deploy Contracts to Testnet  
8. Generate Types from ABI  
9. Database & Subgraph  
10. Linting, Tests & Coverage  
11. CI / CD Pipelines  
12. Troubleshooting  

---

## 1. Prerequisites
| Tool              | Version (min) | Notes                                    |
| ----------------- | ------------- | ---------------------------------------- |
| Node.js           | `18.x LTS`    | Works on 20.x too, but 18 is enforced    |
| pnpm              | `^8.0.0`      | We use pnpm workspaces                   |
| Docker & Compose  | `>= 24`       | Needed for Postgres, IPFS, Graph Node    |
| Foundry           | `>= 0.2.0`    | Ultra-fast Rust-based Solidity toolchain |
| Git               | `>= 2.30`     |                                         |

```bash
# macOS (using asdf)
brew install asdf
asdf plugin-add nodejs
asdf install nodejs latest:18
npm i -g pnpm@latest

# Foundry (Linux / macOS)
curl -L https://foundry.paradigm.xyz | bash && foundryup
```

---

## 2. Clone & Bootstrap

```bash
git clone git@github.com:StellarStage/stage-carnival.git
cd stage-carnival

# install all workspace deps in parallel
pnpm install --frozen-lockfile

# bootstrap TypeScript project references
pnpm run build:types
```

---

## 3. Environment Variables

Copy the example file and edit values as needed:

```bash
cp .env.example .env
```

```dotenv
############################################################
# Blockchain                                              ##
############################################################
RPC_URL=https://rpc.goerli.eth.gateway.fm
PRIVATE_KEY=0xYOUR_PRIVATE_KEY
CHAIN_ID=5
IPFS_API=https://ipfs.infura.io:5001

############################################################
# Database / Cache                                        ##
############################################################
POSTGRES_URL=postgres://carnival:carnival@localhost:5432/carnival
REDIS_URL=redis://localhost:6379

############################################################
# Front-End                                               ##
############################################################
VITE_PUBLIC_GRAPHQL_URL=http://localhost:4000/graphql
VITE_PUBLIC_SOCKET_URL=ws://localhost:4001
```

Tip: Never commit `.env` – it’s ignored by `.gitignore` and checked in CI via [dotenv-safe](https://www.npmjs.com/package/dotenv-safe).

---

## 4. Workspace Layout

```
.
├── apps/
│   ├── frontend/         # React + Three.js client
│   ├── api/              # Fastify + GraphQL server
│   └── subgraph/         # The Graph manifest & mappings
├── packages/
│   ├── contracts/        # Solidity sources & tests
│   ├── core/             # Domain entities & use-cases
│   ├── adapters/         # Ethereum, IPFS, Stream infra
│   └── shared/           # UI libs, config utils, ts-configs
└── infra/
    ├── docker/           # Dockerfiles / compose
    └── k8s/              # Helm charts
```

All packages rely on strict [TypeScript Project References](https://www.typescriptlang.org/docs/handbook/project-references.html) to enforce proper boundaries between **Domain**, **Use-Cases**, and **Adapters**.

---

## 5. Common `package.json` Scripts

```jsonc
{
  "scripts": {
    "dev":        "pnpm -r --parallel run dev",
    "test":       "pnpm -r --parallel run test",
    "lint":       "eslint \"{apps,packages}/**/*.{ts,tsx}\" --fix",
    "format":     "prettier -w \"**/*.{ts,tsx,md,json,yml}\"",
    "typecheck":  "tsc -b",
    "coverage":   "vitest run --coverage",
    "deploy":     "pnpm --filter contracts exec tsx scripts/deploy.ts",
    "graph:codegen": "graph codegen && graph build"
  }
}
```

Run any script at the workspace root or target a specific package via `--filter`.

---

## 6. Run the Full Stack (DEV)

1. Spin up infra services:

```bash
docker compose -f infra/docker/docker-compose.dev.yml up -d
```

This brings up:
* Postgres + PGAdmin  
* Redis  
* IPFS  
* Local Graph Node  
* Hardhat node (if not running Foundry’s `anvil`)  

2. In a new terminal, start everything else:

```bash
pnpm dev
```

`pnpm` will:
* compile and deploy the smart contracts to your local chain  
* launch the API server on `localhost:4000`  
* start the WebSocket bus on `4001`  
* spin up the React/Three front-end on `5173` (Vite)  

Hot-reloading is wired end-to-end – as soon as you tweak an NFT trait strategy or GraphQL resolver, the UI updates in place.

---

## 7. Deploy Contracts to Testnet

We use Foundry for compilation & Hardhat scripts for deployment:

```bash
# compile with foundry (fast)
pnpm --filter contracts run build

# deploy with Ethers.js + Hardhat to Goerli
CHAIN_ID=5 \
RPC_URL=https://rpc.goerli.eth.gateway.fm \
PRIVATE_KEY=0xyourkey \
pnpm --filter contracts exec tsx scripts/deploy.ts
```

The script outputs a fully typed `broadcast/5/latest-deployments.json` map, automatically consumed by the front-end via the `@carnival/contracts` package.

---

## 8. Generate Types from ABI

Any time the Solidity sources change, run:

```bash
pnpm --filter contracts run build        # ensure fresh ABIs
pnpm --filter contracts exec tsx scripts/typegen.ts
```

`typegen.ts` leverages `@typechain/ethers-v6` to emit type-safe contract wrappers used across the entire monorepo.

---

## 9. Database & Subgraph

1. Apply DB migrations (via Drizzle):

```bash
pnpm --filter api exec tsx prisma/migrate.ts
```

2. Prepare The Graph:

```bash
pnpm --filter subgraph run graph:codegen
pnpm --filter subgraph run graph:create-local
pnpm --filter subgraph run graph:deploy-local
```

When contracts emit events (e.g., `ShowPassMinted`, `LootDropped`), the subgraph indexes them and the UI queries real-time data through GraphQL.

---

## 10. Linting, Tests & Coverage

```bash
# lint & fix
pnpm lint

# unit + integration tests
pnpm test

# gas snapshots, state machine property tests
pnpm --filter contracts run test

# coverage report
pnpm coverage
```

The test harness mocks **Ethereum**, **IPFS**, and **WebSocket** layers to validate core business logic with millisecond feedback.

---

## 11. CI / CD Pipelines

GitHub Actions (see `.github/workflows/`) run:

1. `pnpm install --frozen-lockfile`  
2. `pnpm typecheck && pnpm lint`  
3. `pnpm test --run`  
4. Cache & upload contract artifacts  
5. On `main` merge:  
   • Deploy staging infra to Fly.io  
   • Publish `next` tag to NPM for all public packages  

We strictly enforce green builds before allowing merges.

---

## 12. Troubleshooting

| Symptom                                   | Quick Fix                               |
| ----------------------------------------- | --------------------------------------- |
| `ERR_MODULE_NOT_FOUND xyz`                | Run `pnpm install` then `pnpm build`    |
| Contracts hang during migration           | Check `RPC_URL`, local chain running?   |
| Front-end fails to connect to WebSockets  | Verify `.env` `SOCKET_URL`, port 4001   |
| GraphQL returns `ECONNREFUSED`            | Ensure Postgres & Graph Node are up     |
| `anvil` mining too slow                   | `anvil --block-time 0` or use Hardhat   |

---

## That’s It 🎉

You’re now ready to mint your first **ShowPass NFT**, drop in-concert loot, and hack that live e-sports storyline.  
Questions or bugs? Ping us on Discord (#dev-dao) or open an issue.

Happy building! – The StellarStage Carnival Core Team
```