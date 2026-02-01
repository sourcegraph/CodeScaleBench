cmake_minimum_required(VERSION 3.20 FATAL_ERROR)

# ────────────────────────────────────────────────────────────────────────────────
#  Project Metadata
# ────────────────────────────────────────────────────────────────────────────────
project(lexilearn_orchestrator
        VERSION 1.2.0
        DESCRIPTION "LexiLearn MVC Orchestrator for adaptive language-learning applications"
        LANGUAGES C)

# ────────────────────────────────────────────────────────────────────────────────
#  User-configurable Options
# ────────────────────────────────────────────────────────────────────────────────
option(LEXILEARN_ENABLE_SANITIZER       "Enable Address/Undefined sanitizers"          OFF)
option(LEXILEARN_ENABLE_COVERAGE        "Enable coverage instrumentation"              OFF)
option(LEXILEARN_WARNINGS_AS_ERRORS     "Treat all warnings as errors"                 ON)
option(LEXILEARN_BUILD_TESTS            "Build unit/integration tests"                 ON)
option(LEXILEARN_BUILD_DOCS             "Build API documentation (Doxygen)"            OFF)

# ────────────────────────────────────────────────────────────────────────────────
#  Basic Compiler Configuration
# ────────────────────────────────────────────────────────────────────────────────
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

# Output directories
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# ------------------------------------------------------------------------------
#  Strict Compiler Warnings / Errors
# ------------------------------------------------------------------------------
include(CheckCCompilerFlag)
macro(add_warning_flag FLAG)
    check_c_compiler_flag(${FLAG} _has_flag)
    if (_has_flag)
        add_compile_options(${FLAG})
    endif ()
endmacro()

add_warning_flag("-Wall")
add_warning_flag("-Wextra")
add_warning_flag("-Wpedantic")
add_warning_flag("-Wshadow")
add_warning_flag("-Wconversion")
add_warning_flag("-Wdouble-promotion")
add_warning_flag("-Wnull-dereference")
add_warning_flag("-Wstrict-prototypes")
add_warning_flag("-Winline")

if (LEXILEARN_WARNINGS_AS_ERRORS)
    add_warning_flag("-Werror")
endif ()

