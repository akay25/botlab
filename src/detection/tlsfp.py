"""Parse a TLS ClientHello and compute JA3 and JA4 fingerprints.

This module reads raw handshake bytes. It does not decrypt traffic.
The server peeks the first record before the TLS library reads it.
"""

import hashlib
import struct

# GREASE values. A real Chrome build sends them. Most HTTP libraries do not.
GREASE = {0x0A0A, 0x1A1A, 0x2A2A, 0x3A3A, 0x4A4A, 0x5A5A, 0x6A6A, 0x7A7A,
          0x8A8A, 0x9A9A, 0xAAAA, 0xBABA, 0xCACA, 0xDADA, 0xEAEA, 0xFAFA}

EXT_SNI = 0x0000
EXT_EC = 0x000A
EXT_EC_FMT = 0x000B
EXT_SIG_ALGS = 0x000D
EXT_ALPN = 0x0010
EXT_SUPPORTED_VERSIONS = 0x002B

VERSION_NAMES = {0x0304: "13", 0x0303: "12", 0x0302: "11", 0x0301: "10"}


class ParseError(Exception):
    """The byte stream is not a readable ClientHello."""


class Reader:
    """Read big-endian fields from a byte string and track the offset."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, count):
        end = self.pos + count
        if end > len(self.data):
            raise ParseError("record is shorter than the declared length")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack(">H", self.take(2))[0]

    def u24(self):
        raw = self.take(3)
        return (raw[0] << 16) | (raw[1] << 8) | raw[2]

    def left(self):
        return len(self.data) - self.pos


def _u16_list(raw):
    """Split a byte string into a list of 16-bit values."""
    return [struct.unpack(">H", raw[i:i + 2])[0] for i in range(0, len(raw) - 1, 2)]


def _strip_grease(values):
    return [v for v in values if v not in GREASE]


def _sha256_12(text):
    """Return the first 12 hex characters of a SHA-256 digest."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def parse_client_hello(data):
    """Return a dictionary of ClientHello fields. Raise ParseError on bad input."""
    r = Reader(data)
    if r.u8() != 0x16:
        raise ParseError("the first byte is not a TLS handshake record")
    r.u16()          # record version
    r.u16()          # record length
    if r.u8() != 0x01:
        raise ParseError("the handshake message is not a ClientHello")
    r.u24()          # handshake length
    legacy_version = r.u16()
    r.take(32)       # client random
    r.take(r.u8())   # session id

    ciphers = _u16_list(r.take(r.u16()))
    r.take(r.u8())   # compression methods

    out = {
        "legacy_version": legacy_version,
        "ciphers": ciphers,
        "extensions": [],
        "curves": [],
        "ec_formats": [],
        "sig_algs": [],
        "alpn": [],
        "sni": None,
        "supported_versions": [],
        "grease_seen": any(c in GREASE for c in ciphers),
    }

    if r.left() < 2:
        return out
    ext_block = r.take(r.u16())
    e = Reader(ext_block)
    while e.left() >= 4:
        ext_type = e.u16()
        body = e.take(e.u16())
        out["extensions"].append(ext_type)
        if ext_type in GREASE:
            out["grease_seen"] = True
        elif ext_type == EXT_SNI and len(body) >= 5:
            name_len = struct.unpack(">H", body[3:5])[0]
            out["sni"] = body[5:5 + name_len].decode("ascii", "replace")
        elif ext_type == EXT_EC and len(body) >= 2:
            out["curves"] = _u16_list(body[2:])
        elif ext_type == EXT_EC_FMT and len(body) >= 1:
            out["ec_formats"] = list(body[1:])
        elif ext_type == EXT_SIG_ALGS and len(body) >= 2:
            out["sig_algs"] = _u16_list(body[2:])
        elif ext_type == EXT_ALPN and len(body) >= 3:
            a = Reader(body[2:])
            while a.left() >= 1:
                out["alpn"].append(a.take(a.u8()).decode("ascii", "replace"))
        elif ext_type == EXT_SUPPORTED_VERSIONS and len(body) >= 1:
            out["supported_versions"] = _u16_list(body[1:])
    return out


def ja3(hello):
    """Return the JA3 string and the JA3 MD5 hash."""
    parts = [
        str(hello["legacy_version"]),
        "-".join(str(v) for v in _strip_grease(hello["ciphers"])),
        "-".join(str(v) for v in _strip_grease(hello["extensions"])),
        "-".join(str(v) for v in _strip_grease(hello["curves"])),
        "-".join(str(v) for v in hello["ec_formats"]),
    ]
    text = ",".join(parts)
    return text, hashlib.md5(text.encode()).hexdigest()


def _alpn_code(alpn):
    """Return the two-character ALPN code that JA4 uses."""
    if not alpn:
        return "00"
    first = alpn[0]
    if len(first) < 2:
        return "00"
    return first[0] + first[-1]


def ja4(hello, transport="t"):
    """Return the JA4 hash and the JA4_r raw string.

    JA4_r keeps the readable field list. Use it to explain a match in a paper.
    """
    versions = _strip_grease(hello["supported_versions"]) or [hello["legacy_version"]]
    top = max(versions)
    version_code = VERSION_NAMES.get(top, "00")
    sni_code = "d" if hello["sni"] else "i"

    ciphers = _strip_grease(hello["ciphers"])
    exts = _strip_grease(hello["extensions"])
    cipher_count = min(len(ciphers), 99)
    ext_count = min(len(exts), 99)

    part_a = "%s%s%s%02d%02d%s" % (
        transport, version_code, sni_code, cipher_count, ext_count, _alpn_code(hello["alpn"])
    )

    cipher_text = ",".join("%04x" % c for c in sorted(ciphers))
    listed = sorted(x for x in exts if x not in (EXT_SNI, EXT_ALPN))
    ext_text = ",".join("%04x" % x for x in listed)
    sig_text = ",".join("%04x" % s for s in _strip_grease(hello["sig_algs"]))
    ext_field = ext_text + "_" + sig_text if sig_text else ext_text

    part_b = _sha256_12(cipher_text) if ciphers else "000000000000"
    part_c = _sha256_12(ext_field) if listed else "000000000000"

    ja4_hash = "%s_%s_%s" % (part_a, part_b, part_c)
    ja4_raw = "%s_%s_%s" % (part_a, cipher_text, ext_field)
    return ja4_hash, ja4_raw


def fingerprint(data):
    """Parse the bytes and return every fingerprint field the scorer needs."""
    hello = parse_client_hello(data)
    ja3_text, ja3_hash = ja3(hello)
    ja4_hash, ja4_raw = ja4(hello)
    return {
        "ja3": ja3_hash,
        "ja3_text": ja3_text,
        "ja4": ja4_hash,
        "ja4_r": ja4_raw,
        "alpn": hello["alpn"],
        "sni": hello["sni"],
        "grease": hello["grease_seen"],
        "cipher_count": len(_strip_grease(hello["ciphers"])),
        "ext_count": len(_strip_grease(hello["extensions"])),
        "sig_alg_count": len(_strip_grease(hello["sig_algs"])),
        "max_version": max(_strip_grease(hello["supported_versions"]) or [hello["legacy_version"]]),
    }
