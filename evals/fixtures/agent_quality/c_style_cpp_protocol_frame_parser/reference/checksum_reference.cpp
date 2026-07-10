/*
 * Reference from a related message format. The production parser uses the same
 * XOR accumulation idea, but its covered bytes and validation contract come
 * from SPEC.md rather than from this function's parameters.
 */
unsigned char reference_xor_checksum(
    unsigned char message_type,
    unsigned char data_size,
    const unsigned char *data
)
{
    unsigned char checksum = message_type;
    unsigned int index = 0U;

    checksum = (unsigned char)(checksum ^ data_size);
    while (index < (unsigned int)data_size) {
        checksum = (unsigned char)(checksum ^ data[index]);
        index += 1U;
    }
    return checksum;
}
