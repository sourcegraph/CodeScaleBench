#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The expected solution involves several key changes across the codebase:

1.  **New File Creation:** A new file `src/error.rs` is created.

2.  **Content of `src/error.rs`:**
    ```rust
    // src/error.rs
    use axum::{
        http::StatusCode,
        response::{IntoResponse, Response},
        Json,
    };
    use serde_json::json;
    use thiserror::Error;

    #[derive(Error, Debug)]
    pub enum AppError {
        #[error("invalid input: {0}")]
        ValidationError(String),

        #[error("resource not found: {0}")]
        NotFound(String),

        #[error("an internal server error occurred")]
        InternalServerError(#[from] anyhow::Error),

        #[error("database query failed")]
        DatabaseQuery(#[from] sqlx::Error),

        #[error("failed to access cache")]
        Cache(#[from] redis::RedisError),

        #[error("unauthorized access")]
        Unauthorized,
    }

    impl IntoResponse for AppError {
        fn into_response(self) -> Response {
            let (status, error_type, error_message) = match self {
                AppError::ValidationError(msg) => (StatusCode::BAD_REQUEST, "validation", msg),
                AppError::NotFound(msg) => (StatusCode::NOT_FOUND, "not_found", msg),
                AppError::Unauthorized => (StatusCode::UNAUTHORIZED, "unauthorized", "Authentication required".to_string()),
                AppError::DatabaseQuery(e) => (StatusCode::INTERNAL_SERVER_ERROR, "database_error", e.to_string()),
                AppError::Cache(e) => (StatusCode::INTERNAL_SERVER_ERROR, "cache_error", e.to_string()),
                AppError::InternalServerError(e) => (StatusCode::INTERNAL_SERVER_ERROR, "internal_error", e.to_string()),
            };

            let body = Json(json!({
                "error": {
                    "type": error_type,
                    "message": error_message,
                }
            }));

            (status, body).into_response()
        }
    }
    ```

3.  **Modifications in `src/module_*.txt` files:**
    -   **Before:** `pub async fn get_item(id: Uuid) -> Result<Item, String> { ... Err("not found".to_string()) }`
    -   **After:** `use crate::error::AppError; ... pub async fn get_item(id: Uuid) -> Result<Item, AppError> { ... Err(AppError::NotFound("Item not found".to_string())) }`

    -   **Before:** `pub fn process_data(data: &Data) -> Result<(), anyhow::Error> { ... let result = some_fallible_op()?; ... }`
    -   **After:** `use crate::error::AppError; ... pub fn process_data(data: &Data) -> Result<(), AppError> { ... let result = some_fallible_op()?; ... }` (The `?` operator works because of the `From` impls).

4.  **File-level changes:** Dozens of files in `src/` will have their function signatures updated and `use crate::error::AppError;` added. Old error types like `struct Module43Error;` will be deleted.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
