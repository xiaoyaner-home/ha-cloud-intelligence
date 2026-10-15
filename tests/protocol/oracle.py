"""Independent ECB/XOR oracle for the ALCS block format, synthetic only."""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

IV = b"a1b1c1d1e1f1g1h1"


def xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b, strict=True))


def block(data, key, encrypt):
    cipher = Cipher(algorithms.AES(key[:16]), modes.ECB())
    ctx = cipher.encryptor() if encrypt else cipher.decryptor()
    return ctx.update(data) + ctx.finalize()


def encrypt(data, key):
    full = len(data) // 16 * 16
    out, prev = b"", IV
    for i in range(0, full, 16):
        prev = block(xor(data[i : i + 16], prev), key, True)
        out += prev
    pad = 16 - (len(data) - full)
    return out + block(xor(data[full:] + bytes([pad]) * pad, IV), key, True)


def decrypt(data, key):
    out, prev = b"", IV
    for i in range(0, len(data) - 16, 16):
        out += xor(block(data[i : i + 16], key, False), prev)
        prev = data[i : i + 16]
    final = xor(block(data[-16:], key, False), IV)
    assert final[-final[-1] :] == bytes([final[-1]]) * final[-1]
    return out + final[: -final[-1]]
