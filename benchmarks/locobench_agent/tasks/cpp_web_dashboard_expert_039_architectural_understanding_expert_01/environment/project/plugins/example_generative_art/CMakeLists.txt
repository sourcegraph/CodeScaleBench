cmake_minimum_required(VERSION 3.20)

# ------------------------------------------------------------------------------
#  MosaicBoard Studio – Example Generative Art Plugin
#  -----------------------------------------------------------------------------
#  This CMake script builds the “example_generative_art” plugin as a shared
#  library.  The resulting binary is hot-swappable and discovered at run-time by
#  the MosaicBoard Studio core via the plugin manager.
# ------------------------------------------------------------------------------

project(MosaicBoardPlugin_ExampleGenerativeArt
        VERSION 0.3.1
        LANGUAGES CXX)

# ------------------------------------------------------------------------------ 
#  Options
# ------------------------------------------------------------------------------
option(ENABLE_CLANG_TIDY "Enable clang-tidy static analysis"          OFF)
option(BUILD_TESTS       "Build unit tests for this plugin"           OFF)

# ------------------------------------------------------------------------------ 
#  Source Files
# ------------------------------------------------------------------------------
set(PLUGIN_SRC
    src/GenerativeArtPlugin.cpp
    src/GenerativeArtWidget.cpp
    src/ShaderProgram.cpp
    src/NoiseGenerator.cpp

    include/example_generative_art/GenerativeArtPlugin.hpp
    include/example_generative_art/GenerativeArtWidget.hpp
    include/example_generative_art/ShaderProgram.hpp
    include/example_generative_art/NoiseGenerator.hpp
)

# ------------------------------------------------------------------------------ 
#  Target Definition
# ------------------------------------------------------------------------------
add_library(example_generative_art SHARED ${PLUGIN_SRC})

# Public include paths (exported as part of the interface)
target_include_directories(
    example_generative_art
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
        ${MOSAICBOARD_CORE_INCLUDE_DIRS}    # provided by the root project
)

# Require modern C++
target_compile_features(example_generative_art PUBLIC cxx_std_20)

# Strict compile flags
if (MSVC)
    target_compile_options(example_generative_art PRIVATE /W4 /permissive- /EHsc)
else()
    target_compile_options(example_generative_art PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

# Mark as position-independent for safe runtime loading
set_target_properties(example_generative_art
    PROPERTIES
        POSITION_INDEPENDENT_CODE ON
        OUTPUT_NAME               "generative_art"
)

# ------------------------------------------------------------------------------ 
#  Dependencies
# ------------------------------------------------------------------------------
find_package(OpenGL          REQUIRED)
find_package(glfw3   3.3     REQUIRED)
find_package(GLEW            REQUIRED)
find_package(nlohmann_json   REQUIRED)
find_package(fmt             REQUIRED)

target_link_libraries(
    example_generative_art
    PRIVATE
        mosaic::core                    # Exported by main project
        mosaic::event_bus
        OpenGL::GL
        glfw
        GLEW::GLEW
        nlohmann_json::nlohmann_json
        fmt::fmt
)

# ------------------------------------------------------------------------------ 
#  Optional Static Analysis
# ------------------------------------------------------------------------------
if (ENABLE_CLANG_TIDY)
    find_program(CLANG_TIDY_EXE NAMES clang-tidy)
    if (CLANG_TIDY_EXE)
        message(STATUS "clang-tidy enabled for example_generative_art")
        set_target_properties(example_generative_art
            PROPERTIES
                CXX_CLANG_TIDY "${CLANG_TIDY_EXE};-warnings-as-errors=*"
        )
    endif()
endif()

# ------------------------------------------------------------------------------ 
#  RPATH Handling – make sure the plugin finds its deps when hot-loaded
# ------------------------------------------------------------------------------
if (APPLE)
    set(_rpath "@loader_path/../lib")
elseif(UNIX)
    set(_rpath "$ORIGIN/../lib")
endif()

set_target_properties(example_generative_art
    PROPERTIES
        BUILD_WITH_INSTALL_RPATH TRUE
        INSTALL_RPATH            "${_rpath}"
)

# ------------------------------------------------------------------------------ 
#  Installation
# ------------------------------------------------------------------------------
include(GNUInstallDirs)

install(
    TARGETS example_generative_art
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}/mosaic/plugins
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}/mosaic/plugins
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}/mosaic/plugins
)

install(
    DIRECTORY include/
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
    FILES_MATCHING PATTERN "*.hpp"
)

# ------------------------------------------------------------------------------ 
#  Unit Tests
# ------------------------------------------------------------------------------
if (BUILD_TESTS)
    enable_testing()
    add_subdirectory(test)
endif()

# ------------------------------------------------------------------------------ 
#  Packaging Metadata
# ------------------------------------------------------------------------------
set(CPACK_PACKAGE_NAME               "MosaicPlugin-GenerativeArt")
set(CPACK_PACKAGE_VERSION            ${PROJECT_VERSION})
set(CPACK_PACKAGE_VENDOR             "MosaicBoard Studio")
set(CPACK_PACKAGE_CONTACT            "support@mosaicboard.io")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY
    "Generative Art Tile Plugin for MosaicBoard Studio")
include(CPack)