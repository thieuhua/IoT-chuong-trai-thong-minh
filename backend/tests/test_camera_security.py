import json
import pytest
from fastapi import HTTPException

from app.main import app, validate_camera_source
from app import models


async def asgi_request(method, path, body=None, query=b'', headers=None):
    messages = []
    raw_headers = [(b'content-type', b'application/json')]
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode(), v.encode()))

    scope = dict(
        type='http',
        asgi={'version': '3.0'},
        http_version='1.1',
        method=method,
        scheme='http',
        path=path,
        raw_path=path.encode(),
        root_path='',
        query_string=query,
        headers=raw_headers,
        server=('test', 80),
        client=('test', 1),
    )

    async def receive():
        return {'type': 'http.request', 'body': json.dumps(body).encode() if body is not None else b''}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
    raw = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
    try:
        data = json.loads(raw)
    except Exception:
        data = raw
    return status, data


def test_cors_configuration():
    cors_middleware = next(
        m for m in app.user_middleware if "CORSMiddleware" in str(m.cls)
    )
    assert cors_middleware.kwargs["allow_credentials"] is True
    assert "*" not in cors_middleware.kwargs["allow_origins"]


def test_validate_camera_source():
    # Valid allowed device indexes (0 and 1 by default)
    assert validate_camera_source(0) == 0
    assert validate_camera_source("0") == 0
    assert validate_camera_source("1") == 1

    # Not in whitelist
    with pytest.raises(HTTPException) as exc:
        validate_camera_source(2)
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        validate_camera_source(25)
    assert exc.value.status_code == 400

    # Local file paths (LFI prevention)
    with pytest.raises(HTTPException) as exc:
        validate_camera_source("/etc/passwd")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        validate_camera_source("file:///etc/shadow")
    assert exc.value.status_code == 400

    # Localhost / internal addresses (SSRF prevention)
    with pytest.raises(HTTPException) as exc:
        validate_camera_source("http://localhost:8000/stream")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        validate_camera_source("http://127.0.0.1:8000/stream")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        validate_camera_source("rtsp://192.168.1.50:554/live")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        validate_camera_source("http://10.0.0.1/video")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_camera_routes_require_authentication():
    # 1. /camera/feed
    status, _ = await asgi_request("GET", "/camera/feed")
    assert status == 401

    # 2. /camera/status
    status, _ = await asgi_request("GET", "/camera/status")
    assert status == 401

    # 3. /camera/start
    status, _ = await asgi_request("POST", "/camera/start")
    assert status == 401

    # 4. /camera/stop
    status, _ = await asgi_request("POST", "/camera/stop")
    assert status == 401

    # 5. /camera/config
    status, _ = await asgi_request("POST", "/camera/config", body={"allow_person": True})
    assert status == 401


@pytest.mark.asyncio
async def test_camera_routes_authorization():
    from app.main import get_current_user

    admin_user = models.User(id="u1", username="admin", role="Admin", status="active", password_hash="dummy")
    viewer_user = models.User(id="u2", username="viewer", role="Viewer", status="active", password_hash="dummy")

    # Viewer can access status
    app.dependency_overrides[get_current_user] = lambda: viewer_user

    status, body = await asgi_request("GET", "/camera/status")
    assert status == 200

    # Viewer cannot start/stop/config
    status, _ = await asgi_request("POST", "/camera/start")
    assert status == 403

    status, _ = await asgi_request("POST", "/camera/stop")
    assert status == 403

    status, _ = await asgi_request("POST", "/camera/config", body={"allow_person": True})
    assert status == 403

    # Admin can start/stop/config
    app.dependency_overrides[get_current_user] = lambda: admin_user

    # Camera config with malicious source should be rejected with 400
    status, _ = await asgi_request("POST", "/camera/config", body={"source": "/etc/passwd"})
    assert status == 400

    status, _ = await asgi_request("POST", "/camera/config", body={"source": "http://127.0.0.1/private"})
    assert status == 400

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_camera_query_token_auth(monkeypatch):
    from app.services import auth

    test_user = models.User(id="u1", username="viewer", role="Viewer", status="active", password_hash="dummy")

    def mock_get_current_user(db, token):
        if token == "valid-token":
            return test_user
        raise HTTPException(401, "Invalid token")

    monkeypatch.setattr(auth, "get_current_user", mock_get_current_user)

    status, _ = await asgi_request("GET", "/camera/status", query=b"token=valid-token")
    assert status == 200

    status, _ = await asgi_request("GET", "/camera/status", query=b"token=invalid-token")
    assert status == 401

