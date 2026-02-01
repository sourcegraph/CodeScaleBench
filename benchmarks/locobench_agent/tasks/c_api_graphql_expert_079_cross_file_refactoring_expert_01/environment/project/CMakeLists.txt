# ==================================================================================================
#  SynestheticCanvas – API GraphQL Micro-Service
#  CMake build script (top-level) – production ready
#
#  This CMakeLists.txt orchestrates the complete build, test and packaging workflow
#  for the “api_graphql” micro-service written in C.  It supports a modern workflow
#  with dependency fetching, compile-time feature toggles, sanitizers, code coverage,
#  version auto-discovery from git and an exportable Config package.
#
#  Author:  SynestheticCanvas Core Team
#  SPDX-License-Identifier: MIT
# ==================================================================================================

cmake_minimum_required (VERSION 3.18 FATAL_ERROR)

# --------------------------------------------------------------------------------------------------
#  Project metadata
# --------------------------------------------------------------------------------------------------
project (synesthetic_canvas_api_graphql
        VERSION 1.4.0                                   # Semantic version *baseline*; see below
        DESCRIPTION "GraphQL gateway micro-service for SynestheticCanvas constellation"
        LANGUAGES C                                    # Pure C (C17 standard)
        )

set (SC_API_GQL_TARGET       syn_canvas_api_graphql)   # Main target name
set (SC_API_GQL_SOVERSION    1)                        # For shared lib if built


# --------------------------------------------------------------------------------------------------
#  Build options
# --------------------------------------------------------------------------------------------------
option (SC_ENABLE_TESTS        "Build unit/integration tests"                       ON)
option (SC_ENABLE_SANITIZERS   "Enable compile-time sanitizers (Debug only)"        ON)
option (SC_ENABLE_COVERAGE     "Enable coverage instrumentation (GCC/Clang, Debug)" OFF)
option (SC_BUILD_SHARED        "Build shared library instead of executable"         OFF)
option (SC_WARNINGS_AS_ERRORS  "Treat compiler warnings as errors"                  ON)

# --------------------------------------------------------------------------------------------------
#  Toolchain & Compilation
# --------------------------------------------------------------------------------------------------
set (CMAKE_C_STANDARD          17)
set (CMAKE_C_STANDARD_REQUIRED ON)
set (CMAKE_POSITION_INDEPENDENT_CODE ON)            # For shared libs / plugins

if (NOT CMAKE_BUILD_TYPE)
    set (CMAKE_BUILD_TYPE Debug CACHE STRING "Build type" FORCE)
endif ()

