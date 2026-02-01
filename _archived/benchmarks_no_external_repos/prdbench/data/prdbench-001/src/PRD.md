# Task Management CLI Application

## Overview

Build a command-line task management application that allows users to create, list, update, and delete tasks with support for priorities and due dates.

## Requirements

### Core Functionality

1. **Task Creation**
   - Users should be able to create tasks with a title and optional description
   - Tasks should have a unique ID generated automatically
   - Tasks should support priority levels: low, medium, high

2. **Task Listing**
   - Display all tasks in a formatted table
   - Support filtering by status (pending, completed)
   - Support filtering by priority level

3. **Task Updates**
   - Mark tasks as complete
   - Change task priority
   - Edit task title and description

4. **Task Deletion**
   - Delete individual tasks by ID
   - Delete all completed tasks in bulk

### Data Persistence

- Tasks should be persisted to a JSON file
- The application should handle file I/O errors gracefully
- Support import/export of tasks in JSON format

### User Experience

- Clear command-line interface with help text
- Informative error messages
- Confirmation prompts for destructive operations

## Technical Specifications

- Language: Python 3.10+
- No external dependencies required
- Single-file implementation acceptable
- Use argparse for CLI argument parsing
