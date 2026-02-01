```typescript
/**
 * StellarStage Carnival – Database Seeder
 *
 * This script bootstraps a brand-new database with canonical data that the
 * platform relies on to operate in non-production environments (local, CI,
 * staging). It inserts:
 *
 *   1. Sample Shows   – live events that wrap multiple Acts
 *   2. ShowPass NFT   – tiered admission tokens bound to an ERC-721 proxy
 *   3. Loot catalog   – on-chain & off-chain reward blueprints
 *
 * IMPORTANT:
 *   • This script is idempotent – it can be executed multiple times safely.
 *   • All contract addresses are pulled from env vars so we never commit keys.
 *   • Any change here must be reflected in end-to-end tests that rely on the seed.
 */

import 'dotenv/config';
import { PrismaClient, Prisma } from '@prisma/client';
import { randomUUID } from 'crypto';

const prisma = new PrismaClient();

/* -------------------------------------------------------------------------- */
/*                              Helper Utilities                              */
/* -------------------------------------------------------------------------- */

/**
 * Generates a pseudo-random IPFS CID for demo purposes.
 */
const mockCid = () => `bafybeigd${randomUUID().replace(/-/g, '').slice(0, 46)}`;

/**
 * Wraps a call in a "find-or-create" behaviour so that repeated calls
 * won't violate unique constraints.
 */
async function upsertUnique<T extends Prisma.Prisma__Pick<Prisma.ModelName, string>>(
  model: T,
  where: object,
  create: any,
  update: any = {},
) {
  // @ts-ignore – dynamic model access
  return prisma[model].upsert({ where, create, update });
}

/* -------------------------------------------------------------------------- */
/*                                   Seeds                                    */
/* -------------------------------------------------------------------------- */

const showSeeds: Array<{
  id: string;
  title: string;
  description: string;
  startAt: Date;
  endAt: Date;
  bannerCid: string;
  proxyContract: string;
  acts: Array<{
    id: string;
    name: string;
    performer: string;
    startsAt: Date;
    endsAt: Date;
    snapshotCid: string;
  }>;
  passes: Array<{
    id: string;
    name: string;
    supply: number;
    priceEth: string;
    tier: 'GA' | 'VIP' | 'BACKSTAGE';
  }>;
  loot: Array<{
    id: string;
    name: string;
    description: string;
    tier: 'COMMON' | 'RARE' | 'LEGENDARY';
  }>;
}> = [
  {
    id: 'show-mainnet-alpha-001',
    title: 'Carnival Genesis Concert',
    description:
      'The inaugural StellarStage spectacle featuring genre-bending artists and audience-triggered pyrotechnics.',
    startAt: new Date('2024-08-01T18:00:00Z'),
    endAt: new Date('2024-08-01T22:00:00Z'),
    bannerCid: mockCid(),
    proxyContract: process.env.GENESIS_CONCERT_PROXY || '0x0000000000000000000000000000000000000000',
    acts: [
      {
        id: 'act-alpha-dj-set',
        name: 'NeoTokyo DJ Set',
        performer: 'DJ SolSynth',
        startsAt: new Date('2024-08-01T18:00:00Z'),
        endsAt: new Date('2024-08-01T19:30:00Z'),
        snapshotCid: mockCid(),
      },
      {
        id: 'act-alpha-live-band',
        name: 'Quantum Strings',
        performer: 'The Q-Strings',
        startsAt: new Date('2024-08-01T19:45:00Z'),
        endsAt: new Date('2024-08-01T21:15:00Z'),
        snapshotCid: mockCid(),
      },
    ],
    passes: [
      { id: 'pass-alpha-ga', name: 'ShowPass GA', supply: 5000, priceEth: '0.03', tier: 'GA' },
      { id: 'pass-alpha-vip', name: 'ShowPass VIP', supply: 750, priceEth: '0.15', tier: 'VIP' },
      { id: 'pass-alpha-backstage', name: 'Backstage Badge', supply: 150, priceEth: '0.5', tier: 'BACKSTAGE' },
    ],
    loot: [
      { id: 'loot-alpha-coin', name: 'Carnival Token Airdrop', description: '50 CRC governance tokens.', tier: 'COMMON' },
      { id: 'loot-alpha-holo', name: 'Hologram Poster', description: 'Animated concert poster hologram.', tier: 'RARE' },
      { id: 'loot-alpha-1of1', name: 'Signed Master Track', description: '1-of-1 studio recording.', tier: 'LEGENDARY' },
    ],
  },
];

/* -------------------------------------------------------------------------- */
/*                                   Runner                                   */
/* -------------------------------------------------------------------------- */

async function seed() {
  console.info('🌱  Starting database seed…');

  await Promise.all(
    showSeeds.map(async (show) => {
      // 1. Upsert Show
      const dbShow = await upsertUnique('show', { id: show.id }, {
        id: show.id,
        title: show.title,
        description: show.description,
        startAt: show.startAt,
        endAt: show.endAt,
        bannerCid: show.bannerCid,
        proxyContract: show.proxyContract,
      });

      // 2. Upsert Acts
      for (const act of show.acts) {
        await upsertUnique('act', { id: act.id }, {
          id: act.id,
          name: act.name,
          performer: act.performer,
          startsAt: act.startsAt,
          endsAt: act.endsAt,
          snapshotCid: act.snapshotCid,
          showId: dbShow.id,
        });
      }

      // 3. Upsert Passes
      for (const pass of show.passes) {
        await upsertUnique('pass', { id: pass.id }, {
          id: pass.id,
          name: pass.name,
          supply: pass.supply,
          priceEth: pass.priceEth,
          tier: pass.tier,
          showId: dbShow.id,
          contractAddress: process.env.SHOWPASS_PROXY || '0x0000000000000000000000000000000000000000',
        });
      }

      // 4. Upsert Loot
      for (const item of show.loot) {
        await upsertUnique('loot', { id: item.id }, {
          id: item.id,
          name: item.name,
          description: item.description,
          tier: item.tier,
          blueprintCid: mockCid(),
          showId: dbShow.id,
        });
      }
    }),
  );

  console.info('✅  Database seeding completed successfully.');
}

/* -------------------------------------------------------------------------- */
/*                               Script Entrypoint                            */
/* -------------------------------------------------------------------------- */

seed()
  .catch((e) => {
    console.error('❌  Database seeding failed.');
    console.error(e);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
```