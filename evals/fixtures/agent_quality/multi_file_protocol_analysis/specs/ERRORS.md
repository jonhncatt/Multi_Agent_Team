# Parser Error Mapping

- `0`: success
- `-1`: invalid argument
- `-2`: truncated frame
- `-3`: checksum mismatch
- `-4`: payload length exceeds the 64-byte limit

Public documentation must use the symbolic name `FRAME_ERR_CHECKSUM` alongside code `-3`.
