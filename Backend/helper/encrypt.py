import zlib
import base64
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Define the executor for running CPU-bound tasks
executor = ThreadPoolExecutor()

# Aggressive compression
def compress_data(data):
    """Compress data using zlib."""
    return zlib.compress(data.encode(), level=zlib.Z_BEST_COMPRESSION)

def decompress_data(data):
    """Decompress data using zlib."""
    return zlib.decompress(data).decode()

# Base62 encoding and decoding (shortened version)
def base62_encode(data):
    """Encode bytes to base62."""
    BASE62_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    num = int.from_bytes(data, 'big')
    base62 = []
    while num:
        num, rem = divmod(num, 62)
        base62.append(BASE62_ALPHABET[rem])
    return ''.join(reversed(base62)) or '0'

def base62_decode(data):
    """Decode base62 to bytes."""
    BASE62_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    num = 0
    for char in data:
        num = num * 62 + BASE62_ALPHABET.index(char)
    return num.to_bytes((num.bit_length() + 7) // 8, 'big') or b'\0'

# Asynchronous wrapper for CPU-bound functions
async def async_compress_data(data):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, compress_data, data)

async def async_decompress_data(data):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, decompress_data, data)

async def async_base62_encode(data):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, base62_encode, data)

async def async_base62_decode(data):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, base62_decode, data)

# Asynchronous function to encode a string
async def encode_string(data):
    json_data = json.dumps(data)
    compressed_data = await async_compress_data(json_data)
    return await async_base62_encode(compressed_data)

# Asynchronous function to decode a string
async def decode_string(encoded_data: str) -> dict:
    if not encoded_data:
        return {"chat_id": None, "msg_id": None, "hash": None}

    # Format 1: Base64 formatted string (e.g. "chat_id:msg_id:hash")
    try:
        padded = encoded_data + '=' * (-len(encoded_data) % 4)
        raw_bytes = base64.urlsafe_b64decode(padded.encode('ascii'))
        raw_text = raw_bytes.decode('utf-8', errors='ignore')
        parts = raw_text.split(':')
        if len(parts) >= 3 and parts[1].isdigit():
            return {
                "chat_id": int(parts[0]) if parts[0].lstrip('-').isdigit() else parts[0],
                "msg_id": int(parts[1]),
                "hash": parts[2].strip()
            }
        # Check if it's JSON in base64
        if raw_text.strip().startswith('{'):
            data = json.loads(raw_text)
            if isinstance(data, dict):
                return data
    except Exception:
        pass

    # Format 2: Base62 + zlib compressed JSON
    try:
        compressed_data = await async_base62_decode(encoded_data)
        json_data = await async_decompress_data(compressed_data)
        data = json.loads(json_data)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return {"chat_id": None, "msg_id": None, "hash": None}
