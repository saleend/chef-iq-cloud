"""CHEF iQ cloud transport recovered from the installed Android app."""

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from aiohttp import WSMsgType


class CloudError(Exception):
    pass


class AuthError(CloudError):
    pass


async def json_request(session, url, data=None, headers=None):
    async with session.request(
        "POST" if data is not None else "GET",
        url,
        json=data,
        headers=headers,
        timeout=30,
        allow_redirects=False,
    ) as r:
        if r.status in (401, 403):
            raise AuthError("Authentication rejected")
        if r.status >= 400:
            raise CloudError("Cloud request failed: HTTP " + str(r.status))
        return await r.json(content_type=None)


async def refresh(session, api_key, refresh_token):
    async with session.post(
        "https://securetoken.googleapis.com/v1/token",
        params={"key": api_key},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=30,
        allow_redirects=False,
    ) as r:
        if r.status != 200:
            raise AuthError("Account session refresh rejected")
        data = await r.json()
        if not data.get("id_token"):
            raise AuthError("Missing account session")
        return data


async def login(session, api_key, email, password):
    data = await json_request(
        session,
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + api_key,
        {"email": email, "password": password, "returnSecureToken": True},
    )
    if not data.get("refreshToken"):
        raise AuthError("Email/password login failed or requires additional authentication")
    return data


def signed_path(host, keys, now=None):
    now = now or datetime.now(timezone.utc)
    date = now.strftime("%Y%m%d")
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    region = "us-east-1"
    service = "iotdevicegateway"
    scope = f"{date}/{region}/{service}/aws4_request"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": keys["AccessKeyId"] + "/" + scope,
        "X-Amz-Date": stamp,
        "X-Amz-Expires": "900",
        "X-Amz-SignedHeaders": "host",
    }
    query = urlencode(sorted(params.items()), quote_via=quote, safe="~")
    canonical = (
        "GET\n/mqtt\n" + query + "\nhost:" + host + "\n\nhost\n" + hashlib.sha256(b"").hexdigest()
    )
    tosign = (
        "AWS4-HMAC-SHA256\n"
        + stamp
        + "\n"
        + scope
        + "\n"
        + hashlib.sha256(canonical.encode()).hexdigest()
    )
    key = ("AWS4" + keys["SecretKey"]).encode()
    for part in [date, region, service, "aws4_request"]:
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    sig = hmac.new(key, tosign.encode(), hashlib.sha256).hexdigest()
    # IoT expects the temporary token appended after signing the canonical query.
    return (
        "/mqtt?"
        + query
        + "&X-Amz-Signature="
        + sig
        + "&X-Amz-Security-Token="
        + quote(keys["SessionToken"], safe="~")
    )


def text(s):
    b = s.encode()
    return len(b).to_bytes(2, "big") + b


def packet(kind, payload=b""):
    size = len(payload)
    encoded = b""
    while True:
        d = size % 128
        size //= 128
        encoded += bytes([d | (128 if size else 0)])
        if not size:
            break
    return bytes([kind]) + encoded + payload


def unpack(buffer):
    result = []
    pos = 0
    while pos < len(buffer):
        start = pos
        if len(buffer) - pos < 2:
            break
        kind = buffer[pos]
        pos += 1
        length = 0
        mult = 1
        for n in range(4):
            if pos >= len(buffer):
                return result, buffer[start:]
            d = buffer[pos]
            pos += 1
            length += (d & 127) * mult
            mult *= 128
            if not d & 128:
                break
        else:
            raise CloudError("Malformed MQTT length")
        if length > 2_000_000:
            raise CloudError("Oversized MQTT packet")
        if len(buffer) - pos < length:
            return result, buffer[start:]
        result.append((kind, buffer[pos : pos + length]))
        pos += length
    return result, buffer[pos:]


async def stream(
    session, identity, devices, keys, host, on_packet, on_connected, stop, on_ready=None
):
    client_id = identity + "/" + uuid.uuid4().hex
    topics = [
        "ciq-v2/dt/thermometer/" + identity + "~" + d["device_id"] + "/+"
        for d in devices
        if str(d.get("model_number", "")).startswith(("CQ50", "CQ60"))
    ]
    for d in devices:
        base = identity + "~" + d["device_id"]
        topics.extend(
            [
                "ciq-v2/evt/thermometer/" + base + "/notification/+",
                "ciq-v2/cmd/app/" + base + "/res/+",
            ]
        )
    if not topics:
        raise CloudError("No supported thermometer hubs found")
    async with session.ws_connect(
        "wss://" + host + signed_path(host, keys),
        protocols=["mqtt"],
        timeout=20,
        max_msg_size=2_000_000,
    ) as ws:
        await ws.send_bytes(packet(0x10, text("MQTT") + bytes([4, 2, 0, 30]) + text(client_id)))

        async def send(device_id, command, data, request_id):
            if device_id not in {d["device_id"] for d in devices}:
                raise CloudError("Unknown hub")
            base = identity + "~" + device_id
            envelope = {
                "version": "1.0.0",
                "env": "prod",
                "time_stamp": int(time.time() * 1000),
                "request_id": request_id,
                "client_id": client_id,
                "response_topic": "ciq-v2/cmd/app/" + base + "/res/" + request_id,
                "data": data,
            }
            await ws.send_bytes(
                packet(
                    0x30,
                    text("ciq-v2/cmd/thermometer/" + base + "/req/" + command)
                    + json.dumps(envelope).encode(),
                )
            )

        buf = b""
        accepted = False
        subscribed = False
        deadline = time.time() + 20
        expires = float(keys.get("Expiration", time.time() + 3600)) - 120
        last_ping = time.monotonic()
        while not stop.is_set() and time.time() < expires:
            if time.monotonic() - last_ping >= 15:
                await ws.send_bytes(packet(0xC0))
                last_ping = time.monotonic()
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=15)
            except asyncio.TimeoutError:
                if not subscribed and time.time() > deadline:
                    raise CloudError("MQTT subscription timed out")
                await ws.send_bytes(packet(0xC0))
                last_ping = time.monotonic()
                continue
            if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                raise CloudError("Cloud stream disconnected")
            if msg.type != WSMsgType.BINARY:
                continue
            buf += msg.data
            items, buf = unpack(buf)
            for kind, body in items:
                typ = kind >> 4
                if typ == 2:
                    if len(body) != 2 or body[1] != 0:
                        raise AuthError("MQTT connection rejected")
                    accepted = True
                    await ws.send_bytes(
                        packet(
                            0x82,
                            b"\x00\x01" + b"".join(text(t) + b"\x00" for t in topics),
                        )
                    )
                elif typ == 9:
                    if not accepted or len(body) < 3 or any(c == 128 for c in body[2:]):
                        raise AuthError("Cloud subscription rejected")
                    subscribed = True
                    on_connected(True)
                    if on_ready:
                        on_ready(send)
                elif typ == 3:
                    if not subscribed or len(body) < 2:
                        continue
                    n = int.from_bytes(body[:2], "big")
                    topic = body[2 : 2 + n].decode()
                    offset = 2 + n
                    qos = (kind >> 1) & 3
                    if qos:
                        mid = body[offset : offset + 2]
                        offset += 2
                        if qos == 1:
                            await ws.send_bytes(packet(0x40, mid))
                        else:
                            raise CloudError("Unexpected MQTT QoS")
                    if len(body) - offset > 1_000_000:
                        continue
                    try:
                        data = json.loads(body[offset:])
                    except (ValueError, UnicodeError):
                        continue
                    if isinstance(data, dict):
                        on_packet(topic, data)
