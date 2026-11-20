"""eBay digital signatures (required for the Finances API for EU/UK sellers).

One-time: create an Ed25519 key pair via eBay's Key Management API and keep
it in signing_key.json (secret; eBay returns the private key only once).
Each Finances request then gets three headers, built like eBay's official SDK:

  x-ebay-signature-key: <jwe>
  Signature-Input:      sig1=("x-ebay-signature-key" "@method" "@path" "@authority");created=<unix>
  Signature:            sig1=:<base64 Ed25519 signature of the signature base>:
"""
import base64
import json
import os
import time
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import serialization

from .config import ROOT
from .ebay_auth import AuthError, get_app_token

KEY_PATH = ROOT / "signing_key.json"
CREATE_URL = "https://apiz.ebay.com/developer/key_management/v1/signing_key"
RENEW_BEFORE = 30 * 24 * 3600  # make a new key 30 days before expiry
COMPONENTS = ("x-ebay-signature-key", "@method", "@path", "@authority")


def _load_private_key(text):
    """eBay returns base64 PKCS#8 DER; also accept a full PEM."""
    text = text.strip()
    if "BEGIN" in text:
        return serialization.load_pem_private_key(text.encode(), password=None)
    return serialization.load_der_private_key(base64.b64decode(text), password=None)


def _save(key):
    tmp = KEY_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(key, f, indent=2)
    os.chmod(tmp, 0o600)
    tmp.replace(KEY_PATH)


def create_signing_key(ebay_cfg):
    resp = requests.post(
        CREATE_URL,
        headers={"Authorization": "Bearer " + get_app_token(ebay_cfg),
                 "Content-Type": "application/json", "Accept": "application/json"},
        json={"signingKeyCipher": "ED25519"},
        timeout=60,
    )
    if resp.status_code not in (200, 201):
        raise AuthError("eBay-Signaturschlüssel konnte nicht erstellt werden (%s): %s"
                        % (resp.status_code, resp.text[:400]))
    body = resp.json()
    key = {k: body.get(k) for k in ("signingKeyId", "privateKey", "publicKey", "jwe",
                                    "creationTime", "expirationTime", "signingKeyCipher")}
    _save(key)  # save first: eBay returns the private key only once
    try:
        _load_private_key(key["privateKey"] or "")
    except Exception as e:
        raise AuthError("eBay-Signaturschlüssel hat ein unerwartetes Format (%s). "
                        "Er ist in signing_key.json gespeichert. Bitte diese Meldung weitergeben." % e)
    return key


def get_signing_key(ebay_cfg):
    if KEY_PATH.exists():
        with open(KEY_PATH, encoding="utf-8") as f:
            key = json.load(f)
        exp = key.get("expirationTime") or 0
        if key.get("privateKey") and key.get("jwe") and (not exp or exp - time.time() > RENEW_BEFORE):
            return key
    return create_signing_key(ebay_cfg)


def signature_base(method, url, jwe, created):
    u = urlparse(url)
    values = {
        "x-ebay-signature-key": jwe,
        "@method": method.upper(),
        "@path": u.path,
        "@authority": u.netloc,
    }
    params = "(" + " ".join('"%s"' % c for c in COMPONENTS) + ");created=%d" % created
    lines = ['"%s": %s' % (c, values[c]) for c in COMPONENTS]
    lines.append('"@signature-params": ' + params)
    return "\n".join(lines), params


def signed_headers(method, url, key, created=None):
    created = int(created or time.time())
    base, params = signature_base(method, url, key["jwe"], created)
    sig = _load_private_key(key["privateKey"]).sign(base.encode("utf-8"))
    return {
        "x-ebay-signature-key": key["jwe"],
        "Signature-Input": "sig1=" + params,
        "Signature": "sig1=:" + base64.b64encode(sig).decode() + ":",
    }
