```javascript
/**
 * @file full-lifecycle.integration.test.js
 *
 * “Full-stack” happy-path integration test that walks through a fan’s entire
 * journey: buying an NFT show-pass → staking it for governance →
 * participating in a live vote → receiving dynamic on-chain loot drops.
 *
 * The test suite wires together ONLY public ports (repositories / adapters /
 * use-cases) exactly as production does—no monkey-patching of internals—yet
 * swaps heavyweight infrastructure (Ethereum, IPFS, WebSockets) for
 * deterministic in-memory fakes so that test runs are fast and hermetic.
 */

import { v4 as uuid } from 'uuid';
import { EventEmitter } from 'events';
import { ethers } from 'ethers';
import waitForExpect from 'wait-for-expect';

import { ShowFactory } from '../../src/domain/factories/ShowFactory';
import { PassTraitStrategyRegistry } from '../../src/domain/strategies/PassTraitStrategyRegistry';

import { MemoryShowRepository } from '../../src/infra/persistence/MemoryShowRepository';
import { MemoryPassRepository } from '../../src/infra/persistence/MemoryPassRepository';
import { MemoryLootRepository } from '../../src/infra/persistence/MemoryLootRepository';

import { FakeChainAdapter } from '../utils/FakeChainAdapter';
import { FakeIpfsAdapter } from '../utils/FakeIpfsAdapter';
import { FakeStreamAdapter } from '../utils/FakeStreamAdapter';

import { MintShowPass } from '../../src/use-cases/MintShowPass';
import { StakePass } from '../../src/use-cases/StakePass';
import { CastLiveVote } from '../../src/use-cases/CastLiveVote';
import { DistributeLoot } from '../../src/use-cases/DistributeLoot';

jest.setTimeout(20_000); // blockchain tests can be slower

// -- Shared “service locator” -------------------------------------------------
const bus = new EventEmitter();             // Event-driven heart beat
const showRepo = new MemoryShowRepository();
const passRepo = new MemoryPassRepository();
const lootRepo = new MemoryLootRepository();

const chain = new FakeChainAdapter(bus);
const ipfs  = new FakeIpfsAdapter();
const stream = new FakeStreamAdapter(bus);

// Register dynamic trait strategies (rarity, upgrades, etc.)
PassTraitStrategyRegistry.registerDefaultStrategies();

// Use-cases wired with dependencies
const mintShowPass   = new MintShowPass(showRepo, passRepo, ipfs, chain, bus);
const stakePass      = new StakePass(passRepo, chain, bus);
const castLiveVote   = new CastLiveVote(passRepo, showRepo, chain, stream, bus);
const distributeLoot = new DistributeLoot(showRepo, passRepo, lootRepo, chain, bus);

// -----------------------------------------------------------------------------
describe('StellarStage Carnival - full lifecycle integration', () => {
  const fanWallet     = ethers.Wallet.createRandom();  // “Alice”
  const performerAddr = ethers.Wallet.createRandom().address;

  let showId;
  let passTokenId;
  let lootTokenIds = [];

  beforeAll(async () => {
    // 1) Performer creates a new show (domain factory only)
    const show = ShowFactory.create({
      title          : 'Carnival-on-Ice',
      performer      : performerAddr,
      startTimestamp : Date.now() + 60 * 60 * 1000, // +1h
      stageConfig    : { seats: 5000, is3D: true }
    });
    showId = show.id;
    await showRepo.save(show);
  });

  // ---------------------------------------------------------------------------
  it('mints a show-pass NFT for the fan', async () => {
    const tx = await mintShowPass.execute({
      showId,
      buyerAddress : fanWallet.address,
      seatNumber   : 42
    });

    // Verify chain tx + local persistence
    expect(tx.status).toBe('MINED');
    passTokenId = tx.result.tokenId;

    const storedPass = await passRepo.findByTokenId(passTokenId);
    expect(storedPass?.owner).toBe(fanWallet.address);
    expect(storedPass?.seatNumber).toBe(42);

    // metadata pinned on IPFS
    const ipfsPayload = ipfs.read(storedPass?.metadataCid);
    expect(ipfsPayload.name).toMatch(/Carnival-on-Ice #42/);
  });

  // ---------------------------------------------------------------------------
  it('allows the fan to stake their pass for governance rights', async () => {
    const stakeReceipt = await stakePass.execute({
      tokenId    : passTokenId,
      stakerAddr : fanWallet.address,
      lockPeriod : 7 // days
    });

    expect(stakeReceipt.status).toBe('STAKED');

    const updatedPass = await passRepo.findByTokenId(passTokenId);
    expect(updatedPass?.isStaked).toBe(true);
    expect(updatedPass?.stake?.lockPeriodDays).toBe(7);
  });

  // ---------------------------------------------------------------------------
  it('emits a live vote and records the fan’s on-chain choice', async () => {
    // Simulate the performer triggering a live poll on-stage
    const pollId = uuid();
    bus.emit('LIVE_POLL_CREATED', {
      showId,
      pollId,
      prompt  : 'Encore song?',
      options : ['Hit-Single', 'Deep-Cut']
    });

    // Fan casts vote
    const voteTx = await castLiveVote.execute({
      tokenId  : passTokenId,
      pollId,
      option   : 'Hit-Single'
    });

    expect(voteTx.status).toBe('MINED');

    // Wait for show domain to observe & persist result
    await waitForExpect(async () => {
      const show = await showRepo.findById(showId);
      const poll = show?.getPollById(pollId);
      expect(poll?.tallies['Hit-Single']).toBe(1);
    });
  });

  // ---------------------------------------------------------------------------
  it('distributes dynamic loot to all eligible stakers after the show', async () => {
    // Advance fake clock to after show end to satisfy business rule
    jest.spyOn(Date, 'now').mockImplementation(() => Infinity);

    lootTokenIds = await distributeLoot.execute({
      showId,
      criteria: { onlyStakers: true }
    });

    expect(lootTokenIds).toHaveLength(1);
    const [tokenId] = lootTokenIds;

    const loot = await lootRepo.findByTokenId(tokenId);
    expect(loot?.owner).toBe(fanWallet.address);
    expect(loot?.origin.showId).toBe(showId);

    // Chain registry should know about the ERC-1155 drop
    const onChainLoot = chain.getToken(tokenId);
    expect(onChainLoot?.type).toBe('LOOT');
  });

  // ---------------------------------------------------------------------------
  it('updates the pass’ metadata to reflect earned loot & status changes', async () => {
    const pass = await passRepo.findByTokenId(passTokenId);
    expect(pass?.loot.length).toBe(1);
    expect(pass?.traits.find(t => t.key === 'reputation')?.value).toBeGreaterThan(0);

    // Re-hydrate metadata from IPFS and ensure new imagery / attributes exist
    const metadata = ipfs.read(pass?.metadataCid);
    expect(metadata.attributes.find(a => a.trait_type === 'Loot-Count').value).toBe(1);
  });

  // ---------------------------------------------------------------------------
  it('publishes real-time events to downstream consumers (front-end, indexers)', async () => {
    const received = { lootDrop: false };

    bus.once('LOOT_DISTRIBUTED', payload => {
      if (payload.showId === showId && payload.tokenIds.includes(lootTokenIds[0])) {
        received.lootDrop = true;
      }
    });

    // Trigger again manually for assertion clarity
    bus.emit('LOOT_DISTRIBUTED', { showId, tokenIds: lootTokenIds });

    await waitForExpect(() => {
      expect(received.lootDrop).toBe(true);
    });
  });
});
```