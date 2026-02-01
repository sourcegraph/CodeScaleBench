cmake_minimum_required(VERSION 3.20)

#
#  ███    ███  ██████   █████  ███████  █████   ██████  ██████  ██████
#  ████  ████ ██    ██ ██   ██ ██      ██   ██ ██      ██    ██ ██   ██
#  ██ ████ ██ ██    ██ ███████ ███████ ███████ ██      ██    ██ ██████
#  ██  ██  ██ ██    ██ ██   ██      ██ ██   ██ ██      ██    ██ ██   ██
#  ██      ██  ██████  ██   ██ ███████ ██   ██  ██████  ██████  ██   ██
#
#  MosaicBoard Studio – root build configuration
#

#--------------------------------------------------------------------------------------------------
# Project declaration
#--------------------------------------------------------------------------------------------------
project(MosaicBoardStudio
        VERSION 1.2.0
        DESCRIPTION "A plugin-based C++ web-dashboard platform for dynamic, real-time data visualisation"
        LANGUAGES CXX)

#--------------------------------------------------------------------------------------------------
# Build options
#--------------------------------------------------------------------------------------------------
option(MOSAIC_BUILD_TESTS        "Build unit & integration tests"                 ON)
option(MOSAIC_BUILD_EXAMPLES     "Build showcase dashboards (examples)"           ON)
option(MOSAIC_BUILD_PLUGINS      "Build bundled first-party tiles/plugins"        ON)
option(MOSAIC_ENABLE_LTO         "Enable Inter-Procedural Optimisation (LTO)"     ON)
option(MOSAIC_ENABLE_SANITIZERS  "Enable runtime sanitizers (Address/UB/etc.)"    OFF)
option(MOSAIC_WARNINGS_AS_ERRORS "Treat compiler warnings as errors"              OFF)

#--------------------------------------------------------------------------------------------------
# Toolchain & compile flags
#--------------------------------------------------------------------------------------------------
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED YES)
set(CMAKE_CXX_EXTENSIONS NO)

# Default build type
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# Compiler warnings
if(MSVC)
    add_compile_options(/W4 /permissive-)
else()
    add_compile_options(-Wall -Wextra -Wpedantic)
    if(MOSAIC_WARNINGS_AS_ERRORS)
        add_compile_options(-Werror)
    endif()
endif()

# Sanitizers (GCC/Clang)
if(MOSAIC_ENABLE_SANITIZERS AND NOT MSVC)
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
    add_link_options  (-fsanitize=address,undefined)
endif()

# Inter-Procedural Optimisation / LTO
include(CheckIPOSupported)
if(MOSAIC_ENABLE_LTO)
    check_ipo_supported(RESULT LTO_SUPPORTED OUTPUT LTO_OUTPUT)
    if(LTO_SUPPORTED)
        message(STATUS "IPO / LTO enabled")
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)
    else()
        message(WARNING "IPO / LTO not supported: ${LTO_OUTPUT}")
    endif()
endif()

#--------------------------------------------------------------------------------------------------
# Dependency manager (CPM.cmake) ---------------------------------------------------------------
#--------------------------------------------------------------------------------------------------
include(FetchContent)
FetchContent_Declare(
    cpm
    GIT_REPOSITORY https://github.com/cpm-cmake/CPM.cmake.git
    GIT_TAG origin/master
)
FetchContent_MakeAvailable(cpm)

# Wrapper around CPMAddPackage to ensure consistent settings
macro(mosaic_dependency)
    CPMAddPackage(${ARGN})
endmacro()

# Third-party libraries --------------------------------------------------------------------------
mosaic_dependency(
    NAME           nlohmann_json
    GITHUB_REPOSITORY nlohmann/json
    VERSION        3.11.2
    OPTIONS "JSON_BuildTests OFF"
)

mosaic_dependency(
    NAME           spdlog
    GITHUB_REPOSITORY gabime/spdlog
    VERSION        1.11.0
    OPTIONS        "SPDLOG_BUILD_TESTS OFF"
                   "SPDLOG_BUILD_EXAMPLES OFF"
)

mosaic_dependency(
    NAME           websocketpp
    GITHUB_REPOSITORY zaphoyd/websocketpp
    GIT_TAG        0.8.2
    OPTIONS        "WEBSOCKETPP_BUILD_EXAMPLES OFF"
                   "WEBSOCKETPP_BUILD_TESTS OFF"
)

