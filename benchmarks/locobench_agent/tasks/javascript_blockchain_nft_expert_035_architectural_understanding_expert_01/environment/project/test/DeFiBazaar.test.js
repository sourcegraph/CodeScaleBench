```javascript
/*  StellarStageCarnival/test/DeFiBazaar.test.js
 *
 *  Integration tests for the DeFiBazaar smart-contract adapter.
 *  Uses Hardhat’s in-memory EVM + Mocha/Chai for BDD assertions.
 *
 *  Scenarios covered
 *  -----------------
 *  1. NFT listing             – Owner lists a ShowPass w/ asking price
 *  2. NFT purchase            – Buyer pays ERC-20, receives the NFT
 *  3. Royalty distribution    – Creator receives creatorCut on sale
 *  4. Staking & reward accrual– Holder stakes NFT, accrues gov tokens
 *  5. Security regressions    – Only owner may list / unstake, etc.
 */

const { ethers, network } = require("hardhat");
const { expect } = require("chai");

// Helper constants
const ZERO_ADDRESS = ethers.constants.AddressZero;
const CREATOR_CUT_BPS = 750; // 7.5 %

describe("DeFiBazaar", function () {
  let carnivalCredit;  // ERC-20 utility token
  let showPass;        // ERC-721 upgradable NFT
  let bazaar;          // DeFiBazaar contract

  let deployer, creator, seller, buyer, random;
  const initialMint = ethers.utils.parseUnits("10000");

  beforeEach(async function () {
    /* ----------- Bootstrapping signer accounts ------------- */
    [
      deployer,
      creator,
      seller,
      buyer,
      random,
    ] = await ethers.getSigners();

    /* ----------- Deploy mock utility token ----------------- */
    const CarnivalCredit = await ethers.getContractFactory("CarnivalCreditMock");
    carnivalCredit = await CarnivalCredit
      .connect(deployer)
      .deploy("Carnival Credit", "CCRD");
    await carnivalCredit.deployed();

    /* ----------- Mint test balances ------------------------ */
    await carnivalCredit.connect(deployer).mint(buyer.address, initialMint);
    await carnivalCredit.connect(deployer).mint(random.address, initialMint);

    /* ----------- Deploy mock ShowPass NFT ------------------ */
    const ShowPass = await ethers.getContractFactory("ShowPassMock");
    showPass = await ShowPass
      .connect(deployer)
      .deploy("StellarStage ShowPass", "STSP");
    await showPass.deployed();

    /* ----------- Mint & transfer a Pass to seller ---------- */
    await showPass.connect(deployer).mint(seller.address, 1);

    /* ----------- Deploy Bazaar under test ------------------ */
    const DeFiBazaar = await ethers.getContractFactory("DeFiBazaar");
    bazaar = await DeFiBazaar
      .connect(deployer)
      .deploy(
        carnivalCredit.address,
        showPass.address,
        creator.address,
        CREATOR_CUT_BPS
      );
    await bazaar.deployed();
  });

  /***********************************************************
   *  LISTING
   ***********************************************************/
  describe("Listing", function () {
    it("should allow NFT owner to list a ShowPass", async function () {
      const price = ethers.utils.parseUnits("250");

      await showPass.connect(seller).approve(bazaar.address, 1);
      await expect(
        bazaar.connect(seller).listItem(1, price)
      )
        .to.emit(bazaar, "ItemListed")
        .withArgs(seller.address, 1, price);

      // Verify marketplace holds the token
      expect(await showPass.ownerOf(1)).to.equal(bazaar.address);
      const listing = await bazaar.marketItems(1);
      expect(listing.seller).to.equal(seller.address);
      expect(listing.price).to.equal(price);
      expect(listing.active).to.equal(true);
    });

    it("reverts if non-owner attempts to list", async function () {
      const price = ethers.utils.parseUnits("250");
      await showPass.connect(seller).approve(bazaar.address, 1);

      await expect(
        bazaar.connect(random).listItem(1, price)
      ).to.be.revertedWith("Bazaar: caller is not token owner");
    });
  });

  /***********************************************************
   *  PURCHASE
   ***********************************************************/
  describe("Purchase flow", function () {
    const price = ethers.utils.parseUnits("1000");

    beforeEach(async function () {
      await showPass.connect(seller).approve(bazaar.address, 1);
      await bazaar.connect(seller).listItem(1, price);
    });

    it("transfers the NFT & distributes funds/royalties", async function () {
      // Pre-state snapshots
      const royalty = price.mul(CREATOR_CUT_BPS).div(10_000);
      const sellerExpected = price.sub(royalty);

      await carnivalCredit.connect(buyer).approve(bazaar.address, price);

      await expect(
        bazaar.connect(buyer).purchaseItem(1)
      )
        .to.emit(bazaar, "ItemSold")
        .withArgs(buyer.address, 1, price);

      /* ---- post-conditions ---- */
      expect(await showPass.ownerOf(1)).to.equal(buyer.address);

      // Balance checks
      const sellerBal = await carnivalCredit.balanceOf(seller.address);
      const creatorBal = await carnivalCredit.balanceOf(creator.address);

      expect(sellerBal).to.equal(sellerExpected);
      expect(creatorBal).to.equal(royalty);

      // Item should be inactive
      const listing = await bazaar.marketItems(1);
      expect(listing.active).to.equal(false);
    });

    it("cannot be bought twice", async function () {
      await carnivalCredit.connect(buyer).approve(bazaar.address, price);
      await bazaar.connect(buyer).purchaseItem(1);

      await carnivalCredit.connect(random).approve(bazaar.address, price);
      await expect(
        bazaar.connect(random).purchaseItem(1)
      ).to.be.revertedWith("Bazaar: item inactive");
    });

    it("reverts when price not met", async function () {
      const short = price.sub(1);
      await carnivalCredit.connect(buyer).approve(bazaar.address, short);
      await expect(
        bazaar.connect(buyer).purchaseItem(1)
      ).to.be.revertedWith("ERC20: transfer amount exceeds allowance");
    });
  });

  /***********************************************************
   *  STAKING & YIELD
   ***********************************************************/
  describe("Staking & Governance yield", function () {
    const stakeTokenId = 1;
    const rewardRate = ethers.utils.parseUnits("5"); // 5 CCRD / block

    beforeEach(async function () {
      // Give deployer mint authority to seed rewards
      await carnivalCredit.connect(deployer).mint(bazaar.address, initialMint);
      // Tell Bazaar about the reward rate
      await bazaar.connect(deployer).configureStaking(rewardRate);

      // Seller -> Buyer transfer (buyer holds stake NFT)
      await showPass.connect(seller).approve(bazaar.address, stakeTokenId);
      await bazaar.connect(seller).listItem(stakeTokenId, 0);
      await bazaar.connect(buyer).purchaseItem(stakeTokenId); // price 0
    });

    it("allows holder to stake and accrue rewards over time", async function () {
      await showPass.connect(buyer).approve(bazaar.address, stakeTokenId);

      await expect(
        bazaar.connect(buyer).stakePass(stakeTokenId)
      )
        .to.emit(bazaar, "PassStaked")
        .withArgs(buyer.address, stakeTokenId);

      // Fast-forward 200 blocks
      for (let i = 0; i < 200; i++) {
        await network.provider.send("evm_mine");
      }

      const pending = await bazaar.pendingRewards(buyer.address);
      expect(pending).to.equal(rewardRate.mul(200));

      await expect(
        bazaar.connect(buyer).claimRewards()
      )
        .to.emit(bazaar, "RewardsClaimed")
        .withArgs(buyer.address, pending);

      const userBal = await carnivalCredit.balanceOf(buyer.address);
      expect(userBal).to.equal(pending); // buyer started at 0 CCRD
    });

    it("reverts unstake when caller isn't staker", async function () {
      await showPass.connect(buyer).approve(bazaar.address, stakeTokenId);
      await bazaar.connect(buyer).stakePass(stakeTokenId);

      await expect(
        bazaar.connect(random).unstakePass(stakeTokenId)
      ).to.be.revertedWith("Bazaar: caller not staker");
    });
  });

  /***********************************************************
   *  UPGRADEABLE ADMIN GUARD RAILS
   ***********************************************************/
  describe("Admin controls", function () {
    it("prevents non-owner from updating creator cut", async function () {
      await expect(
        bazaar.connect(random).setCreatorCut(500)
      ).to.be.revertedWith("Ownable: caller is not the owner");
    });

    it("owner may update creator cut within limits", async function () {
      const newCut = 500; // 5 %
      await bazaar.connect(deployer).setCreatorCut(newCut);
      expect(await bazaar.creatorCutBps()).to.equal(newCut);
    });

    it("rejects absurd royalty percentages", async function () {
      await expect(
        bazaar.connect(deployer).setCreatorCut(10_001)
      ).to.be.revertedWith("Bazaar: invalid basis points");
    });
  });
});
```