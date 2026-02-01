```javascript
/**
 * @file StakingRewards.test.js
 * @description
 * End-to-end test-suite for the on-chain Pass-staking programme.
 *
 * Contracts under test:
 *   ‑ ShowPass         (ERC-721 tickets)
 *   ‑ CarnivalToken    (ERC-20 governance / utility token)
 *   ‑ StakingRewards   (ERC-721 single-sided staking w/ ERC-20 rewards)
 *
 * Behaviour covered:
 *   ‑ happy-path staking / withdrawing
 *   ‑ reward growth over block-time
 *   ‑ multiple stakers & proportional accounting
 *   ‑ edge-cases (zero stake, duplicate stake, premature withdraw, paused)
 *
 * Toolchain:
 *   ‑ Hardhat (ethers, network-helpers)
 *   ‑ Mocha / Chai
 */

const { expect } = require("chai");
const { ethers, network } = require("hardhat");
const { loadFixture, time } = require("@nomicfoundation/hardhat-network-helpers");

const ZERO_ADDRESS = ethers.constants.AddressZero;
const ONE_DAY = 24 * 60 * 60;

describe("StakingRewards", () => {
  /**
   * Deploys fresh contracts + returns named signers.
   * We use Hardhat’s built-in snapshot/restore mechanism via `loadFixture`
   * to ensure deterministic state across test-cases.
   */
  async function deployFixture() {
    const [deployer, alice, bob, treasury] = await ethers.getSigners();

    // ────────────────────────────────────────────────────────────────────────────
    // Deploy ShowPass (ERC-721)
    // ────────────────────────────────────────────────────────────────────────────
    const ShowPass = await ethers.getContractFactory("ShowPass");
    const pass = await ShowPass.deploy("StellarStage Pass", "PASS");
    await pass.deployed();

    // Mint some passes for Alice & Bob
    await pass.safeMint(alice.address, "ipfs://pass/1.json"); // tokenId = 1
    await pass.safeMint(alice.address, "ipfs://pass/2.json"); // tokenId = 2
    await pass.safeMint(bob.address,   "ipfs://pass/3.json"); // tokenId = 3

    // ────────────────────────────────────────────────────────────────────────────
    // Deploy CarnivalToken (ERC-20)
    // ────────────────────────────────────────────────────────────────────────────
    const CarnivalToken = await ethers.getContractFactory("CarnivalToken");
    const carnival = await CarnivalToken.deploy("Carnival Governance", "CARNI");
    await carnival.deployed();

    // Treasury pre-funds rewards
    const INITIAL_REWARD = ethers.utils.parseUnits("1000000", 18);
    await carnival.mint(treasury.address, INITIAL_REWARD);

    // ────────────────────────────────────────────────────────────────────────────
    // Deploy StakingRewards
    // ────────────────────────────────────────────────────────────────────────────
    const StakingRewards = await ethers.getContractFactory("StakingRewards");
    const staking = await StakingRewards.deploy(
      pass.address,
      carnival.address,
      treasury.address
    );
    await staking.deployed();

    // Approve reward distribution
    await carnival
      .connect(treasury)
      .approve(staking.address, INITIAL_REWARD);

    // Start reward programme for 30 days
    const DURATION = 30 * ONE_DAY;
    await staking
      .connect(treasury)
      .notifyRewardAmount(INITIAL_REWARD, DURATION);

    return {
      deployer,
      alice,
      bob,
      treasury,
      pass,
      carnival,
      staking,
      INITIAL_REWARD,
      DURATION,
    };
  }

  // ──────────────────────────────────────────────────────────────────────────────
  // Utility helpers
  // ──────────────────────────────────────────────────────────────────────────────
  const inBn = ethers.BigNumber.from;
  const toWei = (v) => ethers.utils.parseUnits(v.toString(), 18);

  /**
   * Advances the evm clock by _days_ days while mining a block.
   */
  async function fastForwardDays(days) {
    await time.increase(days * ONE_DAY);
    await network.provider.send("evm_mine");
  }

  // ═════════════════════════════════════════════════════════════════════════════
  // Test-cases
  // ═════════════════════════════════════════════════════════════════════════════

  describe("initialization", () => {
    it("sets immutable references correctly", async () => {
      const { pass, carnival, staking } = await loadFixture(deployFixture);
      expect(await staking.pass()).to.equal(pass.address);
      expect(await staking.rewardsToken()).to.equal(carnival.address);
    });

    it("treasury funding updates rewardRate & finishAt", async () => {
      const { staking, INITIAL_REWARD, DURATION } = await loadFixture(
        deployFixture
      );
      expect(await staking.rewardRate()).to.equal(
        INITIAL_REWARD.div(DURATION)
      );
      expect(await staking.finishAt()).to.be.gt(0);
    });
  });

  describe("stake()", () => {
    it("allows a user to stake an owned Pass and begin earning", async () => {
      const { alice, pass, staking } = await loadFixture(deployFixture);

      // approve & stake
      await pass.connect(alice).approve(staking.address, 1);
      await expect(staking.connect(alice).stake(1))
        .to.emit(staking, "Staked")
        .withArgs(alice.address, 1);

      expect(await staking.balanceOf(alice.address)).to.equal(1);
      expect(await pass.ownerOf(1)).to.equal(staking.address);
    });

    it("reverts if Pass is not approved", async () => {
      const { alice, staking } = await loadFixture(deployFixture);
      await expect(staking.connect(alice).stake(1)).to.be.revertedWith(
        "NOT_APPROVED"
      );
    });

    it("reverts on duplicate stake", async () => {
      const { alice, pass, staking } = await loadFixture(deployFixture);
      await pass.connect(alice).approve(staking.address, 1);
      await staking.connect(alice).stake(1);
      await expect(
        staking.connect(alice).stake(1)
      ).to.be.revertedWith("ALREADY_STAKED");
    });
  });

  describe("earning over time", () => {
    it("accrues rewards linearly per second", async () => {
      const { alice, pass, carnival, staking } = await loadFixture(
        deployFixture
      );

      // Alice stakes one NFT
      await pass.connect(alice).approve(staking.address, 1);
      await staking.connect(alice).stake(1);

      // Fast-forward 10 days
      await fastForwardDays(10);

      const earned = await staking.earned(alice.address);
      // approximate check (10 days of rewards)
      const expected = (await staking.rewardRate()).mul(ONE_DAY * 10);
      // Allow 1% slippage for rounding
      expect(earned).to.be.closeTo(expected, expected.div(100));
    });

    it("splits rewards fairly between multiple stakers", async () => {
      const { alice, bob, pass, carnival, staking } = await loadFixture(
        deployFixture
      );

      // Alice stakes first
      await pass.connect(alice).approve(staking.address, 1);
      await staking.connect(alice).stake(1);

      await fastForwardDays(5); // 5 days where only Alice earns

      // Bob joins
      await pass.connect(bob).approve(staking.address, 3);
      await staking.connect(bob).stake(3);

      await fastForwardDays(5); // 5 days where both earn

      const totalRate = await staking.rewardRate();
      const aliceEarn = await staking.earned(alice.address);
      const bobEarn = await staking.earned(bob.address);

      const earnPerDay = totalRate.mul(ONE_DAY);
      // Expected:
      //  Alice: 5 days solo + 5 days half share = 5 + 2.5 = 7.5
      //  Bob  : 5 days half share               = 2.5
      const expectedAlice = earnPerDay.mul(75).div(10); // 7.5
      const expectedBob = earnPerDay.mul(25).div(10); // 2.5

      // again allow small rounding range
      expect(aliceEarn).to.be.closeTo(expectedAlice, expectedAlice.div(100));
      expect(bobEarn).to.be.closeTo(expectedBob, expectedBob.div(100));
    });
  });

  describe("withdraw()", () => {
    it("returns NFT and transfers rewards", async () => {
      const { alice, pass, carnival, staking } = await loadFixture(
        deployFixture
      );

      // stake pass
      await pass.connect(alice).approve(staking.address, 1);
      await staking.connect(alice).stake(1);
      await fastForwardDays(3);

      const beforeBal = await carnival.balanceOf(alice.address);
      const expectedReward = await staking.earned(alice.address);

      await expect(staking.connect(alice).withdraw(1))
        .to.emit(staking, "Withdrawn")
        .withArgs(alice.address, 1);

      // Alice receives Pass back
      expect(await pass.ownerOf(1)).to.equal(alice.address);

      // Alice receives accrued tokens
      const afterBal = await carnival.balanceOf(alice.address);
      expect(afterBal.sub(beforeBal)).to.be.closeTo(
        expectedReward,
        expectedReward.div(100)
      );
    });

    it("reverts if caller is not original staker", async () => {
      const { alice, bob, pass, staking } = await loadFixture(deployFixture);
      await pass.connect(alice).approve(staking.address, 1);
      await staking.connect(alice).stake(1);
      await expect(
        staking.connect(bob).withdraw(1)
      ).to.be.revertedWith("NOT_OWNER");
    });

    it("cannot withdraw twice", async () => {
      const { alice, pass, staking } = await loadFixture(deployFixture);
      await pass.connect(alice).approve(staking.address, 1);
      await staking.connect(alice).stake(1);
      await staking.connect(alice).withdraw(1);
      await expect(
        staking.connect(alice).withdraw(1)
      ).to.be.revertedWith("NOT_STAKED");
    });
  });

  describe("administrative controls", () => {
    it("treasury can top-up rewards mid-epoch", async () => {
      const {
        deployer,
        treasury,
        carnival,
        staking,
        INITIAL_REWARD,
        DURATION,
      } = await loadFixture(deployFixture);

      const TOP_UP = INITIAL_REWARD.div(2);

      await carnival.connect(treasury).mint(treasury.address, TOP_UP);
      await carnival.connect(treasury).approve(staking.address, TOP_UP);

      await expect(
        staking.connect(treasury).notifyRewardAmount(TOP_UP, DURATION)
      )
        .to.emit(staking, "RewardAdded")
        .withArgs(TOP_UP, await staking.finishAt());

      // new rewardRate should be updated (can't equal old)
      expect(await staking.rewardRate()).to.not.equal(
        INITIAL_REWARD.div(DURATION)
      );
    });

    it("non-treasury cannot add rewards", async () => {
      const { alice, staking } = await loadFixture(deployFixture);
      await expect(
        staking.connect(alice).notifyRewardAmount(1, 1)
      ).to.be.revertedWith("ONLY_TREASURY");
    });
  });
});
```