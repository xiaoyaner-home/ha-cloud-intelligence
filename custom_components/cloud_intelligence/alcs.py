"""Bounded CoAP framing and ALCS session primitives. No credential I/O."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import struct
from collections.abc import Sequence
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

COAP_VERSION = 1
COAP_TYPE_CON = 0
COAP_TYPE_NON = 1
COAP_TYPE_ACK = 2
COAP_OPTION_URI_PATH = 11
AUTH_PATH_FMT = "/dev/{product_key}/{device_name}/core/service/auth"
ALCS_OPT_HEART_V1 = 1
ALCS_OPT_SUPPORT_SEQWINDOWS = 2
ALCS_OPT_PAYLOAD_CHECKSUM = 4
ALCS_IV = b"a1b1c1d1e1f1g1h1"


def _cbc(data: bytes, key: bytes, encrypt: bool) -> bytes:
    cipher = Cipher(algorithms.AES(key[:16]), modes.CBC(ALCS_IV))
    ctx = cipher.encryptor() if encrypt else cipher.decryptor()
    return ctx.update(data) + ctx.finalize()


def alcs_encrypt(payload: bytes, session_key: bytes) -> bytes:
    """CBC full blocks; the final padded block restarts with the fixed IV."""
    if not payload:
        raise ValueError("Empty payload")
    full = len(payload) & ~15
    pad = 16 - (len(payload) - full)
    return _cbc(payload[:full], session_key, True) + _cbc(
        payload[full:] + bytes([pad]) * pad, session_key, True
    )


def alcs_decrypt(ciphertext: bytes, session_key: bytes) -> bytes:
    if not ciphertext or len(ciphertext) % 16:
        raise ValueError("Invalid ciphertext length")
    final = _cbc(ciphertext[-16:], session_key, False)
    pad = final[-1]
    if not 1 <= pad <= 16 or final[-pad:] != bytes([pad]) * pad:
        raise ValueError("Invalid padding")
    return _cbc(ciphertext[:-16], session_key, False) + final[:-pad]


def hmac_sha1_base64(message: bytes, key: bytes) -> str:
    return base64.b64encode(hmac.new(key, message, hashlib.sha1).digest()).decode("ascii")


def hmac_sha1_raw(message: bytes, key: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha1).digest()


def _option_field(value: int) -> tuple[int, bytes]:
    if value < 13:
        return (value, b"")
    if value < 269:
        return (13, bytes([value - 13]))
    return (14, struct.pack("!H", value - 269))


def _encode_option(number: int, value: bytes, previous: int) -> bytes:
    delta_code, delta_ext = _option_field(number - previous)
    length_code, length_ext = _option_field(len(value))
    return bytes([delta_code << 4 | length_code]) + delta_ext + length_ext + value


def coap_encode(
    code: int,
    msgid: int,
    token: bytes,
    path: str,
    payload: bytes = b"",
    message_type: int = COAP_TYPE_CON,
    options: Sequence[tuple[int, bytes]] | None = None,
) -> bytes:
    if not 0 <= msgid <= 65535 or len(token) > 8:
        raise ValueError("invalid CoAP message id or token")
    if not path.startswith("/"):
        raise ValueError("CoAP path must start with /")
    all_options: list[tuple[int, bytes]] = [
        (COAP_OPTION_URI_PATH, part.encode("utf-8")) for part in path.split("/") if part
    ]
    if options:
        all_options.extend(options)
    all_options.sort(key=lambda item: item[0])
    packet = bytearray(
        [COAP_VERSION << 6 | message_type << 4 | len(token), code, msgid >> 8 & 255, msgid & 255]
    )
    packet.extend(token)
    previous = 0
    for number, value in all_options:
        packet.extend(_encode_option(number, value, previous))
        previous = number
    if payload:
        packet.append(255)
        packet.extend(payload)
    return bytes(packet)


def _decode_option_field(code: int, packet: bytes, offset: int) -> tuple[int, int]:
    if code < 13:
        return (code, offset)
    if code == 13:
        if offset >= len(packet):
            raise ValueError("truncated CoAP option")
        return (13 + packet[offset], offset + 1)
    if code == 14:
        if offset + 2 > len(packet):
            raise ValueError("truncated CoAP option")
        return (269 + struct.unpack("!H", packet[offset : offset + 2])[0], offset + 2)
    raise ValueError("reserved CoAP option nibble")


def coap_decode(packet: bytes) -> dict[str, Any]:
    if len(packet) < 4:
        raise ValueError("short CoAP packet")
    first = packet[0]
    code = packet[1]
    msgid = packet[2] << 8 | packet[3]
    version = first >> 6
    message_type = first >> 4 & 3
    token_len = first & 15
    if version != COAP_VERSION or token_len > 8 or len(packet) < 4 + token_len:
        raise ValueError("invalid CoAP header")
    offset = 4
    token = packet[offset : offset + token_len]
    offset += token_len
    options: list[tuple[int, bytes]] = []
    previous = 0
    while offset < len(packet) and packet[offset] != 255:
        header = packet[offset]
        offset += 1
        delta, offset = _decode_option_field(header >> 4, packet, offset)
        length, offset = _decode_option_field(header & 15, packet, offset)
        if offset + length > len(packet):
            raise ValueError("truncated CoAP option value")
        previous += delta
        options.append((previous, packet[offset : offset + length]))
        offset += length
    payload = packet[offset + 1 :] if offset < len(packet) and packet[offset] == 255 else b""
    return {
        "version": version,
        "type": message_type,
        "code": code,
        "msgid": msgid,
        "token": token,
        "options": options,
        "payload": payload,
    }


def _option_values(message: dict[str, Any], number: int) -> list[bytes]:
    return [value for key, value in message["options"] if key == number]


def coap_path(message: dict[str, Any]) -> str:
    return "/" + "/".join(
        value.decode("utf-8", "strict") for value in _option_values(message, COAP_OPTION_URI_PATH)
    )


def build_request(msg_id: int, method: str, params: Any) -> bytes:
    return json.dumps(
        {"id": str(msg_id), "version": "1.0", "params": params, "method": method},
        separators=(",", ":"),
    ).encode("utf-8")


def build_auth_payload(
    msg_id: int,
    product_key: str,
    device_name: str,
    access_key: str,
    access_token: str,
    random_key: str,
) -> bytes:
    sign = hmac_sha1_base64(random_key.encode("ascii"), access_token.encode("utf-8"))
    return json.dumps(
        {
            "version": "1.0",
            "method": "core/service/auth",
            "id": msg_id,
            "params": {
                "prodKey": product_key,
                "deviceName": device_name,
                "encrypt": "payload",
                "randomKey": random_key,
                "sign": sign,
                "accessKey": access_key,
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


def verify_server_proof(auth_data: dict[str, Any], access_token: str) -> None:
    random_key, sign = (auth_data.get("randomKey"), auth_data.get("sign"))
    if not isinstance(random_key, str) or not random_key or (not isinstance(sign, str)):
        raise ValueError("ALCS auth response omitted randomKey/server sign")
    if len(random_key) != 15 or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        for char in random_key
    ):
        raise ValueError("unsupported ALCS server randomKey format")
    try:
        random_bytes = random_key.encode("ascii") + b"\x00"
        supplied = base64.b64decode(sign, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise ValueError("invalid ALCS server proof encoding") from exc
    expected = hmac_sha1_raw(random_bytes, access_token.encode("utf-8"))
    if len(supplied) != 20 or not hmac.compare_digest(supplied, expected):
        raise ValueError("ALCS server proof mismatch")


class UnsupportedAuthOptions(ValueError):
    """Negotiation requires unsupported protection."""


def negotiate_auth_options(auth_data: dict[str, Any]) -> int:
    if "opt" not in auth_data:
        if "seqStart" in auth_data:
            raise UnsupportedAuthOptions("ALCS seqStart without opt is unsupported")
        return 0
    opt = auth_data["opt"]
    if type(opt) is not int or not 0 <= opt <= 4294967295:
        raise ValueError("invalid ALCS opt")
    unknown = opt & ~(ALCS_OPT_HEART_V1 | ALCS_OPT_SUPPORT_SEQWINDOWS | ALCS_OPT_PAYLOAD_CHECKSUM)
    if unknown:
        raise UnsupportedAuthOptions("ALCS unknown option bits are unsupported")
    if opt & ALCS_OPT_SUPPORT_SEQWINDOWS:
        raise UnsupportedAuthOptions("ALCS sequence-window data protection is not implemented")
    if opt & ALCS_OPT_PAYLOAD_CHECKSUM:
        raise UnsupportedAuthOptions("ALCS payload-checksum data protection is not implemented")
    if "seqStart" in auth_data:
        start = auth_data["seqStart"]
        if type(start) is not int or not -2147483648 <= start <= 2147483647:
            raise ValueError("invalid ALCS seqStart")
    return opt
