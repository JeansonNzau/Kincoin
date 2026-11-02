"""Transactions KinCoin (modèle UTXO).

Format d'une transaction (JSON) :

    {
      "version": 1,
      "timestamp": 1793150000,
      "inputs":  [{"txid": "<hex>", "vout": 0, "pubkey": "<hex>", "signature": "<DER hex>"}],
      "outputs": [{"address": "K...", "amount": 150000000}]
    }

- Une entrée dépense une sortie non dépensée (UTXO) désignée par (txid, vout).
- `pubkey` doit correspondre à l'adresse propriétaire de l'UTXO dépensé.
- Toutes les entrées signent le même condensé : le SHA-256 double de la
  transaction dont les champs `signature` sont vides (équivalent de SIGHASH_ALL).
- Frais = somme des entrées - somme des sorties ; ils vont au mineur.

La transaction « coinbase » (première de chaque bloc) n'a pas d'entrées et porte
un champ `coinbase` égal à la hauteur du bloc, ce qui rend son txid unique.
"""
import copy
import time

from . import params
from .crypto import PrivateKey, canonical, is_valid_address, sha256d

MAX_MESSAGE_LEN = 100


def txid(tx: dict) -> str:
    return sha256d(canonical(tx)).hex()


def sighash(tx: dict) -> bytes:
    """Condensé signé par chaque entrée : la transaction sans les signatures."""
    unsigned = copy.deepcopy(tx)
    for i in unsigned["inputs"]:
        i["signature"] = ""
    return sha256d(canonical(unsigned))


def is_coinbase(tx: dict) -> bool:
    return "coinbase" in tx


def make_coinbase(height: int, address: str, amount: int, timestamp: int | None = None,
                  message: str = "") -> dict:
    """Le mineur peut inscrire un court message dans sa coinbase (comme dans Bitcoin)."""
    tx = {
        "version": 1,
        "coinbase": height,
        "timestamp": int(timestamp if timestamp is not None else time.time()),
        "inputs": [],
        "outputs": [{"address": address, "amount": amount}],
    }
    if message:
        tx["message"] = message[:MAX_MESSAGE_LEN]
    return tx


def build_transaction(key: PrivateKey, utxos: list[dict], to_address: str, amount: int,
                      fee: int = 0) -> dict:
    """Construit et signe une transaction (utilisé par le portefeuille en ligne de commande).

    `utxos` : liste de {"txid", "vout", "amount"} appartenant à la clé.
    La monnaie rendue revient à l'adresse de l'expéditeur.
    """
    if amount <= 0:
        raise ValueError("le montant doit être positif")
    selected, total = [], 0
    for u in sorted(utxos, key=lambda u: u["amount"], reverse=True):
        selected.append(u)
        total += u["amount"]
        if total >= amount + fee:
            break
    if total < amount + fee:
        raise ValueError("solde insuffisant")
    pub = key.public_key_hex()
    tx = {
        "version": 1,
        "timestamp": int(time.time()),
        "inputs": [{"txid": u["txid"], "vout": u["vout"], "pubkey": pub, "signature": ""} for u in selected],
        "outputs": [{"address": to_address, "amount": amount}],
    }
    change = total - amount - fee
    if change > 0:
        tx["outputs"].append({"address": key.address(), "amount": change})
    digest = sighash(tx)
    for i in tx["inputs"]:
        i["signature"] = key.sign(digest)
    return tx


def check_structure(tx: dict) -> None:
    """Vérifications indépendantes de l'état de la chaîne. Lève ValueError si invalide."""
    if not isinstance(tx, dict) or tx.get("version") != 1:
        raise ValueError("version de transaction invalide")
    allowed = {"version", "timestamp", "inputs", "outputs", "coinbase", "message"}
    if set(tx) - allowed:
        raise ValueError("champ inconnu dans la transaction")
    if "message" in tx and (not is_coinbase(tx) or not isinstance(tx["message"], str)
                            or len(tx["message"]) > MAX_MESSAGE_LEN):
        raise ValueError("message autorisé uniquement dans la coinbase (100 caractères max)")
    if not isinstance(tx.get("timestamp"), int):
        raise ValueError("horodatage invalide")
    inputs, outputs = tx.get("inputs"), tx.get("outputs")
    if not isinstance(inputs, list) or not isinstance(outputs, list) or not outputs:
        raise ValueError("entrées/sorties invalides")
    if is_coinbase(tx):
        if inputs or not isinstance(tx["coinbase"], int):
            raise ValueError("coinbase invalide")
    elif not inputs:
        raise ValueError("une transaction doit avoir au moins une entrée")
    seen = set()
    for i in inputs:
        if set(i) != {"txid", "vout", "pubkey", "signature"}:
            raise ValueError("entrée mal formée")
        if not (isinstance(i["txid"], str) and len(i["txid"]) == 64 and isinstance(i["vout"], int)):
            raise ValueError("référence d'entrée invalide")
        if (i["txid"], i["vout"]) in seen:
            raise ValueError("la même sortie est dépensée deux fois dans la transaction")
        seen.add((i["txid"], i["vout"]))
    for o in outputs:
        if set(o) != {"address", "amount"}:
            raise ValueError("sortie mal formée")
        if not isinstance(o["amount"], int) or isinstance(o["amount"], bool) or o["amount"] <= 0:
            raise ValueError("montant de sortie invalide (entier > 0 en makuta)")
        if not is_valid_address(o["address"]):
            raise ValueError(f"adresse invalide : {o['address']}")
    if sum(o["amount"] for o in outputs) > params.max_supply():
        raise ValueError("montant supérieur à l'offre maximale")
