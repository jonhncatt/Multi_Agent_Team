# Protocol frame parser specification

Implement `frame_parse` in `src/frame_parser.cpp`.

## Frame layout

| Byte | Meaning |
|---|---|
| `0` | Preamble, always `0xA5` |
| `1` | Command byte |
| `2` | Payload length `N`, from `0` through `FRAME_MAX_PAYLOAD` |
| `3..(3 + N - 1)` | Payload bytes |
| `3 + N` | Checksum |

The exact frame size is `N + 4`. Extra trailing bytes are not allowed.

The checksum is the XOR of the command byte, the payload-length byte, and every payload byte. The preamble is not included.

## Required validation order

Return the first applicable status in this order:

1. `FRAME_PARSE_NULL_ARGUMENT` when `frame` or `out_frame` is null.
2. `FRAME_PARSE_TOO_SHORT` when `frame_size` is less than four bytes.
3. `FRAME_PARSE_BAD_PREAMBLE` when byte zero is not `0xA5`.
4. `FRAME_PARSE_BAD_LENGTH` when `N` exceeds `FRAME_MAX_PAYLOAD` or `frame_size` is not exactly `N + 4`.
5. `FRAME_PARSE_BAD_CHECKSUM` when the checksum byte is wrong.
6. `FRAME_PARSE_OK` otherwise.

## Output contract

- On every error, `out_frame` must remain byte-for-byte unchanged.
- On success, set `command` and `payload_length`, copy exactly `N` payload bytes, and zero all unused bytes in `payload`.
- A zero-length payload is valid.
