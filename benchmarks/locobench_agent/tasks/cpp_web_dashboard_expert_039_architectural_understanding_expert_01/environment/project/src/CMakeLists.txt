# ==================================================================================================
#  MosaicBoard Studio - Source Level CMake
#
#  This CMakeLists.txt configures the main MosaicBoard Studio components that live inside the
#  `src/` tree.  It is responsible for
#      * setting a modern C++ tool-chain
#      * pulling in required third-party dependencies
#      * defining shared/static libraries and the main executable
#      * enabling developer-centric tooling (sanitizers, coverage, clang-tidy, etc.)
#      * exposing an install/export interface for downstream consumers and plugins
#  ----------------------------------------------------------------------------------------------
#  NOTE:
#    The *plugins* themselves are **not** built here – they live in `/plugins` and are added by the
#    parent CMakeLists.txt through `add_subdirectory(plugins)`.  At configuration time we only
#    provide a header-only “Tile API” so that external plugin projects can link against a stable ABI
#    without depending on the full core.
# ==================================================================================================

cmake_minimum_required(VERSION 3.20)

# --------------------------------------------------------------------------------------------------
# PROJECT & TOOLCHAIN
# --------------------------------------------------------------------------------------------------
project(MosaicBoardStudio
        VERSION 1.4.0
        DESCRIPTION "Dynamic C++ Web-Dashboard Platform"
        LANGUAGES CXX)

# Set a global default C++ standard for all targets unless explicitly overridden.
set(CMAKE_CXX_STANDARD          20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS        OFF)

# --------------------------------------------------------------------------------------------------
# USER OPTIONS
# --------------------------------------------------------------------------------------------------
option(MOSAIC_BUILD_TESTS       "Build unit/integration tests"                 ON)
option(MOSAIC_BUILD_DOCS        "Build developer documentation (Doxygen)"      OFF)
option(MOSAIC_ENABLE_SANITIZER  "Enable Address/Undefined sanitizers"          OFF)
option(MOSAIC_ENABLE_COVERAGE   "Enable code-coverage instrumentation"         OFF)
option(MOSAIC_ENABLE_CLANG_TIDY "Run clang-tidy static analysis during build"  OFF)

# --------------------------------------------------------------------------------------------------
# THIRD-PARTY DEPENDENCIES
# --------------------------------------------------------------------------------------------------
include(FetchContent)

# ---------- nlohmann_json ------------------------------------------------------------------------
FetchContent_Declare(
  nlohmann_json
  GIT_REPOSITORY https://github.com/nlohmann/json.git
  GIT_TAG        v3.11.2
)
FetchContent_MakeAvailable(nlohmann_json)

# ---------- spdlog --------------------------------------------------------------------------------
FetchContent_Declare(
  spdlog
  GIT_REPOSITORY https://github.com/gabime/spdlog.git
  GIT_TAG        v1.12.0
)
FetchContent_MakeAvailable(spdlog)

# ---------- cpp-httplib (light-weight REST server) -------------------------------------------------
FetchContent_Declare(
  httplib
  GIT_REPOSITORY https://github.com/yhirose/cpp-httplib.git
  GIT_TAG        v0.13.1
)
FetchContent_MakeAvailable(httplib)

# ---------- sqlite-modern-cpp ---------------------------------------------------------------------
FetchContent_Declare(
  sqlite_modern_cpp
  GIT_REPOSITORY https://github.com/SqliteModernCpp/sqlite_modern_cpp.git
  GIT_TAG        master
)
FetchContent_MakeAvailable(sqlite_modern_cpp)

# ---------- WebSocket++ ---------------------------------------------------------------------------
find_package(Threads REQUIRED)

FetchContent_Declare(
  websocketpp
  GIT_REPOSITORY https://github.com/zaphoyd/websocketpp.git
  GIT_TAG        0.8.2
)
FetchContent_MakeAvailable(websocketpp)