# Extra strictness
if (CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options (
        -Wall -Wextra -Wpedantic
        -Wcast-align -Wpointer-arith -Wstrict-prototypes
        -Wmissing-prototypes -Wformat=2 -Wshadow
    )
    if (SC_WARNINGS_AS_ERRORS)
        add_compile_options (-Werror)
    endif ()
elseif (MSVC)
    add_compile_options (/W4 /permissive-)
endif ()


# --------------------------------------------------------------------------------------------------
#  Version auto-discovery from git (overrides project() version if available)
# --------------------------------------------------------------------------------------------------
# Generates include/sc_version.h with:
#     #define SC_API_GQL_VERSION "1.4.0+g<commit>"
#     #define SC_API_GQL_GIT_HASH "<commit>"
#     #define SC_API_GQL_GIT_BRANCH "<branch>"
# --------------------------------------------------------------------------------------------------
find_package (Git QUIET)

if (GIT_FOUND AND EXISTS "${PROJECT_SOURCE_DIR}/.git")
    execute_process (COMMAND ${GIT_EXECUTABLE} rev-parse --short HEAD
                     OUTPUT_VARIABLE GIT_HASH OUTPUT_STRIP_TRAILING_WHITESPACE)
    execute_process (COMMAND ${GIT_EXECUTABLE} rev-parse --abbrev-ref HEAD
                     OUTPUT_VARIABLE GIT_BRANCH OUTPUT_STRIP_TRAILING_WHITESPACE)
    set (PROJECT_VERSION "${PROJECT_VERSION}+g${GIT_HASH}")
endif ()

configure_file (
    ${CMAKE_CURRENT_SOURCE_DIR}/cmake/templates/sc_version.h.in
    ${CMAKE_CURRENT_BINARY_DIR}/generated/sc_version.h
    @ONLY
)

include_directories (${CMAKE_CURRENT_BINARY_DIR}/generated)
install (FILES ${CMAKE_CURRENT_BINARY_DIR}/generated/sc_version.h
        DESTINATION include/synesthetic_canvas)


# --------------------------------------------------------------------------------------------------
#  Dependencies
# --------------------------------------------------------------------------------------------------
include (FetchContent)

# 1. cJSON – Lightweight JSON parser/serializer
FetchContent_Declare (
    cJSON
    GIT_REPOSITORY https://github.com/DaveGamble/cJSON.git
    GIT_TAG        v1.7.16
)
FetchContent_MakeAvailable (cJSON)

# 2. libgraphqlparser – Facebook’s GraphQL parser (C bindings)
#    Pre-built packages may not exist everywhere, so fallback to FetchContent
find_package (graphqlparser QUIET)
if (NOT graphqlparser_FOUND)
    message (STATUS "libgraphqlparser not found, fetching from source…")
    FetchContent_Declare (
        graphqlparser
        GIT_REPOSITORY https://github.com/graphql/libgraphqlparser.git
        GIT_TAG        0.7.2
    )
    set (BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)        # Build static internally
    FetchContent_MakeAvailable (graphqlparser)
endif ()

# 3. libuv – Event loop / async I/O abstraction
find_package (uv 1.30 REQUIRED)

# 4. OpenSSL (for TLS if we add HTTPS listener)
find_package (OpenSSL 1.1 REQUIRED)

# 5. zlib (for compressed payloads)
find_package (ZLIB REQUIRED)


# --------------------------------------------------------------------------------------------------
#  Source layout
# --------------------------------------------------------------------------------------------------
# We keep a flat list for clarity; you may generate this automatically with filesystem globbing, but
# explicit listing is preferred for reproducible builds.
set (SC_API_GQL_SRC
    src/main.c
    src/http_server.c
    src/http_server.h
    src/graphql_router.c
    src/graphql_router.h
    src/validators.c
    src/validators.h
    src/pagination.c
    src/pagination.h
    src/logging.c
    src/logging.h
    src/metrics.c
    src/metrics.h
    src/config.c
    src/config.h
)

# --------------------------------------------------------------------------------------------------
#  Build target
# --------------------------------------------------------------------------------------------------
if (SC_BUILD_SHARED)
    add_library      (${SC_API_GQL_TARGET} SHARED ${SC_API_GQL_SRC})
    set_target_properties (${SC_API_GQL_TARGET}
        PROPERTIES SOVERSION ${SC_API_GQL_SOVERSION})
else ()
    add_executable   (${SC_API_GQL_TARGET} ${SC_API_GQL_SRC})
endif ()

target_include_directories (${SC_API_GQL_TARGET}
    PUBLIC  $<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>
            $<INSTALL_INTERFACE:include>
)

target_link_libraries (${SC_API_GQL_TARGET}
    PRIVATE
        cjson
        graphqlparser
        uv
        OpenSSL::SSL
        ZLIB::ZLIB
)

# --------------------------------------------------------------------------------------------------
#  Sanitizers (clang/gcc, Debug only)
# --------------------------------------------------------------------------------------------------
if (SC_ENABLE_SANITIZERS AND CMAKE_BUILD_TYPE STREQUAL "Debug")
    if (CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options (${SC_API_GQL_TARGET} PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options    (${SC_API_GQL_TARGET} PRIVATE -fsanitize=address,undefined)
    endif ()
endif ()

# --------------------------------------------------------------------------------------------------
#  Coverage
# --------------------------------------------------------------------------------------------------
if (SC_ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options (${SC_API_GQL_TARGET} PRIVATE -O0 -g --coverage)
    target_link_options    (${SC_API_GQL_TARGET} PRIVATE --coverage)
endif ()


# --------------------------------------------------------------------------------------------------
#  Install rules
# --------------------------------------------------------------------------------------------------
include (GNUInstallDirs)

install (TARGETS ${SC_API_GQL_TARGET}
        EXPORT  SynestheticCanvasTargets
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install (DIRECTORY include/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
        FILES_MATCHING PATTERN "*.h"
)

#  Export a pkg-config file
configure_file (
    ${CMAKE_CURRENT_SOURCE_DIR}/cmake/templates/synesthetic_canvas_api_graphql.pc.in
    ${CMAKE_CURRENT_BINARY_DIR}/synesthetic_canvas_api_graphql.pc
    @ONLY
)
install (FILES ${CMAKE_CURRENT_BINARY_DIR}/synesthetic_canvas_api_graphql.pc
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/pkgconfig)

#  CMake package config for find_package()
install (EXPORT SynestheticCanvasTargets
        FILE SynestheticCanvasTargets.cmake
        NAMESPACE SynestheticCanvas::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/SynestheticCanvas)

include (CMakePackageConfigHelpers)
configure_package_config_file (
    ${CMAKE_CURRENT_SOURCE_DIR}/cmake/templates/SynestheticCanvasConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/SynestheticCanvasConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/SynestheticCanvas
)
install (FILES
    ${CMAKE_CURRENT_BINARY_DIR}/SynestheticCanvasConfig.cmake
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/SynestheticCanvas
)

# --------------------------------------------------------------------------------------------------
#  Testing
# --------------------------------------------------------------------------------------------------
if (SC_ENABLE_TESTS)
    enable_testing ()
    add_subdirectory (tests)
endif ()


# --------------------------------------------------------------------------------------------------
#  Developer utilities
# --------------------------------------------------------------------------------------------------
#   make clang-format / make lint / etc.
add_custom_target (clang-format
    COMMAND clang-format -i ${SC_API_GQL_SRC}
    WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
    COMMENT "Running clang-format on source tree"
)

#  Doxygen documentation (if Doxygen present)
find_package (Doxygen OPTIONAL_COMPONENTS dot)
if (DOXYGEN_FOUND)
    set (DOXYGEN_GENERATE_LATEX NO)
    doxygen_add_docs (doc
        ${PROJECT_SOURCE_DIR}/include
        ${PROJECT_SOURCE_DIR}/src
        COMMENT "Generating API documentation with Doxygen"
    )
endif ()


# --------------------------------------------------------------------------------------------------
#  Summaries
# --------------------------------------------------------------------------------------------------
message (STATUS "")
message (STATUS "==============================================================")
message (STATUS "  SynestheticCanvas – api_graphql")
message (STATUS "  Version          : ${PROJECT_VERSION}")
message (STATUS "  Build Type       : ${CMAKE_BUILD_TYPE}")
message (STATUS "  Sanitizers       : ${SC_ENABLE_SANITIZERS}")
message (STATUS "  Coverage         : ${SC_ENABLE_COVERAGE}")
message (STATUS "  Tests            : ${SC_ENABLE_TESTS}")
message (STATUS "==============================================================")
message (STATUS "")