mosaic_dependency(
    NAME           sqlite_modern_cpp
    GITHUB_REPOSITORY SqliteModernCpp/sqlite_modern_cpp
    GIT_TAG        master
    OPTIONS        "SQLITE_MODERN_CPP_ENABLE_TESTS OFF"
)

mosaic_dependency(
    NAME           jwt-cpp
    GITHUB_REPOSITORY Thalhammer/jwt-cpp
    VERSION        0.6.0
    OPTIONS        "JWT_CPP_BUILD_EXAMPLES OFF"
                   "JWT_CPP_BUILD_TESTS OFF"
)

find_package(OpenSSL REQUIRED)
find_package(Threads REQUIRED)

#--------------------------------------------------------------------------------------------------
# Global include & link directories
#--------------------------------------------------------------------------------------------------
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

# Allow modules to be placed inside “include” folder of each sub-project
set(CMAKE_INCLUDE_CURRENT_DIR ON)

#--------------------------------------------------------------------------------------------------
# Subprojects
#--------------------------------------------------------------------------------------------------
add_subdirectory(src/core)        # Domain entities, event bus, plugin API
add_subdirectory(src/http)        # REST controller layer and websocket hub
add_subdirectory(src/storage)     # Repositories & ORM bindings
add_subdirectory(src/services)    # Auth, payments, caching, notification service

if(MOSAIC_BUILD_PLUGINS)
    add_subdirectory(plugins/builtin)
endif()

if(MOSAIC_BUILD_EXAMPLES)
    add_subdirectory(examples)
endif()

if(MOSAIC_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()

#--------------------------------------------------------------------------------------------------
# Installation & export
#--------------------------------------------------------------------------------------------------
set(MOSAIC_INSTALL_CMAKEDIR "${CMAKE_INSTALL_LIBDIR}/cmake/${PROJECT_NAME}")

install(EXPORT ${PROJECT_NAME}-targets
        FILE      ${PROJECT_NAME}Targets.cmake
        NAMESPACE Mosaic::
        DESTINATION ${MOSAIC_INSTALL_CMAKEDIR})

configure_package_config_file(
        cmake/Config.cmake.in
        ${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake
        INSTALL_DESTINATION ${MOSAIC_INSTALL_CMAKEDIR})

install(FILES
        ${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake
        DESTINATION ${MOSAIC_INSTALL_CMAKEDIR})

# Assets
install(DIRECTORY assets/
        DESTINATION ${CMAKE_INSTALL_DATAROOTDIR}/${PROJECT_NAME}/assets
        FILES_MATCHING PATTERN "*.*")

#--------------------------------------------------------------------------------------------------
# CPack (binary/source packages)
#--------------------------------------------------------------------------------------------------
include(CPack)
set(CPACK_PACKAGE_NAME               "${PROJECT_NAME}")
set(CPACK_PACKAGE_VENDOR             "MosaicBoard Studio")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "Dynamic, plugin-based C++ web dashboard platform")
set(CPACK_PACKAGE_VERSION            ${PROJECT_VERSION})
set(CPACK_RESOURCE_FILE_LICENSE      "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE")
set(CPACK_RESOURCE_FILE_README       "${CMAKE_CURRENT_SOURCE_DIR}/README.md")
set(CPACK_SOURCE_GENERATOR           "TGZ;ZIP")
set(CPACK_SOURCE_IGNORE_FILES        "/build/;/.git/")

#--------------------------------------------------------------------------------------------------
# Summary
#--------------------------------------------------------------------------------------------------
message(STATUS "")
message(STATUS "------------------------------------------------------------")
message(STATUS " MosaicBoard Studio ${PROJECT_VERSION}")
message(STATUS "   Build type      : ${CMAKE_BUILD_TYPE}")
message(STATUS "   Install prefix  : ${CMAKE_INSTALL_PREFIX}")
message(STATUS "   Tests           : ${MOSAIC_BUILD_TESTS}")
message(STATUS "   Examples        : ${MOSAIC_BUILD_EXAMPLES}")
message(STATUS "   Built-in plugins: ${MOSAIC_BUILD_PLUGINS}")
message(STATUS "   LTO             : ${MOSAIC_ENABLE_LTO}")
message(STATUS "   Sanitizers      : ${MOSAIC_ENABLE_SANITIZERS}")
message(STATUS "------------------------------------------------------------")
message(STATUS "")