# ------------------------------------------------------------------------------
#  Sanitizers
# ------------------------------------------------------------------------------
if (LEXILEARN_ENABLE_SANITIZER AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    message(STATUS "Sanitizers enabled")
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
    add_link_options(-fsanitize=address,undefined)
endif ()

# ------------------------------------------------------------------------------
#  Code Coverage
# ------------------------------------------------------------------------------
if (LEXILEARN_ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    message(STATUS "Coverage instrumentation enabled")
    add_compile_options(--coverage -O0)
    add_link_options(--coverage)
endif ()

# ────────────────────────────────────────────────────────────────────────────────
#  Third-party Dependencies
# ────────────────────────────────────────────────────────────────────────────────
include(FetchContent)

# --- cJSON ---------------------------------------------------------------------
FetchContent_Declare(
    cjson
    GIT_REPOSITORY https://github.com/DaveGamble/cJSON.git
    GIT_TAG        v1.7.17
)
FetchContent_MakeAvailable(cjson)

# --- SQLite3 -------------------------------------------------------------------
find_package(SQLite3 REQUIRED)

# --- Threads -------------------------------------------------------------------
set(THREADS_PREFER_PTHREAD_FLAG ON)
find_package(Threads REQUIRED)

# ────────────────────────────────────────────────────────────────────────────────
#  Configure Header Files
# ────────────────────────────────────────────────────────────────────────────────
configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/include/lexilearn/version.h.in
    ${CMAKE_CURRENT_BINARY_DIR}/generated/lexilearn/version.h
    @ONLY
)

include_directories(
    ${CMAKE_CURRENT_BINARY_DIR}/generated
)

# ────────────────────────────────────────────────────────────────────────────────
#  Source Files
# ────────────────────────────────────────────────────────────────────────────────
file(GLOB_RECURSE LEXILEARN_CORE_SOURCES
     CONFIGURE_DEPENDS
     src/controller/*.c
     src/model/*.c
     src/view/*.c
     src/shared/*.c
)

# ────────────────────────────────────────────────────────────────────────────────
#  Library Target
# ────────────────────────────────────────────────────────────────────────────────
add_library(lexilearn_core STATIC
            ${LEXILEARN_CORE_SOURCES})

target_include_directories(lexilearn_core
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${cjson_SOURCE_DIR}  # Public because callers may include <cjson/cJSON.h>
)

target_link_libraries(lexilearn_core
    PUBLIC
        cjson
        SQLite::SQLite3
        Threads::Threads
)

# Windows DLL export macro
if (WIN32 AND BUILD_SHARED_LIBS)
    target_compile_definitions(lexilearn_core PRIVATE LEXILEARN_EXPORTS)
endif ()

# ────────────────────────────────────────────────────────────────────────────────
#  Executable Target
# ────────────────────────────────────────────────────────────────────────────────
add_executable(lexilearn_orchestrator
               src/main.c)

target_link_libraries(lexilearn_orchestrator
    PRIVATE
        lexilearn_core
)

# ────────────────────────────────────────────────────────────────────────────────
#  Installation Rules
# ────────────────────────────────────────────────────────────────────────────────
include(GNUInstallDirs)

install(TARGETS lexilearn_core lexilearn_orchestrator
        EXPORT  lexilearn_targets
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install(DIRECTORY include/
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

# Exported CMake package
install(EXPORT lexilearn_targets
        FILE LexiLearnTargets.cmake
        NAMESPACE LexiLearn::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/LexiLearn
)

include(CMakePackageConfigHelpers)

write_basic_package_version_file(
    ${CMAKE_CURRENT_BINARY_DIR}/LexiLearnConfigVersion.cmake
    VERSION       ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion
)

configure_package_config_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/cmake/LexiLearnConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/LexiLearnConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/LexiLearn
)

install(FILES
    ${CMAKE_CURRENT_BINARY_DIR}/LexiLearnConfig.cmake
    ${CMAKE_CURRENT_BINARY_DIR}/LexiLearnConfigVersion.cmake
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/LexiLearn
)

# ────────────────────────────────────────────────────────────────────────────────
#  Testing
# ────────────────────────────────────────────────────────────────────────────────
if (LEXILEARN_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif ()

# ────────────────────────────────────────────────────────────────────────────────
#  Documentation
# ────────────────────────────────────────────────────────────────────────────────
if (LEXILEARN_BUILD_DOCS)
    find_package(Doxygen REQUIRED dot)
    set(DOXYGEN_IN  ${CMAKE_CURRENT_SOURCE_DIR}/docs/Doxyfile.in)
    set(DOXYGEN_OUT ${CMAKE_CURRENT_BINARY_DIR}/Doxyfile)
    configure_file(${DOXYGEN_IN} ${DOXYGEN_OUT} @ONLY)
    add_custom_target(
        docs
        COMMAND ${DOXYGEN_EXECUTABLE} ${DOXYGEN_OUT}
        WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
        COMMENT "Generating API documentation with Doxygen"
        VERBATIM
    )
endif ()

# ────────────────────────────────────────────────────────────────────────────────
#  Packaging (CPack)
# ────────────────────────────────────────────────────────────────────────────────
include(InstallRequiredSystemLibraries)

set(CPACK_PACKAGE_VENDOR             "LexiLearn Inc.")
set(CPACK_PACKAGE_CONTACT            "support@lexilearn.ai")
set(CPACK_PACKAGE_VERSION_MAJOR      ${PROJECT_VERSION_MAJOR})
set(CPACK_PACKAGE_VERSION_MINOR      ${PROJECT_VERSION_MINOR})
set(CPACK_PACKAGE_VERSION_PATCH      ${PROJECT_VERSION_PATCH})
set(CPACK_RESOURCE_FILE_LICENSE      "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE")
set(CPACK_GENERATOR                  "TGZ;ZIP")

include(CPack)