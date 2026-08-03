"""Read the ClientHello before uvicorn terminates TLS.

uvicorn hands an accepted socket straight to asyncio's SSL layer, which never
exposes the raw handshake bytes, so a fingerprint cannot be taken from inside
the application. This module puts a plain TCP listener in front of uvicorn.

For each connection it reads the first TLS record, computes the JA3 and JA4
fingerprints from it, then opens a connection to uvicorn, replays the bytes it
consumed, and pipes the two sockets together. The stream stays encrypted the
whole way: this front end never holds the key and never decrypts anything.
uvicorn completes the handshake exactly as it would have.

A request finds its own handshake again by the source port of the upstream
connection, which is unique per client connection and stable across keep-alive
requests on it. The real client address travels the same way, because uvicorn
sees only the front end.
"""

import asyncio
import collections
import struct
from typing import Any, Dict, Optional, Tuple

from src.detection import tlsfp

from .logging import get_logger

logger = get_logger("loaders.tls_proxy")

# Fingerprints keyed by the upstream source port the front end used.
_BY_UPSTREAM_PORT: "collections.OrderedDict[int, Dict[str, Any]]" = collections.OrderedDict()
MAX_TRACKED_CONNECTIONS = 400

# A ClientHello arrives in one record in every client the harness targets.
MAX_RECORD_BYTES = 16640
PEEK_TIMEOUT_SECONDS = 5.0


def register(port: int, fingerprint: Optional[dict], client_ip: str) -> None:
    _BY_UPSTREAM_PORT[port] = {"tls": fingerprint, "ip": client_ip}
    _BY_UPSTREAM_PORT.move_to_end(port)
    while len(_BY_UPSTREAM_PORT) > MAX_TRACKED_CONNECTIONS:
        _BY_UPSTREAM_PORT.popitem(last=False)


def unregister(port: int) -> None:
    """Forget a connection as soon as it closes.

    The entry must not outlive the connection it describes. The operating
    system hands out ephemeral ports in sequence and recycles them quickly, so
    a stale entry would eventually be found by an unrelated connection and
    hand it someone else's handshake. While the connection is open its port is
    exclusively its own, which makes the lookup exact.
    """
    _BY_UPSTREAM_PORT.pop(port, None)


def lookup(port: Optional[int]) -> Dict[str, Any]:
    """Return the handshake and the real address behind an upstream port."""
    if port is None:
        return {}
    return _BY_UPSTREAM_PORT.get(port, {})


async def _read_client_hello(reader: asyncio.StreamReader) -> Tuple[bytes, Optional[dict]]:
    """Return the bytes consumed and the fingerprint, if the record parsed."""
    head = await reader.readexactly(5)
    if head[0] != 0x16:
        # Not a handshake. Hand the bytes on and let uvicorn answer.
        return head, None

    length = struct.unpack(">H", head[3:5])[0]
    if length > MAX_RECORD_BYTES:
        return head, None

    body = await reader.readexactly(length)
    raw = head + body
    try:
        return raw, tlsfp.fingerprint(raw)
    except (tlsfp.ParseError, struct.error, IndexError):
        return raw, None


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError, OSError):
        pass
    finally:
        try:
            writer.close()
        except OSError:
            pass


def make_handler(upstream_host: str, upstream_port: int):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername") or ("", 0)
        upstream_writer = None
        local_port = None
        try:
            consumed, fingerprint = await asyncio.wait_for(
                _read_client_hello(reader), timeout=PEEK_TIMEOUT_SECONDS)

            upstream_reader, upstream_writer = await asyncio.open_connection(
                upstream_host, upstream_port)
            local_port = (upstream_writer.get_extra_info("sockname") or ("", 0))[1]
            register(local_port, fingerprint, peer[0])

            # Replay what the peek consumed, then get out of the way.
            upstream_writer.write(consumed)
            await upstream_writer.drain()
            await asyncio.gather(
                _pipe(reader, upstream_writer),
                _pipe(upstream_reader, writer),
            )
        except asyncio.IncompleteReadError:
            pass                       # the client hung up mid-handshake
        except asyncio.TimeoutError:
            logger.debug("A connection from %s sent no ClientHello in time", peer[0])
        except OSError as error:
            logger.warning("Could not reach uvicorn at %s:%s (%s)",
                           upstream_host, upstream_port, error)
        finally:
            if local_port is not None:
                unregister(local_port)
            for stream in (writer, upstream_writer):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    return handle


async def start(listen_host: str, listen_port: int,
                upstream_host: str, upstream_port: int) -> asyncio.AbstractServer:
    server = await asyncio.start_server(
        make_handler(upstream_host, upstream_port), listen_host, listen_port)
    logger.info("TLS front end listening on %s:%s, forwarding to %s:%s",
                listen_host, listen_port, upstream_host, upstream_port)
    return server
