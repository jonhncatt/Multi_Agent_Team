#include "frame_parser.h"

FrameParseStatus frame_parse(
    const unsigned char *frame,
    unsigned int frame_size,
    ParsedFrame *out_frame
)
{
    (void)frame;
    (void)frame_size;
    (void)out_frame;
    return FRAME_PARSE_TOO_SHORT;
}
