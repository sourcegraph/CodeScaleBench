cmake_minimum_required(VERSION 3.18)

#------------------------------------------------------------------------------
#  Project: MosaicBoard Studio – Example Data-Chart Tile
#
#  This CMake file produces the shared-library plugin that can be hot-swapped
#  into a running MosaicBoard Studio instance.  The plugin demonstrates how to
#  subscribe to the real-time event bus, query the service layer for data sets,
#  and render a live-updating chart using the framework’s GPU compositor.
#------------------------------------------------------------------------------

project(example_data_chart
        VERSION 1.2.0
        DESCRIPTION "Reference implementation of a data-driven chart tile"
        LANGUAGES CXX)

#------------------------------------------------------------------------------
#  General build options
#------------------------------------------------------------------------------

option(MBS_STRICT_WARNINGS    "Enable strict compiler warnings"             ON)
option(MBS_ENABLE_LTO         "Enable link-time optimisation (thin-LTO)"    OFF)
option(MBS_INSTALL_SYSCONFIG  "Install plugin-level configuration files"    ON)

# Use modern C++
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Always build position independent code – plugins are shared libs
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

#------------------------------------------------------------------------------
#  Dependencies
#------------------------------------------------------------------------------
# The core SDK is exported from the parent workspace; fall back to system
# installation if the user builds the plugin out-of-tree.

find_package(MosaicBoardSDK CONFIG REQUIRED
             COMPONENTS Core EventBus Renderer ServiceLayer)

# Optional: performance profiler (header-only, so INTERFACE target)
find_package(tracy-client QUIET CONFIG)

#------------------------------------------------------------------------------
#  Source layout
#------------------------------------------------------------------------------
set(EXAMPLE_CHART_PUBLIC_HEADERS
    include/ExampleDataChart.hpp
    include/ChartRenderer.hpp
)

set(EXAMPLE_CHART_PRIVATE_HEADERS
    src/internal/ChartDatasource.hpp
    src/internal/ChartStyle.hpp
)

set(EXAMPLE_CHART_SOURCES
    src/ExampleDataChart.cpp
    src/ChartRenderer.cpp
    src/internal/ChartDatasource.cpp
    src/internal/ChartStyle.cpp
)

#------------------------------------------------------------------------------
#  Target: Shared library
#------------------------------------------------------------------------------
add_library(${PROJECT_NAME} SHARED
            ${EXAMPLE_CHART_PUBLIC_HEADERS}
            ${EXAMPLE_CHART_PRIVATE_HEADERS}
            ${EXAMPLE_CHART_SOURCES})

