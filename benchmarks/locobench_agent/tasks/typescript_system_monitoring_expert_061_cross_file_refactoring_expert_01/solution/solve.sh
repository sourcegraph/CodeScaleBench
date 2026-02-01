#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The expected outcome is a codebase where all alerting logic is handled by a single service.

**Key Changes:**

1.  **New Files Created:**
    - `src/services/notificationService.ts`: Contains the `NotificationService` class, `NotificationChannel` interface, `AlertMessage` type, and concrete channel implementations (`EmailChannel`, `WebhookChannel`, `LogChannel`). Exports a singleton `notificationService`.
    - `src/config/notifications.ts`: Exports a `notificationConfig` object containing settings like `emailRecipients`, `webhookUrl`, etc.

2.  **Modified `utils.ts`:**
    - The function `sendLegacyEmailAlert(to: string, subject: string, body: string): Promise<void>` and any related types have been completely removed.

3.  **Example Module Refactoring (e.g., in `src/module_63.ts`):**

    *   **Before:**
        ```typescript
        import { sendLegacyEmailAlert } from '../utils';
        // ...
        async function checkBackupIntegrity(backupId: string) {
          const isCorrupt = await someCheck(backupId);
          if (isCorrupt) {
            console.error(`CRITICAL-ALERT: Backup ${backupId} is corrupt!`);
            await sendLegacyEmailAlert('sysops@pulsesphere.com', 'Corrupt Backup Detected', `Backup with ID ${backupId} failed integrity check.`);
          }
        }
        ```

    *   **After:**
        ```typescript
        import { notificationService } from '../services/notificationService';
        // ...
        async function checkBackupIntegrity(backupId: string) {
          const isCorrupt = await someCheck(backupId);
          if (isCorrupt) {
            await notificationService.dispatch({
              severity: 'critical',
              title: 'Corrupt Backup Detected',
              sourceModule: 'module_63',
              details: {
                backupId: backupId,
                checkTime: new Date().toISOString(),
                reason: 'Failed integrity check.'
              }
            });
          }
        }
        ```

4.  **All other modules containing alert logic** (e.g., `module_30`, `module_50`, `module_70`) will exhibit similar refactoring patterns, replacing their unique alert calls with a standardized call to `notificationService.dispatch()`.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
