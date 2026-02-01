# ========================================================================
#  SynestheticCanvas : Texture Service – Build Script
#  ---------------------------------------------------
#  CMake build configuration for the “texture-service” micro-service. This
#  service is responsible for dynamic GPU/CPU texture synthesis and format
#  transcoding used by the API-Gateway.  The service exposes a thin C ABI
#  that is consumed by the GraphQL/REST façade layer and by the internal
#  asset-streamer runtime.
#
#  Highlights
#    • C11 compliance, warnings-as-errors
#    • Optional Address/UB sanitizers and coverage
#    • Automatic generation of compile_commands.json
#    • Conan and vcpkg (toolchain) awareness
#    • Out-of-tree builds only (for safety)
#    • Unit tests via CTest + Unity
#    • Installation + export of CMake package config files
# ========================================================================

cmake_minimum_required(VERSION 3.20)

# ------------------------------------------------------------------------
#  Project metadata
# ------------------------------------------------------------------------
project(texture_service
        VERSION 1.2.0
        DESCRIPTION "Dynamic texture synthesis micro-service"
        LANGUAGES C)

# ------------------------------------------------------------------------
#  Safety: forbid in-source builds
# ------------------------------------------------------------------------
if(${CMAKE_SOURCE_DIR} STREQUAL ${CMAKE_BINARY_DIR})
    message(FATAL_ERROR "In-source builds are not allowed. Please invoke CMake "
                        "from a separate build directory (e.g. `mkdir build && "
                        "cd build && cmake ..`).")
endif()

# ------------------------------------------------------------------------
#  Options
# ------------------------------------------------------------------------
option(TEXTURESVC_BUILD_SHARED      "Build shared library"                 ON)
option(TEXTURESVC_ENABLE_SANITIZERS "Enable Address/UBSan (debug only)"   OFF)
option(TEXTURESVC_ENABLE_COVERAGE   "Enable gcov/lcov coverage (gcc/clang)" OFF)
option(TEXTURESVC_ENABLE_TESTS      "Build and run unit tests"            ON)
option(TEXTURESVC_ENABLE_LTO        "Enable link-time optimization"       OFF)

# ------------------------------------------------------------------------
#  Compiler settings
# ------------------------------------------------------------------------
set(C_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)

#  Configure warnings: treat as errors on CI/build servers
set(TEXTURESVC_WARN_FLAGS
        -Wall -Wextra -Wpedantic -Werror
        -Wno-unused-parameter          # allowed in callbacks
        -Wno-missing-field-initializers)

if (MSVC)
    # map GCC style warning flags
else()
    add_compile_options(${TEXTURESVC_WARN_FLAGS})
endif()

# ------------------------------------------------------------------------
#  Build type defaults
# ------------------------------------------------------------------------
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "RelWithDebInfo" CACHE STRING
        "Build type (default RelWithDebInfo)" FORCE)
endif()

