```csharp
// -------------------------------------------------------------------------------------------------
//  TycoonVerse – Enterprise Empire Simulator
//  Copyright © 2023 Neuroverse.
// -------------------------------------------------------------------------------------------------
//  File:        20231027_InitialCreate.cs
//  Description: Initial, idempotent schema for the local-first SQLite data-store. The schema is
//               intentionally “business-centric”; every write ultimately ladders up to the in-game
//               financial model that drives the simulation loop.
//               NOTE: The runtime platform is SQLite on-device. Keep platform specific limitations
//               (e.g., lack of filtered indexes) in mind when authoring migrations.
// -------------------------------------------------------------------------------------------------

#nullable enable

using System;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Migrations;

namespace TycoonVerse.Infrastructure.Persistence.Migrations
{
    /// <summary>
    /// Initial migration—creates the foundational tables and constraints that power the core
    /// business simulation loop (players, companies, inventory, transactions, GL).
    /// </summary>
    [DbContext(typeof(TycoonVerseDbContext))]
    [Migration("20231027_InitialCreate")]
    public sealed class _20231027_InitialCreate : Migration
    {
        /***************************************************************************************************
         * Public API
         **************************************************************************************************/

        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // Players -----------------------------------------------------------------
            migrationBuilder.CreateTable(
                name: "Players",
                columns: table => new
                {
                    Id                = table.Column<Guid>(nullable: false),
                    ExternalIdentity   = table.Column<string>(maxLength: 100, nullable: false),
                    UserName           = table.Column<string>(maxLength: 30, nullable: false),
                    RegionCode         = table.Column<string>(maxLength: 2,  nullable: false),
                    BiometricEnabled   = table.Column<bool>  (nullable: false, defaultValue: false),
                    CreatedAtUtc       = table.Column<DateTime>(nullable: false),
                    UpdatedAtUtc       = table.Column<DateTime>(nullable: true)
                },
                constraints: table => table.PrimaryKey("PK_Players", x => x.Id));

            migrationBuilder.CreateIndex(
                name: "IX_Players_ExternalIdentity",
                table: "Players",
                column: "ExternalIdentity",
                unique: true);

            // Industries --------------------------------------------------------------
            migrationBuilder.CreateTable(
                name: "Industries",
                columns: table => new
                {
                    Id   = table.Column<Guid>(nullable: false),
                    Code = table.Column<string>(maxLength: 10,  nullable: false),
                    Name = table.Column<string>(maxLength: 100, nullable: false)
                },
                constraints: table => table.PrimaryKey("PK_Industries", x => x.Id));

            migrationBuilder.CreateIndex(
                name: "IX_Industries_Code",
                table: "Industries",
                column: "Code",
                unique: true);

            // Companies ---------------------------------------------------------------
            migrationBuilder.CreateTable(
                name: "Companies",
                columns: table => new
                {
                    Id               = table.Column<Guid>(nullable: false),
                    PlayerId         = table.Column<Guid>(nullable: false),
                    IndustryId       = table.Column<Guid>(nullable: false),
                    Ticker           = table.Column<string>(maxLength: 5, nullable: false),
                    Name             = table.Column<string>(maxLength: 50, nullable: false),
                    CashOnHand       = table.Column<decimal>(type: "decimal(18,2)", nullable: false, defaultValue: 0m),
                    Debt             = table.Column<decimal>(type: "decimal(18,2)", nullable: false, defaultValue: 0m),
                    CurrentValuation = table.Column<decimal>(type: "decimal(18,2)", nullable: false, defaultValue: 0m),
                    CreatedAtUtc     = table.Column<DateTime>(nullable: false),
                    UpdatedAtUtc     = table.Column<DateTime>(nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Companies", x => x.Id);
                    table.ForeignKey(
                        name: "FK_Companies_Players_PlayerId",
                        column: x => x.PlayerId,
                        principalTable: "Players",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_Companies_Industries_IndustryId",
                        column: x => x.IndustryId,
                        principalTable: "Industries",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_Companies_PlayerId",
                table: "Companies",
                column: "PlayerId");

            migrationBuilder.CreateIndex(
                name: "IX_Companies_IndustryId",
                table: "Companies",
                column: "IndustryId");

            migrationBuilder.CreateIndex(
                name: "IX_Companies_Ticker",
                table: "Companies",
                column: "Ticker",
                unique: true);

            // InventoryItems ----------------------------------------------------------
            migrationBuilder.CreateTable(
                name: "InventoryItems",
                columns: table => new
                {
                    Id           = table.Column<Guid>(nullable: false),
                    CompanyId    = table.Column<Guid>(nullable: false),
                    SKU          = table.Column<string>(maxLength: 30,  nullable: false),
                    Name         = table.Column<string>(maxLength: 100, nullable: false),
                    Quantity     = table.Column<int>(nullable: false),
                    Cost         = table.Column<decimal>(type: "decimal(18,4)", nullable: false),
                    CreatedAtUtc = table.Column<DateTime>(nullable: false),
                    UpdatedAtUtc = table.Column<DateTime>(nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_InventoryItems", x => x.Id);
                    table.ForeignKey(
                        name: "FK_InventoryItems_Companies_CompanyId",
                        column: x => x.CompanyId,
                        principalTable: "Companies",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_InventoryItems_CompanyId",
                table: "InventoryItems",
                column: "CompanyId");

            migrationBuilder.CreateIndex(
                name: "IX_InventoryItems_SKU",
                table: "InventoryItems",
                column: "SKU",
                unique: true);

            // Transactions ------------------------------------------------------------
            migrationBuilder.CreateTable(
                name: "Transactions",
                columns: table => new
                {
                    Id              = table.Column<Guid>(nullable: false),
                    CompanyId       = table.Column<Guid>(nullable: false),
                    InventoryItemId = table.Column<Guid>(nullable: true),
                    Type            = table.Column<int>(nullable: false), // enum–backed
                    Quantity        = table.Column<int>(nullable: false),
                    UnitPrice       = table.Column<decimal>(type: "decimal(18,4)", nullable: false),
                    Total           = table.Column<decimal>(type: "decimal(18,4)", nullable: false),
                    OccurredAtUtc   = table.Column<DateTime>(nullable: false),
                    CreatedAtUtc    = table.Column<DateTime>(nullable: false),
                    UpdatedAtUtc    = table.Column<DateTime>(nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Transactions", x => x.Id);
                    table.ForeignKey(
                        name: "FK_Transactions_Companies_CompanyId",
                        column: x => x.CompanyId,
                        principalTable: "Companies",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_Transactions_InventoryItems_InventoryItemId",
                        column: x => x.InventoryItemId,
                        principalTable: "InventoryItems",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "IX_Transactions_CompanyId",
                table: "Transactions",
                column: "CompanyId");

            migrationBuilder.CreateIndex(
                name: "IX_Transactions_InventoryItemId",
                table: "Transactions",
                column: "InventoryItemId");

            migrationBuilder.CreateIndex(
                name: "IX_Transactions_OccurredAtUtc",
                table: "Transactions",
                column: "OccurredAtUtc");

            // LedgerEntries -----------------------------------------------------------
            migrationBuilder.CreateTable(
                name: "LedgerEntries",
                columns: table => new
                {
                    Id            = table.Column<Guid>(nullable: false),
                    CompanyId     = table.Column<Guid>(nullable: false),
                    TransactionId = table.Column<Guid>(nullable: true),
                    Description   = table.Column<string>(maxLength: 250, nullable: false),
                    Debit         = table.Column<decimal>(type: "decimal(18,4)", nullable: false, defaultValue: 0m),
                    Credit        = table.Column<decimal>(type: "decimal(18,4)", nullable: false, defaultValue: 0m),
                    RecordedAtUtc = table.Column<DateTime>(nullable: false),
                    CreatedAtUtc  = table.Column<DateTime>(nullable: false),
                    UpdatedAtUtc  = table.Column<DateTime>(nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_LedgerEntries", x => x.Id);
                    table.ForeignKey(
                        name: "FK_LedgerEntries_Companies_CompanyId",
                        column: x => x.CompanyId,
                        principalTable: "Companies",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_LedgerEntries_Transactions_TransactionId",
                        column: x => x.TransactionId,
                        principalTable: "Transactions",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "IX_LedgerEntries_CompanyId",
                table: "LedgerEntries",
                column: "CompanyId");

            migrationBuilder.CreateIndex(
                name: "IX_LedgerEntries_TransactionId",
                table: "LedgerEntries",
                column: "TransactionId");

            migrationBuilder.CreateIndex(
                name: "IX_LedgerEntries_RecordedAtUtc",
                table: "LedgerEntries",
                column: "RecordedAtUtc");

            // PlayerFriends (Self-referencing many-to-many) ---------------------------
            migrationBuilder.CreateTable(
                name: "PlayerFriends",
                columns: table => new
                {
                    PlayerId   = table.Column<Guid>(nullable: false),
                    FriendId   = table.Column<Guid>(nullable: false),
                    AddedAtUtc = table.Column<DateTime>(nullable: false, defaultValueSql: "CURRENT_TIMESTAMP")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_PlayerFriends", x => new { x.PlayerId, x.FriendId });
                    table.ForeignKey(
                        name: "FK_PlayerFriends_Players_PlayerId",
                        column: x => x.PlayerId,
                        principalTable: "Players",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_PlayerFriends_Players_FriendId",
                        column: x => x.FriendId,
                        principalTable: "Players",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_PlayerFriends_FriendId",
                table: "PlayerFriends",
                column: "FriendId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            // Drop in reverse order to honor FK dependencies.
            migrationBuilder.DropTable(name: "LedgerEntries");
            migrationBuilder.DropTable(name: "PlayerFriends");
            migrationBuilder.DropTable(name: "Transactions");
            migrationBuilder.DropTable(name: "InventoryItems");
            migrationBuilder.DropTable(name: "Companies");
            migrationBuilder.DropTable(name: "Industries");
            migrationBuilder.DropTable(name: "Players");
        }
    }
}
```