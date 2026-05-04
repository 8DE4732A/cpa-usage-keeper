"""Redis RESP protocol client for CPA usage queue."""

from __future__ import annotations

import socket
from datetime import timedelta
from typing import Optional
from urllib.parse import urlparse

from loguru import logger

from .endpoints import MANAGEMENT_REDIS_DEFAULT_PORT


class RedisQueueAuthError(Exception):
    pass


class RedisQueueClient:
    """Low-level RESP protocol client for CPA's Redis usage queue."""

    def __init__(
        self,
        base_url: str,
        redis_queue_addr: str,
        management_key: str,
        timeout: timedelta,
        queue_key: str = "queue",
        batch_size: int = 1000,
    ):
        self.address = _redis_queue_address(base_url, redis_queue_addr)
        self.management_key = management_key.strip()
        self.timeout = timeout.total_seconds()
        self.queue_key = queue_key.strip()
        self.batch_size = batch_size

    def probe(self) -> None:
        """Test connection to the Redis queue."""
        sock, _ = self._open_authenticated_connection()
        sock.close()

    def pop_usage(self) -> list[str]:
        """Pop usage messages from the Redis queue."""
        if not self.queue_key:
            raise ValueError("redis queue key is required")
        if self.batch_size <= 0:
            raise ValueError("redis queue batch size must be positive")

        sock, reader = self._open_authenticated_connection()
        try:
            _write_resp_command(sock, "LPOP", self.queue_key, str(self.batch_size))
            response = _read_resp_value(reader)
            logger.debug(f"LPOP response: {response}")
            if response.get("err"):
                raise RuntimeError(f"redis queue pop failed: {response['err']}")
            result = _resp_strings(response)
            logger.debug(f"LPOP parsed {len(result)} messages")
            return result
        finally:
            sock.close()

    def _open_authenticated_connection(self) -> tuple[socket.socket, "_RESPReader"]:
        if not self.address:
            raise ValueError("redis queue address is required")
        if not self.management_key:
            raise ValueError("redis queue management key is required")

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)

        host, port_str = self.address.rsplit(":", 1)
        sock.connect((host, int(port_str)))
        reader = _RESPReader(sock)

        _write_resp_command(sock, "AUTH", self.management_key)
        auth_response = _read_resp_value(reader)
        if auth_response.get("err"):
            sock.close()
            raise RedisQueueAuthError(f"redis queue auth failed: {auth_response['err']}")

        return sock, reader


def _redis_queue_address(base_url: str, redis_queue_addr: str) -> str:
    override = redis_queue_addr.strip()
    if override:
        try:
            parsed = urlparse(override)
            if parsed.hostname:
                port = parsed.port or MANAGEMENT_REDIS_DEFAULT_PORT
                return f"{parsed.hostname}:{port}"
        except Exception:
            pass
        return override

    trimmed = base_url.strip()
    if not trimmed:
        return ""

    try:
        parsed = urlparse(trimmed)
        if parsed.hostname:
            port = parsed.port or MANAGEMENT_REDIS_DEFAULT_PORT
            return f"{parsed.hostname}:{port}"
    except Exception:
        pass

    return trimmed


def _write_resp_command(sock: socket.socket, *parts: str) -> None:
    buf = f"*{len(parts)}\r\n".encode()
    for part in parts:
        encoded = part.encode()
        buf += f"${len(encoded)}\r\n".encode() + encoded + b"\r\n"
    sock.sendall(buf)


class _RESPReader:
    def __init__(self, sock: socket.socket):
        self._sock = sock
        self._buffer = b""

    def _read_byte(self) -> int:
        if not self._buffer:
            self._buffer = self._sock.recv(4096)
            if not self._buffer:
                raise ConnectionError("connection closed")
        b = self._buffer[0]
        self._buffer = self._buffer[1:]
        return b

    def _read_line(self) -> str:
        result = b""
        while True:
            b = self._read_byte()
            if b == ord("\n"):
                return result.rstrip(b"\r").decode()
            result += bytes([b])

    def _read_exact(self, n: int) -> bytes:
        result = b""
        while len(result) < n:
            if self._buffer:
                chunk = self._buffer[:n - len(result)]
                self._buffer = self._buffer[len(chunk):]
                result += chunk
            else:
                self._buffer = self._sock.recv(max(4096, n - len(result)))
                if not self._buffer:
                    raise ConnectionError("connection closed")
        return result


def _read_resp_value(reader: _RESPReader) -> dict:
    prefix = chr(reader._read_byte())
    if prefix == "+":
        line = reader._read_line()
        return {"simple": line}
    elif prefix == "-":
        line = reader._read_line()
        return {"err": line}
    elif prefix == "$":
        line = reader._read_line()
        size = int(line)
        if size < 0:
            return {"nil": True}
        data = reader._read_exact(size + 2)
        return {"bulk": data[:size].decode()}
    elif prefix == "*":
        line = reader._read_line()
        count = int(line)
        if count < 0:
            return {"nil": True}
        items = []
        for _ in range(count):
            items.append(_read_resp_value(reader))
        return {"array": items}
    else:
        raise ValueError(f"unexpected RESP prefix: {prefix!r}")


def _resp_strings(value: dict) -> list[str]:
    if value.get("nil"):
        return []
    if "bulk" in value:
        return [value["bulk"]]
    items = value.get("array", [])
    if not items:
        return []
    result = []
    for item in items:
        if "bulk" in item:
            result.append(item["bulk"])
    return result
