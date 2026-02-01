# =====================================================================
#  HoloCanvas – Wallet Proxy Micro-Service
#
#  CMake build script
#  -------------------------------------------------------------
#  This file is part of the HoloCanvas blockchain NFT platform.
#  The Wallet-Proxy is a façade that exposes a simplified JSON /
#  gRPC API for end–user wallets and 3rd-party dApps, hiding the
#  complexity of multi-chain signing, fee estimation, & roll-up
#  commitments.
#
#  Author:  HoloCanvas Core Team
#  License: MIT
# =====================================================================

cmake_minimum_required (VERSION 3.16)

# ---------------------------------------------------------------------
# Project meta-data
# ---------------------------------------------------------------------
project (wallet_proxy
        VERSION 1.2.0
        DESCRIPTION "HoloCanvas Wallet Proxy Micro-Service"
        LANGUAGES C)

# ---------------------------------------------------------------------
# Global build options
# ---------------------------------------------------------------------
option (WALLET_PROXY_BUILD_SHARED   "Build shared library instead of static"        OFF)
option (WALLET_PROXY_ENABLE_TESTS   "Build unit / integration tests"                ON)
option (WALLET_PROXY_ENABLE_COVERAGE "Enable GCOV/LCOV coverage (Debug only)"       OFF)
option (WALLET_PROXY_ENABLE_SANITIZER
        "Enable Address/Undefined Behavior sanitizers (Debug only)"                 OFF)
option (WALLET_PROXY_ENABLE_CLANGTIDY "Run clang-tidy on compile"                   OFF)

# Default build type ----------------------------------------------------------------
if (NOT CMAKE_BUILD_TYPE)
    set (CMAKE_BUILD_TYPE Release CACHE STRING
         "Build type (Debug, Release, RelWithDebInfo, MinSizeRel)" FORCE)
endif ()

# ---------------------------------------------------------------------
# Compiler Configuration
# ---------------------------------------------------------------------
set (CMAKE_C_STANDARD 11)
set (CMAKE_C_STANDARD_REQUIRED ON)
set (CMAKE_C_EXTENSIONS OFF)

# Treat warnings as errors in CI/Release
set (WALLET_PROXY_COMMON_CFLAGS
     -Wall -Wextra -Wpedantic -Werror
     -Wcast-qual -Wstrict-prototypes -Wmissing-prototypes
     -Wformat=2 -Wshadow -Wpointer-arith)

add_compile_options (${WALLET_PROXY_COMMON_CFLAGS})

# Sanitisers / Coverage ------------------------------------------------
if (CMAKE_BUILD_TYPE STREQUAL "Debug")
    if (WALLET_PROXY_ENABLE_SANITIZER)
        message (STATUS "Address/UB Sanitizers enabled")
        add_compile_options       (-fsanitize=address,undefined -fno-omit-frame-pointer)
        add_link_options          (-fsanitize=address,undefined -fno-omit-frame-pointer)
    endif ()

    if (WALLET_PROXY_ENABLE_COVERAGE)
        message (STATUS "Code coverage instrumentation enabled")
        add_compile_options       (--coverage -O0)
        add_link_options          (--coverage)
    endif ()
endif ()

# clang-tidy -----------------------------------------------------------
if (WALLET_PROXY_ENABLE_CLANGTIDY)
    find_program (CLANG_TIDY_EXE NAMES clang-tidy)
    if (CLANG_TIDY_EXE)
        message (STATUS "clang-tidy found: ${CLANG_TIDY_EXE}")
        set (CMAKE_C_CLANG_TIDY
            ${CLANG_TIDY_EXE};-config=;
            --header-filter=.*;
            -checks=*,-clang-diagnostic-*,
                    -llvm-header-guard,
                    -readability-magic-numbers,
                    -readability-identifier-length)
    else ()
        message (WARNING "clang-tidy requested but not found")
    endif ()
endif ()

# ---------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------
include (FetchContent)

# cJSON – lightweight JSON library (MIT)
FetchContent_Declare (
    cjson
    GIT_REPOSITORY https://github.com/DaveGamble/cJSON.git
    GIT_TAG        v1.7.16)
FetchContent_MakeAvailable (cjson)

