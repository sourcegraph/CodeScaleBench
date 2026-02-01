// CanvasChain Symphony – CCS Proto build script
//
// This build-script compiles every `.proto` file found under the `proto/`
// directory (recursively) into Rust source code using `tonic-build`.
//
// It supports the following cargo-features:
//   - `client`  : generate gRPC client stubs
//   - `server`  : generate gRPC server stubs
//
// If neither feature is selected we default to generating **both** client
// and server code.  When both are selected the behaviour is also to generate
// both sides.
//
// Environment variables
// ----------------------
// CCS_PROTO_OUT_DIR   – override default OUT_DIR for generated files
// PROTOC              – explicit path to the `protoc` binary to use
// RUST_LOG=info       – enables progress output from this script
//
// Re-generation is automatically triggered when *any* proto file changes or
// when `build.rs` itself is modified.
//
// ---------------------------------------------------------------------------

use std::{
    env,
    error::Error,
    fs,
    path::{Path, PathBuf},
};

use walkdir::WalkDir;

/// Relative directory (to the crate root) that contains all *.proto sources.
const PROTO_ROOT_DIR: &str = "proto";

/// Entry point for Cargo build-script execution.
fn main() -> Result<(), Box<dyn Error>> {
    // --------------------------------------------------
    // 1. Discover .proto sources & include directories
    // --------------------------------------------------
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR")?);
    let proto_root = manifest_dir.join(PROTO_ROOT_DIR);

    if !proto_root.exists() {
        eprintln!(
            "cargo:warning=No '{}' directory found, nothing to compile",
            PROTO_ROOT_DIR
        );
        return Ok(());
    }

    // Collect all .proto files while emitting rerun-if-changed for every file.
    let mut proto_files = Vec::<PathBuf>::new();
    for entry in WalkDir::new(&proto_root)
        .into_iter()
        .filter_entry(|e| !is_hidden(e.path()))
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if path.extension().map(|ext| ext == "proto").unwrap_or(false) {
            proto_files.push(path.to_owned());
            println!("cargo:rerun-if-changed={}", path.display());
        }
    }

    // Also re-run if build.rs itself changes
    println!("cargo:rerun-if-changed=build.rs");

    // Provide include dirs (root + google's protos bundled by prost)
    let include_dirs = vec![proto_root.clone()];

    // --------------------------------------------------
    // 2. Decide what to generate based on enabled features
    // --------------------------------------------------
    let feature_client = env::var_os("CARGO_FEATURE_CLIENT").is_some();
    let feature_server = env::var_os("CARGO_FEATURE_SERVER").is_some();

    // Default behaviour if no features are explicitly selected.
    let (generate_client, generate_server) = match (feature_client, feature_server) {
        (false, false) => (true, true),
        (client, server) => (client, server),
    };

    // --------------------------------------------------
    // 3. Where to put the generated files?
    // --------------------------------------------------
    let out_dir_env = env::var_os("CCS_PROTO_OUT_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR not set")));

    // Ensure the directory exists so tonic-build won't fail on non-existing path.
    fs::create_dir_all(&out_dir_env)?;

    // --------------------------------------------------
    // 4. Configure tonic-build
    // --------------------------------------------------
    let mut config = tonic_build::configure()
        .build_client(generate_client)
        .build_server(generate_server)
        .out_dir(&out_dir_env)
        // Put all generated code inside a module to avoid name collisions
        .compile_well_known_types(true)
        .compile_with_config(prost_build::Config::new(), &[], &[])?; // placeholder to get config object

    // Because we called compile_with_config with empty lists we cannot get config; we need restructure.
}

// Actually previous attempt parted incorrectly. We'll restructure:

