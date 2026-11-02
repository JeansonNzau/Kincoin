"""Arbre de Merkle (même construction que Bitcoin).

Les feuilles sont les identifiants des transactions. On hache les paires deux
à deux jusqu'à obtenir une racine unique ; si un niveau a un nombre impair
d'éléments, le dernier est dupliqué.
"""
from .crypto import sha256d


def merkle_root(txids: list[str]) -> str:
    if not txids:
        return "00" * 32
    level = [bytes.fromhex(t) for t in txids]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0].hex()


def merkle_proof(txids: list[str], index: int) -> list[dict]:
    """Preuve d'inclusion : liste des hash « frères » à combiner pour retrouver la racine."""
    level = [bytes.fromhex(t) for t in txids]
    proof = []
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        sibling = index ^ 1
        proof.append({"hash": level[sibling].hex(), "position": "left" if sibling < index else "right"})
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
        index //= 2
    return proof


def verify_proof(txid: str, proof: list[dict], root: str) -> bool:
    h = bytes.fromhex(txid)
    for step in proof:
        sib = bytes.fromhex(step["hash"])
        h = sha256d(sib + h) if step["position"] == "left" else sha256d(h + sib)
    return h.hex() == root
