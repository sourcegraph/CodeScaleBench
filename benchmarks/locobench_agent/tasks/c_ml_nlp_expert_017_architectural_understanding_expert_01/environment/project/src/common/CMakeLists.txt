#========================================================================================
#  LexiLearn MVC Orchestrator – Common Library
#
#  This CMake configuration builds the `lexilearn_common` static/shared library that
#  provides logging, configuration‐parsing, metrics aggregation, and other reusable
#  utilities shared across the Controller / Model / View layers.
#
#  The file is intentionally self-contained so that other sub-projects can simply call
#     add_subdirectory(src/common)
#  and link against the `lexilearn::common` target while inheriting compile options,
#  sanitizers, warnings, and installation rules.
#========================================================================================

cmake_minimum_required (VERSION 3.18)

#-------------------------------------------------
# Options (user-tunable via -D on the CLI)
#-------------------------------------------------
option(LEXILEARN_BUILD_SHARED        "Build liblexilearn_common as a shared lib"   ON)
option(LEXILEARN_ENABLE_SANITIZER    "Compile with Address + Undefined Behaviour Sanitizers" OFF)
option(LEXILEARN_WARNINGS_AS_ERRORS  "Treat all warnings as errors"                ON)

#-------------------------------------------------
# Source files
#-------------------------------------------------
file (GLOB_RECURSE LEXILEARN_COMMON_SOURCES
      CONFIGURE_DEPENDS
      *.c
)

# Fail early if no sources are found
if (LEXILEARN_COMMON_SOURCES STREQUAL "")
    message (FATAL_ERROR "No source files found in ${CMAKE_CURRENT_SOURCE_DIR}")
endif ()

#-------------------------------------------------
# Library type & creation
#-------------------------------------------------
if (LEXILEARN_BUILD_SHARED)
    add_library (lexilearn_common SHARED ${LEXILEARN_COMMON_SOURCES})
else ()
    add_library (lexilearn_common STATIC ${LEXILEARN_COMMON_SOURCES})
endif ()

add_library (lexilearn::common ALIAS lexilearn_common)

#-------------------------------------------------
# Compile settings
#-------------------------------------------------
target_compile_features (lexilearn_common PUBLIC c_std_11)

target_include_directories (
    lexilearn_common
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include           # public headers
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/internal          # private headers
)

#------------------------ Warnings & Sanitizers -------------------------------
if (CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options (lexilearn_common PRIVATE
        -Wall -Wextra -Wpedantic
        -Wshadow -Wconversion -Wdouble-promotion
        -Wcast-qual -Wnull-dereference -Wformat=2
    )

    if (LEXILEARN_WARNINGS_AS_ERRORS)
        target_compile_options (lexilearn_common PRIVATE -Werror)
    endif ()

    # Address & Undefined Behavior Sanitizers
    if (LEXILEARN_ENABLE_SANITIZER)
        target_compile_options (lexilearn_common PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options    (lexilearn_common PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
    endif ()
elseif (MSVC)
    target_compile_options (lexilearn_common PRIVATE
        /W4 /permissive- /wd4201 /wd4100
    )
    if (LEXILEARN_WARNINGS_AS_ERRORS)
        target_compile_options (lexilearn_common PRIVATE /WX)
    endif ()
endif ()

#------------------------ Position-Independent Code ---------------------------
set_target_properties (lexilearn_common PROPERTIES
    POSITION_INDEPENDENT_CODE ON
)

#-------------------------------------------------
# Dependencies
#-------------------------------------------------
find_package (Threads REQUIRED)
find_package (jansson 2.13 QUIET)          # JSON parsing
find_package (m   QUIET)                   # math lib (fallback for non-POSIX)

# jansson is optional; fallback to bundled JSON if absent
if (jansson_FOUND)
    target_link_libraries (lexilearn_common PUBLIC jansson::jansson)
    target_compile_definitions (lexilearn_common PUBLIC HAVE_EXTERNAL_JANSSON=1)
else ()
    message (STATUS "jansson not found – using bundled minimalist JSON parser")
endif ()

target_link_libraries (lexilearn_common
    PUBLIC
        Threads::Threads
    PRIVATE
        ${CMAKE_DL_LIBS}                   # dlopen / dlsym on *nix
)

#-------------------------------------------------
# Code Coverage (GCC/Clang)
#-------------------------------------------------
option (LEXILEARN_COVERAGE "Enable coverage flags (Debug only)" OFF)
if (LEXILEARN_COVERAGE AND CMAKE_BUILD_TYPE STREQUAL "Debug")
    if (CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options (lexilearn_common PRIVATE --coverage)
        target_link_libraries   (lexilearn_common PRIVATE --coverage)
    endif ()
endif ()

#-------------------------------------------------
# Exported interface definitions
#-------------------------------------------------
target_compile_definitions (lexilearn_common
    PUBLIC
        $<$<CONFIG:Debug>:LEXILEARN_DEBUG_BUILD>
        LEXILEARN_VERSION_MAJOR=${PROJECT_VERSION_MAJOR}
        LEXILEARN_VERSION_MINOR=${PROJECT_VERSION_MINOR}
)

#-------------------------------------------------
# Installation Rules
#-------------------------------------------------
include (GNUInstallDirs)

install (
    TARGETS  lexilearn_common
    EXPORT   LexiLearnCommonTargets
    RUNTIME  DESTINATION ${CMAKE_INSTALL_BINDIR}
    LIBRARY  DESTINATION ${CMAKE_INSTALL_LIBDIR}
    ARCHIVE  DESTINATION ${CMAKE_INSTALL_LIBDIR}
    INCLUDES DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

install (
    DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/include/
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/lexilearn/common
    FILES_MATCHING PATTERN "*.h"
)

# Export the target description for downstream CMake projects
install (
    EXPORT  LexiLearnCommonTargets
    FILE    LexiLearnCommonTargets.cmake
    NAMESPACE lexilearn::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/LexiLearnCommon
)

#-------------------------------------------------
# Summary
#-------------------------------------------------
message (STATUS "-------------------------------------------------------------------")
message (STATUS " LexiLearn Common Library configured:")
message (STATUS "    Build type      : ${CMAKE_BUILD_TYPE}")
message (STATUS "    Shared library  : ${LEXILEARN_BUILD_SHARED}")
message (STATUS "    Sanitizers      : ${LEXILEARN_ENABLE_SANITIZER}")
message (STATUS "    Werror          : ${LEXILEARN_WARNINGS_AS_ERRORS}")
message (STATUS "    Coverage flags  : ${LEXILEARN_COVERAGE}")
if (jansson_FOUND)
    message (STATUS "    JSON            : external jansson ${jansson_VERSION}")
else ()
    message (STATUS "    JSON            : bundled")
endif ()
message (STATUS "-------------------------------------------------------------------")