/*
 * SynestheticCanvas - Audio Service Unit Tests
 *
 * File:    SynestheticCanvas/services/audio-service/tests/test_audio_service.c
 * License: MIT
 *
 * These unit-tests exercise the public interface exposed by the audio-service
 * component.  The test-suite is built with CMocka, a lightweight framework that
 * integrates well with modern CMake-based pipelines.
 *
 * Build example (from repository root):
 *
 *   mkdir -p build && cd build
 *   cmake -DSC_ENABLE_TESTS=ON ..
 *   make && ctest --output-on-failure
 */

#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <stdint.h>
#include <cmocka.h>

#include "../include/audio_service.h"   /* Production header under test */

/* ------------------------------------------------------------------------- */
/*                              Test Fixtures                                */
/* ------------------------------------------------------------------------- */

/*
 * The audio-service keeps global state (buffer pools, backend handles, etc.)
 * To guarantee deterministic behaviour, every test is isolated in its own
 * process (via cmocka_run_group_tests).  Still, we supply setup/teardown
 * helpers in case the implementation migrates to a context-object later on.
 */
static int
test_group_setup(void **state)
{
    (void) state;
    return 0;  /* Non-zero -> setup failure */
}

static int
test_group_teardown(void **state)
{
    (void) state;
    return 0;
}

/* ------------------------------------------------------------------------- */
/*                              Mocked Symbols                               */
/* ------------------------------------------------------------------------- */

/* The audio-service delegates low-level I/O to a pluggable backend.  */
int __wrap_audio_backend_open_device(const char *device_name,
                                     uint32_t       sample_rate,
                                     uint8_t        channels)
{
    check_expected_ptr(device_name);
    check_expected(sample_rate);
    check_expected(channels);
    /*
     * The backend normally returns an opaque handle (>0 on success).
     * We forward the value injected by the test through cmocka.
     */
    return (int) mock();
}

int __wrap_audio_backend_close_device(int device_handle)
{
    check_expected(device_handle);
    return (int) mock();
}

ssize_t __wrap_audio_backend_write(int device_handle,
                                   const void *frames,
                                   size_t      frame_count)
{
    check_expected(device_handle);
    check_expected_ptr(frames);
    check_expected(frame_count);
    return (ssize_t) mock();
}

/* ------------------------------------------------------------------------- */
/*                             Helper Utilities                              */
/* ------------------------------------------------------------------------- */

/* Provide a canonical configuration used by multiple test-cases. */
static audio_service_config_t
canonical_config(void)
{
    return (audio_service_config_t) {
        .sample_rate = 48000,
        .channels    = 2,
        .device_name = "UnitTest-Device"
    };
}

/* ------------------------------------------------------------------------- */
/*                               Test-Cases                                  */
/* ------------------------------------------------------------------------- */

/* 1. Happy-path initialisation */
static void
test_audio_service_init_success(void **state)
{
    (void) state;

    audio_service_config_t cfg = canonical_config();

    /* Expect a backend call with the same parameters we pass. */
    expect_string(__wrap_audio_backend_open_device, device_name, cfg.device_name);
    expect_value(__wrap_audio_backend_open_device,  sample_rate, cfg.sample_rate);
    expect_value(__wrap_audio_backend_open_device,  channels,    cfg.channels);
    will_return(__wrap_audio_backend_open_device,  42); /* Fake handle */

    assert_int_equal(audio_service_init(&cfg), 0);
    assert_true(audio_service_is_ready());

    /* Ensure we can shut the service down afterwards. */
    expect_value(__wrap_audio_backend_close_device, device_handle, 42);
    will_return(__wrap_audio_backend_close_device,  0);

    assert_int_equal(audio_service_shutdown(), 0);
}

/* 2. Invalid configuration (sample_rate == 0) must fail */
static void
test_audio_service_init_invalid_config(void **state)
{
    (void) state;

    audio_service_config_t cfg = canonical_config();
    cfg.sample_rate = 0;               /* Invalid */

    /* Backend must NOT be touched when validation fails. */
    assert_int_not_equal(audio_service_init(&cfg), 0);
    assert_false(audio_service_is_ready());
}

