```typescript
/**
 * Cypress – Reusable Custom Commands
 * file: packages/frontend/cypress/support/commands.ts
 *
 * These helpers make e2e/ci tests declarative and resilient by abstracting
 * common flows across the StellarStage Carnival dApp such as:
 *  • Simulated wallet connections & signature prompts
 *  • GraphQL operation interception / aliasing
 *  • NFT minting, staking and governance actions
 *  • UI-level assertions (toasts, loaders, balances, etc.)
 *
 * NOTE: All commands are written in TypeScript and augment the Cypress chain-able
 * type definitions for proper IntelliSense.
 */

import 'cypress-wait-until';               // Utility plugin for async polling
import '@testing-library/cypress/add-commands'; // Testing Library commands
import { faker } from '@faker-js/faker';   // Used for generating random test data

// -----------------------------------------------------------------------------
// Config
// -----------------------------------------------------------------------------

/**
 * Default GraphQL endpoint path that the front-end uses (see Apollo client setup)
 */
const GRAPHQL_ROUTE = '/graphql';

/**
 * A deterministic test wallet (never funded on mainnet!!) used to stub
 * Metamask/EIP-1193 provider interactions in CI environments.
 */
const TEST_WALLET = {
  address: '0xAbCdEf0123456789aBCdef0123456789aBCDef01',
  privateKey:
    '0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
};

// -----------------------------------------------------------------------------
// Utility helpers (internal)
// -----------------------------------------------------------------------------

/**
 * Injects a lightweight EIP-1193 stub provider onto the window object. This is
 * enough for front-end wallet-detection libraries (ethers.js, web3-react, wagmi,
 * etc.) to believe that a user has a connected wallet.
 */
function injectStubProvider(win: Window & typeof globalThis) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const provider: any = {
    isMetaMask: true,
    selectedAddress: TEST_WALLET.address,
    request: ({ method, params }: { method: string; params?: unknown[] }) => {
      switch (method) {
        case 'eth_requestAccounts':
        case 'eth_accounts':
          return Promise.resolve([TEST_WALLET.address]);
        case 'personal_sign':
          // Naïve signature imitation — DO NOT expose real keys in test builds.
          return Promise.resolve(
            `0x${Buffer.from('signed:' + params?.[0]).toString('hex')}`,
          );
        case 'eth_chainId':
          // Arbitrarily choose Goerli id
          return Promise.resolve('0x5');
        default:
          throw new Error(`Provider method not mocked: ${method}`);
      }
    },
    on: cy.stub().as('providerOn'),
    removeListener: cy.stub().as('providerRemoveListener'),
  };

  // Inject onto window as the primary provider
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (win as any).ethereum = provider;
}

/**
 * Intercepts every GraphQL POST request and aliases by operationName so that tests
 * can `cy.wait('@GetShowQuery')` independently of network details.
 */
function setupGraphQLInterceptor() {
  cy.intercept('POST', GRAPHQL_ROUTE, (req) => {
    // Make sure it has an operationName. For anonymous ops we give fallback
    const opName =
      req.body.operationName ??
      (req.body.query.match(/^\s*(query|mutation)\s+(\w+)/)?.[2] || 'anonymous');

    req.alias = opName;
  });
}

// -----------------------------------------------------------------------------
// Cypress Command Augmentation
// -----------------------------------------------------------------------------

declare global {
  namespace Cypress {
    interface Chainable {
      /**
       * Boots the dApp with a stubbed wallet already connected.
       *
       * Usage:
       *    cy.visitWithStubbedWallet('/');
       */
      visitWithStubbedWallet(path?: string): Chainable<Element>;

      /**
       * Mints a new ShowPass NFT for the currently selected Show.
       *
       * Usage:
       *    cy.mintShowPass().then(passId => { ... })
       */
      mintShowPass(): Chainable<string>;

      /**
       * Stakes the given Pass ID for governance rewards.
       *
       * Usage:
       *    cy.stakePass('1234');
       */
      stakePass(passId: string): Chainable<Element>;

      /**
       * Asserts that a toast notification with given text is visible.
       *
       * Usage:
       *    cy.assertToast('Mint successful');
       */
      assertToast(message: string): Chainable<Element>;

      /**
       * Helper to alias all GraphQL requests by operationName.
       */
      interceptGraphQL(): Chainable<void>;
    }
  }
}

// -----------------------------------------------------------------------------
// Command Implementations
// -----------------------------------------------------------------------------

/**
 * Visits the provided route and injects a stubbed provider *before* any
 * application code runs. Also wires up GraphQL aliasing.
 */
Cypress.Commands.add(
  'visitWithStubbedWallet',
  (path = '/') => {
    cy.log('🔌  Injecting stubbed EIP-1193 provider');

    cy.visit(path, {
      onBeforeLoad: (win) => {
        injectStubProvider(win);
      },
    });

    cy.interceptGraphQL();

    // Wait until front-end dispatches a "wallet connected" event
    cy.waitUntil(() =>
      cy.window().then((w) => !!(w as any).__TEST_STATE__?.walletConnected),
    );
  },
);

/**
 * Aliases GraphQL requests for easy waits and fixture injections.
 */
Cypress.Commands.add('interceptGraphQL', () => {
  setupGraphQLInterceptor();
});

/**
 * Mints a new ShowPass NFT via the UI modal flow. The GraphQL mutation
 * is aliased so tests can hook into the resulting passID.
 */
Cypress.Commands.add('mintShowPass', () => {
  cy.log('🎟️  Minting new ShowPass');

  // Open mint modal
  cy.findByRole('button', { name: /mint/i }).click();

  // Select default tier
  cy.findByRole('radio', { name: /general admission/i }).check({ force: true });

  // Submit
  cy.findByRole('button', { name: /confirm mint/i }).click();

  // Wait for mutation
  cy.wait('@MintShowPass').then((interception) => {
    const passId = interception.response?.body?.data?.mintShowPass?.passId;
    expect(passId, 'returned passId').to.be.a('string').and.not.be.empty;

    cy.wrap(passId).as('mintedPassId');
  });

  // Toast appears
  cy.assertToast(/successfully minted/i);

  return cy.get<string>('@mintedPassId');
});

/**
 * Stakes a given Pass ID from the portfolio screen.
 */
Cypress.Commands.add('stakePass', (passId: string) => {
  cy.log(`📌  Staking pass ${passId}`);

  cy.visitWithStubbedWallet(`/portfolio/${passId}`);

  cy.findByRole('button', { name: /stake/i }).click();

  // Confirm modal
  cy.findByRole('button', { name: /confirm stake/i }).click();

  cy.wait('@StakePass');

  cy.assertToast(/pass staked/i);
});

/**
 * Simple assertion that a toast with specific text is present.
 */
Cypress.Commands.add('assertToast', (message: string | RegExp) => {
  cy.findByRole('status', { timeout: 10_000 })
    .should('be.visible')
    .and('contain.text', message);
});

// -----------------------------------------------------------------------------
// Global beforeEach/afterEach hooks (optional)
// -----------------------------------------------------------------------------

/**
 * Reset backend between tests when running against ephemeral dev chains. This
 * keeps NFT/token state isolated from test to test. We rely on a testing-only
 * HTTP endpoint exposed via docker-compose config.
 */
beforeEach(() => {
  cy.request('POST', '/__e2e__/reset');
});

/**
 * Automatically fail test if there are uncaught GraphQL errors in network
 * responses. This helps surface backend issues early.
 */
afterEach(() => {
  cy.get('@GraphQLErrors', { log: false }).then((errors) => {
    if (errors && errors.length) {
      throw new Error(
        `GraphQL errors detected in test:\n${JSON.stringify(errors, null, 2)}`,
      );
    }
  });
});
```