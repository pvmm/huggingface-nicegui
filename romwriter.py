from io import BytesIO
from typing import BinaryIO


def overwrite_rom_file(filename: str, pos: int, mem: BinaryIO) -> BinaryIO:
    '''Overwrite 16KB with zeros starting at a specified position'''
     # Seek to end of file
    mem.seek(0, 2)
    size = mem.tell()
    mem.seek(0, 0)
    if size > 16384:
        raise AttributeError('data is too big')

    buffer = BytesIO()
    with open(filename, 'rb') as f:
        buffer.write(f.read())
        buffer.seek(pos, 0)
        buffer.write(mem.read())
    print(f"Successfully wrote {size} bytes at offset {pos} in {filename}")
    return buffer
