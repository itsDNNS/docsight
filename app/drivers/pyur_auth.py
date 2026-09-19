"""Portable, fixed-5000-round SHA512-crypt for the PYUR login protocol.

Implements the algorithm in https://www.akkadia.org/drepper/SHA-crypt.txt
using hashlib only. This deliberately supports raw salts, not crypt settings
or selectable rounds. It is a modem protocol helper, not a password store.
"""

from hashlib import sha512
import re


def sha512_crypt(password: str, salt: str) -> str:
    """Return $6$salt$digest; reject settings and bound work before hashing."""
    if not isinstance(salt, str) or not re.fullmatch(r"[./A-Za-z0-9]{1,16}", salt):
        raise ValueError("PYUR invalid SHA512-crypt salt")
    if not isinstance(password, str) or len(password) > 1024 or "\0" in password:
        raise ValueError("PYUR invalid password length or encoding")
    try:
        key = password.encode("utf-8")
    except UnicodeError:
        raise ValueError("PYUR invalid password encoding") from None
    if len(key) > 1024:
        raise ValueError("PYUR password exceeds 1024 bytes")
    salt_bytes = salt.encode("ascii")
    size = len(key)

    alternate = sha512(key + salt_bytes + key).digest()
    context = sha512(key + salt_bytes)
    context.update((alternate * (size // 64 + 1))[:size])
    bits = size
    while bits:
        context.update(alternate if bits & 1 else key)
        bits >>= 1
    digest = context.digest()

    password_digest = sha512(key * size).digest()
    password_sequence = (password_digest * (size // 64 + 1))[:size]
    salt_sequence = sha512(salt_bytes * (16 + digest[0])).digest()[:len(salt_bytes)]
    for round_index in range(5000):
        context = sha512(password_sequence if round_index & 1 else digest)
        if round_index % 3:
            context.update(salt_sequence)
        if round_index % 7:
            context.update(password_sequence)
        context.update(digest if round_index & 1 else password_sequence)
        digest = context.digest()

    # SHA-crypt's byte permutation and little-endian crypt base64 alphabet.
    groups = (
        (0, 21, 42), (22, 43, 1), (44, 2, 23), (3, 24, 45),
        (25, 46, 4), (47, 5, 26), (6, 27, 48), (28, 49, 7),
        (50, 8, 29), (9, 30, 51), (31, 52, 10), (53, 11, 32),
        (12, 33, 54), (34, 55, 13), (56, 14, 35), (15, 36, 57),
        (37, 58, 16), (59, 17, 38), (18, 39, 60), (40, 61, 19),
        (62, 20, 41),
    )
    alphabet = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    encoded = []
    for high, middle, low in groups:
        value = (digest[high] << 16) | (digest[middle] << 8) | digest[low]
        for shift in (0, 6, 12, 18):
            encoded.append(alphabet[(value >> shift) & 63])
    encoded.extend((alphabet[digest[63] & 63], alphabet[digest[63] >> 6]))
    return f"$6${salt}${''.join(encoded)}"
