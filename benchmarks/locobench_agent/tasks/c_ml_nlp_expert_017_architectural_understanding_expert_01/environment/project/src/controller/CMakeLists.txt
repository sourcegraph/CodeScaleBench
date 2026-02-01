cmake_minimum_required(VERSION 3.16)

#--------------------------------------------------------------------------
#  LexiLearn MVC Orchestrator – Controller Module
#
#  This CMakeLists.txt builds the Controller component, responsible for
#  orchestrating NLP/ML pipelines, LMS ingestion, experiment tracking, and
#  automated model-drift handling.  The target is built as a static library
#  that other tiers (e.g., CLI, REST-gateway, or View layer) can link to.
#--------------------------------------------------------------------------

project(lexilearn_controller
        VERSION 2.3.1
        LANGUAGES C)

#--------------------------------------------------------------------------
#  Build Options
#--------------------------------------------------------------------------

option(LEXILEARN_ENABLE_COVERAGE "Compile Controller with gcov coverage info" OFF)
option(LEXILEARN_ENABLE_SANITIZERS "Compile Controller with Address/UB sanitizers" OFF)

set(CMAKE_C_STANDARD           11)
set(CMAKE_C_STANDARD_REQUIRED  ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)      # For safe static-to-shared linking

#--------------------------------------------------------------------------
#  Compiler Flags
#--------------------------------------------------------------------------

set(CONTROLLER_WARN_FLAGS
    -Wall -Wextra -Werror -Wpedantic
    -Wcast-align -Wformat=2 -Wshadow
    -Wstrict-prototypes -Wmissing-prototypes
    -Wpointer-arith -Wunreachable-code)

if (CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    set(CONTROLLER_OPT_FLAGS   "-O3 -flto")
endif()

if (LEXILEARN_ENABLE_SANITIZERS AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    set(CONTROLLER_SAN_FLAGS "-fsanitize=address,undefined -fno-omit-frame-pointer")
endif()

#--------------------------------------------------------------------------
#  External Dependencies
#--------------------------------------------------------------------------

find_package(Threads REQUIRED)
find_package(CURL    REQUIRED)          # LMS REST ingestion
find_package(OpenSSL REQUIRED)          # TLS + JWT signing
find_package(PkgConfig REQUIRED)

# json-c is used for lightweight configuration and telemetry payloads
pkg_check_modules(JSONC REQUIRED json-c)

# Model layer (Strategy Pattern) – exported by sibling build
find_package(lexilearn_model REQUIRED CONFIG)

#--------------------------------------------------------------------------
#  Source & Header Files
#--------------------------------------------------------------------------

set(CONTROLLER_SRC
    orchestrator.c
    pipeline.c
    drift_monitor.c
    retrain_scheduler.c
    lms_adapter.c
    utils/logging.c
)

set(CONTROLLER_HEADERS
    orchestrator.h
    pipeline.h
    drift_monitor.h
    retrain_scheduler.h
    lms_adapter.h
    utils/logging.h
)

#--------------------------------------------------------------------------
#  Library Target
#--------------------------------------------------------------------------

add_library(lexilearn_controller STATIC
            ${CONTROLLER_SRC}
            ${CONTROLLER_HEADERS})

target_include_directories(lexilearn_controller
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/utils>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/lexilearn/controller>
        ${JSONC_INCLUDEDIR}
)

target_compile_options(lexilearn_controller PRIVATE
        ${CONTROLLER_WARN_FLAGS}
        ${CONTROLLER_OPT_FLAGS}
        ${CONTROLLER_SAN_FLAGS})

target_link_options(lexilearn_controller PRIVATE
        ${CONTROLLER_SAN_FLAGS})

target_link_libraries(lexilearn_controller
    PUBLIC
        lexilearn_model::lexilearn_model
        CURL::libcurl
        OpenSSL::SSL
        OpenSSL::Crypto
        Threads::Threads
        ${JSONC_LIBRARIES}
)

set_target_properties(lexilearn_controller PROPERTIES
    VERSION   ${PROJECT_VERSION}
    SOVERSION ${PROJECT_VERSION_MAJOR}
)

#--------------------------------------------------------------------------
#  Code Coverage (GCC only)
#--------------------------------------------------------------------------

if (LEXILEARN_ENABLE_COVERAGE AND CMAKE_C_COMPILER_ID STREQUAL "GNU")
    target_compile_options(lexilearn_controller PRIVATE --coverage)
    target_link_options   (lexilearn_controller PRIVATE --coverage)
endif()

#--------------------------------------------------------------------------
#  Static Analysis & Formatting Helpers
#--------------------------------------------------------------------------

# clang-format -------------------------------------------------------------
find_program(CLANG_FORMAT_EXE NAMES clang-format)
if (CLANG_FORMAT_EXE)
    add_custom_target(format
        COMMAND ${CLANG_FORMAT_EXE}
            -style=file
            -i ${CONTROLLER_SRC} ${CONTROLLER_HEADERS}
        COMMENT "Running clang-format on Controller sources")
endif()

# cppcheck ----------------------------------------------------------------
find_program(CPPCHECK_EXE NAMES cppcheck)
if (CPPCHECK_EXE)
    add_custom_target(static-analysis
        COMMAND ${CPPCHECK_EXE}
            --enable=all --inconclusive --force
            --std=c11 --language=c
            --error-exitcode=1
            --suppress=missingIncludeSystem
            ${CMAKE_CURRENT_SOURCE_DIR}
        COMMENT "Running cppcheck on Controller sources")
endif()

#--------------------------------------------------------------------------
#  Installation
#--------------------------------------------------------------------------

include(GNUInstallDirs)

install(TARGETS lexilearn_controller
        EXPORT  lexilearn_controllerTargets
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

install(DIRECTORY .
        DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/lexilearn/controller
        FILES_MATCHING PATTERN "*.h")

install(EXPORT lexilearn_controllerTargets
        FILE      lexilearn_controllerTargets.cmake
        NAMESPACE lexilearn_controller::
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/lexilearn_controller)

#--------------------------------------------------------------------------
#  Unit Tests
#--------------------------------------------------------------------------

include(CTest)               # Enables BUILD_TESTING option
if (BUILD_TESTING)
    add_subdirectory(tests)  # tests/CMakeLists.txt must exist
endif()
