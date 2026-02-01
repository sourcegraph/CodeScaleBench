```javascript
/**
 * CarnivalGovernance.test.js
 *
 * Integration / unit-tests for the CarnivalGovernance stack:
 *  - CarnivalPass (ERC-721, upgradeable show-ticket NFT)
 *  - PassStaking   (ERC-721 => ERC-20 wrapper that mints voting power)
 *  - TimeLock      (governance timelock)
 *  - CarnivalGovernor (Governor-Bravo style governor contract)
 *
 * The tests spin-up the full governance pipeline in a Hardhat in-memory
 * chain, mimicking real DAO flows performed by end-users:
 *
 *  1. Fans mint a ShowPass (ERC-721)
 *  2. They stake the pass to receive voting tokens
 *  3. A proposal is created to add a new headliner to the show
 *  4. Fans vote, the proposal is queued in the timelock, executed,
 *     and the on-chain Show lineup is updated.
 *
 * Edge-cases covered:
 *  - Double-voting / late staking
 *  - Quorum not reached
 *  - Access-control on execution
 *  - Delegation flow for off-chain signature voting (EIP-712)
 */

const { expect }        = require('chai');
const { ethers, network } = require('hardhat');
const { utils, BigNumber } = ethers;

const DAY   = 24 * 60 * 60;
const WEEK  = 7  * DAY;

const ZERO_ADDRESS = ethers.constants.AddressZero;

/**
 * Helpers
 */
async function latestBlockTimestamp () {
  const block = await ethers.provider.getBlock('latest');
  return BigNumber.from(block.timestamp);
}

async function fastForward (seconds) {
  await network.provider.send('evm_increaseTime', [seconds]);
  await network.provider.send('evm_mine');
}

async function mineBlocks (count) {
  for (let i = 0; i < count; i++) {
    await network.provider.send('evm_mine');
  }
}

describe('Carnival Governance ‑ end-to-end', function () {
  let deployer, fan1, fan2, team, treasury;
  let CarnivalPass, carnivalPass;
  let PassStaking, passStaking;
  let CarnivalGovernor, carnivalGovernor;
  let TimeLock, timeLock;
  let ShowLineup, showLineup; // dummy contract to mutate through governance

  const GOVERNANCE_DELAY   = 2 * DAY;   // timelock delay
  const VOTING_PERIOD      = 5;         // in blocks
  const VOTING_DELAY       = 1;         // in blocks
  const PROPOSAL_THRESHOLD = utils.parseEther('10'); // voting token threshold
  const QUORUM_FRACTION    = 4;         // 4% of supply

  before(async function () {
    // fixture signers
    [deployer, fan1, fan2, team, treasury] = await ethers.getSigners();

    // ---------------------------------------------------------------------------------------
    // Deploy dummy ShowLineup to prove proposal execution mutates state
    // ---------------------------------------------------------------------------------------
    const ShowLineupFactory = await ethers.getContractFactory('ShowLineupMock');
    showLineup = await ShowLineupFactory.deploy();
    await showLineup.deployed();

    // ---------------------------------------------------------------------------------------
    // Deploy CarnivalPass (upgradeable ERC-721)
    // ---------------------------------------------------------------------------------------
    CarnivalPass = await ethers.getContractFactory('CarnivalPass');
    carnivalPass = await CarnivalPass.deploy('StellarStage Carnival Pass', 'SSC');
    await carnivalPass.deployed();

    // ---------------------------------------------------------------------------------------
    // Deploy PassStaking (ERC-721 to ERC-20 voting wrapper)
    // ---------------------------------------------------------------------------------------
    PassStaking = await ethers.getContractFactory('PassStaking');
    passStaking = await PassStaking.deploy(
      carnivalPass.address,
      'StellarStage Voting Power',
      'vPOWER'
    );
    await passStaking.deployed();

    // ---------------------------------------------------------------------------------------
    // Deploy TimeLock
    // ---------------------------------------------------------------------------------------
    TimeLock = await ethers.getContractFactory('TimelockController');
    timeLock = await TimeLock.deploy(GOVERNANCE_DELAY, [deployer.address], [deployer.address]);
    await timeLock.deployed();

    // ---------------------------------------------------------------------------------------
    // Deploy CarnivalGovernor
    // ---------------------------------------------------------------------------------------
    CarnivalGovernor = await ethers.getContractFactory('CarnivalGovernor');
    carnivalGovernor = await CarnivalGovernor.deploy(
      passStaking.address,
      timeLock.address,
      QUORUM_FRACTION,
      VOTING_PERIOD,
      VOTING_DELAY,
      PROPOSAL_THRESHOLD
    );
    await carnivalGovernor.deployed();

    // Transfer governance roles
    await timeLock.grantRole(await timeLock.PROPOSER_ROLE(), carnivalGovernor.address);
    await timeLock.grantRole(await timeLock.EXECUTOR_ROLE(), ZERO_ADDRESS); // everyone
    await timeLock.revokeRole(await timeLock.TIMELOCK_ADMIN_ROLE(), deployer.address);
  });

  describe('Minting & staking passes', function () {
    const PASS_ID_1 = 1;
    const PASS_ID_2 = 2;

    it('fans can mint passes and stake them for voting power', async function () {
      // Mint two passes
      await carnivalPass.connect(fan1).mint(fan1.address, PASS_ID_1);
      await carnivalPass.connect(fan2).mint(fan2.address, PASS_ID_2);

      // Approve staking contract
      await carnivalPass.connect(fan1).approve(passStaking.address, PASS_ID_1);
      await carnivalPass.connect(fan2).approve(passStaking.address, PASS_ID_2);

      // Stake NFT (mints ERC-20 voting tokens at 10 vPOWER per pass)
      await expect(passStaking.connect(fan1).stake(PASS_ID_1))
        .to.emit(passStaking, 'Staked')
        .withArgs(fan1.address, PASS_ID_1);

      await expect(passStaking.connect(fan2).stake(PASS_ID_2))
        .to.emit(passStaking, 'Staked')
        .withArgs(fan2.address, PASS_ID_2);

      // Voting weight
      const balance1 = await passStaking.balanceOf(fan1.address);
      const balance2 = await passStaking.balanceOf(fan2.address);
      expect(balance1).to.equal(utils.parseEther('10'));
      expect(balance2).to.equal(utils.parseEther('10'));
    });

    it('staked passes confer delegation power', async function () {
      // Self-delegate by default
      const votes1 = await passStaking.getVotes(fan1.address);
      expect(votes1).to.equal(utils.parseEther('10'));

      // fan2 delegates to fan1
      await passStaking.connect(fan2).delegate(fan1.address);

      const votes1After = await passStaking.getVotes(fan1.address);
      expect(votes1After).to.equal(utils.parseEther('20'));
    });
  });

  describe('Proposal lifecycle', function () {
    let proposalId;
    const NEW_HEADLINER = '0x536B6F756C20496E204E65766572'; /* hex "Soul In Never" */

    it('fan1 can create a proposal with enough threshold', async function () {
      const encodedCall = showLineup.interface.encodeFunctionData(
        'addHeadliner',
        [NEW_HEADLINER]
      );

      const proposeTx = await carnivalGovernor.connect(fan1).propose(
        [showLineup.address],
        [0],
        ['addHeadliner(bytes32)'],
        [encodedCall],
        'Add Soul In Never to lineup'
      );

      const receipt = await proposeTx.wait();
      proposalId = receipt.events.find(e => e.event === 'ProposalCreated').args.proposalId;

      expect(await carnivalGovernor.state(proposalId)).to.equal(0); // Pending
    });

    it('voting activates after delay and counts votes correctly', async function () {
      await mineBlocks(VOTING_DELAY);

      // cast votes
      await carnivalGovernor.connect(fan1).castVote(proposalId, 1); // 1 = FOR
      await carnivalGovernor.connect(fan2).castVote(proposalId, 0); // AGAINST

      // Cannot vote twice
      await expect(
        carnivalGovernor.connect(fan2).castVote(proposalId, 0)
      ).to.be.revertedWith('GovernorVotingSimple: vote already cast');

      await mineBlocks(VOTING_PERIOD);

      expect(await carnivalGovernor.state(proposalId)).to.equal(4); // Succeeded (enum 4)
    });

    it('proposal queues in timelock then executes', async function () {
      const descriptionHash = utils.id('Add Soul In Never to lineup');

      await carnivalGovernor.queue(
        [showLineup.address],
        [0],
        ['addHeadliner(bytes32)'],
        [showLineup.interface.encodeFunctionData('addHeadliner', [NEW_HEADLINER])],
        descriptionHash
      );

      expect(await carnivalGovernor.state(proposalId)).to.equal(5); // Queued

      await fastForward(GOVERNANCE_DELAY + 1);

      // Execute!
      await carnivalGovernor.execute(
        [showLineup.address],
        [0],
        ['addHeadliner(bytes32)'],
        [showLineup.interface.encodeFunctionData('addHeadliner', [NEW_HEADLINER])],
        descriptionHash
      );

      expect(await showLineup.headliners(0)).to.equal(NEW_HEADLINER);
      expect(await carnivalGovernor.state(proposalId)).to.equal(7); // Executed
    });
  });

  describe('Edge cases', function () {
    it('fails if quorum not reached', async function () {
      // fan1 & fan2 unstake to drop supply
      await passStaking.connect(fan1).unstake(1);
      await passStaking.connect(fan2).unstake(2);

      // Mint and stake only one tiny pass
      await carnivalPass.connect(fan1).mint(fan1.address, 3);
      await carnivalPass.connect(fan1).approve(passStaking.address, 3);
      await passStaking.connect(fan1).stake(3);

      // New proposal
      const encodedCall = showLineup.interface.encodeFunctionData(
        'addHeadliner',
        [utils.formatBytes32String('ZeroQuorum')]
      );

      const tx = await carnivalGovernor.connect(fan1).propose(
        [showLineup.address],
        [0],
        ['addHeadliner(bytes32)'],
        [encodedCall],
        'Proposal that will fail quorum'
      );

      const receipt = await tx.wait();
      const propId = receipt.events.find(e => e.event === 'ProposalCreated').args.proposalId;

      await mineBlocks(VOTING_DELAY);
      await carnivalGovernor.connect(fan1).castVote(propId, 1); // for
      await mineBlocks(VOTING_PERIOD);

      expect(await carnivalGovernor.state(propId)).to.equal(3); // Defeated
    });

    it('prevents staking after snapshot block for current proposals', async function () {
      // Create proposal
      const encodedCall = showLineup.interface.encodeFunctionData(
        'addHeadliner',
        [utils.formatBytes32String('LateStake')]
      );

      const tx = await carnivalGovernor.connect(fan1).propose(
        [showLineup.address],
        [0],
        ['addHeadliner(bytes32)'],
        [encodedCall],
        'Late stake test'
      );

      const { proposalId } = await tx.wait().then(r =>
        r.events.find(e => e.event === 'ProposalCreated').args
      );

      const snapshotBlock = await carnivalGovernor.proposalSnapshot(proposalId);

      // Mine block to attempt stake after snapshot
      await mineBlocks(2);

      // Mint new pass and stake
      await carnivalPass.connect(fan2).mint(fan2.address, 4);
      await carnivalPass.connect(fan2).approve(passStaking.address, 4);

      await passStaking.connect(fan2).stake(4);

      // fan2 tries to vote, should revert because has no voting power at snapshot
      await expect(
        carnivalGovernor.connect(fan2).castVote(proposalId, 1)
      ).to.be.revertedWith('GovernorVotingSimple: voting power is 0');

      // clean up
      await mineBlocks(VOTING_PERIOD + 1);
    });
  });

  describe('EIP-712 delegated voting by signature', function () {
    it('allows off-chain delegations via signature', async function () {
      const chainId = (await ethers.provider.getNetwork()).chainId;
      const nonce = await passStaking.nonces(fan1.address);
      const expiry = Math.floor(Date.now() / 1000) + DAY;

      const domain = {
        name: await passStaking.name(),
        version: '1',
        chainId,
        verifyingContract: passStaking.address
      };

      const types = {
        Delegation: [
          { name: 'delegatee', type: 'address' },
          { name: 'nonce',     type: 'uint256' },
          { name: 'expiry',    type: 'uint256' }
        ]
      };

      const value = {
        delegatee: fan2.address,
        nonce,
        expiry
      };

      // sign typed data
      const signature = await fan1._signTypedData(domain, types, value);
      const { r, s, v } = ethers.utils.splitSignature(signature);

      // delegate by sig
      await passStaking.connect(fan2).delegateBySig(
        fan2.address,
        nonce,
        expiry,
        v, r, s
      );

      expect(await passStaking.delegates(fan1.address)).to.equal(fan2.address);
    });
  });
});
```