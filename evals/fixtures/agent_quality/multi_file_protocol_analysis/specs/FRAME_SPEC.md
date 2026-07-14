# Frame Specification

Frames begin with marker `0x7E`. The two-byte payload length is encoded in little-endian order and excludes the header and checksum. A payload may contain at most 64 bytes.

The checksum is CRC-16/CCITT-FALSE, calculated over the length field followed by the payload. Its polynomial is `0x1021` and initial value is `0xFFFF`.
