# Data Processing Pipeline

## Overview

Build a data processing pipeline that reads CSV files, performs transformations, and outputs aggregated reports.

## Requirements

### Input Processing

1. **CSV File Reading**
   - Read CSV files with automatic header detection
   - Handle missing values gracefully
   - Support common encodings (UTF-8, Latin-1)

2. **Data Validation**
   - Validate required columns exist
   - Type checking for numeric columns
   - Report validation errors without crashing

### Transformations

1. **Filtering**
   - Filter rows by column values
   - Support multiple filter conditions (AND/OR)

2. **Aggregation**
   - Group by one or more columns
   - Support sum, count, mean, min, max operations
   - Custom aggregation functions

3. **Derived Columns**
   - Create new columns from expressions
   - Support basic arithmetic operations

### Output

1. **Report Generation**
   - Output to CSV format
   - Output to JSON format
   - Summary statistics report

2. **Logging**
   - Log processing steps
   - Report number of rows processed/filtered

## Technical Specifications

- Use pandas library for data operations
- Support command-line arguments for configuration
- Configuration via YAML file
- Exit with appropriate codes (0=success, 1=error)
