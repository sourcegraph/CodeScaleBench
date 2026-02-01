```typescript
/// <reference types="cypress" />

/**
 * nft_minting_flow.spec.ts
 * --------------------------------------------------
 * End-to-end tests for the NFT minting user flow that
 * powers the StellarStage Carnival front-end.
 *
 * The tests:
 *  1. Stub the injected `window.ethereum` provider
 *  2. Intercept GraphQL + REST calls to backend + chain
 *  3. Assert optimistic UI behavior during pending state
 *  4. Assert final UI state once the transaction is mined
 *  5. Cover unhappy-path (reverted transaction) branches
 *
 * NOTE: These tests exercise only the browser layer. The
 *       domain + smart-contract specifics are mocked out
 *       so that the test suite remains deterministic and
 *       network-agnostic.
 * --------------------------------------------------
 */

import { ethers } from 'ethers';
import { faker } from '@faker-js/faker';

type EthereumRequestArgs = {
  method: string;
  params?: any[];
};

const GRAPHQL_ENDPOINT = '/graphql';
const REST_MINT_ENDPOINT = '/api/mint/show-pass';

const FAKE_ACCOUNT = `0x${'cafe'.padEnd(40, '0')}`;
const FAKE_TX_HASH = `0x${'deadbeef'.padEnd(64, '0')}`;

/**
 * Injects a stubbed EIP-1193 provider so that the dApp can
 * interact with a "wallet" without depending on a real one.
 */
function injectStubbedProvider(): void {
  cy.window().then((win) => {
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore – we intentionally add the field
    win.ethereum = {
      isMetaMask: true,
      request: ({ method }: EthereumRequestArgs) => {
        switch (method) {
          case 'eth_requestAccounts':
          case 'eth_accounts':
            return Promise.resolve([FAKE_ACCOUNT]);

          case 'eth_chainId':
            // Mainnet
            return Promise.resolve('0x1');

          case 'eth_sendTransaction':
            // Simulate async mining delay
            return new Promise((resolve) => {
              setTimeout(() => resolve(FAKE_TX_HASH), 500);
            });

          case 'eth_getTransactionReceipt':
            return Promise.resolve({
              status: '0x1',
              transactionHash: FAKE_TX_HASH,
              blockNumber: ethers.utils.hexlify(15_000_000),
            });

          default:
            // Unsupported method: fail fast so we catch newly
            // introduced calls that aren’t covered by the stub.
            throw new Error(`Unsupported ethereum.request(${method})`);
        }
      },
      // Event listeners are no-ops for the purpose of this test
      on: cy.stub(),
      removeListener: cy.stub(),
    };
  });
}

/**
 * Intercepts the on-chain mint REST call so we can stub
 * various code-paths (success, revert, insufficient gas…)
 */
function interceptMintEndpoint({
  statusCode = 200,
  failWithRevert = false,
}: {
  statusCode?: number;
  failWithRevert?: boolean;
} = {}): void {
  cy.intercept('POST', REST_MINT_ENDPOINT, (req) => {
    if (failWithRevert) {
      req.reply({
        statusCode: 400,
        body: { message: 'Transaction reverted: balance too low' },
      });
      return;
    }

    req.reply({
      delay: 300, // simulate network latency
      statusCode,
      body: { txHash: FAKE_TX_HASH },
    });
  }).as('mintRequest');
}

/**
 * Intercepts GraphQL requests so we can stub the cache
 * evolution during optimistic UI updates.
 */
function interceptGraphQl() {
  cy.intercept('POST', GRAPHQL_ENDPOINT, (req) => {
    const { operationName } = req.body;

    switch (operationName) {
      case 'ShowPassQuery':
        req.alias = 'gqlShowPass';
        // First fetch returns "no pass yet"
        if (!req.headers['x-test-pass-owned']) {
          req.reply({
            data: { viewerPass: null },
          });
        } else {
          // Subsequent fetch returns minted pass
          req.reply({
            data: {
              viewerPass: {
                id: nanoId(),
                owner: FAKE_ACCOUNT,
                level: 1,
                traits: ['Early-Bird'],
              },
            },
          });
        }
        break;

      case 'MintShowPassMutation':
        req.alias = 'gqlMintPass';
        req.reply({
          data: { mintShowPass: { txHash: FAKE_TX_HASH } },
        });
        break;

      default:
        // Let anything else through untouched
        break;
    }
  });
}

/**
 * Generates a nano-sized id for GraphQL mocks
 */
function nanoId(): string {
  return faker.string.alphanumeric(12);
}

describe('NFT Minting Flow', () => {
  beforeEach(() => {
    injectStubbedProvider();
    interceptGraphQl();
  });

  it('successfully mints a Show-Pass NFT and updates the UI', () => {
    interceptMintEndpoint();

    cy.visit('/shows/galactic-odyssey');

    // Connect wallet
    cy.contains('Connect Wallet').click();
    cy.findByText(new RegExp(FAKE_ACCOUNT.slice(0, 6))).should('be.visible');

    // Mint CTA should become enabled
    cy.contains('button', /Mint.*Pass/i).as('mintButton').should('be.enabled');
    cy.get('@mintButton').click();

    // Optimistic UI: pending state
    cy.contains(/Minting in progress/i).should('be.visible');

    // Wait for the REST endpoint and GraphQL mutation
    cy.wait('@mintRequest');
    cy.wait('@gqlMintPass');

    // Force a refresh of ShowPassQuery with header trick
    cy.intercept('POST', GRAPHQL_ENDPOINT, (req) => {
      if (req.body.operationName === 'ShowPassQuery') {
        req.headers['x-test-pass-owned'] = 'true';
      }
    });

    // UI should eventually reflect ownership
    cy.contains(/Your Show-Pass/i, { timeout: 10_000 }).should('be.visible');
    cy.contains(/Level 1/i).should('be.visible');
    cy.contains(/Early-Bird/i).should('be.visible');
  });

  it('surfaces a meaningful error message when the transaction reverts', () => {
    interceptMintEndpoint({ statusCode: 400, failWithRevert: true });

    cy.visit('/shows/galactic-odyssey');
    cy.contains('Connect Wallet').click();

    cy.contains('button', /Mint.*Pass/i).click();

    cy.wait('@mintRequest');

    cy.contains(/Transaction reverted/i, { timeout: 5_000 }).should('be.visible');
    cy.contains(/balance too low/i).should('be.visible');

    // The CTA should allow retry after a failure
    cy.contains('button', /Retry/i).should('be.enabled');
  });

  it('disables minting when the viewer already owns a pass', () => {
    // Intercept ShowPassQuery to immediately return that the user owns a pass
    cy.intercept('POST', GRAPHQL_ENDPOINT, (req) => {
      if (req.body.operationName === 'ShowPassQuery') {
        req.reply({
          data: {
            viewerPass: {
              id: nanoId(),
              owner: FAKE_ACCOUNT,
              level: 4,
              traits: ['VIP', 'Backstage'],
            },
          },
        });
      }
    });

    cy.visit('/shows/galactic-odyssey');

    cy.contains(/Your Show-Pass/i).should('be.visible');
    cy.contains(/Level 4/i).should('be.visible');

    cy.contains('button', /Mint.*Pass/i).should('be.disabled');
  });
});
```