/* 3. Volume setter clamps to [0.0, 1.0] */
static void
test_audio_service_set_volume_clamping(void **state)
{
    (void) state;

    audio_service_config_t cfg = canonical_config();

    /* Prepare a successful init path (re-uses mocks) */
    expect_string(__wrap_audio_backend_open_device, device_name, cfg.device_name);
    expect_value(__wrap_audio_backend_open_device,  sample_rate, cfg.sample_rate);
    expect_value(__wrap_audio_backend_open_device,  channels,    cfg.channels);
    will_return(__wrap_audio_backend_open_device,  7);

    assert_int_equal(audio_service_init(&cfg), 0);

    /* Set an out-of-range volume; expect clamped internally to 1.0 */
    assert_int_equal(audio_service_set_volume(+3.14f), 0);
    assert_float_equal(audio_service_get_volume(), 1.0f, 0.0001);

    /* Likewise for negative. */
    assert_int_equal(audio_service_set_volume(-0.5f), 0);
    assert_float_equal(audio_service_get_volume(), 0.0f, 0.0001);

    /* Cleanup */
    expect_value(__wrap_audio_backend_close_device, device_handle, 7);
    will_return(__wrap_audio_backend_close_device,  0);
    assert_int_equal(audio_service_shutdown(), 0);
}

/* 4. Passing NULL to process_stream returns -EINVAL */
static void
test_audio_service_process_stream_null_ptr(void **state)
{
    (void) state;

    audio_service_config_t cfg = canonical_config();

    expect_string(__wrap_audio_backend_open_device, device_name, cfg.device_name);
    expect_value(__wrap_audio_backend_open_device,  sample_rate, cfg.sample_rate);
    expect_value(__wrap_audio_backend_open_device,  channels,    cfg.channels);
    will_return(__wrap_audio_backend_open_device,  13);

    assert_int_equal(audio_service_init(&cfg), 0);

    assert_int_equal(audio_service_process_stream(NULL, 256), -EINVAL);

    /* Cleanup */
    expect_value(__wrap_audio_backend_close_device, device_handle, 13);
    will_return(__wrap_audio_backend_close_device,  0);
    assert_int_equal(audio_service_shutdown(), 0);
}

/* 5. process_stream relays buffer to backend */
static void
test_audio_service_process_stream_success(void **state)
{
    (void) state;

    audio_service_config_t cfg = canonical_config();

    expect_string(__wrap_audio_backend_open_device, device_name, cfg.device_name);
    expect_value(__wrap_audio_backend_open_device,  sample_rate, cfg.sample_rate);
    expect_value(__wrap_audio_backend_open_device,  channels,    cfg.channels);
    will_return(__wrap_audio_backend_open_device,  99);

    assert_int_equal(audio_service_init(&cfg), 0);

    /* Generate dummy audio frames */
    uint16_t dummy_frames[512] = {0};

    expect_value(__wrap_audio_backend_write, device_handle, 99);
    expect_any(__wrap_audio_backend_write,   frames);
    expect_value(__wrap_audio_backend_write, frame_count, 512);
    will_return(__wrap_audio_backend_write,  512); /* Written successfully */

    assert_int_equal(audio_service_process_stream(dummy_frames, 512), 0);

    /* Cleanup */
    expect_value(__wrap_audio_backend_close_device, device_handle, 99);
    will_return(__wrap_audio_backend_close_device,  0);
    assert_int_equal(audio_service_shutdown(), 0);
}

/* ------------------------------------------------------------------------- */
/*                                 Runner                                    */
/* ------------------------------------------------------------------------- */

int
main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_audio_service_init_success),
        cmocka_unit_test(test_audio_service_init_invalid_config),
        cmocka_unit_test(test_audio_service_set_volume_clamping),
        cmocka_unit_test(test_audio_service_process_stream_null_ptr),
        cmocka_unit_test(test_audio_service_process_stream_success),
    };

    return cmocka_run_group_tests(tests,
                                  test_group_setup,
                                  test_group_teardown);
}