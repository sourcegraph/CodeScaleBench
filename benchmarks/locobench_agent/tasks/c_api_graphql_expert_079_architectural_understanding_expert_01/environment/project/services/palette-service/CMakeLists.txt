cmake_minimum_required(VERSION 3.18)

#------------------------------------------------------------------------------
# Project definition
#------------------------------------------------------------------------------
project(palette-service
        VERSION 1.2.0
        DESCRIPTION "SynestheticCanvas – Palette micro-service"
        LANGUAGES C)

#------------------------------------------------------------------------------
# User-visible build options
#------------------------------------------------------------------------------
option(PALETTE_ENABLE_LTO        "Enable link-time optimisation"          ON)
option(PALETTE_ENABLE_SANITIZER  "Build with address/undefined sanitiser" OFF)
option(PALETTE_BUILD_TESTS       "Build unit/integ tests"                 ON)
option(PALETTE_ENABLE_COVERAGE   "Enable coverage flags (Debug only)"     OFF)

#------------------------------------------------------------------------------
# Dependencies (✨ switch to vcpkg/Conan if you prefer)
#------------------------------------------------------------------------------
find_package(Threads REQUIRED)

# cJSON is used for the REST + GraphQL fallback payloads
find_package(cJSON 1.7 REQUIRED)

# loguru provides lightweight, colourised logging
find_package(loguru 2.1 REQUIRED)

#------------------------------------------------------------------------------
# Generate a build-time configuration header (contains git SHA, version, etc.)
#------------------------------------------------------------------------------
include(CheckIncludeFile)
include(CheckSymbolExists)

# Attempt to extract git metadata, silently ignore if not a git workspace
execute_process(
    COMMAND git rev-parse --short HEAD
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    RESULT_VARIABLE _git_result
    OUTPUT_VARIABLE GIT_COMMIT_SHA
    OUTPUT_STRIP_TRAILING_WHITESPACE)

if(NOT _git_result EQUAL 0)
    set(GIT_COMMIT_SHA "UNKNOWN")
endif()

configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/cmake/config.h.in
    ${CMAKE_CURRENT_BINARY_DIR}/generated/config.h
    @ONLY)

# Make generated headers accessible to all targets
include_directories(${CMAKE_CURRENT_BINARY_DIR}/generated)

#------------------------------------------------------------------------------
# Compiler flags and warnings
#------------------------------------------------------------------------------
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Common warnings (platform/compiler agnostic)
if (MSVC)
    add_compile_options(/W4 /permissive-)
    add_compile_definitions(_CRT_SECURE_NO_WARNINGS)
else()
    add_compile_options(-Wall -Wextra -Wpedantic -Werror
                        -fvisibility=hidden
                        $<$<CONFIG:Debug>:-O0 -g>)
endif()

# Sanitizers
if(PALETTE_ENABLE_SANITIZER AND NOT MSVC)
    add_compile_options(-fsanitize=address -fsanitize=undefined)
    add_link_options   (-fsanitize=address -fsanitize=undefined)
endif()

# Coverage
if(PALETTE_ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    if(NOT CMAKE_BUILD_TYPE STREQUAL "Debug")
        message(WARNING "Coverage requested but build type is not Debug; enabling Debug")
        set(CMAKE_BUILD_TYPE "Debug" CACHE STRING "" FORCE)
    endif()
    add_compile_options(--coverage)
    add_link_options(--coverage)
endif()

# LTO
include(CheckIPOSupported)
if(PALETTE_ENABLE_LTO)
    check_ipo_supported(RESULT lto_supported OUTPUT ipo_out)
    if(lto_supported)
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)
    else()
        message(WARNING "IPO/LTO not supported: ${ipo_out}")
    endif()
endif()

#------------------------------------------------------------------------------
# Source layout
#------------------------------------------------------------------------------
file(GLOB_RECURSE PALETTE_CORE_SOURCES CONFIGURE_DEPENDS
     "${CMAKE_CURRENT_SOURCE_DIR}/src/core/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/src/http/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/src/graphql/*.c")

file(GLOB PALETTE_PUBLIC_HEADERS
     "${CMAKE_CURRENT_SOURCE_DIR}/include/palette/*.h")

#------------------------------------------------------------------------------
# Library target
#------------------------------------------------------------------------------
add_library(palette-core STATIC
            ${PALETTE_CORE_SOURCES}
            ${PALETTE_PUBLIC_HEADERS})

target_include_directories(palette-core
        PUBLIC
            $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
            $<INSTALL_INTERFACE:include>)

target_link_libraries(palette-core
        PUBLIC
            Threads::Threads
            cJSON::cJSON
            loguru::loguru)

target_compile_definitions(palette-core
        PRIVATE
            PALETTE_BUILD_INTERNAL
        PUBLIC
            $<BUILD_INTERFACE:PALETTE_VERSION=\"${PROJECT_VERSION}\">
            $<BUILD_INTERFACE:PALETTE_GIT_SHA=\"${GIT_COMMIT_SHA}\">)

set_target_properties(palette-core PROPERTIES
                      VERSION     ${PROJECT_VERSION}
                      SOVERSION   ${PROJECT_VERSION_MAJOR})

#------------------------------------------------------------------------------
# Executable (service entry point)
#------------------------------------------------------------------------------
add_executable(palette-service
               src/main.c)

target_link_libraries(palette-service PRIVATE palette-core)

#------------------------------------------------------------------------------
# Tests
#------------------------------------------------------------------------------
if(PALETTE_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()

#------------------------------------------------------------------------------
# Installation
#------------------------------------------------------------------------------
include(GNUInstallDirs)

install(TARGETS palette-core
        EXPORT  palette-coreTargets
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        INCLUDES DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

install(TARGETS palette-service
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

install(DIRECTORY include/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

install(EXPORT palette-coreTargets
        FILE   palette-coreTargets.cmake
        NAMESPACE SynestheticCanvas::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/palette-core)

#------------------------------------------------------------------------------
# Packaging (CPack)
#------------------------------------------------------------------------------
include(CPack)

set(CPACK_PACKAGE_NAME            "palette-service")
set(CPACK_PACKAGE_VENDOR          "SynestheticCanvas")
set(CPACK_PACKAGE_DESCRIPTION     "Palette micro-service for SynestheticCanvas")
set(CPACK_PACKAGE_VERSION         ${PROJECT_VERSION})
set(CPACK_SOURCE_GENERATOR        "TGZ")
set(CPACK_PACKAGE_CONTACT         "dev@synestheticcanvas.io")
set(CPACK_DEBIAN_PACKAGE_MAINTAINER "SynestheticCanvas")
set(CPACK_DEBIAN_PACKAGE_SECTION  "graphics")

#------------------------------------------------------------------------------
# Summary helper
#------------------------------------------------------------------------------
message(STATUS "")
message(STATUS "--------------------------------------------------------")
message(STATUS "Palette-service build configuration")
message(STATUS "  Git SHA          : ${GIT_COMMIT_SHA}")
message(STATUS "  Build type       : ${CMAKE_BUILD_TYPE}")
message(STATUS "  Sanitizer        : ${PALETTE_ENABLE_SANITIZER}")
message(STATUS "  Coverage         : ${PALETTE_ENABLE_COVERAGE}")
message(STATUS "  LTO              : ${PALETTE_ENABLE_LTO}")
message(STATUS "  Tests enabled    : ${PALETTE_BUILD_TESTS}")
message(STATUS "--------------------------------------------------------")
message(STATUS "")