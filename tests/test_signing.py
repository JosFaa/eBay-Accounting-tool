import base64
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ebay_tool.signing import _load_private_key, signature_base, signed_headers

URL = "https://apiz.ebay.com/sell/finances/v1/transaction"


def make_key(pem=False):
    priv = Ed25519PrivateKey.generate()
    if pem:
        text = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode()
    else:
        text = base64.b64encode(priv.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption())).decode()
    return priv, {"privateKey": text, "jwe": "eyJ6aXAiOiJERUYi.test"}


class TestSigning(unittest.TestCase):
    def test_base_matches_ebay_sdk_format(self):
        base, params = signature_base("get", URL + "?filter=x&limit=10", "JWE", 1658440308)
        self.assertEqual(base, (
            '"x-ebay-signature-key": JWE\n'
            '"@method": GET\n'
            '"@path": /sell/finances/v1/transaction\n'
            '"@authority": apiz.ebay.com\n'
            '"@signature-params": ("x-ebay-signature-key" "@method" "@path" "@authority");created=1658440308'))

    def test_headers_verify_with_public_key(self):
        for pem in (False, True):
            priv, key = make_key(pem)
            h = signed_headers("GET", URL, key, created=1700000000)
            self.assertEqual(h["Signature-Input"],
                             'sig1=("x-ebay-signature-key" "@method" "@path" "@authority");created=1700000000')
            self.assertTrue(h["Signature"].startswith("sig1=:") and h["Signature"].endswith(":"))
            sig = base64.b64decode(h["Signature"][6:-1])
            base, _ = signature_base("GET", URL, key["jwe"], 1700000000)
            priv.public_key().verify(sig, base.encode())  # raises if wrong
            self.assertEqual(h["x-ebay-signature-key"], key["jwe"])

    def test_bad_key_raises(self):
        with self.assertRaises(Exception):
            _load_private_key("not-a-key")


if __name__ == "__main__":
    unittest.main()
