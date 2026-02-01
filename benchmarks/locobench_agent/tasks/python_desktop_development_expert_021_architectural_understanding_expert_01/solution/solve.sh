#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The solution is a set of changes across multiple files that correctly uses the established architectural patterns.

1.  **`configs/default_settings.json`**: Added `"focus_mode_enabled": false`.
2.  **`flockdesk/core/ipc/event_types.py`**: Added a new event type like `FOCUS_MODE_CHANGED = 'system/focus_mode_changed'`.
3.  **`flockdesk/core/shortcuts/commands.py`**: A new class `ToggleFocusModeCommand` is implemented. Its `execute` method gets the `SettingsService` and `EventBus` (likely via a service locator or singleton pattern), toggles the setting, and publishes the `FOCUS_MODE_CHANGED` event with the new boolean state.
4.  **`flockdesk/core/shell/menu_bar.py`**: A new `QAction` for 'Toggle Focus Mode' is created and connected to an instance of `ToggleFocusModeCommand`.
5.  **`flockdesk/modules/chat/viewmodel/chat_vm.py`**: The ViewModel's `__init__` subscribes to `FOCUS_MODE_CHANGED`. A handler method updates a new property (e.g., `self.is_snoozed`). The logic for suppressing notifications would also be tied to this property.
6.  **`flockdesk/modules/dashboard/viewmodel/dashboard_vm.py`**: The ViewModel's `__init__` subscribes to `FOCUS_MODE_CHANGED`. A handler method updates a new property (e.g., `self.activity_feed_opacity`).
7.  **`flockdesk/modules/dashboard/view/dashboard_widget.py`**: The widget's styling logic for the activity feed is connected to the new ViewModel property, dynamically changing its appearance.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
