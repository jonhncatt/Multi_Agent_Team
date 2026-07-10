#include "frame_parser.h"

#include <stdio.h>
#include <string.h>

static int failures = 0;

static void expect_status(const char *name, FrameParseStatus actual, FrameParseStatus expected)
{
    if (actual != expected) {
        printf("FAIL %s: expected status %d, got %d\n", name, (int)expected, (int)actual);
        failures += 1;
    }
}

static void expect_unchanged(const char *name, const ParsedFrame *actual, const ParsedFrame *expected)
{
    if (memcmp(actual, expected, sizeof(ParsedFrame)) != 0) {
        printf("FAIL %s: output changed on an error path\n", name);
        failures += 1;
    }
}

static ParsedFrame sentinel_frame(void)
{
    ParsedFrame value;
    unsigned int index = 0U;
    value.command = 0xE1U;
    value.payload_length = 0xE2U;
    while (index < FRAME_MAX_PAYLOAD) {
        value.payload[index] = (unsigned char)(0x80U + index);
        index += 1U;
    }
    return value;
}

static void test_null_arguments(void)
{
    const unsigned char valid[] = {0xA5U, 0x10U, 0x00U, 0x10U};
    ParsedFrame output = sentinel_frame();
    const ParsedFrame before = output;

    expect_status("null frame", frame_parse(0, 4U, &output), FRAME_PARSE_NULL_ARGUMENT);
    expect_unchanged("null frame", &output, &before);
    expect_status("null output", frame_parse(valid, 4U, 0), FRAME_PARSE_NULL_ARGUMENT);
}

static void test_validation_order_and_unchanged_output(void)
{
    ParsedFrame output = sentinel_frame();
    ParsedFrame before = output;
    const unsigned char too_short[] = {0x00U, 0x20U, 0x7FU};
    const unsigned char bad_preamble[] = {0x00U, 0x20U, 0x7FU, 0x00U};
    const unsigned char bad_length[] = {0xA5U, 0x20U, 0x02U, 0x11U, 0x33U};
    const unsigned char oversized[] = {0xA5U, 0x20U, 33U, 0x00U};
    const unsigned char bad_checksum[] = {0xA5U, 0x20U, 0x01U, 0x11U, 0x00U};

    expect_status("too short", frame_parse(too_short, 3U, &output), FRAME_PARSE_TOO_SHORT);
    expect_unchanged("too short", &output, &before);
    expect_status("bad preamble", frame_parse(bad_preamble, 4U, &output), FRAME_PARSE_BAD_PREAMBLE);
    expect_unchanged("bad preamble", &output, &before);
    expect_status("bad exact length", frame_parse(bad_length, 5U, &output), FRAME_PARSE_BAD_LENGTH);
    expect_unchanged("bad exact length", &output, &before);
    expect_status("oversized payload", frame_parse(oversized, 4U, &output), FRAME_PARSE_BAD_LENGTH);
    expect_unchanged("oversized payload", &output, &before);
    expect_status("bad checksum", frame_parse(bad_checksum, 5U, &output), FRAME_PARSE_BAD_CHECKSUM);
    expect_unchanged("bad checksum", &output, &before);
}

static void test_success_with_payload(void)
{
    const unsigned char frame[] = {0xA5U, 0x42U, 0x03U, 0x10U, 0x20U, 0x30U, 0x41U};
    ParsedFrame output = sentinel_frame();
    unsigned int index = 0U;

    expect_status("payload success", frame_parse(frame, 7U, &output), FRAME_PARSE_OK);
    if (output.command != 0x42U || output.payload_length != 3U) {
        printf("FAIL payload success: command or length mismatch\n");
        failures += 1;
    }
    if (output.payload[0] != 0x10U || output.payload[1] != 0x20U || output.payload[2] != 0x30U) {
        printf("FAIL payload success: payload mismatch\n");
        failures += 1;
    }
    index = 3U;
    while (index < FRAME_MAX_PAYLOAD) {
        if (output.payload[index] != 0U) {
            printf("FAIL payload success: unused payload byte %u was not zero\n", index);
            failures += 1;
            break;
        }
        index += 1U;
    }
}

static void test_zero_length_payload(void)
{
    const unsigned char frame[] = {0xA5U, 0x7EU, 0x00U, 0x7EU};
    ParsedFrame output = sentinel_frame();
    unsigned int index = 0U;

    expect_status("zero payload", frame_parse(frame, 4U, &output), FRAME_PARSE_OK);
    if (output.command != 0x7EU || output.payload_length != 0U) {
        printf("FAIL zero payload: command or length mismatch\n");
        failures += 1;
    }
    while (index < FRAME_MAX_PAYLOAD) {
        if (output.payload[index] != 0U) {
            printf("FAIL zero payload: payload byte %u was not zero\n", index);
            failures += 1;
            break;
        }
        index += 1U;
    }
}

int main(void)
{
    test_null_arguments();
    test_validation_order_and_unchanged_output();
    test_success_with_payload();
    test_zero_length_payload();
    if (failures != 0) {
        printf("%d test failure(s)\n", failures);
        return 1;
    }
    printf("All frame parser tests passed.\n");
    return 0;
}
