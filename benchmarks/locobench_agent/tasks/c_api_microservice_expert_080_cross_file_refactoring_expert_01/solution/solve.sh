#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The ground truth is a description of the final state, not the full code of all 70+ modified files.

**1. New File: `src/logging.h`**
```c
#ifndef LOGGING_H
#define LOGGING_H

#include <stdio.h>
#include <stdarg.h>

// Public API for the logging module

typedef enum {
    LOG_LEVEL_DEBUG,
    LOG_LEVEL_INFO,
    LOG_LEVEL_WARN,
    LOG_LEVEL_ERROR
} LogLevel;

void log_init(LogLevel level, const char* log_file);
void log_message(LogLevel level, const char* file, int line, const char* fmt, ...);

#define LOG_DEBUG(fmt, ...) log_message(LOG_LEVEL_DEBUG, __FILE__, __LINE__, fmt, ##__VA_ARGS__)
#define LOG_INFO(fmt, ...) log_message(LOG_LEVEL_INFO, __FILE__, __LINE__, fmt, ##__VA_ARGS__)
#define LOG_WARN(fmt, ...) log_message(LOG_LEVEL_WARN, __FILE__, __LINE__, fmt, ##__VA_ARGS__)
#define LOG_ERROR(fmt, ...) log_message(LOG_LEVEL_ERROR, __FILE__, __LINE__, fmt, ##__VA_ARGS__)

#endif // LOGGING_H
```

**2. New File: `src/logging.c`**
```c
#include "logging.h"
#include <time.h>
#include <string.h>

static struct {
    LogLevel level;
    FILE* output;
} config = {LOG_LEVEL_INFO, NULL};

void log_init(LogLevel level, const char* log_file) {
    config.level = level;
    if (log_file) {
        config.output = fopen(log_file, "a");
        if (!config.output) {
            config.output = stderr; // Fallback to stderr
            fprintf(stderr, "ERROR: Could not open log file %s. Falling back to stderr.\n", log_file);
        }
    } else {
        config.output = stderr;
    }
}

void log_message(LogLevel level, const char* file, int line, const char* fmt, ...) {
    if (level < config.level) {
        return;
    }

    // Get current time
    time_t timer = time(NULL);
    struct tm* tm_info = localtime(&timer);
    char time_buf[26];
    strftime(time_buf, 26, "%Y-%m-%d %H:%M:%S", tm_info);

    const char* level_str[] = {"DEBUG", "INFO", "WARN", "ERROR"};

    // Print log prefix
    fprintf(config.output, "%s [%s] (%s:%d): ", time_buf, level_str[level], file, line);

    // Print user message
    va_list args;
    va_start(args, fmt);
    vfprintf(config.output, fmt, args);
    va_end(args);

    fprintf(config.output, "\n");
    fflush(config.output);
}
```

**3. Modification in `src/module_31.txt`:**
- The file `src/module_31.txt` should now contain `#include "logging.h"`.
- The function `mercury_hub_main` should have `log_init(LOG_LEVEL_INFO, NULL);` as one of its first statements.

**4. Example Refactoring in `src/module_42.txt`:**
- **Before:** `fprintf(stderr, "[ERROR] Failed to allocate memory for user session\n");`
- **After:** `LOG_ERROR("Failed to allocate memory for user session");`

**5. Example Refactoring in `src/module_7.txt`:**
- **Before:** `printf("INFO: Processing batch of %d records.\n", record_count);`
- **After:** `LOG_INFO("Processing batch of %d records.", record_count);`

**6. Summary of Changes:**
- The files `src/logging.c` and `src/logging.h` are created.
- A significant number of files in `src/` (likely 50+) are modified to replace `printf`/`fprintf` with the new logging macros and to include `logging.h`.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
