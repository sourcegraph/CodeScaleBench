```javascript
/**
 * @file ShowPass.test.js
 *
 * End-to-end / use-case tests for Show-Pass lifecycle:
 *   1. Minting a brand-new NFT show-pass
 *   2. Preventing duplicate mints for the same wallet / tier
 *   3. Staking an existing pass for governance rewards
 *   4. Guarding double-stake attempts
 *
 * The real implementations of the use-cases live in `src/useCases/*`.
 * Here we wire them up with deterministic in-memory doubles so that no
 * external systems (EVM, IPFS, etc.) are touched while running Jest.
 *
 * The tests strictly operate on the public API of the use-cases; they
 * assert domain events and repository side-effects in line with the
 * project’s Clean Architecture style.
 */

/* ──────────────────────────────────────────────────────────────────
 * Imports
 * ────────────────────────────────────────────────────────────────── */
import { v4 as uuid }           from 'uuid';
import { ethers }               from 'ethers';
import MintShowPass             from '../src/useCases/MintShowPass';
import StakePass                from '../src/useCases/StakePass';

/* ──────────────────────────────────────────────────────────────────
 * In-memory test doubles
 * ────────────────────────────────────────────────────────────────── */

/**
 * Simple event bus that pushes every published event into a queue so
 * the tests can later assert on the emission order / payload.
 */
class FakeEventBus {
  #events = [];

  publish(event) {
    this.#events.push(event);
  }

  pullLast() {
    return this.#events[this.#events.length - 1];
  }

  eventCount(type) {
    return this.#events.filter(e => e.type === type).length;
  }
}

/**
 * In-memory repository for Show-Pass NFTs.
 * The real repo is chain / DB backed; here we just keep things in RAM.
 */
class InMemoryPassRepository {
  constructor() {
    /** @type {Map<string, object>} */
    this.store = new Map();
  }

  async nextId() {
    return uuid();
  }

  /**
   * @param {object} pass
   */
  async save(pass) {
    this.store.set(pass.id, pass);
  }

  /**
   * @param {string} id
   */
  async findById(id) {
    return this.store.get(id) ?? null;
  }

  /**
   * Prevent the same wallet from minting the exact same show/tier twice.
   */
  async findByOwnerShowTier({ owner, showId, tier }) {
    return (
      [...this.store.values()].find(
        p => p.owner === owner && p.showId === showId && p.tier === tier,
      ) ?? null
    );
  }
}

/**
 * Fake show-catalog. A real show repo would check concert existence /
 * time validity, performer wallet, etc. Only a happy-path here.
 */
class InMemoryShowRepository {
  #shows = new Set();

  constructor() {
    // bootstrap with a single fake show
    const defaultShowId = uuid();
    this.#shows.add(defaultShowId);
    this.defaultShowId = defaultShowId;
  }

  async exists(id) {
    return this.#shows.has(id);
  }
}

/* ──────────────────────────────────────────────────────────────────
 * Helpers
 * ────────────────────────────────────────────────────────────────── */

const anyEthAddress = () => ethers.Wallet.createRandom().address;
const now           = () => new Date().toISOString();

/* ──────────────────────────────────────────────────────────────────
 * System Under Test (SUT) factory
 * ────────────────────────────────────────────────────────────────── */

function givenMintShowPassUseCase({ passRepo, showRepo, bus }) {
  return new MintShowPass({
    passRepository:  passRepo,
    showRepository:  showRepo,
    eventBus:        bus,
    idGenerator:     uuid,
    clock:           () => new Date(), // injectable for determinism
  });
}

function givenStakePassUseCase({ passRepo, bus }) {
  return new StakePass({
    passRepository: passRepo,
    eventBus:       bus,
    clock:          () => new Date(),
  });
}

/* ──────────────────────────────────────────────────────────────────
 * Tests
 * ────────────────────────────────────────────────────────────────── */

