"""Blocs et preuve de travail.

Un bloc = un en-tête + la liste de ses transactions :

    {
      "header": {
        "version": 1, "height": 12, "prev_hash": "<hex>", "merkle_root": "<hex>",
        "timestamp": 1793150000, "target": "<64 hex>", "nonce": 48213
      },
      "transactions": [ <coinbase>, <tx>, ... ]
    }

Hash du bloc = SHA-256 double de l'en-tête (JSON canonique).
Le bloc est valide si ce hash, lu comme un entier de 256 bits, est <= target.
Plus la cible est petite, plus il faut d'essais (de nonces) pour la trouver.
"""
from . import params
from .crypto import canonical, pubkey_to_address, sha256d
from .merkle import merkle_root
from .tx import make_coinbase, txid


def header_hash(header: dict) -> str:
    return sha256d(canonical(header)).hex()


def block_hash(block: dict) -> str:
    return header_hash(block["header"])


def target_hex(target: int) -> str:
    return format(target, "064x")


def work(target: int) -> int:
    """Quantité de travail représentée par un bloc (nombre moyen d'essais)."""
    return 2 ** 256 // (target + 1)


def difficulty(target: int) -> float:
    """Difficulté relative : combien de fois plus dur que la cible initiale."""
    return params.INITIAL_TARGET / target


def genesis_block() -> dict:
    """Bloc 0, identique sur tous les nœuds. Sa récompense est envoyée à une
    adresse sans clé privée connue (comme le bloc genèse de Bitcoin, non dépensable)."""
    # « Clé publique » qui n'est pas un point de la courbe : personne ne peut signer pour elle.
    burn_address = pubkey_to_address(sha256d(params.GENESIS_MESSAGE.encode()))
    cb = make_coinbase(0, burn_address, params.block_reward(0), params.GENESIS_TIMESTAMP,
                       message=params.GENESIS_MESSAGE)
    header = {
        "version": 1,
        "height": 0,
        "prev_hash": "00" * 32,
        "merkle_root": merkle_root([txid(cb)]),
        "timestamp": params.GENESIS_TIMESTAMP,
        "target": target_hex(params.INITIAL_TARGET),
        "nonce": 0,
    }
    return {"header": header, "transactions": [cb]}


class PowSearch:
    """Recherche de nonce optimisée : seul le nonce change entre deux essais,
    on pré-calcule donc le JSON canonique avant et après lui."""

    def __init__(self, header: dict):
        h = dict(header)
        h["nonce"] = 0
        raw = canonical(h)
        marker = b'"nonce":0'
        idx = raw.index(marker) + len(b'"nonce":')
        self.prefix, self.suffix = raw[:idx], raw[idx + 1:]
        self.target = int(header["target"], 16)

    def search(self, start: int, count: int) -> int | None:
        prefix, suffix, target = self.prefix, self.suffix, self.target
        for nonce in range(start, start + count):
            digest = sha256d(prefix + str(nonce).encode() + suffix)
            if int.from_bytes(digest, "big") <= target:
                return nonce
        return None