# --------------------------------------------------------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------------------------------------------------------
function(mosaic_target_common_settings TARGET_NAME)
    # Apply strict warning and optimization flags
    if (MSVC)
        target_compile_options(${TARGET_NAME} PRIVATE /W4 /permissive-)
    else()
        target_compile_options(${TARGET_NAME}
            PRIVATE
                -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion
                -Werror                      # Treat warnings as errors in CI
                -fno-omit-frame-pointer
        )
    endif()

    # Sanitizer support (Address + Undefined)
    if(MOSAIC_ENABLE_SANITIZER AND NOT MSVC)
        target_compile_options(${TARGET_NAME} PRIVATE -fsanitize=address,undefined)
        target_link_options(${TARGET_NAME}    PRIVATE -fsanitize=address,undefined)
    endif()

    # Code coverage
    if(MOSAIC_ENABLE_COVERAGE AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(${TARGET_NAME} PRIVATE --coverage)
        target_link_options(${TARGET_NAME}    PRIVATE --coverage)
    endif()

    # Spdlog header-only; ensure same compile options
    target_compile_definitions(${TARGET_NAME}
        PRIVATE
            SPDLOG_FMT_EXTERNAL=ON
            SPDLOG_ACTIVE_LEVEL=SPDLOG_LEVEL_DEBUG
    )

    # Global include folders (public -> for plugins)
    target_include_directories(${TARGET_NAME}
        PUBLIC
            $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/>
            $<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>
            $<INSTALL_INTERFACE:include>
    )

    # clang-tidy
    if (MOSAIC_ENABLE_CLANG_TIDY)
        set_target_properties(${TARGET_NAME} PROPERTIES
            CXX_CLANG_TIDY "clang-tidy;--quiet"
        )
    endif()
endfunction()

# --------------------------------------------------------------------------------------------------
# SOURCE FILES
# --------------------------------------------------------------------------------------------------
set(MOSAIC_CORE_SOURCES
    Core/Application.cpp
    Core/EventBus.cpp
    Core/TileRegistry.cpp
    Core/PluginLoader.cpp
    Core/Configuration.cpp
    Core/HttpServer.cpp
    Core/WebSocketHub.cpp
    Services/AuthService.cpp
    Services/PaymentService.cpp
    Services/NotificationService.cpp
    Repositories/UserRepository.cpp
    Repositories/PaymentRepository.cpp
    Utils/Log.cpp
    Utils/Timer.cpp
)

set(MOSAIC_CORE_PUBLIC_HEADERS
    ${PROJECT_SOURCE_DIR}/include/Mosaic/Tile.hpp
    ${PROJECT_SOURCE_DIR}/include/Mosaic/PluginAPI.hpp
)

# --------------------------------------------------------------------------------------------------
# CORE SHARED LIBRARY
# --------------------------------------------------------------------------------------------------
add_library(mosaic_core SHARED
    ${MOSAIC_CORE_SOURCES}
    ${MOSAIC_CORE_PUBLIC_HEADERS}
)

# 3rd-party linkage
target_link_libraries(mosaic_core
    PUBLIC
        nlohmann_json::nlohmann_json
        spdlog::spdlog_header_only
    PRIVATE
        sqlite_modern_cpp
        httplib
        websocketpp
        Threads::Threads
)

# Apply common compile/link options
mosaic_target_common_settings(mosaic_core)

set_target_properties(mosaic_core
    PROPERTIES
        VERSION       ${PROJECT_VERSION}
        SOVERSION     ${PROJECT_VERSION_MAJOR}
        PUBLIC_HEADER "${MOSAIC_CORE_PUBLIC_HEADERS}"
)

# --------------------------------------------------------------------------------------------------
# MAIN APPLICATION EXECUTABLE
# --------------------------------------------------------------------------------------------------
add_executable(mosaic_dashboard
    main.cpp
)

target_link_libraries(mosaic_dashboard
    PRIVATE
        mosaic_core
)

mosaic_target_common_settings(mosaic_dashboard)

# --------------------------------------------------------------------------------------------------
# UNIT/INTEGRATION TESTS (Catch2)
# --------------------------------------------------------------------------------------------------
if(MOSAIC_BUILD_TESTS)
    enable_testing()

    FetchContent_Declare(
      Catch2
      GIT_REPOSITORY https://github.com/catchorg/Catch2.git
      GIT_TAG        v3.4.0
    )
    FetchContent_MakeAvailable(Catch2)

    add_executable(mosaic_tests
        tests/CoreTests.cpp
        tests/ServiceTests.cpp
        tests/RepositoryTests.cpp
    )

    target_link_libraries(mosaic_tests
        PRIVATE
            mosaic_core
            Catch2::Catch2WithMain
    )

    mosaic_target_common_settings(mosaic_tests)

    add_test(NAME all_tests COMMAND mosaic_tests)
endif()

# --------------------------------------------------------------------------------------------------
# DOCUMENTATION (Doxygen)
# --------------------------------------------------------------------------------------------------
if(MOSAIC_BUILD_DOCS)
    find_package(Doxygen REQUIRED dot)
    set(DOXYGEN_IN  ${CMAKE_CURRENT_SOURCE_DIR}/Doxyfile.in)
    set(DOXYGEN_OUT ${CMAKE_CURRENT_BINARY_DIR}/Doxyfile)

    configure_file(${DOXYGEN_IN} ${DOXYGEN_OUT} @ONLY)

    add_custom_target(docs
        COMMAND ${DOXYGEN_EXECUTABLE} ${DOXYGEN_OUT}
        WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
        COMMENT "Generating API documentation with Doxygen"
        VERBATIM
    )
endif()

# --------------------------------------------------------------------------------------------------
# INSTALL & EXPORT
# --------------------------------------------------------------------------------------------------
include(GNUInstallDirs)

install(
    TARGETS          mosaic_core mosaic_dashboard
    EXPORT           mosaic_targets
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    PUBLIC_HEADER DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/Mosaic
)

export(
    EXPORT  mosaic_targets
    FILE    ${CMAKE_CURRENT_BINARY_DIR}/mosaic_targets.cmake
    NAMESPACE Mosaic::
)

# Also install the CMake package config for find_package(Mosaic)
include(CMakePackageConfigHelpers)

configure_package_config_file(
    ${PROJECT_SOURCE_DIR}/cmake/MosaicConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/MosaicConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/Mosaic
)

write_basic_package_version_file(
    ${CMAKE_CURRENT_BINARY_DIR}/MosaicConfigVersion.cmake
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion
)

install(
    FILES
        ${CMAKE_CURRENT_BINARY_DIR}/MosaicConfig.cmake
        ${CMAKE_CURRENT_BINARY_DIR}/MosaicConfigVersion.cmake
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/Mosaic
)

# --------------------------------------------------------------------------------------------------
# DEVELOPER FRIENDLINESS
# --------------------------------------------------------------------------------------------------
# Export compile_commands.json for IDEs and static analysis
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Colourized Ninja output (if supported)
if (CMAKE_GENERATOR STREQUAL "Ninja")
    set_property(GLOBAL PROPERTY RULE_LAUNCH_COMPILE "${CMAKE_COMMAND} -E env CLICOLOR_FORCE=1")
endif()

# Provide a summary after configuration
message(STATUS "-------------------------------------------------------------")
message(STATUS "        MosaicBoard Studio Configuration Summary")
message(STATUS "-------------------------------------------------------------")
message(STATUS "  Project Version        : v${PROJECT_VERSION}")
message(STATUS "  Build Type             : ${CMAKE_BUILD_TYPE}")
message(STATUS "  Build Tests            : ${MOSAIC_BUILD_TESTS}")
message(STATUS "  Build Docs             : ${MOSAIC_BUILD_DOCS}")
message(STATUS "  Sanitizers             : ${MOSAIC_ENABLE_SANITIZER}")
message(STATUS "  Code Coverage          : ${MOSAIC_ENABLE_COVERAGE}")
message(STATUS "  clang-tidy             : ${MOSAIC_ENABLE_CLANG_TIDY}")
message(STATUS "-------------------------------------------------------------")