describe('Show-Pass lifecycle', () => {
  let passRepository;
  let showRepository;
  let eventBus;

  beforeEach(() => {
    passRepository  = new InMemoryPassRepository();
    showRepository  = new InMemoryShowRepository();
    eventBus        = new FakeEventBus();
  });

  /* ─────────────── Minting ─────────────── */

  it('mints a new pass with correct metadata and persists it', async () => {
    // Arrange
    const mintShowPass = givenMintShowPassUseCase({
      passRepo: passRepository,
      showRepo: showRepository,
      bus:      eventBus,
    });

    const owner   = anyEthAddress();
    const tier    = 'VIP';
    const showId  = showRepository.defaultShowId;

    // Act
    const mintedPass = await mintShowPass.execute({
      showId,
      owner,
      tier,
      requestedAt: now(),
    });

    // Assert
    const persisted = await passRepository.findById(mintedPass.id);

    expect(persisted).toBeDefined();
    expect(persisted.owner).toBe(owner);
    expect(persisted.showId).toBe(showId);
    expect(persisted.tier).toBe(tier);
    expect(eventBus.eventCount('PassMinted')).toBe(1);

    const lastEvent = eventBus.pullLast();
    expect(lastEvent.payload.passId).toBe(mintedPass.id);
    expect(lastEvent.payload.owner).toBe(owner);
  });

  it('throws when trying to mint the same tier twice for one owner / show', async () => {
    // Arrange
    const mintShowPass = givenMintShowPassUseCase({
      passRepo: passRepository,
      showRepo: showRepository,
      bus:      eventBus,
    });

    const owner   = anyEthAddress();
    const tier    = 'GA';
    const showId  = showRepository.defaultShowId;

    await mintShowPass.execute({ showId, owner, tier, requestedAt: now() });

    // Act + Assert
    await expect(
      mintShowPass.execute({ showId, owner, tier, requestedAt: now() }),
    ).rejects.toThrow('PASS_ALREADY_EXISTS');
  });

  it('rejects unknown showId on mint', async () => {
    // Arrange
    const mintShowPass = givenMintShowPassUseCase({
      passRepo: passRepository,
      showRepo: showRepository,
      bus:      eventBus,
    });

    const owner   = anyEthAddress();
    const tier    = 'GA';
    const unknown = uuid(); // not whitelisted in InMemoryShowRepository

    // Act + Assert
    await expect(
      mintShowPass.execute({ showId: unknown, owner, tier, requestedAt: now() }),
    ).rejects.toThrow('SHOW_NOT_FOUND');
  });

  /* ─────────────── Staking ─────────────── */

  it('stakes an existing pass and publishes PassStaked event', async () => {
    // Arrange
    const mintShowPass  = givenMintShowPassUseCase({
      passRepo: passRepository,
      showRepo: showRepository,
      bus:      eventBus,
    });

    const stakePass     = givenStakePassUseCase({ passRepo: passRepository, bus: eventBus });

    const owner  = anyEthAddress();
    const tier   = 'VIP';
    const showId = showRepository.defaultShowId;

    const { id: passId } = await mintShowPass.execute({
      showId,
      owner,
      tier,
      requestedAt: now(),
    });

    // Act
    const stakedPass = await stakePass.execute({
      passId,
      owner,
      stakedAt: now(),
    });

    // Assert
    expect(stakedPass.isStaked).toBe(true);
    expect(stakedPass.stakedAt).toBeDefined();
    expect(eventBus.eventCount('PassStaked')).toBe(1);

    const lastEvent = eventBus.pullLast();
    expect(lastEvent.payload.passId).toBe(passId);
    expect(lastEvent.payload.owner).toBe(owner);
  });

  it('prevents double-staking of the same pass', async () => {
    // Arrange
    const mintShowPass  = givenMintShowPassUseCase({
      passRepo: passRepository,
      showRepo: showRepository,
      bus:      eventBus,
    });

    const stakePass     = givenStakePassUseCase({ passRepo: passRepository, bus: eventBus });

    const owner  = anyEthAddress();
    const tier   = 'GA';
    const showId = showRepository.defaultShowId;

    const { id: passId } = await mintShowPass.execute({
      showId,
      owner,
      tier,
      requestedAt: now(),
    });

    await stakePass.execute({ passId, owner, stakedAt: now() });

    // Act + Assert
    await expect(
      stakePass.execute({ passId, owner, stakedAt: now() }),
    ).rejects.toThrow('PASS_ALREADY_STAKED');
  });

  it('fails staking when pass does not belong to owner', async () => {
    // Arrange
    const mintShowPass  = givenMintShowPassUseCase({
      passRepo: passRepository,
      showRepo: showRepository,
      bus:      eventBus,
    });

    const stakePass     = givenStakePassUseCase({ passRepo: passRepository, bus: eventBus });

    const realOwner = anyEthAddress();
    const impostor  = anyEthAddress();
    const tier      = 'GA';
    const showId    = showRepository.defaultShowId;

    const { id: passId } = await mintShowPass.execute({
      showId,
      owner: realOwner,
      tier,
      requestedAt: now(),
    });

    // Act + Assert
    await expect(
      stakePass.execute({ passId, owner: impostor, stakedAt: now() }),
    ).rejects.toThrow('NOT_PASS_OWNER');
  });
});
```