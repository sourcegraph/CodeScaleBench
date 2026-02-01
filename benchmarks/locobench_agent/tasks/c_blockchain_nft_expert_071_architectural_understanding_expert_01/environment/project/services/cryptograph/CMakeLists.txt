cmake_minimum_required(VERSION 3.18 FATAL_ERROR)

# ─────────────────────────────────────────────────────────────────────────────
#  HoloCanvas :: Cryptograph Service
#
#  CMake build script for the “Cryptograph” micro-service.  The service
#  provides high-performance, constant-time cryptographic primitives used by
#  the broader HoloCanvas platform (LedgerCore, Governance-Hall, DeFi-Garden,
#  etc.).  It is shipped both as a shared library (`libcryptograph.so/.dll`)
#  and as a standalone gRPC server binary (`cryptograph-service`).
#
#  Author:     HoloCanvas Core Team
#  SPDX-License-Identifier: MIT
# ─────────────────────────────────────────────────────────────────────────────

project(cryptograph
        VERSION 1.2.0
        DESCRIPTION "HoloCanvas Cryptographic Micro-Service"
        LANGUAGES C)

# --------------------------------------------------------------------------- #
# Build options
# --------------------------------------------------------------------------- #
option(CRYPTOGRAPH_BUILD_STATIC       "Produce a static library instead of shared" OFF)
option(CRYPTOGRAPH_ENABLE_ASAN        "Enable Address Sanitizer"                   OFF)
option(CRYPTOGRAPH_ENABLE_UBSAN       "Enable Undefined Behavior Sanitizer"        OFF)
option(CRYPTOGRAPH_ENABLE_LTO         "Enable Link-Time Optimisation (IPO/LTO)"    ON)
option(CRYPTOGRAPH_BUILD_TESTS        "Build unit/integration tests"               ON)
option(CRYPTOGRAPH_WARN_AS_ERROR      "Treat all warnings as errors"               ON)

# --------------------------------------------------------------------------- #
# Compiler configuration
# --------------------------------------------------------------------------- #
set(CMAKE_C_STANDARD               11)
set(CMAKE_C_STANDARD_REQUIRED      ON)
set(CMAKE_C_EXTENSIONS             OFF)

# Universal warning flags
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    set(COMMON_WARNINGS
        -Wall -Wextra -Wpedantic
        -Wshadow -Wcast-align -Wstrict-prototypes
        -Wconversion -Wsign-conversion -Wdouble-promotion
    )
    add_compile_options(${COMMON_WARNINGS})
    if(CRYPTOGRAPH_WARN_AS_ERROR)
        add_compile_options(-Werror)
    endif()
elseif(MSVC)
    add_compile_options(/W4 /permissive-)
    if(CRYPTOGRAPH_WARN_AS_ERROR)
        add_compile_options(/WX)
    endif()
endif()

# Sanitizers
set(_SAN_FLAGS "")
if(CRYPTOGRAPH_ENABLE_ASAN)
    list(APPEND _SAN_FLAGS -fsanitize=address)
endif()
if(CRYPTOGRAPH_ENABLE_UBSAN)
    list(APPEND _SAN_FLAGS -fsanitize=undefined)
endif()
if(_SAN_FLAGS)
    add_compile_options(${_SAN_FLAGS})
    add_link_options(${_SAN_FLAGS})
endif()

# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
find_package(OpenSSL 1.1 REQUIRED)   # SHA-256, EC primitives, ASN.1 utilities

include(FindPkgConfig)
pkg_check_modules(LIBSODIUM REQUIRED libsodium>=1.0.18)  # Constant-time crypto

# --------------------------------------------------------------------------- #
# Source layout
# --------------------------------------------------------------------------- #
set(CRYPTOGRAPH_SRC
    src/cryptograph.c
    src/keystore.c
    src/schnorr_sig.c
    src/merkle_tree.c
    src/codec/base58.c
    src/codec/varint.c
    src/utils/byte_utils.c

    include/cryptograph/cryptograph.h
    include/cryptograph/keystore.h
    include/cryptograph/merkle_tree.h
    include/cryptograph/utils.h
)

# Public/Private include directories
set(CRYPTOGRAPH_PUBLIC_INC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

set(CRYPTOGRAPH_PRIVATE_INC
    ${LIBSODIUM_INCLUDE_DIRS}
    ${CMAKE_CURRENT_BINARY_DIR}               # For generated config.h
)

# --------------------------------------------------------------------------- #
# Library target
# --------------------------------------------------------------------------- #
if(CRYPTOGRAPH_BUILD_STATIC)
    add_library(cryptograph STATIC ${CRYPTOGRAPH_SRC})
else()
    add_library(cryptograph SHARED ${CRYPTOGRAPH_SRC})
    set_target_properties(cryptograph PROPERTIES
        VERSION   ${PROJECT_VERSION}
        SOVERSION 1
    )
endif()

target_include_directories(cryptograph
    PUBLIC  ${CRYPTOGRAPH_PUBLIC_INC}
    PRIVATE ${CRYPTOGRAPH_PRIVATE_INC}
)

target_link_libraries(cryptograph
    PUBLIC  OpenSSL::SSL
    PRIVATE ${LIBSODIUM_LIBRARIES}
)

# Link-Time Optimisation
include(CheckIPOSupported)
if(CRYPTOGRAPH_ENABLE_LTO)
    check_ipo_supported(RESULT IPO_OK OUTPUT IPO_ERROR)
    if(IPO_OK)
        set_target_properties(cryptograph PROPERTIES INTERPROCEDURAL_OPTIMIZATION TRUE)
    else()
        message(WARNING "LTO disabled: ${IPO_ERROR}")
    endif()
endif()

# --------------------------------------------------------------------------- #
# Service executable
# --------------------------------------------------------------------------- #
add_executable(cryptograph-service src/service_main.c)
target_link_libraries(cryptograph-service PRIVATE cryptograph)

# --------------------------------------------------------------------------- #
# Configuration header (auto-generated)
# --------------------------------------------------------------------------- #
configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/config.h.in
    ${CMAKE_CURRENT_BINARY_DIR}/config.h
    @ONLY
)

# --------------------------------------------------------------------------- #
# Testing
# --------------------------------------------------------------------------- #
if(CRYPTOGRAPH_BUILD_TESTS)
    enable_testing()
    add_subdirectory(test)   # Expects `test/CMakeLists.txt`
endif()

# --------------------------------------------------------------------------- #
# Installation rules
# --------------------------------------------------------------------------- #
include(GNUInstallDirs)

install(TARGETS cryptograph
        EXPORT  cryptographTargets
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install(DIRECTORY include/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
        FILES_MATCHING PATTERN "*.h"
)

install(EXPORT  cryptographTargets
        NAMESPACE HoloCanvas::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/cryptograph
)

# --------------------------------------------------------------------------- #
# Packaging (CPack)
# --------------------------------------------------------------------------- #
include(CPack)

# --------------------------------------------------------------------------- #
# Status summary
# --------------------------------------------------------------------------- #
message(STATUS "")
message(STATUS "────────────────────────────────────────────────────")
message(STATUS "  HoloCanvas :: Cryptograph Build Summary")
message(STATUS "────────────────────────────────────────────────────")
message(STATUS "  Project version         : ${PROJECT_VERSION}")
message(STATUS "  C compiler              : ${CMAKE_C_COMPILER}")
message(STATUS "  Build type              : ${CMAKE_BUILD_TYPE}")
message(STATUS "  Build static library    : ${CRYPTOGRAPH_BUILD_STATIC}")
message(STATUS "  Build tests             : ${CRYPTOGRAPH_BUILD_TESTS}")
message(STATUS "  Enable ASan             : ${CRYPTOGRAPH_ENABLE_ASAN}")
message(STATUS "  Enable UBSan            : ${CRYPTOGRAPH_ENABLE_UBSAN}")
message(STATUS "  Enable LTO              : ${CRYPTOGRAPH_ENABLE_LTO}")
message(STATUS "  OpenSSL root            : ${OPENSSL_ROOT_DIR}")
message(STATUS "  Sodium include dirs     : ${LIBSODIUM_INCLUDE_DIRS}")
message(STATUS "────────────────────────────────────────────────────")
message(STATUS "")