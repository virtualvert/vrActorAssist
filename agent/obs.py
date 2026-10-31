"""A small obs-websocket 5.x client (spec §8.5.1): identify, then requests, one at a time.

JSON over one WebSocket (rpc version 1): Hello → Identify (with the answer to the password
challenge) → Identified, then Request → RequestResponse, matched by requestId. No events are
subscribed: the camera runtime polls. Protocol:
https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidURI, WebSocketException

TIMEOUT_S = 5.0
RPC_VERSION = 1
OP_HELLO, OP_IDENTIFY, OP_IDENTIFIED, OP_REQUEST, OP_RESPONSE = 0, 1, 2, 6, 7
CLOSE_AUTH_FAILED = 4009


class ObsError(Exception):
    """OBS isn't reachable, refused us, or a request failed; the message is shown to the operator."""


def auth_string(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class ObsClient:
    def __init__(self, ws, version: str):
        self._ws = ws
        self._lock = asyncio.Lock()
        self._next_id = 0
        # obs-websocket's version, from Hello
        self.version = version

    @classmethod
    async def open(cls, url: str, password: str) -> "ObsClient":
        try:
            ws = await connect(url, open_timeout=TIMEOUT_S, max_size=2**22)
        except InvalidURI as exc:
            raise ObsError(f"{url} isn't a WebSocket address (ws://host:port)") from exc
        except (OSError, asyncio.TimeoutError, WebSocketException) as exc:
            raise ObsError("OBS isn't running, or its WebSocket server is off (OBS → Tools → WebSocket Server Settings)") from exc
        try:
            hello = await cls._receive(ws)
            if hello.get("op") != OP_HELLO:
                raise ObsError(f"{url} isn't OBS's WebSocket server")
            info = hello.get("d") or {}
            identify: dict = {"rpcVersion": RPC_VERSION, "eventSubscriptions": 0}
            challenge = info.get("authentication")
            if challenge:
                if not password:
                    raise ObsError("OBS asks for a password: enter it in Settings → Camera")
                identify["authentication"] = auth_string(password, challenge["salt"], challenge["challenge"])
            await ws.send(json.dumps({"op": OP_IDENTIFY, "d": identify}))
            if (await cls._receive(ws)).get("op") != OP_IDENTIFIED:
                raise ObsError("OBS didn't accept the connection")
        except ConnectionClosed as exc:
            await ws.close()
            if exc.rcvd and exc.rcvd.code == CLOSE_AUTH_FAILED:
                raise ObsError("OBS refused the password (Settings → Camera)") from exc
            raise ObsError(f"OBS closed the connection ({exc})") from exc
        except BaseException:
            await ws.close()
            raise
        return cls(ws, str(info.get("obsWebSocketVersion") or ""))

    @staticmethod
    async def _receive(ws) -> dict:
        try:
            message = json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT_S))
        except asyncio.TimeoutError as exc:
            raise ObsError("OBS didn't answer") from exc
        except ValueError as exc:
            raise ObsError("OBS sent something that isn't JSON") from exc
        if not isinstance(message, dict):
            raise ObsError("OBS sent something unexpected")
        return message

    async def request(self, request_type: str, data: dict | None = None) -> dict:
        """The response data, or ObsError when the connection is gone or OBS says no."""
        async with self._lock:
            self._next_id += 1
            request_id = str(self._next_id)
            try:
                await self._ws.send(json.dumps({"op": OP_REQUEST, "d": {
                    "requestType": request_type, "requestId": request_id, "requestData": data or {}}}))
                while True:  # skip a late answer to a request that timed out
                    message = await self._receive(self._ws)
                    reply = message.get("d") or {}
                    if message.get("op") == OP_RESPONSE and reply.get("requestId") == request_id:
                        break
            except ConnectionClosed as exc:
                raise ObsError("Lost the connection to OBS") from exc
        status = reply.get("requestStatus") or {}
        if not status.get("result"):
            raise ObsError(f"OBS refused {request_type}: {status.get('comment') or 'code ' + str(status.get('code'))}")
        return reply.get("responseData") or {}

    async def close(self) -> None:
        await self._ws.close()
