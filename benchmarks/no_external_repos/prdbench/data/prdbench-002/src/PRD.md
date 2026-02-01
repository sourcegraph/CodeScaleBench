# REST API for Bookshelf Service

## Overview

Build a RESTful API service for managing a personal bookshelf. Users can add books, track reading progress, and organize books into shelves.

## Requirements

### Core Endpoints

1. **Books API**
   - `GET /api/books` - List all books with pagination
   - `POST /api/books` - Add a new book
   - `GET /api/books/{id}` - Get book details
   - `PUT /api/books/{id}` - Update book information
   - `DELETE /api/books/{id}` - Remove a book

2. **Shelves API**
   - `GET /api/shelves` - List all shelves
   - `POST /api/shelves` - Create a new shelf
   - `PUT /api/shelves/{id}/books/{book_id}` - Add book to shelf
   - `DELETE /api/shelves/{id}/books/{book_id}` - Remove book from shelf

3. **Reading Progress API**
   - `POST /api/books/{id}/progress` - Update reading progress
   - `GET /api/books/{id}/progress` - Get reading history

### Data Model

- **Book**: id, title, author, isbn, page_count, cover_url, status, created_at
- **Shelf**: id, name, description, book_ids[], created_at
- **Progress**: book_id, current_page, timestamp, note

### Technical Requirements

- Use Flask or FastAPI framework
- SQLite database for persistence
- JSON responses with proper HTTP status codes
- Basic input validation
- Handle common error cases

## API Response Format

```json
{
  "success": true,
  "data": {...},
  "meta": {
    "page": 1,
    "per_page": 10,
    "total": 100
  }
}
```
