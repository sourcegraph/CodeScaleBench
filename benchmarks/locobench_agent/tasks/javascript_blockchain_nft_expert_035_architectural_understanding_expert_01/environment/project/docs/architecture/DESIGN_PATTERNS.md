```markdown
# StellarStage Carnival – Architecture & Design Patterns
> Version: 1.3  
> Last-updated: 2024-06-05  
> Authors: Core Platform Team (@StellarStageCarnival)

StellarStage Carnival follows **Clean Architecture** principles while leveraging time-tested design patterns to keep the codebase modular, testable and future-proof.  
This document is an engineering reference that explains **where** and **why** each pattern is used and provides TypeScript/JavaScript excerpts that you can paste directly into a live project.

---

## Table of Contents
1. Layered Overview (Clean Architecture)
2. Factory Pattern – Dynamic NFT Trait Generation
3. Strategy Pattern – Pluggable Loot Distribution
4. State Machine – NFT Lifecycle Management
5. Observer Pattern – Real-time Stage Telemetry
6. Event-Driven Architecture – Service Orchestration
7. Proxy Pattern – Upgradeable Smart Contracts
8. Glossary & Further Reading

---

## 1. Layered Overview

```mermaid
graph TD
  subgraph Domain (Pure)
    Show
    Act
    Pass
    Loot
  end
  subgraph UseCases (Application)
    MintShowPass --> Pass
    DistributeLoot --> Loot
    CastLiveVote --> Show
    StakePass --> Pass
  end
  subgraph Infra (Adapters)
    Ethereum[ERC-721A Proxy]
    L2[Optimistic Rollup]
    IPFSGateway
    GQLAPI[GraphQL subscriptions]
    WS[WebSocket bus]
  end
  subgraph UI (Interface)
    Frontend[React-Three UI]
  end

  Ethereum -->|ports| DistributeLoot
  L2 --> MintShowPass
  IPFSGateway --> MintShowPass
  GQLAPI --> UI
  WS --> UI
  Frontend --> WS
  Frontend --> GQLAPI
```

Each layer depends only **inward**; outer layers implement the contracts defined by inner layers, never the other way around.

---

## 2. Factory Pattern – Dynamic NFT Trait Generation

Dynamic NFTs in StellarStage Carnival can change appearance based on live audience participation.  
A **Factory** is used to encapsulate the creation of *Trait* value objects so that business rules stay out of the calling code.

### Code

```ts
// domain/value-objects/Trait.ts
export interface TraitProps {
  name: string;
  level: number;
  rarity: 'common' | 'rare' | 'legendary';
}

export class Trait {
  constructor(private readonly props: TraitProps) {
    if (props.level < 0) throw new Error('Level cannot be negative');
  }
  // getters ...
}

// domain/factories/TraitFactory.ts
import { Trait } from '../value-objects/Trait';

export interface TraitContext {
  liveVotes: number;
  stageTimeMs: number;
  performerEnergy: number; // 0–1
}

export class TraitFactory {
  static createBackstagePass(ctx: TraitContext): Trait {
    const level = Math.floor(ctx.liveVotes / 100);
    const rarity =
      ctx.performerEnergy > 0.8 ? 'legendary'
      : ctx.performerEnergy > 0.5 ? 'rare'
      : 'common';

    return new Trait({ name: 'Backstage Pass', level, rarity });
  }

  // Additional trait builders...
}
```

#### Why Factory?
• Keeps `Trait` immutable and dumb  
• Single place for rules, easier to test  
• Swappable during unit tests via **dependency injection**

---

## 3. Strategy Pattern – Pluggable Loot Distribution

Different shows may want to reward fans using various on-chain tokenomics.  
The **Strategy Pattern** allows us to plug in a reward algorithm without changing the orchestrator.

### Code

```ts
// domain/ports/LootDistributionStrategy.ts
export interface LootDistributionStrategy {
  distribute(toAddress: string, amount: bigint): Promise<void>;
}

// infra/strategies/FanQuotaStrategy.ts
import { LootDistributionStrategy } from '../../domain/ports/LootDistributionStrategy';
import { erc20 } from '../chain/erc20';

export class FanQuotaStrategy implements LootDistributionStrategy {
  constructor(private readonly maxPerFan: bigint) {}

  async distribute(to: string, amount: bigint) {
    const balance = await erc20.balanceOf(to);
    if (balance + amount > this.maxPerFan)
      throw new Error('Per-fan quota exceeded');

    return erc20.transfer(to, amount);
  }
}

// use-cases/DistributeLoot.ts
export class DistributeLoot {
  constructor(
    private readonly strategy: LootDistributionStrategy, // injected
    private readonly fanRepo: FanRepository
  ) {}

  async execute(fanId: string, amount: bigint) {
    const fan = await this.fanRepo.findById(fanId);
    await this.strategy.distribute(fan.wallet, amount);
  }
}
```

#### Switching Strategies

```ts
// bootstrap
const strategy = process.env.NETWORK === 'mainnet'
  ? new FanQuotaStrategy(10_000n * 10n ** 18n)
  : new UnlimitedTestnetStrategy();

container.register('LootStrategy', strategy);
```

---

## 4. State Machine – NFT Lifecycle Management

A Show-Pass NFT travels through `UNMINTED -> ACTIVE -> STAKED -> EXPIRED` states with specific invariants.  
We use the **State Machine Pattern** to guarantee valid transitions.

### Code

```ts
// domain/state/ShowPassState.ts
import { IllegalStateError } from '../errors';

