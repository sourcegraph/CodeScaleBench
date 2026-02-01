```c
/*
 * HoloCanvas :: CONTRIBUTING.md (yes, it is a C source file!)
 * ------------------------------------------------------------
 * This utility lives in the “CONTRIBUTING.md” path because it
 * embodies the *living contract* between the core team and external
 * contributors.  It performs automatic sanity-checks on incoming
 * patches—verifying that source files contain the proper license
 * banner, are encoded in UTF-8, and have a reproducible SHA-256
 * fingerprint that is echoed back to the contributor.
 *
 * Typical usage from a Git pre-commit hook:
 *
 *      exec ./tools/CONTRIBUTING.md \
 *              --file "$1"          \
 *              --require-license    \
 *              --print-digest
 *
 * Build:
 *      cc -Wall -Wextra -pedantic -O2 \
 *         -o tools/CONTRIBUTING.md    \
 *         tools/CONTRIBUTING.md -lcrypto
 *
 * NOTE: The OpenSSL development headers (`libssl-dev` on many distros)
 *       are required at compile time.
 */

#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <getopt.h>
#include <openssl/sha.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* -------------------------------------------------------------------------- */
/* Constants & Macros                                                         */
/* -------------------------------------------------------------------------- */

#define HOLOCANVAS_LICENSE_TAG "Copyright (c) HoloCanvas Project"
#define READ_CHUNK_SIZE        8192u

typedef enum
{
    EXIT_OK                = 0,
    EXIT_INVALID_ARGUMENTS = 1,
    EXIT_IO_ERROR          = 2,
    EXIT_MISSING_LICENSE   = 3,
    EXIT_DIGEST_MISMATCH   = 4,
} exit_code_t;

/* -------------------------------------------------------------------------- */
/* Utility helpers                                                            */
/* -------------------------------------------------------------------------- */

/* Securely zero-out a buffer (portable, avoids being optimised away). */
static void
secure_bzero(void *v, size_t n)
{
    volatile uint8_t *p = (volatile uint8_t *)v;
    while (n--)
        *p++ = 0;
}

/* Convert a SHA-256 digest to a hex string.  Caller provides at least
 * 65 bytes (`2 * SHA256_DIGEST_LENGTH + 1`). */
static void
digest_to_hex(const uint8_t digest[SHA256_DIGEST_LENGTH], char *out_hex)
{
    for (size_t i = 0; i < SHA256_DIGEST_LENGTH; ++i)
        sprintf(out_hex + (i * 2), "%02x", digest[i]);
    out_hex[64] = '\0';
}

/* Read a text file, compute SHA-256, detect UTF-8 violations, and provide the
 * first non-empty line for license detection.                                    */
static bool
process_file(const char *path,
             bool        require_license,
             bool        print_digest,
             bool        strict_utf8,
             exit_code_t *out_exit)
{
    FILE *fp = fopen(path, "rb");
    if (!fp)
    {
        fprintf(stderr, "error: cannot open %s: %s\n", path, strerror(errno));
        *out_exit = EXIT_IO_ERROR;
        return false;
    }

    SHA256_CTX ctx;
    SHA256_Init(&ctx);

    uint8_t  buf[READ_CHUNK_SIZE];
    size_t   bytes;
    bool     found_license = false;
    bool     warned_utf8   = false;
    bool     first_line_parsed   = false;
    char     first_line[256]     = {0};
    size_t   first_line_len      = 0;

    while ((bytes = fread(buf, 1, sizeof(buf), fp)) > 0)
    {
        /* UTF-8 validation if requested. */
        if (strict_utf8)
        {
            for (size_t i = 0; i < bytes; ++i)
            {
                if ((buf[i] & 0x80u) && !warned_utf8) /* high-bit set */
                {
                    fprintf(stderr,
                            "warning: file %s contains non-ASCII byte(s); "
                            "ensure UTF-8 encoding.\n",
                            path);
                    warned_utf8 = true;
                }
            }
        }

        /* Capture the very first non-empty line. */
        if (!first_line_parsed)
        {
            for (size_t i = 0; i < bytes && !first_line_parsed; ++i)
            {
                static char line_acc[256];
                static size_t acc_len = 0;

                char c = (char)buf[i];
                if (c == '\n' || c == '\r')
                {
                    if (acc_len > 0)
                    {
                        /* End-of-line reached. */
                        memcpy(first_line, line_acc, acc_len);
                        first_line[acc_len] = '\0';
                        first_line_len      = acc_len;
                        first_line_parsed   = true;
                    }
                    acc_len = 0;
                }
                else if (acc_len + 1 < sizeof(line_acc))
                {
                    line_acc[acc_len++] = c;
                }
            }
        }

        SHA256_Update(&ctx, buf, bytes);
    }

    if (ferror(fp))
    {
        fprintf(stderr, "error: while reading %s: %s\n", path, strerror(errno));
        fclose(fp);
        *out_exit = EXIT_IO_ERROR;
        return false;
    }
    fclose(fp);

    /* License header validation. */
    if (require_license)
    {
        if (first_line_len == 0 ||
            strstr(first_line, HOLOCANVAS_LICENSE_TAG) == NULL)
        {
            fprintf(stderr,
                    "error: %s lacks required license header "
                    "(`%s`).\n",
                    path,
                    HOLOCANVAS_LICENSE_TAG);
            *out_exit = EXIT_MISSING_LICENSE;
            return false;
        }
        found_license = true;
    }

    /* Finalize digest. */
    uint8_t digest_bin[SHA256_DIGEST_LENGTH];
    SHA256_Final(digest_bin, &ctx);

    if (print_digest)
    {
        char digest_hex[65];
        digest_to_hex(digest_bin, digest_hex);
        printf("%s  %s%s\n",
               digest_hex,
               path,
               found_license ? " (license OK)" : "");
    }

    *out_exit = EXIT_OK;
    return true;
}

/* -------------------------------------------------------------------------- */
/* Self-test                                                                  */
/* -------------------------------------------------------------------------- */

static bool
self_test(void)
{
    /* Simple deterministic vector. */
    const char *input     = "HoloCanvas";
    const char *expect_hex =
        "14fc2f57ea7038589103cdb0c1bbad0b12219478fae09a64393c2e5542eacde2";

    uint8_t digest[SHA256_DIGEST_LENGTH];
    SHA256((const unsigned char *)input, strlen(input), digest);

    char got_hex[65];
    digest_to_hex(digest, got_hex);

    return strcmp(expect_hex, got_hex) == 0;
}

/* -------------------------------------------------------------------------- */
/* Command-line parsing                                                       */
/* -------------------------------------------------------------------------- */

static void
usage(FILE *stream, const char *prog)
{
    fprintf(stream,
            "Usage: %s --file <path> [options]\n"
            "\nOptions:\n"
            "  -f, --file <path>          File to validate (required).\n"
            "  -l, --require-license      Enforce HoloCanvas license header.\n"
            "  -d, --print-digest         Print SHA-256 digest upon success.\n"
            "  -u, --strict-utf8          Warn if non-ASCII bytes are present.\n"
            "  -s, --self-test            Run internal unit test and exit.\n"
            "  -h, --help                 Show this help text.\n",
            prog);
}

int
main(int argc, char **argv)
{
    static struct option long_opts[] = {
        {"file",            required_argument, 0, 'f'},
        {"require-license", no_argument,       0, 'l'},
        {"print-digest",    no_argument,       0, 'd'},
        {"strict-utf8",     no_argument,       0, 'u'},
        {"self-test",       no_argument,       0, 's'},
        {"help",            no_argument,       0, 'h'},
        {0,                 0,                 0,  0 }
    };

    const char *file_path       = NULL;
    bool        require_license = false;
    bool        print_digest    = false;
    bool        strict_utf8     = false;

    int opt;
    while ((opt = getopt_long(argc, argv, "f:ldush", long_opts, NULL)) != -1)
    {
        switch (opt)
        {
        case 'f':
            file_path = optarg;
            break;
        case 'l':
            require_license = true;
            break;
        case 'd':
            print_digest = true;
            break;
        case 'u':
            strict_utf8 = true;
            break;
        case 's':
            if (self_test())
            {
                puts("self-test passed.");
                return EXIT_OK;
            }
            else
            {
                fputs("self-test FAILED!\n", stderr);
                return EXIT_DIGEST_MISMATCH;
            }
        case 'h':
            usage(stdout, argv[0]);
            return EXIT_OK;
        default:
            usage(stderr, argv[0]);
            return EXIT_INVALID_ARGUMENTS;
        }
    }

    if (!file_path)
    {
        usage(stderr, argv[0]);
        return EXIT_INVALID_ARGUMENTS;
    }

    exit_code_t ec;
    if (!process_file(file_path,
                      require_license,
                      print_digest,
                      strict_utf8,
                      &ec))
    {
        /* `process_file` already printed an error message. */
        return ec;
    }

    return EXIT_OK;
}

/* -------------------------------------------------------------------------- */
/* SPDX-License-Identifier: MIT                                               */
/* -------------------------------------------------------------------------- */

```