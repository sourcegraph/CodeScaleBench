# ===================================================================================
#  CMake build script for the SynestheticCanvas Narrative Service
#
#  This file configures, builds, tests and installs the narrative-service component.
#  It follows the same production-grade conventions used across the entire
#  SynestheticCanvas micro-service constellation.
#
#  Highlights
#  ----------
#  • Modern CMake (>= 3.19)                                                   
#  • Strict compiler warnings ‑> errors (can be relaxed via SC_WERROR)        
#  • Optional Address/UB sanitizers                                           
#  • Out-of-tree build and install support                                    
#  • Unit-test integration with CTest                                         
#  • Automatic version/header generation                                      
#
#  ============================================================================

cmake_minimum_required(VERSION 3.19)

# -----------------------------------------------------------------------------
#  Project metadata
# -----------------------------------------------------------------------------
project(
    narrative-service                     # Target micro-service
    VERSION 1.4.2                         # Semantic version (major.minor.patch)
    DESCRIPTION "Narrative branching engine for SynestheticCanvas"
    LANGUAGES C
)

# -----------------------------------------------------------------------------
#  Compile options
# -----------------------------------------------------------------------------
option(SC_ENABLE_SANITIZERS   "Enable Address/UB sanitizers"      OFF)
option(SC_ENABLE_COVERAGE     "Enable code-coverage flags"        OFF)
option(SC_WERROR              "Treat warnings as errors"          ON)
option(SC_BUILD_TESTS         "Build narrative-service test tree" ON)
option(SC_BUILD_SHARED        "Build shared libs instead of static" OFF)

# ----------------------------------------------------------------------------- 
#  Output directories
# -----------------------------------------------------------------------------
set(SC_RUNTIME_OUTPUT_DIR ${CMAKE_BINARY_DIR}/bin          CACHE PATH "Runtime output")
set(SC_LIBRARY_OUTPUT_DIR ${CMAKE_BINARY_DIR}/lib          CACHE PATH "Library output")
set(SC_ARCHIVE_OUTPUT_DIR ${CMAKE_BINARY_DIR}/lib          CACHE PATH "Archive output")

foreach(_type RUNTIME LIBRARY ARCHIVE)
    set(CMAKE_${_type}_OUTPUT_DIRECTORY ${SC_${_type}_OUTPUT_DIR})
endforeach()

# -----------------------------------------------------------------------------
#  Build type defaults
# -----------------------------------------------------------------------------
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING
        "Choose the type of build (Debug, Release, RelWithDebInfo, MinSizeRel)"
        FORCE)
endif()

# -----------------------------------------------------------------------------
#  Compiler feature detection and flags
# -----------------------------------------------------------------------------
include(CheckCCompilerFlag)
set(SC_STRICT_FLAGS "")
set(_warn_flags -Wall -Wextra -Wpedantic -Wconversion -Wcast-qual -Wwrite-strings)
set(_opt_flags  "")
set(_dbg_flags  "")

# GCC / Clang family
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    list(APPEND SC_STRICT_FLAGS ${_warn_flags} -Wmissing-prototypes -Wshadow)
    if(SC_WERROR)
        list(APPEND SC_STRICT_FLAGS -Werror)
    endif()

    # Address/UB sanitizers
    if(SC_ENABLE_SANITIZERS)
        add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
        add_link_options(-fsanitize=address,undefined)
    endif()

    # Coverage (GCC + Clang LLVM)
    if(SC_ENABLE_COVERAGE)
        add_compile_options(--coverage)
        add_link_options(--coverage)
    endif()
endif()

# MSVC (for completeness)
if(MSVC)
    list(APPEND SC_STRICT_FLAGS /W4)
    if(SC_WERROR)
        list(APPEND SC_STRICT_FLAGS /WX)
    endif()
endif()

# Apply global compile flags
add_compile_options(${SC_STRICT_FLAGS})

# Enforce C11 by default
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED YES)
set(CMAKE_C_EXTENSIONS NO)

# -----------------------------------------------------------------------------
#  Dependencies
# -----------------------------------------------------------------------------
find_package(Threads REQUIRED)

# cJSON – lightweight JSON parser (required)
find_package(cjson 1.7 REQUIRED CONFIG)

# graphqlparser – shared lex/yacc GraphQL AST parser (required)
find_package(graphqlparser 0.7 REQUIRED CONFIG)

# Zlib – compressed narrative assets (optional but strongly recommended)
find_package(ZLIB)

# pkg-config detection for optional libs
find_package(PkgConfig)

# libbson (optional – for upcoming story export to Mongo)
if(PKG_CONFIG_FOUND)
    pkg_check_modules(LIBBSON libbson-1.0)
endif()

