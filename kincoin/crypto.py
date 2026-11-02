"""Primitives cryptographiques de KinCoin.

- SHA-256 double (comme Bitcoin) pour les hash de blocs et de transactions ;
- ECDSA sur la courbe secp256k1 (bibliothèque `cryptography`, qui s'appuie sur OpenSSL) ;
- adresses en Base58Check ;
- sérialisation JSON canonique, identique en Python et en JavaScript.
"""
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from . import params

CURVE = ec.SECP256K1()
# Ordre du groupe de secp256k1 (pour la normalisation « low-S »).
CURVE_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


# --------------------------------------------------------------------------- hash
def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256d(data: bytes) -> bytes:
    """SHA-256 appliqué deux fois."""
    return sha256(sha256(data))


def canonical(obj) -> bytes:
    """JSON canonique : clés triées, aucun espace, ASCII uniquement.

    Le portefeuille web (JavaScript) produit exactement les mêmes octets,
    ce qui permet de signer côté navigateur et de vérifier côté nœud.
    Les montants sont des entiers (makuta) : jamais de nombres à virgule.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


# ------------------------------------------------------------------------ base58
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    pad = len(data) - len(data.lstrip(b"\0"))
    return "1" * pad + out


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        if c not in _B58:
            raise ValueError("caractère Base58 invalide")
        n = n * 58 + _B58.index(c)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\0" * pad + body


# ----------------------------------------------------------------------- adresses
def pubkey_to_address(pubkey: bytes) -> str:
    """Adresse = Base58Check(version || 20 premiers octets de SHA256d(clé publique)).

    Bitcoin utilise RIPEMD160(SHA256(pk)) ; RIPEMD160 n'est pas disponible
    dans les navigateurs (WebCrypto), on le remplace par SHA-256 double tronqué.
    """
    payload = bytes([params.ADDRESS_VERSION]) + sha256d(pubkey)[:20]
    return b58encode(payload + sha256d(payload)[:4])


def is_valid_address(address: str) -> bool:
    try:
        raw = b58decode(address)
    except ValueError:
        return False
    if len(raw) != 25 or raw[0] != params.ADDRESS_VERSION:
        return False
    return sha256d(raw[:21])[:4] == raw[21:]


# ------------------------------------------------------------------------- clés
class PrivateKey:
    def __init__(self, key: ec.EllipticCurvePrivateKey):
        self._key = key

    @classmethod
    def generate(cls) -> "PrivateKey":
        return cls(ec.generate_private_key(CURVE))

    @classmethod
    def from_hex(cls, hex_str: str) -> "PrivateKey":
        return cls(ec.derive_private_key(int(hex_str, 16), CURVE))

    def to_hex(self) -> str:
        return format(self._key.private_numbers().private_value, "064x")

    def public_key_bytes(self) -> bytes:
        """Clé publique compressée (33 octets : 02/03 + x)."""
        return self._key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint
        )

    def public_key_hex(self) -> str:
        return self.public_key_bytes().hex()

    def address(self) -> str:
        return pubkey_to_address(self.public_key_bytes())

    def sign(self, digest32: bytes) -> str:
        """Signe un condensé de 32 octets ; renvoie la signature DER en hexadécimal (low-S)."""
        der = self._key.sign(digest32, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        r, s = utils.decode_dss_signature(der)
        if s > CURVE_ORDER // 2:
            s = CURVE_ORDER - s
        return utils.encode_dss_signature(r, s).hex()


def verify(pubkey_hex: str, signature_hex: str, digest32: bytes) -> bool:
    """Vérifie une signature ECDSA secp256k1 (DER hex) sur un condensé de 32 octets."""
    try:
        pub = ec.EllipticCurvePublicKey.from_encoded_point(CURVE, bytes.fromhex(pubkey_hex))
        der = bytes.fromhex(signature_hex)
        r, s = utils.decode_dss_signature(der)
        if s > CURVE_ORDER // 2:   # refuse les signatures « high-S » (malléabilité)
            return False
        pub.verify(der, digest32, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
