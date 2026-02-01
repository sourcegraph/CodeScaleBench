# --------------------------------------------------------------------------------------------------
#  CardioInsight360 – Unit & Integration Test Build Configuration
#  File: cardio_insight_360/tests/CMakeLists.txt
#
#  This CMake script configures the build for all test executables, integrates GoogleTest via
#  FetchContent when not supplied by the tool-chain, and registers tests with CTest.  The goal is to
#  offer a single, friction-less command (`ctest`) that exercises the entire CardioInsight360 stack
#  —from low-level signal parsers to the high-level ETL pipeline contracts.
#
#  Usage:
#    mkdir build && cd build
#    cmake -DENABLE_TEST_COVERAGE=ON -DENABLE_ASAN=ON ..
#    make -j && ctest --output-on-failure
#
#  Author: CardioInsight360 Engineering
# --------------------------------------------------------------------------------------------------

cmake_minimum_required(VERSION 3.16)
project(cardioinsight360_tests LANGUAGES CXX)

# --------------------------------------------------------------------------------------------------
#  Global build flags
# --------------------------------------------------------------------------------------------------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(ENABLE_ASAN           "Enable Address Sanitizer for test builds"             OFF)
option(ENABLE_UBSAN          "Enable Undefined Behavior Sanitizer for test builds"  OFF)
option(ENABLE_TEST_COVERAGE  "Enable GCOV/LCOV code-coverage instrumentation"       OFF)

# --------------------------------------------------------------------------------------------------
#  Append sanitizer/coverage flags if requested
# --------------------------------------------------------------------------------------------------
if (ENABLE_ASAN)
    message(STATUS "AddressSanitizer enabled")
    set(SANITIZER_FLAGS "-fsanitize=address -fno-omit-frame-pointer")
    add_compile_options(${SANITIZER_FLAGS})
    add_link_options(${SANITIZER_FLAGS})
endif()

if (ENABLE_UBSAN)
    message(STATUS "UBSan enabled")
    set(UBSAN_FLAGS "-fsanitize=undefined -fno-omit-frame-pointer")
    add_compile_options(${UBSAN_FLAGS})
    add_link_options(${UBSAN_FLAGS})
endif()