# Public interface includes
target_include_directories(${PROJECT_NAME}
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

# Link with MosaicBoard SDK (namespaced imported targets)
target_link_libraries(${PROJECT_NAME}
    PUBLIC
        MosaicBoard::Core
        MosaicBoard::EventBus
        MosaicBoard::Renderer
        MosaicBoard::ServiceLayer
    PRIVATE
        $<$<BOOL:${tracy-client_FOUND}>:tracy::tracy-client>
)

#------------------------------------------------------------------------------
#  Compiler warnings & feature flags
#------------------------------------------------------------------------------
function(mbs_enable_strict_warnings _tgt)
    if(NOT MBS_STRICT_WARNINGS)
        return()
    endif()

    if(MSVC)
        target_compile_options(${_tgt} PRIVATE /W4 /permissive- /EHsc /utf-8)
    else()
        target_compile_options(${_tgt} PRIVATE
            -Wall -Wextra -Wpedantic -Werror
            -Wconversion -Wnon-virtual-dtor
            -Wold-style-cast -Woverloaded-virtual
            -Wsign-conversion
        )
    endif()
endfunction()

mbs_enable_strict_warnings(${PROJECT_NAME})

#------------------------------------------------------------------------------
#  Link-Time Optimisation (mainly for Release)
#------------------------------------------------------------------------------
if(MBS_ENABLE_LTO)
    include(CheckIPOSupported)
    check_ipo_supported(RESULT ipo_supported OUTPUT ipo_err)
    if(ipo_supported)
        set_target_properties(${PROJECT_NAME} PROPERTIES INTERPROCEDURAL_OPTIMIZATION TRUE)
    else()
        message(WARNING "IPO/LTO not supported: ${ipo_err}")
    endif()
endif()

#------------------------------------------------------------------------------
#  Platform-specific runtime search paths
#------------------------------------------------------------------------------
if(APPLE)
    # @loader_path searches relative to plugin dylib
    set_target_properties(${PROJECT_NAME} PROPERTIES
        INSTALL_RPATH "@loader_path;@loader_path/../${MOSAICBOARD_PLUGIN_RPATH_SUFFIX}"
    )
elseif(UNIX)
    set_target_properties(${PROJECT_NAME} PROPERTIES
        INSTALL_RPATH "\$ORIGIN:\$ORIGIN/../${MOSAICBOARD_PLUGIN_RPATH_SUFFIX}"
    )
endif()

#------------------------------------------------------------------------------
#  Pre-processor definitions
#------------------------------------------------------------------------------
target_compile_definitions(${PROJECT_NAME}
    PRIVATE
        $<$<BOOL:${tracy-client_FOUND}>:MBS_USE_TRACY_PROFILER>
)

#------------------------------------------------------------------------------
#  Install rules
#------------------------------------------------------------------------------
include(GNUInstallDirs)

# Destination inside the MosaicBoard installation prefix
set(MBS_PLUGIN_DESTINATION "${CMAKE_INSTALL_LIBDIR}/mosaicboard/plugins")

install(TARGETS ${PROJECT_NAME}
        EXPORT  example_data_chart-targets
        LIBRARY DESTINATION ${MBS_PLUGIN_DESTINATION}
        RUNTIME DESTINATION ${MBS_PLUGIN_DESTINATION}      # Windows
        ARCHIVE DESTINATION ${MBS_PLUGIN_DESTINATION}      # Static (rare)
)

# Install public headers for SDK consumers
install(DIRECTORY include/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/mosaicboard/plugins/example_data_chart
        FILES_MATCHING PATTERN "*.hpp"
)

# Plugin manifest (JSON) tells MosaicBoard Studio how to display it
install(FILES plugin.json
        DESTINATION ${MBS_PLUGIN_DESTINATION}/example_data_chart)

# Optional system-wide configuration override
if(MBS_INSTALL_SYSCONFIG)
    install(FILES config/default_chart_style.yaml
            DESTINATION ${CMAKE_INSTALL_SYSCONFDIR}/mosaicboard/example_data_chart)
endif()

#------------------------------------------------------------------------------
#  Export build directory for downstream consumers (makes this plugin
#  importable via find_package while still in the build-tree)
#------------------------------------------------------------------------------
export(EXPORT example_data_chart-targets
       FILE   ${CMAKE_CURRENT_BINARY_DIR}/example_data_chartTargets.cmake
       NAMESPACE MosaicBoard::)

# Create a basic package config for install-tree
include(CMakePackageConfigHelpers)
configure_package_config_file(
    cmake/example_data_chartConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/example_data_chartConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/example_data_chart
)

write_basic_package_version_file(
    ${CMAKE_CURRENT_BINARY_DIR}/example_data_chartConfigVersion.cmake
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY AnyNewerVersion
)

install(EXPORT example_data_chart-targets
        FILE   example_data_chartTargets.cmake
        NAMESPACE MosaicBoard::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/example_data_chart)

install(FILES
        ${CMAKE_CURRENT_BINARY_DIR}/example_data_chartConfig.cmake
        ${CMAKE_CURRENT_BINARY_DIR}/example_data_chartConfigVersion.cmake
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/example_data_chart)

#------------------------------------------------------------------------------
#  Developer tooling
#------------------------------------------------------------------------------
# Target for running clang-format in-place (requires clang-format in PATH)
find_program(CLANG_FORMAT_EXE NAMES clang-format)
if(CLANG_FORMAT_EXE)
    add_custom_target(example_data_chart-format
        COMMAND ${CLANG_FORMAT_EXE}
                -i
                -style=file
                ${EXAMPLE_CHART_PUBLIC_HEADERS}
                ${EXAMPLE_CHART_PRIVATE_HEADERS}
                ${EXAMPLE_CHART_SOURCES}
        COMMENT "Running clang-format on example_data_chart sources"
    )
endif()

#------------------------------------------------------------------------------
#  Summary
#------------------------------------------------------------------------------
message(STATUS "-----------------------------------------------------")
message(STATUS "ExampleDataChart plugin:")
message(STATUS "  Version              : ${PROJECT_VERSION}")
message(STATUS "  Strict warnings      : ${MBS_STRICT_WARNINGS}")
message(STATUS "  LTO                  : ${MBS_ENABLE_LTO}")
message(STATUS "  Install dir          : ${CMAKE_INSTALL_PREFIX}/${MBS_PLUGIN_DESTINATION}")
message(STATUS "-----------------------------------------------------")