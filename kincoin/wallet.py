"""Portefeuille en ligne de commande (secours si le portefeuille web n'est pas disponible).

    python -m kincoin.wallet new                       crée une clé dans wallet.json
    python -m kincoin.wallet address                   affiche l'adresse
    python -m kincoin.wallet balance  [--node URL]
    python -m kincoin.wallet send ADRESSE MONTANT_KIN [--fee MAKUTA] [--node URL]

Le fichier peut être changé avec --wallet (ex. la clé d'un mineur : data/node_key.json).
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from . import params
from .crypto import PrivateKey, is_valid_address
from .tx import build_transaction


def _get(node, path):
    with urllib.request.urlopen(node.rstrip("/") + path, timeout=15) as r:
        return json.load(r)


def _post(node, path, body):
    req = urllib.request.Request(node.rstrip("/") + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"refusé par le nœud : {json.load(e).get('detail')}")


def fmt(makuta: int) -> str:
    return f"{makuta / params.COIN:,.8f} KIN".replace(",", " ")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kincoin.wallet")
    ap.add_argument("--wallet", default="wallet.json")
    ap.add_argument("--node", default=os.environ.get("KIN_NODE", "http://localhost:8001"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("new")
    sub.add_parser("address")
    sub.add_parser("balance")
    s = sub.add_parser("send")
    s.add_argument("to")
    s.add_argument("amount", type=lambda v: float(v.replace(",", ".")), help="montant en KIN (12,5 ou 12.5)")
    s.add_argument("--fee", type=int, default=1000, help="frais en makuta (défaut 1000)")
    a = ap.parse_args(argv)

    if a.cmd == "new":
        if os.path.exists(a.wallet):
            sys.exit(f"{a.wallet} existe déjà")
        k = PrivateKey.generate()
        with open(a.wallet, "w") as f:
            json.dump({"private_key": k.to_hex(), "address": k.address()}, f, indent=2)
        os.chmod(a.wallet, 0o600)
        print(k.address())
        return

    with open(a.wallet) as f:
        key = PrivateKey.from_hex(json.load(f)["private_key"])
    if a.cmd == "address":
        print(key.address())
    elif a.cmd == "balance":
        info = _get(a.node, f"/address/{key.address()}")
        print(key.address())
        print("solde :", fmt(info["balance"]), f"({len(info['utxos'])} UTXO disponibles)")
    elif a.cmd == "send":
        if not is_valid_address(a.to):
            sys.exit("adresse de destination invalide")
        info = _get(a.node, f"/address/{key.address()}")
        amount = round(a.amount * params.COIN)
        try:
            tx = build_transaction(key, info["utxos"], a.to, amount, a.fee)
        except ValueError as e:
            sys.exit(f"impossible : {e}")
        print("transaction envoyée :", _post(a.node, "/tx", tx)["txid"])


if __name__ == "__main__":
    main()
