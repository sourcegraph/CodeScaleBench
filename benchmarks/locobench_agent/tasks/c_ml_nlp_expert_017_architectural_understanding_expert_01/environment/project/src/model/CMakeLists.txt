# ----------------------------------------------------------------------------------
#  LexiLearn MVC Orchestrator – Model Layer
#  CMake build script
#
#  This CMakeLists.txt configures and builds the Model layer of the LexiLearn
#  platform.  It produces a reusable C static library (`lexilearn_model`) that
#  encapsulates data–pre-processing, feature-engineering, experiment tracking,
#  and model-evaluation utilities.  Optional components such as GPU kernels,
#  Python bindings, sanitizers, and code-coverage instrumentation can be
#  toggled via standard CMake options.
#
#  Author:  LexiLearn Core Team
#  License: MIT
# ----------------------------------------------------------------------------------

cmake_minimum_required(VERSION 3.20 FATAL_ERROR)
project(lexilearn_model
        VERSION 1.4.2
        LANGUAGES C)

# -------------------------------------------------------------------------------
# User-configurable build options
# -------------------------------------------------------------------------------
option(LEXI_ENABLE_OPENMP      "Enable OpenMP parallelization"           ON)
option(LEXI_ENABLE_SANITIZERS  "Compile with Address/UB sanitizers"      OFF)
option(LEXI_ENABLE_COVERAGE    "Compile with coverage instrumentation"   OFF)
option(LEXI_ENABLE_CUDA        "Enable CUDA-accelerated kernels"         OFF)
option(LEXI_ENABLE_PYBINDINGS  "Build Python C-API bindings"             OFF)
option(LEXI_BUILD_SHARED       "Build lexilearn_model as a shared lib"   ON)

