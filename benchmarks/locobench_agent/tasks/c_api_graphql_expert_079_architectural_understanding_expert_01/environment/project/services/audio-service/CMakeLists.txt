# =========================== CMakeLists.txt ===========================
# SynestheticCanvas – Audio Service
#
# Build configuration for the Audio-Reactive micro-service responsible
# for translating low-level audio features into colour-space events that
# can be consumed by the API gateway (GraphQL & REST).  The service is
# implemented in C11 and depends on several third-party libraries.
#
# ---------------------  Minimum CMake version -------------------------
cmake_minimum_required(VERSION 3.18 FATAL_ERROR)

# ---------------------------  Project  --------------------------------
project(
    synesthetic_audio_service           # Unique name inside constellation
    VERSION 1.6.0                       # Semantic version (major.minor.patch)
    DESCRIPTION "Real-time audio analysis micro-service for SynestheticCanvas"
    LANGUAGES C                         # Pure-C implementation
)

# ----------------------  Global Configuration -------------------------
# Create compile_commands.json for IDEs / static analysis
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Use a modern C standard.  Make it configurable via cache.
set(SYN_AUDIO_C_STANDARD "11" CACHE STRING "C language standard to use")
set(CMAKE_C_STANDARD ${SYN_AUDIO_C_STANDARD})
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

# Disallow in-source builds to keep repo clean.
if("${CMAKE_SOURCE_DIR}" STREQUAL "${CMAKE_BINARY_DIR}")
    message(FATAL_ERROR
        "In-source builds are forbidden.  "
        "Please run 'cmake -S . -B build' instead.")
endif()

option(SYN_AUDIO_BUILD_SHARED      "Build shared library variant." ON)
option(SYN_AUDIO_ENABLE_TESTS      "Build unit & integration tests." ON)
option(SYN_AUDIO_WARN_AS_ERROR     "Treat warnings as errors." OFF)
option(SYN_AUDIO_ENABLE_SANITIZERS "Enable Address & Undefined behaviour Sanitisers." OFF)
option(SYN_AUDIO_ENABLE_COVERAGE   "Enable GCC/Clang coverage flags." OFF)

# --------------------------  Dependencies  ----------------------------
# 1. PortAudio – cross-platform audio I/O
find_package(PortAudio REQUIRED)
# 2. libsndfile – decode/encode audio files
find_package(SndFile REQUIRED)
# 3. Zstd (for compressed event payloads)
find_package(ZSTD REQUIRED)

# Optional: Prometheus client for metrics (if present, we'll expose them)
find_package(prometheus-cpp QUIET)

# ------------------------  Target: Library ----------------------------
set(AUDIO_SERVICE_SRC
    src/audio_bus.c
    src/audio_detector.c
    src/fft_adapter.c
    src/internal/bounded_queue.c
    include/synesthetic/audio_bus.h
    include/synesthetic/audio_detector.h
    include/synesthetic/fft_adapter.h
    include/synesthetic/internal/bounded_queue.h
)

add_library(synesthetic_audio
    ${AUDIO_SERVICE_SRC}
)

# Decide linkage type based on option
if(SYN_AUDIO_BUILD_SHARED)
    set_target_properties(synesthetic_audio PROPERTIES
        POSITION_INDEPENDENT_CODE ON
        WINDOWS_EXPORT_ALL_SYMBOLS ON
    )
else()
    set_target_properties(synesthetic_audio PROPERTIES
        STATIC_LIBRARY_OPTIONS "-DSTATIC_LINK"
    )
endif()

