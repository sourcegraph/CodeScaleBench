cmake_minimum_required(VERSION 3.20)

# ==================================================================================
#  MosaicBoard Studio – Tests
#  CMake configuration for unit / integration tests.
# ==================================================================================
project(MosaicBoardStudioTests LANGUAGES CXX)

include(CTest)           # Brings add_test(), enable_testing() …
include(FetchContent)    # Used to download GoogleTest if not provided.

# ------------------------------------------------------------------------------
# Options
# ------------------------------------------------------------------------------
option(MOSAIC_ENABLE_SANITIZERS "Compile with address/UB sanitizers" OFF)
option(MOSAIC_BUILD_COVERAGE    "Compile with coverage information"  OFF)
option(MOSAIC_USE_SYSTEM_GTEST  "Use a system-installed GoogleTest"  OFF)

# ------------------------------------------------------------------------------
# Build type & C++ standard
# ------------------------------------------------------------------------------
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Debug CACHE STRING
        "Choose the build type (Debug, Release, RelWithDebInfo, MinSizeRel)" FORCE)
    message(STATUS "Defaulting to Debug build.")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ------------------------------------------------------------------------------
# Compiler warnings / errors
# ------------------------------------------------------------------------------
if(MSVC)
    add_compile_options(/W4 /WX)
else()
    add_compile_options(-Wall -Wextra -Wpedantic -Werror)
endif()

# ------------------------------------------------------------------------------
# Sanitizers
# ------------------------------------------------------------------------------
if(MOSAIC_ENABLE_SANITIZERS AND NOT MSVC)
    message(STATUS "Building with sanitizers enabled.")
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
    add_link_options   (-fsanitize=address,undefined)
endif()

# ------------------------------------------------------------------------------
# Coverage
# ------------------------------------------------------------------------------
if(MOSAIC_BUILD_COVERAGE AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    message(STATUS "Building with coverage flags.")
    add_compile_options(--coverage -O0)
    add_link_options(--coverage)
endif()

# ------------------------------------------------------------------------------
# GoogleTest
# ------------------------------------------------------------------------------
if(MOSAIC_USE_SYSTEM_GTEST)
    find_package(GTest REQUIRED)
else()
    set(FETCHCONTENT_QUIET ON)
    FetchContent_Declare(
        googletest
        GIT_REPOSITORY https://github.com/google/googletest.git
        GIT_TAG        v1.14.0
    )
    # Avoid overriding parent's CRT settings on Windows
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
endif()

enable_testing()

# ------------------------------------------------------------------------------
# Collect test sources
# ------------------------------------------------------------------------------
file(GLOB_RECURSE MOSAIC_TEST_SOURCES CONFIGURE_DEPENDS
     ${CMAKE_CURRENT_SOURCE_DIR}/*_test.cpp
)

add_executable(mosaic_tests
    ${MOSAIC_TEST_SOURCES}
)

# ------------------------------------------------------------------------------
# Link against the main library target (defined in the root project)
# ------------------------------------------------------------------------------
if(TARGET mosaic-core)
    target_link_libraries(mosaic_tests PRIVATE mosaic-core)
else()
    message(WARNING
        "Target 'mosaic-core' was not found. "
        "Tests will be compiled without linking to the core library. "
        "Ensure the library target name matches."
    )
endif()

target_link_libraries(mosaic_tests PRIVATE
    GTest::gtest
    GTest::gmock
    GTest::gtest_main
)

# Include public headers from the main project
target_include_directories(mosaic_tests PRIVATE
    ${PROJECT_SOURCE_DIR}/../src    # Adjust if your headers live elsewhere
)

# Enable test-specific macros
target_compile_definitions(mosaic_tests PRIVATE MOSAIC_TESTING=1)

# Ensure symbols are exported for dynamic libraries on *nix
if(NOT WIN32)
    target_link_options(mosaic_tests PRIVATE "-Wl,--no-as-needed")
endif()

# ------------------------------------------------------------------------------
# Test discovery
# ------------------------------------------------------------------------------
include(GoogleTest)
gtest_discover_tests(mosaic_tests
    WORKING_DIRECTORY ${CMAKE_RUNTIME_OUTPUT_DIRECTORY}
    PROPERTIES VS_DEBUGGER_WORKING_DIRECTORY "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
)

# ------------------------------------------------------------------------------
# Coverage target
# ------------------------------------------------------------------------------
if(MOSAIC_BUILD_COVERAGE AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    find_program(LCOV_EXECUTABLE   lcov)
    find_program(GENHTML_EXECUTABLE genhtml)

    if(LCOV_EXECUTABLE AND GENHTML_EXECUTABLE)
        add_custom_target(coverage
            COMMENT "Generating code-coverage report."
            WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
            COMMAND ${LCOV_EXECUTABLE} --directory . --capture --output-file coverage.info
            COMMAND ${LCOV_EXECUTABLE} --remove coverage.info '/usr/*' '${CMAKE_BINARY_DIR}/_deps/*' --output-file coverage.info.cleaned
            COMMAND ${GENHTML_EXECUTABLE} coverage.info.cleaned --output-directory coverage_report
            COMMAND ${CMAKE_COMMAND} -E echo "Coverage report generated at: ${CMAKE_BINARY_DIR}/coverage_report/index.html"
            DEPENDS mosaic_tests
        )
    else()
        message(WARNING "lcov or genhtml not found; coverage target will not be generated.")
    endif()
endif()