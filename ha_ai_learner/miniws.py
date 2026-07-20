"""Minimal dependency-free asyncio WebSocket client (RFC 6455, client side).

Supports: text frames, fragmentation, ping/pong, close, 7/16/64-bit payload
lengths, client-side masking. Enough for the Home Assistant WebSocket API.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import struct
from urllib.parse import urlparse

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


class WSError(Exception):
    pass


class WSClosed(WSError):
    pass


def encode_frame(opcode: int, payload: bytes, mask: bool = True, fin: bool = True) -> bytes:
    head = bytes([(0x80 if fin else 0) | opcode])
    mbit = 0x80 if mask else 0
    n = len(payload)
    if n < 126:
        head += bytes([mbit | n])
    elif n < 65536:
        head += bytes([mbit | 126]) + struct.pack(">H", n)
    else:
        head += bytes([mbit | 127]) + struct.pack(">Q", n)
    if mask:
        key = os.urandom(4)
        masked = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
        return head + key + masked
    return head + payload


async def _read_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    try:
        return await reader.readexactly(n)
    except (asyncio.IncompleteReadError, ConnectionError) as exc:
        raise WSClosed(f"connection closed: {exc}") from exc


async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bool, bytes]:
    """Return (opcode, fin, payload)."""
    b1, b2 = await _read_exact(reader, 2)
    fin = bool(b1 & 0x80)
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        (length,) = struct.unpack(">H", await _read_exact(reader, 2))
    elif length == 127:
        (length,) = struct.unpack(">Q", await _read_exact(reader, 8))
    key = await _read_exact(reader, 4) if masked else None
    payload = await _read_exact(reader, length) if length else b""
    if key:
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return opcode, fin, payload


class MiniWS:
    """Usage:
        ws = await MiniWS.connect("ws://host:8123/api/websocket")
        await ws.send_text('{"type": ...}')
        msg = await ws.recv_text()
        await ws.close()
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self._closed = False

    @classmethod
    async def connect(cls, url: str, timeout: float = 15.0) -> "MiniWS":
        u = urlparse(url)
        secure = u.scheme == "wss"
        port = u.port or (443 if secure else 80)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(u.hostname, port, ssl=secure), timeout
        )
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {u.hostname}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        writer.write(req.encode())
        await writer.drain()

        # read HTTP response headers
        status = await asyncio.wait_for(reader.readline(), timeout)
        if b"101" not in status:
            raise WSError(f"WebSocket handshake rejected: {status.decode(errors='replace').strip()}")
        accept = None
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout)
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.decode(errors="replace").partition(":")
            if name.strip().lower() == "sec-websocket-accept":
                accept = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
        if accept != expected:
            raise WSError("WebSocket handshake: bad Sec-WebSocket-Accept")
        return cls(reader, writer)

    async def send_text(self, text: str) -> None:
        self.writer.write(encode_frame(OP_TEXT, text.encode("utf-8")))
        await self.writer.drain()

    async def recv_text(self, timeout: float = 60.0) -> str:
        """Receive the next complete text message (handles fragmentation & ping)."""
        buffer = b""
        msg_opcode = None
        while True:
            opcode, fin, payload = await asyncio.wait_for(read_frame(self.reader), timeout)
            if opcode == OP_PING:
                self.writer.write(encode_frame(OP_PONG, payload))
                await self.writer.drain()
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                await self.close()
                raise WSClosed("server closed the connection")
            if opcode in (OP_TEXT, OP_BIN):
                msg_opcode = opcode
                buffer = payload
            elif opcode == OP_CONT:
                buffer += payload
            if fin and msg_opcode is not None:
                if msg_opcode == OP_TEXT:
                    return buffer.decode("utf-8")
                buffer = b""  # ignore binary messages
                msg_opcode = None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.writer.write(encode_frame(OP_CLOSE, struct.pack(">H", 1000)))
            await self.writer.drain()
        except (ConnectionError, RuntimeError):
            pass
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass
