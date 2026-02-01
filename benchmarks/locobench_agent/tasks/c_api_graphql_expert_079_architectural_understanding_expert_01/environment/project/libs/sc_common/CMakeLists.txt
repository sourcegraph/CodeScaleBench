cmake_minimum_required(VERSION 3.18 FATAL_ERROR)

#
#  SynestheticCanvas – sc_common
#  Centralised utility library (logging, error-handling, time helpers, etc.)
#
#  This CMakeLists.txt is intentionally verbose because it is consumed
#  by every micro-service in the constellation as an interface package.
#  “Measure twice, cut once.”
#

# ──────────────────────────────────────────────────────────────────────────────
# Project
# ──────────────────────────────────────────────────────────────────────────────
project(sc_common
        VERSION 1.2.0          # Keep in sync with include/sc_common/version.h
        DESCRIPTION "SynestheticCanvas – Common C-level utilities"
        LANGUAGES C)

# ──────────────────────────────────────────────────────────────────────────────
# Global Options
# ──────────────────────────────────────────────────────────────────────────────
option(SC_COMMON_BUILD_SHARED   "Build sc_common as a shared library"        ON)
option(SC_COMMON_ENABLE_TESTS   "Build unit & integration tests"            ON)
option(SC_COMMON_ENABLE_COVERAGE "Enable coverage instrumentation (gcc/clang)" OFF)
option(SC_COMMON_ENABLE_SANITIZE "Enable (address,undefined) sanitizers"     OFF)

# ──────────────────────────────────────────────────────────────────────────────
# Compile Settings
# ──────────────────────────────────────────────────────────────────────────────
# Require at least C11
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

# Strict warnings, different per-compiler
if (MSVC)
    add_compile_options(/W4 /permissive-)
else()
    add_compile_options(
        -Wall -Wextra -Wpedantic
        -Wconversion -Wdouble-promotion -Wformat=2
        -Wshadow -Wstrict-prototypes
    )
endif()

# Sanitizers (optional)
if (SC_COMMON_ENABLE_SANITIZE AND NOT MSVC)
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
    add_link_options   (-fsanitize=address,undefined -fno-omit-frame-pointer)
endif()

# Coverage (requires GNU or Clang)
if (SC_COMMON_ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(--coverage -O0)
    add_link_options   (--coverage)
endif()

# ──────────────────────────────────────────────────────────────────────────────
# Dependencies
# ──────────────────────────────────────────────────────────────────────────────
include(GNUInstallDirs)
find_package(Threads REQUIRED)

# cJSON – lightweight JSON (used by request validator helpers)
find_package(PkgConfig REQUIRED)
pkg_check_modules(CJSON REQUIRED IMPORTED_TARGET cjson)

# OpenSSL – UUID v4 generation & secure random helper
find_package(OpenSSL REQUIRED)

# ──────────────────────────────────────────────────────────────────────────────
# Sources & Headers
# ──────────────────────────────────────────────────────────────────────────────
# NOTE: Keep the list explicit; GLOB_RECURSE hides accidental file additions.
set(SC_COMMON_PUBLIC_HEADERS
    include/sc_common/api.h
    include/sc_common/assert.h
    include/sc_common/log.h
    include/sc_common/result.h
    include/sc_common/uuid.h
    include/sc_common/version.h
)

set(SC_COMMON_PRIVATE_SOURCES
    src/assert.c
    src/log.c
    src/result.c
    src/uuid.c
    src/platform/time.c
)

set(SC_COMMON_PRIVATE_HEADERS
    src/platform/time.h
)

add_library(sc_common
    ${SC_COMMON_PUBLIC_HEADERS}
    ${SC_COMMON_PRIVATE_SOURCES}
    ${SC_COMMON_PRIVATE_HEADERS}
)

# Header visibility
target_include_directories(sc_common
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
)

# Library type
set_target_properties(sc_common PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    C_VISIBILITY_PRESET        hidden
    VISIBILITY_INLINES_HIDDEN  YES
    WINDOWS_EXPORT_ALL_SYMBOLS ON      # Proper symbol export for MSVC
    OUTPUT_NAME                sc_common
)

if (SC_COMMON_BUILD_SHARED)
    set_target_properties(sc_common PROPERTIES TYPE SHARED)
else()
    set_target_properties(sc_common PROPERTIES TYPE STATIC)
endif()

# Link dependencies
target_link_libraries(sc_common
    PUBLIC
        Threads::Threads
        OpenSSL::Crypto
    PRIVATE
        PkgConfig::CJSON
)

# Public compile definitions
target_compile_definitions(sc_common
    PUBLIC
        $<$<BOOL:${SC_COMMON_BUILD_SHARED}>:SC_COMMON_SHARED>
        $<$<NOT:$<BOOL:${SC_COMMON_BUILD_SHARED}>>:SC_COMMON_STATIC>
)

# ──────────────────────────────────────────────────────────────────────────────
# Installation
# ──────────────────────────────────────────────────────────────────────────────
include(CMakePackageConfigHelpers)

# Install target
install(TARGETS sc_common
        EXPORT sc_commonTargets
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        INCLUDES DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

# Install headers
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

# Export target file
install(EXPORT sc_commonTargets
        FILE sc_commonTargets.cmake
        NAMESPACE SynestheticCanvas::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/sc_common)

# Generate and install the config & version files
configure_package_config_file(
    cmake/sc_commonConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/sc_commonConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/sc_common
)

write_basic_package_version_file(
    ${CMAKE_CURRENT_BINARY_DIR}/sc_commonConfigVersion.cmake
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion
)

install(FILES
    ${CMAKE_CURRENT_BINARY_DIR}/sc_commonConfig.cmake
    ${CMAKE_CURRENT_BINARY_DIR}/sc_commonConfigVersion.cmake
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/sc_common
)

# ──────────────────────────────────────────────────────────────────────────────
# Testing
# ──────────────────────────────────────────────────────────────────────────────
if (SC_COMMON_ENABLE_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()

# ──────────────────────────────────────────────────────────────────────────────
# CPack – binary / source package generation (optional)
# ──────────────────────────────────────────────────────────────────────────────
include(CPack)
set(CPACK_PACKAGE_NAME               "sc_common")
set(CPACK_PACKAGE_VENDOR             "SynestheticCanvas")
set(CPACK_PACKAGE_CONTACT            "oss@synestheticcanvas.io")
set(CPACK_PACKAGE_VERSION            ${PROJECT_VERSION})
set(CPACK_RESOURCE_FILE_LICENSE      "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE")

# Source package excludes build artifacts
set(CPACK_SOURCE_GENERATOR           "TGZ")
set(CPACK_SOURCE_IGNORE_FILES
    "/build/"
    "/\\.git/"
    "/\\.vscode/"
    "~$"
)

# Finalise CPack
cpack()