# -----------------------------------------------------------------------------
#  Source layout
# -----------------------------------------------------------------------------
set(SC_SRC_DIR     ${CMAKE_CURRENT_SOURCE_DIR}/src)
set(SC_INCLUDE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/include)

file(GLOB_RECURSE NARRATIVE_SERVICE_HEADERS
     CONFIGURE_DEPENDS
     ${SC_INCLUDE_DIR}/scnarr/*.h
)

file(GLOB_RECURSE NARRATIVE_SERVICE_SOURCES
     CONFIGURE_DEPENDS
     ${SC_SRC_DIR}/*.c
)

# -----------------------------------------------------------------------------
#  Version header generation
# -----------------------------------------------------------------------------
configure_file(
    ${SC_INCLUDE_DIR}/scnarr/version.h.in
    ${CMAKE_CURRENT_BINARY_DIR}/generated/version.h
    @ONLY
)

# Provide generated dir to include path
include_directories(${CMAKE_CURRENT_BINARY_DIR}/generated)

# -----------------------------------------------------------------------------
#  Library target (core narrative engine)
# -----------------------------------------------------------------------------
set(NARRATIVE_CORE_TARGET narrative_core)

add_library(${NARRATIVE_CORE_TARGET}
    ${NARRATIVE_SERVICE_SOURCES}
    ${NARRATIVE_SERVICE_HEADERS}
)

if(SC_BUILD_SHARED)
    set_target_properties(${NARRATIVE_CORE_TARGET} PROPERTIES
        POSITION_INDEPENDENT_CODE ON
        WINDOWS_EXPORT_ALL_SYMBOLS ON
    )
else()
    set_target_properties(${NARRATIVE_CORE_TARGET} PROPERTIES
        POSITION_INDEPENDENT_CODE OFF
    )
endif()

target_include_directories(${NARRATIVE_CORE_TARGET}
    PUBLIC
        $<BUILD_INTERFACE:${SC_INCLUDE_DIR}>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/generated>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries(${NARRATIVE_CORE_TARGET}
    PUBLIC
        cjson::cjson
        graphqlparser::graphqlparser
        Threads::Threads
    PRIVATE
        $<$<BOOL:${ZLIB_FOUND}>:ZLIB::ZLIB>
        $<$<BOOL:${LIBBSON_FOUND}>:${LIBBSON_LIBRARIES}>
)

# -----------------------------------------------------------------------------
#  Executable target (micro-service REST/GraphQL)
# -----------------------------------------------------------------------------
add_executable(narrative-service
    ${SC_SRC_DIR}/main.c
)

target_link_libraries(narrative-service
    PRIVATE ${NARRATIVE_CORE_TARGET}
)

# -----------------------------------------------------------------------------
#  Installation
# -----------------------------------------------------------------------------
include(GNUInstallDirs)

install(
    TARGETS ${NARRATIVE_CORE_TARGET} narrative-service
    EXPORT  narrativeTargets
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install(
    DIRECTORY ${SC_INCLUDE_DIR}/
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
    FILES_MATCHING PATTERN "*.h"
)

install(
    FILES ${CMAKE_CURRENT_BINARY_DIR}/generated/version.h
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/scnarr
)

# Exporting package for find_package()
install(
    EXPORT narrativeTargets
    NAMESPACE scnarr::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/narrative
)

# -----------------------------------------------------------------------------
#  Testing
# -----------------------------------------------------------------------------
if(SC_BUILD_TESTS)
    enable_testing()
    add_subdirectory(test)
endif()

# -----------------------------------------------------------------------------
#  Packaging (CPack)
# -----------------------------------------------------------------------------
include(CPack)

# -----------------------------------------------------------------------------
#  Summary
# -----------------------------------------------------------------------------
message(STATUS "")
message(STATUS "SynestheticCanvas Narrative Service Configuration Summary:")
message(STATUS "  Build type...............: ${CMAKE_BUILD_TYPE}")
message(STATUS "  Install prefix...........: ${CMAKE_INSTALL_PREFIX}")
message(STATUS "  Compiler.................: ${CMAKE_C_COMPILER_ID} ${CMAKE_C_COMPILER_VERSION}")
message(STATUS "  Strict flags.............: ${SC_STRICT_FLAGS}")
message(STATUS "  Sanitizers enabled.......: ${SC_ENABLE_SANITIZERS}")
message(STATUS "  Coverage enabled.........: ${SC_ENABLE_COVERAGE}")
message(STATUS "  Warnings as errors.......: ${SC_WERROR}")
message(STATUS "  Build shared libs........: ${SC_BUILD_SHARED}")
message(STATUS "  Build tests..............: ${SC_BUILD_TESTS}")
message(STATUS "")