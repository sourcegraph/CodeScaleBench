```typescript
/* eslint-disable max-classes-per-file */
/**
 * File: packages/backend/src/__tests__/integration/pass.integration.test.ts
 *
 * High-level integration tests for the Pass (show-ticket NFT) flow.
 * The goal is to validate end-to-end behaviour starting from the HTTP
 * boundary down to the (stubbed) smart-contract gateway, persistence
 * layer and domain event bus.
 *
 * NOTE: these tests purposefully spin up an Express app with fully
 * in-memory adapters so that no external services (database, chain node,
 * message broker, etc.) are required. The wiring logic mirrors the real
 * production composition found in the IoC bootstrapper, giving us a
 * realistic testing surface while keeping the suite fast and deterministic.
 *
 * Tech-stack: Jest, Supertest, TypeScript
 */
import { randomUUID } from 'crypto';
import http, { Server } from 'http';
import express, { Express, Request, Response } from 'express';
import supertest from 'supertest';
import { ethers } from 'ethers';

/*--------------------------------------------------------------------*/
/*  Domain layer – simplified representations for the purposes of     */
/*  these tests. In production these come from the real domain pkg.   */
/*--------------------------------------------------------------------*/
type WalletAddress = `0x${string}`;

class Show {
  constructor(
    public readonly id: string,
    public readonly title: string,
    public readonly startsAt: Date,
  ) {}
}

class Pass {
  constructor(
    public readonly tokenId: string,
    public readonly showId: string,
    public readonly owner: WalletAddress,
    public readonly txHash: string,
  ) {}
}

/*--------------------------------------------------------------------*/
/*  Domain Events                                                     */
/*--------------------------------------------------------------------*/
class PassMintedEvent {
  readonly type = 'PassMinted';

  constructor(public readonly payload: Pass) {}
}

/*--------------------------------------------------------------------*/
/*  Ports & Adapters (in-memory stubs for integration testing)        */
/*--------------------------------------------------------------------*/
interface EventBus {
  publish(event: PassMintedEvent): Promise<void>;
  takeLast(): PassMintedEvent | undefined;
}

class InMemoryEventBus implements EventBus {
  private readonly buffer: PassMintedEvent[] = [];

  async publish(event: PassMintedEvent): Promise<void> {
    this.buffer.push(event);
  }

  takeLast(): PassMintedEvent | undefined {
    return this.buffer.pop();
  }
}

interface PassRepository {
  save(pass: Pass): Promise<void>;
  findByShowAndOwner(showId: string, owner: WalletAddress): Promise<Pass | null>;
  count(): Promise<number>;
}

class InMemoryPassRepository implements PassRepository {
  private readonly store = new Map<string, Pass>();

  async save(pass: Pass): Promise<void> {
    this.store.set(pass.tokenId, pass);
  }

  async findByShowAndOwner(showId: string, owner: WalletAddress): Promise<Pass | null> {
    for (const p of this.store.values()) {
      if (p.showId === showId && p.owner === owner) return p;
    }
    return null;
  }

  async count(): Promise<number> {
    return this.store.size;
  }
}

interface ShowRepository {
  getById(id: string): Promise<Show | null>;
  save(show: Show): Promise<void>;
}

class InMemoryShowRepository implements ShowRepository {
  private readonly store = new Map<string, Show>();

  async getById(id: string): Promise<Show | null> {
    return this.store.get(id) ?? null;
  }

  async save(show: Show): Promise<void> {
    this.store.set(show.id, show);
  }
}

interface SmartContractGateway {
  mintPass(showId: string, owner: WalletAddress): Promise<{ tokenId: string; txHash: string }>;
}

class FakeSmartContractGateway implements SmartContractGateway {
  async mintPass(): Promise<{ tokenId: string; txHash: string }> {
    // Fake the on-chain interaction by returning deterministic, but unique, IDs.
    return {
      tokenId: randomUUID(),
      txHash: ethers.utils.hexlify(ethers.utils.randomBytes(32)),
    };
  }
}

/*--------------------------------------------------------------------*/
/*  Use-case implementation                                           */
/*--------------------------------------------------------------------*/
class MintShowPass {
  constructor(
    private readonly passRepo: PassRepository,
    private readonly showRepo: ShowRepository,
    private readonly scGateway: SmartContractGateway,
    private readonly eventBus: EventBus,
  ) {}

  async execute(showId: string, owner: WalletAddress): Promise<Pass> {
    // Guard 1: Is show live?
    const show = await this.showRepo.getById(showId);
    if (!show) throw new Error(`Show ${showId} not found`);

    // Guard 2: Prevent double-minting for same wallet
    const existing = await this.passRepo.findByShowAndOwner(showId, owner);
    if (existing) throw new Error(`Pass already minted for ${owner} on show ${showId}`);

    // Side-effect: Mint on-chain
    const { tokenId, txHash } = await this.scGateway.mintPass(showId, owner);

    // Persist in repository
    const pass = new Pass(tokenId, showId, owner, txHash);
    await this.passRepo.save(pass);

    // Emit domain event
    await this.eventBus.publish(new PassMintedEvent(pass));

    return pass;
  }
}

/*--------------------------------------------------------------------*/
/*  Express composition for the tests                                 */
/*--------------------------------------------------------------------*/
interface TestAppContext {
  app: Express;
  server: Server;
  passRepo: InMemoryPassRepository;
  showRepo: InMemoryShowRepository;
  eventBus: InMemoryEventBus;
}

async function createTestApplication(): Promise<TestAppContext> {
  const passRepo = new InMemoryPassRepository();
  const showRepo = new InMemoryShowRepository();
  const eventBus = new InMemoryEventBus();
  const scGateway = new FakeSmartContractGateway();

  const mintShowPass = new MintShowPass(passRepo, showRepo, scGateway, eventBus);

  const app = express();
  app.use(express.json());

  /**
   * POST /shows/:id/passes/mint
   * body:
   *   { owner: "0xabc..." }
   */
  app.post('/shows/:id/passes/mint', async (req: Request, res: Response) => {
    const { id: showId } = req.params;
    const { owner } = req.body;

    // Basic payload validation – real implementation would be more robust
    if (!owner || !ethers.utils.isAddress(owner)) {
      return res.status(400).json({ message: 'Invalid owner address' });
    }

    try {
      const pass = await mintShowPass.execute(showId, owner as WalletAddress);
      return res.status(201).json(pass);
    } catch (err) {
      if (err instanceof Error) {
        if (err.message.includes('not found')) return res.status(404).json({ message: err.message });
        if (err.message.includes('already')) return res.status(409).json({ message: err.message });
      }
      // Fallback 500
      // eslint-disable-next-line no-console
      console.error(err);
      return res.status(500).json({ message: 'Internal server error' });
    }
  });

  // Create HTTP server to more closely mimic production deployment
  const server = http.createServer(app);

  return { app, server, passRepo, showRepo, eventBus };
}

/*--------------------------------------------------------------------*/
/*  Jest hooks & test cases                                           */
/*--------------------------------------------------------------------*/
describe('Pass – Integration Flow', () => {
  let ctx: TestAppContext;
  const request = () => supertest(ctx.app);

  const sampleShowId = randomUUID();
  const sampleWallet: WalletAddress = ethers.Wallet.createRandom().address as WalletAddress;

  beforeAll(async () => {
    ctx = await createTestApplication();
    // Start the server so that any middlewares relying on req.socket, etc. work
    await new Promise<void>((resolve) => ctx.server.listen(0, resolve));

    // Seed a show fixture
    const upcomingShow = new Show(sampleShowId, '🎸  TestFest 2033', new Date(Date.now() + 86_400_000));
    await ctx.showRepo.save(upcomingShow);
  });

  afterAll(async () => {
    await new Promise<void>((resolve) => ctx.server.close(() => resolve()));
  });

  it('successfully mints a new pass NFT and persists the record', async () => {
    const res = await request()
      .post(`/shows/${sampleShowId}/passes/mint`)
      .send({ owner: sampleWallet })
      .expect(201);

    // Response schema validation
    expect(res.body).toEqual(
      expect.objectContaining({
        tokenId: expect.any(String),
        showId: sampleShowId,
        owner: sampleWallet,
        txHash: expect.stringMatching(/^0x[a-fA-F0-9]{64}$/),
      }),
    );

    // Repository side-effect
    expect(await ctx.passRepo.count()).toBe(1);

    // Domain Event emission
    const evt = ctx.eventBus.takeLast();
    expect(evt?.type).toBe('PassMinted');
    expect(evt?.payload.tokenId).toBe(res.body.tokenId);
  });

  it('prevents double-minting for the same wallet / show combo', async () => {
    await request()
      .post(`/shows/${sampleShowId}/passes/mint`)
      .send({ owner: sampleWallet })
      .expect(409); // Conflict

    // Repository should still hold only 1 record
    expect(await ctx.passRepo.count()).toBe(1);
  });

  it('returns 400 for invalid wallet address', async () => {
    await request()
      .post(`/shows/${sampleShowId}/passes/mint`)
      .send({ owner: 'not-a-wallet' })
      .expect(400);
  });

  it('returns 404 when show is not found', async () => {
    const unknownShowId = randomUUID();
    await request()
      .post(`/shows/${unknownShowId}/passes/mint`)
      .send({ owner: ethers.Wallet.createRandom().address })
      .expect(404);
  });
});
```