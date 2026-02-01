```c
/**
 * SynestheticCanvas – Narrative Service
 * Unit-Tests
 *
 * File: SynestheticCanvas/services/narrative-service/tests/test_narrative_service.c
 *
 * These tests exercise the public contract exposed by narrative_service.[ch].
 * They rely on cmocka for assertions and for stubbing the repository layer.
 *
 * Author: SynestheticCanvas Core Team
 * License: MIT
 */

#define _GNU_SOURCE /* Needed for asprintf */
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <cmocka.h>

#include "narrative_service.h"   /* Production header */

/* ------------------------------------------------------------------------- */
/* Helper types mirroring production data-structures.                        */
/* ------------------------------------------------------------------------- */

#ifndef NARRATIVE_TYPES_H
#define NARRATIVE_TYPES_H

/* Keep this in sync with production code – simplified for testing. */
typedef struct scn_scene {
    char     id[64];
    char     branch_id[64];
    uint32_t version;
    char    *payload;            /* JSON-encoded scene data */
} scene_t;

#endif /* NARRATIVE_TYPES_H */

/* ------------------------------------------------------------------------- */
/* Repository-layer stubs.
 *
 *  Production code links against real repository implementations (PostgreSQL,
 *  Redis, etc).  For unit-testing the service layer we intercept those calls
 *  and provide deterministic behaviour through cmocka’s expect_* / will_return.
 * ------------------------------------------------------------------------- */

/* Create a new branch record. */
int narrative_repo_create_branch(const char *story_id,
                                 const char *parent_branch_id,
                                 const char *name,
                                 char       *out_branch_id,
                                 size_t      out_size)
{
    check_expected_ptr(story_id);
    check_expected_ptr(name);
    if (parent_branch_id != NULL) {
        check_expected_ptr(parent_branch_id);
    }

    int rc = mock_type(int);
    if (rc == 0) {
        const char *fake_id = mock_type(const char *);
        strncpy(out_branch_id, fake_id, out_size);
    }
    return rc;
}

/* Fetch a single scene, used by get_scene(). */
static int repo_fetch_scene_call_count = 0;
int narrative_repo_fetch_scene(const char *scene_id, scene_t *out_scene)
{
    repo_fetch_scene_call_count++;

    check_expected_ptr(scene_id);
    int rc = mock_type(int);

    if (rc == 0 && out_scene != NULL) {
        const scene_t *template_scene = mock_type(const scene_t *);
        memcpy(out_scene, template_scene, sizeof(scene_t));
    }
    return rc;
}

/* List scenes with pagination. */
int narrative_repo_list_scenes(const char *branch_id,
                               size_t       offset,
                               size_t       limit,
                               scene_t     *out_scenes,
                               size_t      *out_count)
{
    check_expected_ptr(branch_id);
    check_expected(offset == (size_t)mock_type(int));
    check_expected(limit  == (size_t)mock_type(int));

    int rc = mock_type(int);
    if (rc == 0) {
        size_t fake_count = (size_t)mock_type(int);
        *out_count = fake_count;

        const scene_t *template_scene = mock_type(const scene_t *);
        for (size_t i = 0; i < fake_count && i < limit; ++i) {
            memcpy(&out_scenes[i], template_scene, sizeof(scene_t));
        }
    }
    return rc;
}

/* Update choice record (simplified). */
int narrative_repo_update_choice(const char *choice_id,
                                 const char *next_scene_id,
                                 uint32_t    expected_version)
{
    check_expected_ptr(choice_id);
    check_expected_ptr(next_scene_id);
    check_expected(expected_version == (uint32_t)mock_type(int));

    return mock_type(int);
}

/* ------------------------------------------------------------------------- */
/* Test fixtures                                                             */
/* ------------------------------------------------------------------------- */

static int setup(void **state)
{
    (void)state;
    repo_fetch_scene_call_count = 0;
    return 0;
}

static int teardown(void **state)
{
    (void)state;
    return 0;
}

/* ------------------------------------------------------------------------- */
/* Test cases                                                                */
/* ------------------------------------------------------------------------- */

/* Happy path: branch creation succeeds and returns the new identifier. */
static void test_create_branch_success(void **state)
{
    (void)state;

    const char story_id[] = "story-xyz";
    const char parent_id[] = "root";
    const char branch_name[] = "Alternative Ending";
    const char expected_branch_id[] = "branch-123";

    /* Repository expectations */
    expect_string(narrative_repo_create_branch, story_id, story_id);
    expect_string(narrative_repo_create_branch, parent_branch_id, parent_id);
    expect_string(narrative_repo_create_branch, name, branch_name);
    will_return(narrative_repo_create_branch, 0);                /* rc */
    will_return(narrative_repo_create_branch, expected_branch_id);

    char actual_branch_id[64] = {0};
    int rc = narrative_service_create_branch(story_id,
                                             parent_id,
                                             branch_name,
                                             actual_branch_id,
                                             sizeof(actual_branch_id));

    assert_int_equal(rc, NARRSVC_SUCCESS);
    assert_string_equal(actual_branch_id, expected_branch_id);
}

/* Negative test: invalid input propagates to caller without hitting repo. */
static void test_create_branch_invalid_input(void **state)
{
    (void)state;

    /* Name is NULL – should fail fast. */
    char dummy_id[64];
    int rc = narrative_service_create_branch("story-xyz",
                                             NULL,
                                             NULL,
                                             dummy_id,
                                             sizeof(dummy_id));

    assert_int_equal(rc, NARRSVC_ERR_INVALID_INPUT);
}

/* Caching behaviour: repository is hit only on first call. */
static void test_get_scene_cached(void **state)
{
    (void)state;

    const char scene_id[] = "scene-0001";
    scene_t template_scene = {
        .id       = "scene-0001",
        .branch_id = "branch-root",
        .version  = 1,
        .payload  = "{\"text\":\"Hello world\"}"
    };

    /* First invocation – expect repo access. */
    expect_string(narrative_repo_fetch_scene, scene_id, scene_id);
    will_return(narrative_repo_fetch_scene, 0);              /* rc  */
    will_return(narrative_repo_fetch_scene, &template_scene);

    scene_t out1 = {0};
    int rc1 = narrative_service_get_scene(scene_id, &out1);
    assert_int_equal(rc1, NARRSVC_SUCCESS);
    assert_string_equal(out1.id, "scene-0001");

    /* Second invocation – no expectation set, should be cached. */
    scene_t out2 = {0};
    int rc2 = narrative_service_get_scene(scene_id, &out2);
    assert_int_equal(rc2, NARRSVC_SUCCESS);
    assert_string_equal(out2.id, "scene-0001");

    /* Verify that the underlying storage was queried exactly once. */
    assert_int_equal(repo_fetch_scene_call_count, 1);
}

/* Pagination: ensure correct offset/limit are forwarded and counts returned. */
static void test_list_scenes_pagination(void **state)
{
    (void)state;

    const char branch_id[] = "branch-root";
    const size_t offset = 10;
    const size_t limit  = 5;
    const size_t expected_count = 5;

    scene_t template_scene = {
        .id        = "scene-template",
        .branch_id = "branch-root",
        .version   = 1,
        .payload   = "{\"text\":\"Placeholder\"}"
    };

    /* Expectations */
    expect_string(narrative_repo_list_scenes, branch_id, branch_id);
    will_check(narrative_repo_list_scenes, offset); /* custom helper macro */
    will_check(narrative_repo_list_scenes, limit);
    /* Provide rc, total_count, and scene template */
    will_return(narrative_repo_list_scenes, 0);                   /* rc */
    will_return(narrative_repo_list_scenes, expected_count);      /* out_count */
    will_return(narrative_repo_list_scenes, &template_scene);

    scene_t results[5] = {0};
    size_t  result_count = 0;

    int rc = narrative_service_list_scenes(branch_id,
                                           offset,
                                           limit,
                                           results,
                                           &result_count);

    assert_int_equal(rc, NARRSVC_SUCCESS);
    assert_int_equal(result_count, expected_count);
    for (size_t i = 0; i < result_count; ++i) {
        assert_string_equal(results[i].branch_id, branch_id);
    }
}

/* Error propagation: repository failure is surfaced to service caller. */
static void test_update_choice_error_propagation(void **state)
{
    (void)state;

    const char choice_id[] = "choice-01";
    const char next_scene[] = "scene-9999";
    const uint32_t expected_ver = 2;

    expect_string(narrative_repo_update_choice, choice_id, choice_id);
    expect_string(narrative_repo_update_choice, next_scene_id, next_scene);
    expect_value(narrative_repo_update_choice, expected_version, expected_ver);
    will_return(narrative_repo_update_choice, NARRSVC_ERR_CONFLICT);

    int rc = narrative_service_update_choice(choice_id, next_scene, expected_ver);
    assert_int_equal(rc, NARRSVC_ERR_CONFLICT);
}

/* ------------------------------------------------------------------------- */
/* Test runner                                                               */
/* ------------------------------------------------------------------------- */

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test_setup_teardown(test_create_branch_success,
                                        setup, teardown),
        cmocka_unit_test(test_create_branch_invalid_input),
        cmocka_unit_test_setup_teardown(test_get_scene_cached,
                                        setup, teardown),
        cmocka_unit_test_setup_teardown(test_list_scenes_pagination,
                                        setup, teardown),
        cmocka_unit_test(test_update_choice_error_propagation),
    };

    return cmocka_run_group_tests_name("SynestheticCanvas Narrative-Service",
                                       tests, NULL, NULL);
}
```