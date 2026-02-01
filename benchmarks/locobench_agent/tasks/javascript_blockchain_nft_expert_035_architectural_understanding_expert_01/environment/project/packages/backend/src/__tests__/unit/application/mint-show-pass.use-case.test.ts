```typescript
/**************************************************************************************************
 * File: packages/backend/src/__tests__/unit/application/mint-show-pass.use-case.test.ts
 * Description:
 *   Unit-tests for the MintShowPass use-case.  The use-case is responsible for orchestrating the
 *   complete workflow of minting an up-gradable NFT ticket (a.k.a. “show-pass”).  Tests ensure
 *   correct interaction with repositories, blockchain gateway, and event-bus, while covering
 *   success path, business-rule violations and external-failure scenarios.
 *************************************************************************************************/

import { MintShowPass } from '../../../../application/mint-show-pass.use-case';
import {
  PassRepository,
  ShowRepository,
  BlockchainGatewayPort,
  EventBusPort,
  IdGeneratorPort
} from '../../../../domain/ports';                // Barrel file aggregating all ports
import { PassMintedEvent } from '../../../../domain/events/pass-minted.event';
import { Show } from '../../../../domain/entities/show.entity';
import { Pass } from '../../../../domain/entities/pass.entity';
import { DomainError } from '../../../../domain/errors/domain-error';

// Jest helpers
import { jest } from '@jest/globals';

// --------------------------------------------------------------------------------------------------------------------
// Mock implementations of ports
// --------------------------------------------------------------------------------------------------------------------
const passRepositoryMock = (): jest.Mocked<PassRepository> => ({
  findByShowAndOwner:      jest.fn(),
  save:                    jest.fn(),
  ofId:                    jest.fn(),          // Additional method(s) used elsewhere in codebase
  remove:                  jest.fn()
});

const showRepositoryMock = (): jest.Mocked<ShowRepository> => ({
  findById:                jest.fn(),
  isSoldOut:               jest.fn(),
  incrementMintedCount:    jest.fn()
});

const blockchainGatewayMock = (): jest.Mocked<BlockchainGatewayPort> => ({
  mintShowPass:            jest.fn()
});

const eventBusMock = (): jest.Mocked<EventBusPort> => ({
  publish:                 jest.fn()
});

const idGeneratorMock = (): jest.Mocked<IdGeneratorPort> => ({
  generate:                jest.fn()
});

// --------------------------------------------------------------------------------------------------------------------
// Test suite
// --------------------------------------------------------------------------------------------------------------------
describe('MintShowPass – Use-Case', () => {
  const SHOW_ID   = 'show-123';
  const OWNER_ID  = '0xF4cC97e8C7c4b5a3cAF1312cA66fDBe7d5cE477a';  // Eth wallet
  const PASS_ID   = 'pass-999';
  const TOKEN_ID  = 42;
  const TX_HASH   = '0xabc';

  let passRepo:       jest.Mocked<PassRepository>;
  let showRepo:       jest.Mocked<ShowRepository>;
  let blockchain:     jest.Mocked<BlockchainGatewayPort>;
  let eventBus:       jest.Mocked<EventBusPort>;
  let idGenerator:    jest.Mocked<IdGeneratorPort>;

  let subject: MintShowPass;

  beforeEach(() => {
    // Instantiate a fresh mock set before each test
    passRepo       = passRepositoryMock();
    showRepo       = showRepositoryMock();
    blockchain     = blockchainGatewayMock();
    eventBus       = eventBusMock();
    idGenerator    = idGeneratorMock();

    // Common mock behaviour
    idGenerator.generate.mockReturnValue(PASS_ID);
    showRepo.findById.mockResolvedValue(
      Show.restore({                       // `restore` brings an existing aggregate from persistence
        id: SHOW_ID,
        capacity: 100,
        mintedCount: 1,
        title: 'Burning Beats Festival'
      })
    );
    showRepo.isSoldOut.mockResolvedValue(false);

    blockchain.mintShowPass.mockResolvedValue({
      txHash:  TX_HASH,
      tokenId: TOKEN_ID
    });

    subject = new MintShowPass(
      passRepo,
      showRepo,
      blockchain,
      eventBus,
      idGenerator
    );
  });

  // ------------------------------------------------------------------------------------------------
  // Successful mint
  // ------------------------------------------------------------------------------------------------
  it('mints a new show-pass, persists it, and raises a PassMinted event', async () => {
    // Given ‑ owner has NOT minted a pass before
    passRepo.findByShowAndOwner.mockResolvedValue(null);

    // When
    const result = await subject.execute({
      showId:  SHOW_ID,
      ownerId: OWNER_ID,
      tier:    'VIP'
    });

    // Then ‑ repositories and ports have been called with expected parameters
    expect(idGenerator.generate).toHaveBeenCalledTimes(1);

    // Blockchain call
    expect(blockchain.mintShowPass).toHaveBeenCalledWith(OWNER_ID, expect.objectContaining({
      showId: SHOW_ID,
      tier:   'VIP'
    }));

    // Repository save
    expect(passRepo.save).toHaveBeenCalledTimes(1);
    const savedPass = passRepo.save.mock.calls[0][0] as Pass;
    expect(savedPass.id).toBe(PASS_ID);
    expect(savedPass.tokenId).toBe(TOKEN_ID);

    // Show repository update
    expect(showRepo.incrementMintedCount).toHaveBeenCalledWith(SHOW_ID);

    // Event bus publish
    expect(eventBus.publish).toHaveBeenCalledWith(
      expect.any(PassMintedEvent)
    );

    // Use-case returns the newly created pass aggregate
    expect(result.id).toBe(PASS_ID);
    expect(result.ownerId).toBe(OWNER_ID);
    expect(result.txHash).toBe(TX_HASH);
  });

  // ------------------------------------------------------------------------------------------------
  // Business-rule: user already owns a pass
  // ------------------------------------------------------------------------------------------------
  it('throws a DomainError when the owner already possesses a pass for the show', async () => {
    // Given
    passRepo.findByShowAndOwner.mockResolvedValue(
      Pass.restore({
        id:      'existing-pass',
        showId:  SHOW_ID,
        ownerId: OWNER_ID,
        tokenId: 1,
        tier:    'GA',
        txHash:  '0xdeadbeef'
      })
    );

    // When / Then
    await expect(
      subject.execute({ showId: SHOW_ID, ownerId: OWNER_ID, tier: 'VIP' })
    ).rejects.toThrow(DomainError);

    // Ensure no side-effects occurred
    expect(blockchain.mintShowPass).not.toHaveBeenCalled();
    expect(passRepo.save).not.toHaveBeenCalled();
    expect(eventBus.publish).not.toHaveBeenCalled();
  });

  // ------------------------------------------------------------------------------------------------
  // Business-rule: show is sold out
  // ------------------------------------------------------------------------------------------------
  it('throws a DomainError when the show is sold out', async () => {
    // Given
    showRepo.isSoldOut.mockResolvedValue(true);

    // When / Then
    await expect(
      subject.execute({ showId: SHOW_ID, ownerId: OWNER_ID, tier: 'VIP' })
    ).rejects.toThrow(DomainError);

    // No external calls
    expect(blockchain.mintShowPass).not.toHaveBeenCalled();
    expect(passRepo.save).not.toHaveBeenCalled();
    expect(eventBus.publish).not.toHaveBeenCalled();
  });

  // ------------------------------------------------------------------------------------------------
  // External failure: blockchain transaction fails
  // ------------------------------------------------------------------------------------------------
  it('propagates blockchain errors and performs no persistence on failure', async () => {
    // Given
    blockchain.mintShowPass.mockRejectedValue(new Error('Gas price too low'));

    // When / Then
    await expect(
      subject.execute({ showId: SHOW_ID, ownerId: OWNER_ID, tier: 'VIP' })
    ).rejects.toThrow('Gas price too low');

    // Check that the system did NOT persist the pass nor publish event
    expect(passRepo.save).not.toHaveBeenCalled();
    expect(eventBus.publish).not.toHaveBeenCalled();
    // Mint count must not be incremented
    expect(showRepo.incrementMintedCount).not.toHaveBeenCalled();
  });
});
```