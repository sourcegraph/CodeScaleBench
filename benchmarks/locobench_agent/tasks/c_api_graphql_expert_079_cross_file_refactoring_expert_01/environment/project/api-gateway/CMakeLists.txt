# ====================================================================================
# SynestheticCanvas/api-gateway – CMakeLists.txt
#
# This top-level build script configures, builds, tests and packages the
# “api-gateway” component of the SynestheticCanvas API Suite.
#
# Highlights
# ----------
# • Out-of-source, target-based CMake (>=3.20) with modern C standards (C17)
# • Automatic version detection from Git tags + “overridable” build timestamp
# • Strict compile flags + optional sanitizers           (ENABLE_SANITIZERS=ON)
# • Static analysis with clang-tidy & cppcheck           (ENABLE_ANALYSIS=ON)
# • Flexible dependency discovery (system, FetchContent, vendor fall-back)
# • Unit/Integration tests via CTest + Coverage          (ENABLE_COVERAGE=ON)
# • Install rules & CPACK packaging for DEB/RPM/TGZ
# • API gateway can be built as shared lib and CLI tool  (BUILD_CLI=ON)
# ====================================================================================

cmake_minimum_required(VERSION 3.20 FATAL_ERROR)
project(api_gateway
        VERSION 1.4.0                       # fallback version (overridden by git)
        DESCRIPTION "SynestheticCanvas GraphQL / REST API gateway"
        LANGUAGES C)

# -----------------------------------------------------------------------------
# Options
# -----------------------------------------------------------------------------
option(BUILD_SHARED_LIBS  "Build shared library instead of static" ON)
option(BUILD_CLI          "Build the standalone gateway executable" ON)
option(ENABLE_TESTS       "Build unit & integration tests"          ON)
option(ENABLE_SANITIZERS  "Enable address/undefined sanitizers"     OFF)
option(ENABLE_COVERAGE    "Enable coverage instrumentation"         OFF)
option(ENABLE_ANALYSIS    "Run static analysis tools at build time" OFF)

# -----------------------------------------------------------------------------
# Project version (prefer Git tags if available)
# -----------------------------------------------------------------------------
include(CheckIPOSupported)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)
include(CTest)

find_program(GIT_EXECUTABLE git)
if(GIT_EXECUTABLE)
    execute_process(
        COMMAND ${GIT_EXECUTABLE} describe --tags --abbrev=0
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        OUTPUT_VARIABLE _GIT_TAG
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET)
    if(_GIT_TAG)
        message(STATUS "Project version derived from git: ${_GIT_TAG}")
        set(PROJECT_VERSION "${_GIT_TAG}" CACHE STRING "Project version" FORCE)
    endif()
endif()

# -----------------------------------------------------------------------------
# Build type & default flags
# -----------------------------------------------------------------------------
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "RelWithDebInfo" CACHE STRING
        "Build type (Debug, Release, RelWithDebInfo, MinSizeRel)" FORCE)
endif()

set(C_API_STANDARD 17)
set(CMAKE_C_STANDARD ${C_API_STANDARD})
set(CMAKE_C_STANDARD_REQUIRED ON)

# Strict compilation flags
set(__WARN_FLAGS
    -Wall -Wextra -Wpedantic -Werror
    -Wshadow -Wconversion -Wdouble-promotion -Wformat=2
)
if(MSVC)
    add_compile_options(/W4 /WX)
else()
    add_compile_options(${__WARN_FLAGS})
endif()

# Optional sanitizers
if(ENABLE_SANITIZERS AND NOT MSVC)
    add_compile_options(-fsanitize=address,undefined)
    add_link_options    (-fsanitize=address,undefined)
endif()

# Coverage flags
if(ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(--coverage -O0)
    add_link_options(--coverage)
endif()

# -----------------------------------------------------------------------------
# External Dependencies
# -----------------------------------------------------------------------------
include(FetchContent)

# GraphQL C library (graphql-c)
FetchContent_Declare(
    graphql-c
    GIT_REPOSITORY https://github.com/graphql/libgraphqlparser.git
    GIT_TAG        v0.7.0
)
FetchContent_MakeAvailable(graphql-c)

# cJSON (lightweight JSON)
FetchContent_Declare(
    cjson
    GIT_REPOSITORY https://github.com/DaveGamble/cJSON.git
    GIT_TAG        v1.7.17
)
FetchContent_MakeAvailable(cjson)

# libuv for async I/O
find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBUV libuv REQUIRED)

# -------------------------------------------------------------------------
# Source files
# -------------------------------------------------------------------------
file(GLOB_RECURSE API_GATEWAY_SRC CONFIGURE_DEPENDS
     "src/*.c" "src/*.h" "include/*.h")

