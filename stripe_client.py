"""
Minimal Stripe client (stdlib only) for a Connect marketplace:
- Express connected accounts + onboarding links for sellers
- Checkout Sessions with destination charges and a platform fee
- Webhook signature verification
"""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request


class StripeError(Exception):
    pass


def _flatten(params, prefix=""):
    """Encode nested dicts/lists the way Stripe expects: a[b][0][c]=value."""
    pairs = []
    items = params.items() if isinstance(params, dict) else enumerate(params)
    for key, value in items:
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, (dict, list)):
            pairs.extend(_flatten(value, name))
        elif isinstance(value, bool):
            pairs.append((name, "true" if value else "false"))
        elif value is not None:
            pairs.append((name, str(value)))
    return pairs


class Stripe:
    def __init__(self, secret_key, api_base="https://api.stripe.com", opener=None):
        self.secret_key = secret_key
        self.api_base = api_base.rstrip("/")
        self.opener = opener or urllib.request.build_opener()

    def request(self, method, path, params=None):
        data = urllib.parse.urlencode(_flatten(params or {})).encode() if method == "POST" else None
        request = urllib.request.Request(
            self.api_base + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                message = json.loads(error.read())["error"]["message"]
            except Exception:
                message = f"HTTP {error.code}"
            raise StripeError(message) from None
        except (urllib.error.URLError, OSError) as error:
            raise StripeError(f"cannot reach Stripe: {error}") from None

    # ------------------------------------------------------------ Connect

    def create_express_account(self, metadata):
        return self.request("POST", "/v1/accounts", {
            "type": "express",
            "capabilities": {
                "card_payments": {"requested": True},
                "transfers": {"requested": True},
            },
            "metadata": metadata,
        })

    def create_onboarding_link(self, account_id, refresh_url, return_url):
        return self.request("POST", "/v1/account_links", {
            "account": account_id,
            "refresh_url": refresh_url,
            "return_url": return_url,
            "type": "account_onboarding",
        })

    def retrieve_account(self, account_id):
        return self.request("GET", f"/v1/accounts/{urllib.parse.quote(account_id)}")

    # ------------------------------------------------------------ Checkout

    def create_checkout_session(self, *, title, amount_cents, currency, fee_cents,
                                destination, success_url, cancel_url, metadata):
        return self.request("POST", "/v1/checkout/sessions", {
            "mode": "payment",
            "line_items": [{
                "quantity": 1,
                "price_data": {
                    "currency": currency,
                    "unit_amount": amount_cents,
                    "product_data": {"name": title[:250]},
                },
            }],
            "payment_intent_data": {
                "application_fee_amount": fee_cents,
                "transfer_data": {"destination": destination},
                "metadata": metadata,
            },
            "metadata": metadata,
            "client_reference_id": metadata.get("order_id"),
            "success_url": success_url,
            "cancel_url": cancel_url,
        })

    def retrieve_checkout_session(self, session_id):
        return self.request("GET", f"/v1/checkout/sessions/{urllib.parse.quote(session_id)}")


def verify_webhook(payload, signature_header, secret, tolerance=300):
    """Validate a Stripe-Signature header and return the parsed event."""
    timestamp = None
    signatures = []
    for part in (signature_header or "").split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures:
        raise StripeError("malformed Stripe-Signature header")
    if abs(time.time() - int(timestamp)) > tolerance:
        raise StripeError("webhook timestamp outside tolerance")
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise StripeError("webhook signature mismatch")
    return json.loads(payload)
