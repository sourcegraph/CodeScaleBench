```cmake
#==============================================================
#  CardioInsight360 – Unified Healthcare Analytics Engine
#
#  Top-level CMakeLists.txt
#  -----------------------------------------------------------
#  This file orchestrates the build of the CardioInsight360
#  monolithic binary and its optional sub-components.  The
#  project is intentionally kept monolithic to simplify FDA/
#  CE-mark audits and healthcare change-control processes.
#
#  Author: CardioInsight Engineering
#  License: Proprietary – All Rights Reserved
#==============================================================

cmake_minimum_required(VERSION 3.17)

#--------------------------------------------------------------
#  Project meta-data
#--------------------------------------------------------------
project(
    CardioInsight360
    VERSION 1.4.2
    LANGUAGES CXX
    DESCRIPTION "Unified Healthcare Analytics Engine for high-volume physiological and operational data"
)

#--------------------------------------------------------------
#  Build options
#--------------------------------------------------------------
option(CI360_BUILD_TESTS         "Build unit / integration tests"              ON)
option(CI360_ENABLE_SANITIZERS   "Enable Compile-time Sanitizers in Debug"     OFF)
option(CI360_ENABLE_LTO          "Enable Link-Time-Optimization (Release)"     ON)
option(CI360_ENABLE_COVERAGE     "Enable GCOV/LCOV code-coverage (Debug)"      OFF)
option(CI360_WARNINGS_AS_ERRORS  "Treat compiler warnings as errors"           OFF)
option(CI360_BUILD_SHARED_LIBS   "Build shared instead of static libs"         OFF)

#--------------------------------------------------------------
#  Globals
#--------------------------------------------------------------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if (NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING
        "Choose the type of build (Debug|Release|RelWithDebInfo|MinSizeRel)." FORCE)
endif()

#--------------------------------------------------------------
#  Compiler flags & warnings
#--------------------------------------------------------------
include(CheckIPOSupported)
if (CI360_ENABLE_LTO)
    check_ipo_supported(RESULT LTO_SUPPORTED OUTPUT LTO_OUTPUT)
    if (LTO_SUPPORTED)
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
    else()
        message(WARNING "IPO/LTO not supported: ${LTO_OUTPUT}")
    endif()
endif()

if (MSVC)
    add_compile_options(/permissive- /W4)
    if (CI360_WARNINGS_AS_ERRORS)
        add_compile_options(/WX)
    endif()
else()
    add_compile_options(
        -Wall -Wextra -Wshadow -Wnon-virtual-dtor -pedantic
        $<$<CONFIG:Release>:-O3>
    )
    if (CI360_WARNINGS_AS_ERRORS)
        add_compile_options(-Werror)
    endif()

    if (CI360_ENABLE_SANITIZERS AND CMAKE_BUILD_TYPE STREQUAL "Debug")
        add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
        link_libraries(-fsanitize=address,undefined)
    endif()

    if (CI360_ENABLE_COVERAGE AND CMAKE_BUILD_TYPE STREQUAL "Debug")
        add_compile_options(--coverage)
        link_libraries(--coverage)
    endif()
endif()

#--------------------------------------------------------------
#  Dependencies
#--------------------------------------------------------------
include(FetchContent)

# Intel TBB ----------------------------------------------------
find_package(TBB REQUIRED COMPONENTS tbb)

# Apache Arrow + Parquet --------------------------------------
find_package(Arrow REQUIRED)
find_package(Parquet REQUIRED)

# librdkafka ---------------------------------------------------
find_package(RdKafka REQUIRED)

# OpenSSL ------------------------------------------------------
find_package(OpenSSL REQUIRED)

# Protobuf (for HL7/FHIR proto stubs) --------------------------
find_package(Protobuf REQUIRED)

# Threads (Portable) ------------------------------------------
find_package(Threads REQUIRED)

#--------------------------------------------------------------
#  Source Layout
#--------------------------------------------------------------
# The actual code resides in sub-directories located under
#   modules/
# Each module builds an Object Library which is later linked
# into the monolithic executable `cardioinsight360`.
#
#   modules/core        – Domain models, utilities, error-handling
#   modules/io          – HL7/FHIR ingestion, data-lake façade
#   modules/pipeline    – ETL & parallel-processing abstractions
#   modules/services    – Scheduler, visualization, recovery
#   modules/monitoring  – Observer pattern + metrics
#   modules/cli         – Command-line front-end
#
# The individual module CMakeLists.txt files are responsible
# for declaring their own sources and include directories.
#--------------------------------------------------------------
add_subdirectory(modules/core)
add_subdirectory(modules/io)
add_subdirectory(modules/pipeline)
add_subdirectory(modules/services)
add_subdirectory(modules/monitoring)
add_subdirectory(modules/cli)

#--------------------------------------------------------------
#  Monolithic Executable
#--------------------------------------------------------------
add_executable(cardioinsight360
    $<TARGET_OBJECTS:ci360_core>
    $<TARGET_OBJECTS:ci360_io>
    $<TARGET_OBJECTS:ci360_pipeline>
    $<TARGET_OBJECTS:ci360_services>
    $<TARGET_OBJECTS:ci360_monitoring>
    $<TARGET_OBJECTS:ci360_cli>
)

target_link_libraries(cardioinsight360
    PRIVATE
        TBB::tbb
        Arrow::arrow_shared
        Parquet::parquet_shared
        RdKafka::rdkafka++
        OpenSSL::SSL
        OpenSSL::Crypto
        Protobuf::libprotobuf
        Threads::Threads
)

target_compile_definitions(cardioinsight360
    PRIVATE
        $<$<CONFIG:Debug>:CI360_DEBUG_BUILD>
        PROJECT_VERSION="${PROJECT_VERSION}"
)

# Expose public headers for IDEs
target_include_directories(cardioinsight360
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

#--------------------------------------------------------------
#  Tests
#--------------------------------------------------------------
if (CI360_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()

#--------------------------------------------------------------
#  Packaging / Installation
#--------------------------------------------------------------
include(GNUInstallDirs)

install(TARGETS cardioinsight360
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install(DIRECTORY configs/
    DESTINATION ${CMAKE_INSTALL_DATADIR}/cardioinsight360/configs
    FILES_MATCHING PATTERN "*.json"
)

configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/cmake/CardioInsight360Config.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/CardioInsight360Config.cmake
    @ONLY
)

install(FILES
    "${CMAKE_CURRENT_BINARY_DIR}/CardioInsight360Config.cmake"
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/CardioInsight360
)

#--------------------------------------------------------------
#  CPack – platform-agnostic packaging
#--------------------------------------------------------------
include(CPack)
set(CPACK_PACKAGE_NAME "CardioInsight360")
set(CPACK_PACKAGE_VENDOR "CardioInsight Engineering")
set(CPACK_PACKAGE_CONTACT "support@cardioinsight.ai")
set(CPACK_PACKAGE_VERSION ${PROJECT_VERSION})
set(CPACK_RESOURCE_FILE_LICENSE "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE")
set(CPACK_SOURCE_IGNORE_FILES /.git/;.vscode/;build/;cmake-build*/)

# Deb/RPM specifics
set(CPACK_GENERATOR "TGZ;ZIP")
if(UNIX AND NOT APPLE)
    list(APPEND CPACK_GENERATOR "DEB" "RPM")
    set(CPACK_DEBIAN_PACKAGE_MAINTAINER "CardioInsight Engineering")
    set(CPACK_DEBIAN_PACKAGE_SHLIBDEPS ON)
    set(CPACK_RPM_PACKAGE_LICENSE "Proprietary")
endif()

#--------------------------------------------------------------
#  Friendly summary
#--------------------------------------------------------------
message(STATUS "--------------------------------------------------")
message(STATUS " CardioInsight360 build configuration")
message(STATUS "  - Version            : ${PROJECT_VERSION}")
message(STATUS "  - CMake Build Type   : ${CMAKE_BUILD_TYPE}")
message(STATUS "  - Tests Enabled      : ${CI360_BUILD_TESTS}")
message(STATUS "  - Sanitizers Enabled : ${CI360_ENABLE_SANITIZERS}")
message(STATUS "  - LTO Enabled        : ${CI360_ENABLE_LTO}")
message(STATUS "  - Coverage Enabled   : ${CI360_ENABLE_COVERAGE}")
message(STATUS "  - Warnings as Errors : ${CI360_WARNINGS_AS_ERRORS}")
message(STATUS "--------------------------------------------------")
```