export enum ShowPassStatus {
  Unminted = 'UNMINTED',
  Active   = 'ACTIVE',
  Staked   = 'STAKED',
  Expired  = 'EXPIRED'
}

export class ShowPassState {
  constructor(private status: ShowPassStatus) {}

  mint() {
    if (this.status !== ShowPassStatus.Unminted)
      throw new IllegalStateError('Already minted');
    this.status = ShowPassStatus.Active;
  }

  stake() {
    if (this.status !== ShowPassStatus.Active)
      throw new IllegalStateError('Not active');
    this.status = ShowPassStatus.Staked;
  }

  expire() {
    if (this.status === ShowPassStatus.Expired)
      throw new IllegalStateError('Already expired');
    this.status = ShowPassStatus.Expired;
  }

  get value() { return this.status; }
}
```

#### Benefits
• Business invariants are enforced at compile time  
• Reduces edge-case bugs in front-end syncing  

---

## 5. Observer Pattern – Real-time Stage Telemetry

Stage events (song change, critical hit in an e-sport match, punchline in comedy show) propagate to multiple subsystems: UI overlays, NFT trait updates, and loot airdrops.  
We use an **Observer/Event Bus** to fan-out those updates.

### Code

```ts
// infra/bus/EventBus.ts
type Listener<T> = (evt: T) => void;

export class EventBus {
  private listeners = new Map<string, Set<Listener<any>>>();

  on<T>(topic: string, fn: Listener<T>) {
    const set = this.listeners.get(topic) ?? new Set();
    set.add(fn);
    this.listeners.set(topic, set);
  }

  off<T>(topic: string, fn: Listener<T>) {
    this.listeners.get(topic)?.delete(fn);
  }

  emit<T>(topic: string, payload: T) {
    this.listeners.get(topic)?.forEach(fn => fn(payload));
  }
}
```

### Usage Example

```ts
// domain/events.ts
export type SongChanged = { songId: string; timestamp: number };

// bootstrap
const bus = new EventBus();
bus.on<SongChanged>('song.changed', payload => {
  console.log('Update UI for new song:', payload.songId);
});

// Somewhere in performance adapter
bus.emit<SongChanged>('song.changed', { songId: '42', timestamp: Date.now() });
```

---

## 6. Event-Driven Architecture – Service Orchestration

While the Observer handles in-process listeners, cross-service communication relies on kafka-like topics (AWS SNS/SQS, NATS, or Redis streams depending on runtime env).

Example workflow:

1. `MintShowPass` emits `pass.minted`  
2. `LootDistributor` microservice consumes `pass.minted` and calls `DistributeLoot`  
3. `Governance` microservice updates quorum  

We wrap all domain events in a **canonical envelope**:

```ts
export interface DomainEvent<TPayload> {
  id: string;           // UUID
  type: string;         // e.g. 'pass.minted'
  ts: number;           // unix epoch ms
  payload: TPayload;
  version: number;      // schema version
}
```

Adapters convert this envelope to the underlying broker format, keeping the domain decoupled from infra specifics.

---

## 7. Proxy Pattern – Upgradeable Smart Contracts

Smart-contract logic inevitably evolves—bug fixes, new features, updated royalty splits.  
To avoid breaking NFT ownership, we ship **EIP-1967** proxy contracts:

```solidity
// onchain/contracts/ShowProxy.sol
contract ShowProxy is ERC1967Proxy {
    constructor(address impl, bytes memory data)
        ERC1967Proxy(impl, data) {}
}
```

The JS SDK hides the proxy layer:

```ts
// infra/chain/ShowContract.ts
import { ethers } from 'ethers';
import ShowImplAbi from './abi/ShowImpl.json';

export class ShowContract {
  private readonly proxy: ethers.Contract;

  constructor(address: string, provider: ethers.Signer | ethers.Provider) {
    this.proxy = new ethers.Contract(address, ShowImplAbi, provider);
  }

  async currentAct(): Promise<string> {
    return this.proxy.currentAct();
  }

  // Upgrades performed only by DAO multisig
  static async upgrade(
    proxyAddr: string,
    newImpl: string,
    signer: ethers.Signer
  ) {
    const proxyAdmin = new ethers.Contract(
      proxyAddr,
      ['function upgradeTo(address) external'],
      signer
    );
    await proxyAdmin.upgradeTo(newImpl);
  }
}
```

Benefits:

• Continuous delivery of contract improvements  
• Preservation of token IDs & royalty recipients  
• Governance-gated upgrades mitigate rug-pull risk  

---

## 8. Glossary & Further Reading
Pattern | Reference
------- | ----------
Factory | GoF Book §3.2, *Effective JavaScript* Item 38
Strategy | GoF §1.2  
State Machine | [XState Docs](https://xstate.js.org/)  
Observer | GoF §2.3  
Event-Driven | *Designing Event-Driven Systems* (P. Kleppmann)  
Proxy | EIP-1967, OpenZeppelin Upgrades

For implementation specifics, dive into the `/domain` and `/use-cases` folders; see also unit tests under `/__tests__/pattern_*`.

---

© 2024 StellarStage Carnival – All Rights Reserved
```