# -----------------------  Include & Linkage ---------------------------
target_include_directories(synesthetic_audio
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries(synesthetic_audio
    PUBLIC
        PortAudio::PortAudio
        SndFile::sndfile
        ZSTD::ZSTD
    PRIVATE
        $<$<BOOL:prometheus-cpp::core>:prometheus-cpp::core>
)

# -----------------------  Compiler Warnings ---------------------------
# Portable warning flags
if(MSVC)
    target_compile_options(synesthetic_audio PRIVATE /W4)
else()
    target_compile_options(synesthetic_audio PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(SYN_AUDIO_WARN_AS_ERROR)
    if(MSVC)
        target_compile_options(synesthetic_audio PRIVATE /WX)
    else()
        target_compile_options(synesthetic_audio PRIVATE -Werror)
    endif()
endif()

# -----------------------  Sanitizers / Coverage -----------------------
if(SYN_AUDIO_ENABLE_SANITIZERS AND NOT MSVC)
    target_compile_options(synesthetic_audio PRIVATE -fsanitize=address,undefined)
    target_link_options   (synesthetic_audio PRIVATE -fsanitize=address,undefined)
endif()

if(SYN_AUDIO_ENABLE_COVERAGE AND (CMAKE_C_COMPILER_ID MATCHES "Clang|GNU"))
    target_compile_options(synesthetic_audio PRIVATE --coverage -O0)
    target_link_options   (synesthetic_audio PRIVATE --coverage)
endif()

# ---------------------------  Executable ------------------------------
add_executable(audio-service src/main.c)
target_link_libraries(audio-service PRIVATE synesthetic_audio)

# Embed build info (Git SHA, build timestamp, version)
target_compile_definitions(audio-service PRIVATE
    SYN_BUILD_VERSION="${PROJECT_VERSION}"
    SYN_BUILD_TIMESTAMP="$<COMPILE_TIME:%Y-%m-%dT%H:%M:%S>"
)

# -----------------------------  Tests ---------------------------------
if(SYN_AUDIO_ENABLE_TESTS)
    enable_testing()
    # Fetch Catch2 via CMake's FetchContent
    include(FetchContent)
    FetchContent_Declare(
        catch2
        GIT_REPOSITORY https://github.com/catchorg/Catch2.git
        GIT_TAG        v3.5.1
    )
    FetchContent_MakeAvailable(catch2)

    add_executable(test_audio_service
        tests/test_fft_adapter.c
        tests/test_bounded_queue.c
    )
    target_link_libraries(test_audio_service PRIVATE
        synesthetic_audio
        Catch2::Catch2WithMain
    )
    add_test(NAME AudioServiceUnitTests COMMAND test_audio_service)
endif()

# ---------------------------  Install ---------------------------------
include(GNUInstallDirs)
install(
    TARGETS synesthetic_audio audio-service
    EXPORT  synesthetic_audioTargets
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    INCLUDES DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

install(
    DIRECTORY include/
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
    FILES_MATCHING PATTERN "*.h"
)

# Export targets for downstream usage
install(
    EXPORT synesthetic_audioTargets
    FILE   synesthetic_audioTargets.cmake
    NAMESPACE synesthetic::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/synesthetic_audio
)

# ----------------------------  Packaging ------------------------------
include(CPack)
set(CPACK_PACKAGE_VENDOR        "SynestheticCanvas")
set(CPACK_PACKAGE_CONTACT       "dev@synestheticcanvas.io")
set(CPACK_PACKAGE_DESCRIPTION   "Real-time audio analysis micro-service")
set(CPACK_PACKAGE_VERSION       ${PROJECT_VERSION})
set(CPACK_RESOURCE_FILE_LICENSE "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE")
set(CPACK_GENERATOR             "TGZ;ZIP")
cpack()

# -------------------------  Static Analysis ---------------------------
# Optional: clang-tidy integration (user's compiler must support it)
find_program(CLANG_TIDY_EXE NAMES clang-tidy)
if(CLANG_TIDY_EXE)
    set_target_properties(synesthetic_audio PROPERTIES C_CLANG_TIDY "${CLANG_TIDY_EXE}")
endif()

# ---------------------------  Summary ---------------------------------
message(STATUS "")
message(STATUS "SynestheticCanvas – Audio Service ${PROJECT_VERSION}")
message(STATUS "  Build Type              : ${CMAKE_BUILD_TYPE}")
message(STATUS "  C Standard              : C${CMAKE_C_STANDARD}")
message(STATUS "  Shared Library          : ${SYN_AUDIO_BUILD_SHARED}")
message(STATUS "  Tests Enabled           : ${SYN_AUDIO_ENABLE_TESTS}")
message(STATUS "  Sanitizers              : ${SYN_AUDIO_ENABLE_SANITIZERS}")
message(STATUS "  Coverage                : ${SYN_AUDIO_ENABLE_COVERAGE}")
message(STATUS "  Prometheus Metrics      : $<BOOL:prometheus-cpp::core>")
message(STATUS "")