# -------------------------------------------------------------------------------
# Global compile settings
# -------------------------------------------------------------------------------
set(CMAKE_C_STANDARD          17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Treat warnings as errors for production safety
add_library(lexi_warnings INTERFACE)
target_compile_options(lexi_warnings INTERFACE
  $<$<C_COMPILER_ID:GNU,Clang>:-Wall -Wextra -Wpedantic -Werror>
  $<$<C_COMPILER_ID:MSVC>:/W4 /WX>)

# -------------------------------------------------------------------------------
# Collector for model-layer source files
# -------------------------------------------------------------------------------
file(GLOB_RECURSE LEXI_MODEL_SRC
     CONFIGURE_DEPENDS
     "${CMAKE_CURRENT_SOURCE_DIR}/pipeline/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/feature_store/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/registry/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/strategies/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/utils/*.c")

# -------------------------------------------------------------------------------
# Optional CUDA sources
# -------------------------------------------------------------------------------
if(LEXI_ENABLE_CUDA)
    enable_language(CUDA)
    file(GLOB_RECURSE LEXI_MODEL_CUDA_SRC
         CONFIGURE_DEPENDS
         "${CMAKE_CURRENT_SOURCE_DIR}/kernels/*.cu")
    list(APPEND LEXI_MODEL_SRC ${LEXI_MODEL_CUDA_SRC})
endif()

# -------------------------------------------------------------------------------
# Create the target
# -------------------------------------------------------------------------------
if(LEXI_BUILD_SHARED)
    add_library(lexilearn_model SHARED ${LEXI_MODEL_SRC})
    target_compile_definitions(lexilearn_model PUBLIC LEXI_MODEL_DLL)  # For export macros
else()
    add_library(lexilearn_model STATIC ${LEXI_MODEL_SRC})
endif()

# Link internal warnings interface
target_link_libraries(lexilearn_model PUBLIC lexi_warnings)

# -------------------------------------------------------------------------------
# Public include directory
# -------------------------------------------------------------------------------
target_include_directories(lexilearn_model
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)

# -------------------------------------------------------------------------------
# Optional: OpenMP support
# -------------------------------------------------------------------------------
if(LEXI_ENABLE_OPENMP)
    find_package(OpenMP QUIET)
    if(OpenMP_FOUND)
        target_link_libraries(lexilearn_model PUBLIC OpenMP::OpenMP_C)
        target_compile_definitions(lexilearn_model PUBLIC LEXI_ENABLE_OPENMP)
    else()
        message(WARNING "OpenMP requested but not found — continuing without.")
    endif()
endif()

# -------------------------------------------------------------------------------
# Optional: Sanitizers
# -------------------------------------------------------------------------------
if(LEXI_ENABLE_SANITIZERS AND (CMAKE_C_COMPILER_ID MATCHES "Clang|GNU"))
    target_compile_options(lexilearn_model
        PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(lexilearn_model
        PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
endif()

# -------------------------------------------------------------------------------
# Optional: Code coverage instrumentation
# -------------------------------------------------------------------------------
if(LEXI_ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID STREQUAL "GNU")
    target_compile_options(lexilearn_model PUBLIC --coverage)
    target_link_libraries(lexilearn_model PUBLIC --coverage)
endif()

# -------------------------------------------------------------------------------
# Optional: Python C-API bindings
# -------------------------------------------------------------------------------
if(LEXI_ENABLE_PYBINDINGS)
    find_package(Python3 COMPONENTS Interpreter Development REQUIRED)
    add_subdirectory(python)  # Expect python/CMakeLists.txt for bindings
    target_compile_definitions(lexilearn_model PUBLIC LEXI_ENABLE_PYBINDINGS)
endif()

# -------------------------------------------------------------------------------
# Export header auto-generation (version & build info)
# -------------------------------------------------------------------------------
include(GNUInstallDirs)

configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/include/lexi_model_export.h.in
    ${CMAKE_CURRENT_BINARY_DIR}/generated/lexi_model_export.h
    @ONLY)

target_include_directories(lexilearn_model
    PUBLIC ${CMAKE_CURRENT_BINARY_DIR}/generated)

# -------------------------------------------------------------------------------
# Installation directives
# -------------------------------------------------------------------------------
install(TARGETS lexilearn_model
        EXPORT  lexilearn_modelTargets
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

install(DIRECTORY include/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

install(FILES
        ${CMAKE_CURRENT_BINARY_DIR}/generated/lexi_model_export.h
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

# Generate a Config file for downstream `find_package(lexilearn_model)`
include(CMakePackageConfigHelpers)
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/lexilearn_modelConfigVersion.cmake"
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion)

install(EXPORT lexilearn_modelTargets
        FILE   lexilearn_modelTargets.cmake
        NAMESPACE lexilearn::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/lexilearn_model)

configure_package_config_file(
    ${CMAKE_CURRENT_LIST_DIR}/cmake/lexilearn_modelConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/lexilearn_modelConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/lexilearn_model)

install(FILES
        ${CMAKE_CURRENT_BINARY_DIR}/lexilearn_modelConfig.cmake
        ${CMAKE_CURRENT_BINARY_DIR}/lexilearn_modelConfigVersion.cmake
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/lexilearn_model)

# -------------------------------------------------------------------------------
# Unit-testing integration (optional)
# -------------------------------------------------------------------------------
if(CMAKE_PROJECT_NAME STREQUAL PROJECT_NAME AND BUILD_TESTING)
    enable_testing()
    add_subdirectory(tests)
endif()

# -------------------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------------------
message(STATUS "------------------------------------------------------")
message(STATUS " LexiLearn Model build summary")
message(STATUS "   Version:             ${PROJECT_VERSION}")
message(STATUS "   Build type:          ${CMAKE_BUILD_TYPE}")
message(STATUS "   Shared library:      ${LEXI_BUILD_SHARED}")
message(STATUS "   OpenMP:              ${LEXI_ENABLE_OPENMP}")
message(STATUS "   Sanitizers:          ${LEXI_ENABLE_SANITIZERS}")
message(STATUS "   Coverage:            ${LEXI_ENABLE_COVERAGE}")
message(STATUS "   CUDA kernels:        ${LEXI_ENABLE_CUDA}")
message(STATUS "   Python bindings:     ${LEXI_ENABLE_PYBINDINGS}")
message(STATUS "------------------------------------------------------")