# ------------------------------------------------------------------------
#  Sanitisers
# ------------------------------------------------------------------------
if(TEXTURESVC_ENABLE_SANITIZERS AND NOT CMAKE_CROSSCOMPILING)
    if(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
        add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
        add_link_options(-fsanitize=address,undefined)
    endif()
endif()

# ------------------------------------------------------------------------
#  Coverage
# ------------------------------------------------------------------------
if(TEXTURESVC_ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    message(STATUS "Code coverage enabled")
    add_compile_options(--coverage -O0)
    add_link_options(--coverage)
endif()

# ------------------------------------------------------------------------
#  LTO
# ------------------------------------------------------------------------
if(TEXTURESVC_ENABLE_LTO)
    include(CheckIPOSupported)
    check_ipo_supported(RESULT lto_supported OUTPUT lto_error)
    if(lto_supported)
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION ON)
    else()
        message(WARNING "IPO/LTO not supported: ${lto_error}")
    endif()
endif()

# ------------------------------------------------------------------------
#  Dependencies
# ------------------------------------------------------------------------
include(FetchContent)

# 1. cJSON (MIT) – minimal JSON lib used for texture descriptors
FetchContent_Declare(
    cjson
    GIT_REPOSITORY https://github.com/DaveGamble/cJSON.git
    GIT_TAG v1.7.16)
FetchContent_MakeAvailable(cjson)

# 2. stb_image (public domain) – header-only, no build step
set(STB_IMAGE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/third_party/stb_image)
if(NOT EXISTS ${STB_IMAGE_DIR}/stb_image.h)
    message(FATAL_ERROR "third_party/stb_image not found. Run git submodule "
                        "update --init --recursive")
endif()

# 3. Optional libpng (system or package manager)
find_package(PNG 1.6 QUIET)

# ------------------------------------------------------------------------
#  Source files
# ------------------------------------------------------------------------
file(GLOB_RECURSE TEXTURESVC_SRC CONFIGURE_DEPENDS
     src/*.c
     include/*.h)

add_library(texture_service
    ${TEXTURESVC_SRC})

if(TEXTURESVC_BUILD_SHARED)
    set_target_properties(texture_service PROPERTIES
        POSITION_INDEPENDENT_CODE ON
        WINDOWS_EXPORT_ALL_SYMBOLS ON)
endif()

target_include_directories(texture_service
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE
        ${STB_IMAGE_DIR})

# Link third-party libs
target_link_libraries(texture_service
    PUBLIC
        cjson
    PRIVATE
        $<$<BOOL:${PNG_FOUND}>:PNG::PNG>)

# Export compile_commands.json for IDE integration
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ------------------------------------------------------------------------
#  Testing
# ------------------------------------------------------------------------
if(TEXTURESVC_ENABLE_TESTS)
    enable_testing()
    # Unity (single-file test framework) via FetchContent
    FetchContent_Declare(
        unity
        GIT_REPOSITORY https://github.com/ThrowTheSwitch/Unity.git
        GIT_TAG v2.5.2)
    FetchContent_MakeAvailable(unity)

    file(GLOB_RECURSE TEST_SRC CONFIGURE_DEPENDS tests/*.c)
    add_executable(texture_service_tests ${TEST_SRC})
    target_link_libraries(texture_service_tests PRIVATE texture_service unity)

    add_test(NAME texture_service_unit
             COMMAND texture_service_tests)
endif()

# ------------------------------------------------------------------------
#  Installation
# ------------------------------------------------------------------------
include(GNUInstallDirs)

install(TARGETS texture_service
        EXPORT texture_serviceTargets
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})

install(DIRECTORY include/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

#  Package config
install(EXPORT texture_serviceTargets
        FILE texture_serviceTargets.cmake
        NAMESPACE SynestheticCanvas::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/texture_service)

include(CMakePackageConfigHelpers)

configure_package_config_file(
    cmake/texture_serviceConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/texture_serviceConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/texture_service)

write_basic_package_version_file(
    ${CMAKE_CURRENT_BINARY_DIR}/texture_serviceConfigVersion.cmake
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion)

install(FILES
        ${CMAKE_CURRENT_BINARY_DIR}/texture_serviceConfig.cmake
        ${CMAKE_CURRENT_BINARY_DIR}/texture_serviceConfigVersion.cmake
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/texture_service)

# ------------------------------------------------------------------------
#  Packaging (CPack)
# ------------------------------------------------------------------------
include(CPack)
set(CPACK_PACKAGE_VENDOR "SynestheticCanvas")
set(CPACK_PACKAGE_CONTACT "dev-ops@synestheticcanvas.io")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "Dynamic texture synthesis micro-service")
set(CPACK_PACKAGE_VERSION ${PROJECT_VERSION})

# ------------------------------------------------------------------------
#  Developer utilities
# ------------------------------------------------------------------------
add_custom_target(
    clang_format
    COMMAND clang-format
            -i
            -style=file
            ${TEXTURESVC_SRC}
            ${TEST_SRC}
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    COMMENT "Format source with clang-format")

# Re-export compile commands to top-level for convenience
add_custom_command(TARGET texture_service POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${CMAKE_BINARY_DIR}/compile_commands.json
            ${CMAKE_SOURCE_DIR}/compile_commands.json)

# ========================================================================
#  End of file
# ========================================================================