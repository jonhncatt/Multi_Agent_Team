#ifndef FRAME_PARSER_H
#define FRAME_PARSER_H

#define FRAME_MAX_PAYLOAD 32U

typedef enum FrameParseStatusTag {
    FRAME_PARSE_OK = 0,
    FRAME_PARSE_NULL_ARGUMENT = 1,
    FRAME_PARSE_TOO_SHORT = 2,
    FRAME_PARSE_BAD_PREAMBLE = 3,
    FRAME_PARSE_BAD_LENGTH = 4,
    FRAME_PARSE_BAD_CHECKSUM = 5
} FrameParseStatus;

typedef struct ParsedFrameTag {
    unsigned char command;
    unsigned char payload_length;
    unsigned char payload[FRAME_MAX_PAYLOAD];
} ParsedFrame;

FrameParseStatus frame_parse(
    const unsigned char *frame,
    unsigned int frame_size,
    ParsedFrame *out_frame
);

#endif