# libuv – high-performance event loop (MIT)
FetchContent_Declare (
    libuv
    GIT_REPOSITORY https://github.com/libuv/libuv.git
    GIT_TAG        v1.48.0)
FetchContent_MakeAvailable (libuv)

# nanopb – Protocol Buffers for embedded C (zlib)
FetchContent_Declare (
    nanopb
    GIT_REPOSITORY https://github.com/nanopb/nanopb.git
    GIT_TAG        nanopb-0.4.8)
FetchContent_MakeAvailable (nanopb)

# OpenSSL – crypto primitives (system or vendored)
find_package (OpenSSL 1.1 REQUIRED)

# ---------------------------------------------------------------------
# Source layout
# ---------------------------------------------------------------------
set (WALLET_PROXY_SRC
    src/wallet_proxy.c
    src/wallet_proxy_codec.c
    src/wallet_proxy_events.c
    src/wallet_proxy_rpc.c
    src/wallet_proxy_signer.c
    include/wallet_proxy/wallet_proxy.h
    include/wallet_proxy/wallet_proxy_codec.h
    include/wallet_proxy/wallet_proxy_events.h
    include/wallet_proxy/wallet_proxy_rpc.h
    include/wallet_proxy/wallet_proxy_signer.h)

# Generated protobuf sources (nanopb)
set (PROTO_FILES proto/wallet_proxy.proto)

foreach (proto ${PROTO_FILES})
    get_filename_component (proto_name ${proto} NAME_WE)
    set (pb_src "${CMAKE_CURRENT_BINARY_DIR}/${proto_name}.pb.c")
    set (pb_hdr "${CMAKE_CURRENT_BINARY_DIR}/${proto_name}.pb.h")

    add_custom_command (
        OUTPUT  ${pb_src} ${pb_hdr}
        COMMAND protobuf-nanopb
                --output-dir=${CMAKE_CURRENT_BINARY_DIR}
                ${CMAKE_CURRENT_SOURCE_DIR}/${proto}
        DEPENDS ${proto}
        COMMENT "Generating nanopb C source for ${proto}")
    list (APPEND WALLET_PROXY_SRC ${pb_src} ${pb_hdr})
endforeach ()

# ---------------------------------------------------------------------
# Build target
# ---------------------------------------------------------------------
if (WALLET_PROXY_BUILD_SHARED)
    add_library (wallet_proxy SHARED  ${WALLET_PROXY_SRC})
    set_target_properties (wallet_proxy PROPERTIES
        POSITION_INDEPENDENT_CODE ON
        OUTPUT_NAME "wallet_proxy")
else ()
    add_library (wallet_proxy STATIC  ${WALLET_PROXY_SRC})
endif ()

target_include_directories (wallet_proxy
    PUBLIC  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
            $<INSTALL_INTERFACE:include>
    PRIVATE ${CMAKE_CURRENT_BINARY_DIR})

target_link_libraries (wallet_proxy
    PUBLIC
        OpenSSL::Crypto
        uv_a              # static from libuv
    PRIVATE
        cjson
        nanopb)

# ---------------------------------------------------------------------
# Service executable
# ---------------------------------------------------------------------
add_executable (wallet_proxy_service src/main.c)
target_link_libraries (wallet_proxy_service PRIVATE wallet_proxy)

# ---------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------
include (GNUInstallDirs)

install (TARGETS wallet_proxy wallet_proxy_service
        EXPORT wallet_proxy_targets
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})

install (DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

# Export package for find_package() --------------------------------------------------
install (EXPORT wallet_proxy_targets
        FILE WalletProxyTargets.cmake
        NAMESPACE HoloCanvas::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/WalletProxy)

include (CMakePackageConfigHelpers)

configure_package_config_file (
    cmake/WalletProxyConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/WalletProxyConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/WalletProxy)

install (FILES ${CMAKE_CURRENT_BINARY_DIR}/WalletProxyConfig.cmake
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/WalletProxy)

# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------
if (WALLET_PROXY_ENABLE_TESTS)
    enable_testing ()
    add_subdirectory (tests)
endif ()

# ---------------------------------------------------------------------
# Packaging (CPack)
# ---------------------------------------------------------------------
include (CPack)

# EOF -----------------------------------------------------------------