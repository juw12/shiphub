"""
Zero-dependency Web Push sender (VAPID, RFC 8292).

- ECDSA P-256 / SHA-256 (ES256) implemented in pure Python to sign VAPID JWTs.
- Pushes are sent WITHOUT a payload, so no RFC 8291 payload encryption is needed.
  The service worker wakes up, fetches the newest notification from the API and
  shows it. This keeps notification text off third-party push servers entirely.

Note: this scalar multiplication is not constant-time. It only ever signs
short-lived VAPID tokens server-side, but use a vetted library (e.g.
`cryptography`) if you ever reuse it for anything else.
"""
import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

# NIST P-256 domain parameters
P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (
    0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
    0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5,
)

# Push services that browsers actually use. Endpoints elsewhere are refused (SSRF guard).
PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    "push.services.mozilla.com",
    "notify.windows.com",
    "push.apple.com",
)


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _point_add(first, second):
    if first is None:
        return second
    if second is None:
        return first
    x1, y1 = first
    x2, y2 = second
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None
        slope = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (slope * slope - x1 - x2) % P
    y3 = (slope * (x1 - x3) - y1) % P
    return (x3, y3)


def _scalar_mult(scalar, point):
    result = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        scalar >>= 1
    return result


def is_on_curve(point):
    x, y = point
    return (y * y - (x * x * x + A * x + B)) % P == 0


def generate_private_key():
    return secrets.randbelow(N - 1) + 1


def public_key_bytes(private_key):
    """Uncompressed SEC1 point (65 bytes) - the browser's applicationServerKey."""
    x, y = _scalar_mult(private_key, G)
    return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def sign(private_key, message):
    """ES256 signature as raw r||s (64 bytes), as JWS requires."""
    digest = int.from_bytes(hashlib.sha256(message).digest(), "big")
    while True:
        nonce = secrets.randbelow(N - 1) + 1
        r = _scalar_mult(nonce, G)[0] % N
        if r == 0:
            continue
        s = pow(nonce, -1, N) * (digest + r * private_key) % N
        if s != 0:
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def verify(public_key, message, signature):
    """Verify a raw r||s ES256 signature against a 65-byte public key."""
    if len(public_key) != 65 or public_key[0] != 4 or len(signature) != 64:
        return False
    point = (int.from_bytes(public_key[1:33], "big"), int.from_bytes(public_key[33:], "big"))
    if not is_on_curve(point):
        return False
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    if not (0 < r < N and 0 < s < N):
        return False
    digest = int.from_bytes(hashlib.sha256(message).digest(), "big")
    inverse = pow(s, -1, N)
    combined = _point_add(
        _scalar_mult(digest * inverse % N, G),
        _scalar_mult(r * inverse % N, point),
    )
    return combined is not None and combined[0] % N == r


def vapid_jwt(private_key, audience, subject, ttl_seconds=12 * 3600):
    header = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64url(json.dumps(
        {"aud": audience, "exp": int(time.time()) + ttl_seconds, "sub": subject},
        separators=(",", ":"),
    ).encode())
    signing_input = f"{header}.{claims}".encode()
    return f"{header}.{claims}.{b64url(sign(private_key, signing_input))}"


def endpoint_allowed(endpoint, extra_hosts=()):
    parsed = urllib.parse.urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    if host in extra_hosts:
        return parsed.scheme in ("http", "https")
    if parsed.scheme != "https":
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in PUSH_HOST_SUFFIXES)


def send_push(endpoint, private_key, subject, ttl=86400, opener=None):
    """Send an empty 'wake up' push. Returns the HTTP status (404/410 = subscription gone)."""
    parsed = urllib.parse.urlparse(endpoint)
    audience = f"{parsed.scheme}://{parsed.netloc}"
    token = vapid_jwt(private_key, audience, subject)
    request = urllib.request.Request(
        endpoint,
        data=b"",
        method="POST",
        headers={
            "TTL": str(ttl),
            "Urgency": "normal",
            "Content-Length": "0",
            "Authorization": f"vapid t={token}, k={b64url(public_key_bytes(private_key))}",
        },
    )
    try:
        with (opener or urllib.request.build_opener()).open(request, timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