if (ENABLE_TEST_COVERAGE)
    if (CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        message(STATUS "Test coverage instrumentation enabled")
        add_compile_options(-O0 -g --coverage)
        add_link_options(--coverage)
    else()
        message(WARNING "Code coverage requested, but unsupported compiler: ${CMAKE_CXX_COMPILER_ID}")
    endif()
endif()

# --------------------------------------------------------------------------------------------------
#  Dependencies
# --------------------------------------------------------------------------------------------------
include(FetchContent)

# --- GoogleTest ---------------------------------------------------------------
# Use system-provided GTest when available; otherwise fetch a known-good release.
find_package(GTest QUIET)

if (NOT GTest_FOUND)
    message(STATUS "GoogleTest not found – fetching it via FetchContent")
    FetchContent_Declare(
        googletest
        URL https://github.com/google/googletest/archive/refs/tags/v1.14.0.zip
        URL_HASH SHA256=43a0c892b7ce0cb7da2340573184c8a2c65e7ec2fe9074f46d828c665c202be9
    )
    # Prevent GoogleTest from overriding compiler/linker flags
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
endif()

# --------------------------------------------------------------------------------------------------
#  Locate CardioInsight360 library targets from the parent project
# --------------------------------------------------------------------------------------------------
# We assume these targets are declared in the top-level CMakeLists.txt.
#   cardioinsight::core          – Core utilities (logging, common types)
#   cardioinsight::etl           – ETL pipeline components
#   cardioinsight::stream        – Streaming bus façade
#   cardioinsight::data_lake     – Data-lake abstraction layer
#   cardioinsight::validation    – Data-quality check policies
#   cardioinsight::domain        – Domain-model (signals, ontologies)
#
# If this file is included from an external test runner, ensure those targets are imported.
if (NOT TARGET cardioinsight::core)
    message(FATAL_ERROR "CardioInsight360 library targets not found. "
                        "Make sure you include this tests directory from the main build.")
endif()

enable_testing()

# --------------------------------------------------------------------------------------------------
#  Helper function to add tests uniformly
# --------------------------------------------------------------------------------------------------
function(add_c360_test TEST_NAME)
    # The first argument is the test name, the remaining arguments are source files.
    cmake_parse_arguments(ARGS "" "" "SRC" ${ARGN})
    add_executable(${TEST_NAME} ${ARGS_SRC})

    target_link_libraries(
        ${TEST_NAME}
        PRIVATE
            GTest::gtest GTest::gtest_main
            cardioinsight::core
            cardioinsight::etl
            cardioinsight::stream
            cardioinsight::data_lake
            cardioinsight::validation
            cardioinsight::domain
    )

    # Inject compile definitions for all tests, e.g., to activate mock flags.
    target_compile_definitions(${TEST_NAME} PRIVATE
        CI360_TEST_BUILD
    )

    # Treat warnings as errors in test builds to avoid silent failures
    if (CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(${TEST_NAME} PRIVATE -Wall -Wextra -Wpedantic -Werror)
    elseif (MSVC)
        target_compile_options(${TEST_NAME} PRIVATE /W4 /WX)
    endif()

    add_test(NAME ${TEST_NAME} COMMAND ${TEST_NAME})
endfunction()

# --------------------------------------------------------------------------------------------------
#  Unit-tests — fine-grained verification of components
# --------------------------------------------------------------------------------------------------
set(C360_UNIT_TEST_SOURCES
    unit/etl_pipeline_tests.cpp
    unit/validation_rule_tests.cpp
    unit/strategy_pattern_tests.cpp
    unit/streaming_bus_tests.cpp
    unit/data_lake_tests.cpp
)

foreach(_src IN LISTS C360_UNIT_TEST_SOURCES)
    get_filename_component(_name "${_src}" NAME_WE)
    add_c360_test("${_name}" SRC "${_src}")
endforeach()

# --------------------------------------------------------------------------------------------------
#  Integration tests — cross-component boundaries
# --------------------------------------------------------------------------------------------------
set(C360_INTEGRATION_TEST_SOURCES
    integration/real_time_alerting_tests.cpp
    integration/hipaa_encryption_roundtrip_tests.cpp
)

foreach(_src IN LISTS C360_INTEGRATION_TEST_SOURCES)
    get_filename_component(_name "${_src}" NAME_WE)
    set(_target_name "integration_${_name}")
    add_c360_test("${_target_name}" SRC "${_src}")
endforeach()

# --------------------------------------------------------------------------------------------------
#  Benchmarking (optional) ------------------------------------------------------
#  We only build benchmarks when the main project enabled them via ENABLE_BENCHMARKS.
# --------------------------------------------------------------------------------------------------
if (DEFINED ENABLE_BENCHMARKS AND ENABLE_BENCHMARKS)
    find_package(benchmark QUIET) # Google Benchmark
    if (benchmark_FOUND)
        add_executable(performance_signal_transform_bench bench/signal_transform_bench.cpp)
        target_link_libraries(performance_signal_transform_bench PRIVATE
            benchmark::benchmark
            cardioinsight::etl
            cardioinsight::core
            cardioinsight::domain
        )
    else()
        message(WARNING "Google Benchmark requested but not found; skipping benchmarks.")
    endif()
endif()

# --------------------------------------------------------------------------------------------------
#  Coverage Target -------------------------------------------------------------
#  Generates a coverage report in `build/coverage`.
# --------------------------------------------------------------------------------------------------
if (ENABLE_TEST_COVERAGE AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    find_program(LCOV_EXEC lcov)
    find_program(GENHTML_EXEC genhtml)

    if (LCOV_EXEC AND GENHTML_EXEC)
        add_custom_target(coverage
            COMMENT "Generate code-coverage report with lcov/genhtml"
            COMMAND ${LCOV_EXEC} --directory . --capture --output-file coverage.info
            COMMAND ${LCOV_EXEC} --remove coverage.info '/usr/*' '*/extern/*' --output-file coverage.info
            COMMAND ${GENHTML_EXEC} coverage.info --output-directory coverage
            WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
            DEPENDS ${C360_UNIT_TEST_SOURCES} ${C360_INTEGRATION_TEST_SOURCES}
        )
    else()
        message(WARNING "Coverage tools (lcov/genhtml) not found; skipping coverage target.")
    endif()
endif()

# --------------------------------------------------------------------------------------------------
#  Packaging Test Artifacts -----------------------------------------------------
#  When the main project is packaged, include compiled tests as optional components to aid
#  downstream integrators during validation.
# --------------------------------------------------------------------------------------------------
include(CPack)  # Provided by top-level, but safe to call here as no-op if already included.

# EOF ----------------------------------------------------------------------------------------------