# Generate build timestamp
string(TIMESTAMP BUILD_TIMESTAMP "%Y-%m-%d %H:%M:%S")
add_compile_definitions(BUILD_TIMESTAMP=\"${BUILD_TIMESTAMP}\")

# -------------------------------------------------------------------------
# Library Target
# -------------------------------------------------------------------------
add_library(api_gateway ${API_GATEWAY_SRC})
add_library(SynestheticCanvas::api_gateway ALIAS api_gateway)

target_include_directories(api_gateway
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
        ${graphql-c_SOURCE_DIR}/src
        ${cjson_SOURCE_DIR}/include
        ${LIBUV_INCLUDE_DIRS}
)

target_link_libraries(api_gateway
    PUBLIC
        graphqlparser
        cjson
        ${LIBUV_LIBRARIES}
)

# LTO/IPO
check_ipo_supported(RESULT ipo_supported OUTPUT ipo_error)
if(ipo_supported)
    set_target_properties(api_gateway PROPERTIES INTERPROCEDURAL_OPTIMIZATION ON)
endif()

# -------------------------------------------------------------------------
# CLI Application Target
# -------------------------------------------------------------------------
if(BUILD_CLI)
    add_executable(api_gateway_cli src/main.c)
    target_link_libraries(api_gateway_cli PRIVATE api_gateway)
    set_target_properties(api_gateway_cli PROPERTIES OUTPUT_NAME "synesthetic-gw")
    install(TARGETS api_gateway_cli
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
endif()

# -------------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------------
if(ENABLE_TESTS)
    enable_testing()

    # FetchCriterion for lightweight unit tests
    FetchContent_Declare(
        criterion
        GIT_REPOSITORY https://github.com/Snaipe/Criterion.git
        GIT_TAG        v2.3.3
    )
    FetchContent_MakeAvailable(criterion)

    file(GLOB_RECURSE TEST_SOURCES CONFIGURE_DEPENDS "tests/*.c")
    add_executable(api_gateway_tests ${TEST_SOURCES})
    target_link_libraries(api_gateway_tests PRIVATE api_gateway criterion)

    add_test(NAME api_gateway_unit COMMAND api_gateway_tests)
endif()

# -------------------------------------------------------------------------
# Static Analysis
# -------------------------------------------------------------------------
if(ENABLE_ANALYSIS)
    find_program(CLANG_TIDY_EXE NAMES clang-tidy)
    if(CLANG_TIDY_EXE)
        set(CMAKE_C_CLANG_TIDY ${CLANG_TIDY_EXE})
    endif()

    find_program(CPPCHECK_EXE NAMES cppcheck)
    if(CPPCHECK_EXE)
        set(CMAKE_C_CPPCHECK
            ${CPPCHECK_EXE};
            --enable=warning,style,performance,portability;
            --error-exitcode=1;
            --inline-suppr
        )
    endif()
endif()

# -------------------------------------------------------------------------
# Installation
# -------------------------------------------------------------------------
set(INSTALL_CONFIGDIR ${CMAKE_INSTALL_LIBDIR}/cmake/${PROJECT_NAME})

install(TARGETS api_gateway
        EXPORT api_gatewayTargets
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

# Export target configuration for downstream projects
export(EXPORT api_gatewayTargets
       FILE "${CMAKE_CURRENT_BINARY_DIR}/api_gatewayTargets.cmake"
       NAMESPACE SynestheticCanvas::)

configure_package_config_file(
    cmake/api_gatewayConfig.cmake.in
    "${CMAKE_CURRENT_BINARY_DIR}/api_gatewayConfig.cmake"
    INSTALL_DESTINATION ${INSTALL_CONFIGDIR}
)
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/api_gatewayConfigVersion.cmake"
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion
)

install(EXPORT api_gatewayTargets
        FILE api_gatewayTargets.cmake
        NAMESPACE SynestheticCanvas::
        DESTINATION ${INSTALL_CONFIGDIR}
)
install(FILES
        "${CMAKE_CURRENT_BINARY_DIR}/api_gatewayConfig.cmake"
        "${CMAKE_CURRENT_BINARY_DIR}/api_gatewayConfigVersion.cmake"
        DESTINATION ${INSTALL_CONFIGDIR}
)

# -------------------------------------------------------------------------
# Packaging with CPack
# -------------------------------------------------------------------------
include(CPack)
set(CPACK_PACKAGE_NAME           "synestheticcanvas-api-gateway")
set(CPACK_PACKAGE_VENDOR         "SynestheticCanvas")
set(CPACK_PACKAGE_CONTACT        "dev@synestheticcanvas.io")
set(CPACK_PACKAGE_DESCRIPTION    "GraphQL/REST API gateway for SynestheticCanvas")
set(CPACK_PACKAGE_VERSION        ${PROJECT_VERSION})
set(CPACK_RESOURCE_FILE_LICENSE  "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE")
set(CPACK_RESOURCE_FILE_README   "${CMAKE_CURRENT_SOURCE_DIR}/README.md")
set(CPACK_DEBIAN_PACKAGE_SECTION "net")
set(CPACK_RPM_PACKAGE_LICENSE    "MIT")
# Force .tar.gz by default
set(CPACK_SOURCE_GENERATOR "TGZ")

# -------------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------------
message(STATUS "")
message(STATUS "Configuration Summary for api_gateway ${PROJECT_VERSION}")
message(STATUS "  Build type            : ${CMAKE_BUILD_TYPE}")
message(STATUS "  Install prefix        : ${CMAKE_INSTALL_PREFIX}")
message(STATUS "  Build lib as shared   : ${BUILD_SHARED_LIBS}")
message(STATUS "  Build CLI             : ${BUILD_CLI}")
message(STATUS "  Enable tests          : ${ENABLE_TESTS}")
message(STATUS "  Enable sanitizers     : ${ENABLE_SANITIZERS}")
message(STATUS "  Enable coverage       : ${ENABLE_COVERAGE}")
message(STATUS "  Enable static analysis: ${ENABLE_ANALYSIS}")
if(ipo_supported)
    message(STATUS "  IPO/LTO               : ENABLED")
else()
    message(STATUS "  IPO/LTO               : DISABLED (${ipo_error})")
endif()
message(STATUS "")