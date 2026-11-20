"""eBay OAuth (authorization code grant) with refresh-token storage.

One-time login: open the consent URL, sign in to eBay, then paste the URL of
the page eBay redirects to. After that the refresh token (valid ~18 months)
is used to get fresh access tokens automatically.
"""
import base64
import time
import webbrowser
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import requests

from .config import load_tokens, save_tokens

AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"

SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.finances",
]


class AuthError(Exception):
    pass


def _basic_auth(ebay_cfg):
    raw = "%s:%s" % (ebay_cfg["client_id"], ebay_cfg["client_secret"])
    return "Basic " + base64.b64encode(raw.encode()).decode()


def consent_url(ebay_cfg):
    params = {
        "client_id": ebay_cfg["client_id"],
        "redirect_uri": ebay_cfg["ru_name"],
        "response_type": "code",
        "scope": " ".join(SCOPES),
    }
    return AUTH_URL + "?" + urlencode(params)


def extract_code(pasted):
    """Accept either the full redirect URL or just the code."""
    pasted = pasted.strip()
    if "code=" in pasted:
        qs = parse_qs(urlparse(pasted).query)
        if "code" in qs:
            return qs["code"][0]
    return unquote(pasted)


def _token_request(ebay_cfg, data):
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": _basic_auth(ebay_cfg),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=data,
        timeout=30,
    )
    if resp.status_code != 200:
        raise AuthError("eBay-Anmeldung fehlgeschlagen (%s): %s" % (resp.status_code, resp.text))
    return resp.json()


def _store(body, old=None):
    now = time.time()
    tokens = dict(old or {})
    tokens["access_token"] = body["access_token"]
    tokens["access_expires_at"] = now + int(body.get("expires_in", 7200)) - 60
    if "refresh_token" in body:
        tokens["refresh_token"] = body["refresh_token"]
        tokens["refresh_expires_at"] = now + int(body.get("refresh_token_expires_in", 0))
    save_tokens(tokens)
    return tokens


def interactive_login(ebay_cfg):
    url = consent_url(ebay_cfg)
    print("\nIm Browser öffnet sich jetzt die eBay-Anmeldung.")
    print("Falls nicht, diese Adresse öffnen:\n  " + url + "\n")
    webbrowser.open(url)
    pasted = input(
        "Nach dem Zustimmen landest du auf einer eBay-Seite.\n"
        "Kopiere die komplette Adresse aus der Adresszeile und füge sie hier ein:\n> "
    )
    finish_login(ebay_cfg, pasted)
    print("eBay-Anmeldung gespeichert.\n")


def finish_login(ebay_cfg, pasted):
    body = _token_request(
        ebay_cfg,
        {
            "grant_type": "authorization_code",
            "code": extract_code(pasted),
            "redirect_uri": ebay_cfg["ru_name"],
        },
    )
    _store(body)


def login_state():
    """'ok', 'expired' or 'none'."""
    t = load_tokens()
    if not t.get("refresh_token"):
        return "none"
    if t.get("refresh_expires_at") and t["refresh_expires_at"] < time.time():
        return "expired"
    return "ok"


def get_access_token(ebay_cfg):
    tokens = load_tokens()
    if tokens.get("access_token") and tokens.get("access_expires_at", 0) > time.time():
        return tokens["access_token"]
    if not tokens.get("refresh_token"):
        raise AuthError("Noch nicht bei eBay angemeldet. Bitte oben auf „Bei eBay anmelden“ klicken.")
    if tokens.get("refresh_expires_at") and tokens["refresh_expires_at"] < time.time():
        raise AuthError("eBay-Anmeldung abgelaufen. Bitte oben erneut „Bei eBay anmelden“ klicken.")
    body = _token_request(
        ebay_cfg,
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "scope": " ".join(SCOPES),
        },
    )
    return _store(body, tokens)["access_token"]


_app_token = {}


def get_app_token(ebay_cfg):
    """Application token (client credentials), e.g. for the Key Management API."""
    if _app_token.get("token") and _app_token.get("expires", 0) > time.time():
        return _app_token["token"]
    body = _token_request(ebay_cfg, {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    })
    _app_token["token"] = body["access_token"]
    _app_token["expires"] = time.time() + int(body.get("expires_in", 7200)) - 60
    return _app_token["token"]
