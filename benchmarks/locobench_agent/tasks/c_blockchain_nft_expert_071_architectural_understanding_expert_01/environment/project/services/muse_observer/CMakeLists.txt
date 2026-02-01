cmake_minimum_required(VERSION 3.18)

# ------------------------------------------------------------------------------
#  HoloCanvas :: Muse Observer Micro-Service
#
#  Production-grade CMake build script.
# ------------------------------------------------------------------------------

project(muse_observer
        VERSION 1.4.0
        DESCRIPTION "Observer-Pattern micro-service that reacts to artistic triggers and mutates NFT state."
        LANGUAGES C)

# ------------------------------------------------------------------------------
#  Build Options
# ------------------------------------------------------------------------------
option(BUILD_SHARED_LIBS     "Build shared instead of static binaries" ON)
option(BUILD_TESTS           "Build unit/integration tests"            ON)
option(ENABLE_SANITIZER      "Enable address/undefined sanitizers"     OFF)
option(ENABLE_CLANG_TIDY     "Enable clang-tidy static analysis"       OFF)
option(ENABLE_COVERAGE       "Enable code-coverage flags"              OFF)

# ------------------------------------------------------------------------------
#  Toolchain & Standards
# ------------------------------------------------------------------------------
set(CMAKE_C_STANDARD          17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(ENABLE_CLANG_TIDY)
    find_program(CLANG_TIDY_EXE NAMES clang-tidy)
    if(CLANG_TIDY_EXE)
        message(STATUS "clang-tidy found: ${CLANG_TIDY_EXE}")
        set(CMAKE_C_CLANG_TIDY "${CLANG_TIDY_EXE};-quiet")
    endif()
endif()

# ------------------------------------------------------------------------------
#  Build Flags
# ------------------------------------------------------------------------------
if(NOT MSVC)
    add_compile_options(
        -Wall -Wextra -Wpedantic
        $<$<CONFIG:Debug>:-Og -g>
        $<$<CONFIG:Release>:-O3>
    )

    # Treat warnings as errors in CI/release builds
    if(DEFINED ENV{CI} OR CMAKE_BUILD_TYPE STREQUAL "Release")
        add_compile_options(-Werror)
    endif()

    if(ENABLE_SANITIZER)
        add_compile_options(-fsanitize=address,undefined)
        add_link_options(-fsanitize=address,undefined)
    endif()

    if(ENABLE_COVERAGE AND CMAKE_BUILD_TYPE STREQUAL "Debug")
        add_compile_options(--coverage)
        add_link_options(--coverage)
    endif()
endif()

# ------------------------------------------------------------------------------
#  Dependencies
# ------------------------------------------------------------------------------
include(FindPkgConfig)
pkg_check_modules(RDKAFKA       REQUIRED IMPORTED_TARGET rdkafka>=1.8)
pkg_check_modules(GRPC_C        REQUIRED IMPORTED_TARGET grpc)
pkg_check_modules(PROTOBUF_C    REQUIRED IMPORTED_TARGET libprotobuf-c)
find_package(OpenSSL            REQUIRED)

# Optional testing dependency
if(BUILD_TESTS)
    find_package(CMocka 1.1.5 REQUIRED)
endif()

# ------------------------------------------------------------------------------
#  Version Header (generated)
# ------------------------------------------------------------------------------
configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/include/muse/version.h.in
    ${CMAKE_CURRENT_BINARY_DIR}/generated/version.h
    @ONLY
)

# ------------------------------------------------------------------------------
#  Source Files
# ------------------------------------------------------------------------------
file(GLOB_RECURSE MUSE_OBSERVER_SOURCES CONFIGURE_DEPENDS
    "src/*.c"
    "include/muse/*.h"
)

add_library(muse_observer ${MUSE_OBSERVER_SOURCES})

target_include_directories(muse_observer
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/generated>
        $<INSTALL_INTERFACE:include>
    PRIVATE
        src
)

target_link_libraries(muse_observer
    PUBLIC
        PkgConfig::RDKAFKA
        PkgConfig::GRPC_C
        PkgConfig::PROTOBUF_C
        OpenSSL::SSL
        OpenSSL::Crypto
)

set_target_properties(muse_observer PROPERTIES
    VERSION     ${PROJECT_VERSION}
    SOVERSION   ${PROJECT_VERSION_MAJOR}
    OUTPUT_NAME "muse_observer"
)

# ------------------------------------------------------------------------------
#  Executable
# ------------------------------------------------------------------------------
add_executable(muse_observerd src/main.c)
target_link_libraries(muse_observerd PRIVATE muse_observer)

# ------------------------------------------------------------------------------
#  Unit / Integration Tests
# ------------------------------------------------------------------------------
if(BUILD_TESTS)
    enable_testing()
    add_executable(muse_observer_tests
        tests/test_event_dispatch.c
        tests/test_strategy_loader.c
    )
    target_link_libraries(muse_observer_tests
        PRIVATE
            muse_observer
            CMocka::CMocka
    )
    add_test(NAME muse_observer_all COMMAND muse_observer_tests)
endif()

# ------------------------------------------------------------------------------
#  Installation
# ------------------------------------------------------------------------------
include(GNUInstallDirs)

install(TARGETS muse_observer muse_observerd
        EXPORT  muse_observerTargets
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})

install(DIRECTORY include/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
        FILES_MATCHING PATTERN "*.h")

install(EXPORT muse_observerTargets
        FILE muse_observerTargets.cmake
        NAMESPACE holo_canvas::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/muse_observer)

# ------------------------------------------------------------------------------
#  Packaging (CPack)
# ------------------------------------------------------------------------------
include(CPack)

set(CPACK_PACKAGE_VENDOR       "HoloCanvas")
set(CPACK_PACKAGE_CONTACT      "dev@holocanvas.art")
set(CPACK_PACKAGE_VERSION      ${PROJECT_VERSION})
set(CPACK_PACKAGE_DESCRIPTION  "Muse Observer micro-service for the HoloCanvas generative NFT blockchain.")
set(CPACK_GENERATOR            "TGZ;ZIP")

# ------------------------------------------------------------------------------
#  Summary
# ------------------------------------------------------------------------------
message(STATUS "--------------------------------------------------------")
message(STATUS "Muse Observer Configuration")
message(STATUS "  Version            : ${PROJECT_VERSION}")
message(STATUS "  Build Type         : ${CMAKE_BUILD_TYPE}")
message(STATUS "  Shared Libraries   : ${BUILD_SHARED_LIBS}")
message(STATUS "  Tests Enabled      : ${BUILD_TESTS}")
message(STATUS "  Sanitizers Enabled : ${ENABLE_SANITIZER}")
message(STATUS "  Coverage Enabled   : ${ENABLE_COVERAGE}")
message(STATUS "--------------------------------------------------------")