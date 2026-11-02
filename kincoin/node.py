"""Nœud KinCoin : API REST (FastAPI) + réseau P2P + mineur.

Lancement :  uvicorn kincoin.node:app --host 0.0.0.0 --port 8000

Variables d'environnement :
    NODE_NAME       nom affiché (défaut : kincoin-node)
    DATA_DIR        dossier où la chaîne est enregistrée (défaut : ./data)
    PUBLIC_URL      URL publique de CE nœud, annoncée aux pairs (ex. https://kincoin-1.onrender.com)
    PEERS           URL des autres nœuds, séparées par des virgules
    P2P_TRANSPORT   ws (défaut) ou http
    MINING          1 pour miner au démarrage (défaut : 0)
    MINER_ADDRESS   adresse qui reçoit les récompenses (sinon une clé est créée dans DATA_DIR)
    MINER_MESSAGE   message inscrit dans les coinbase de ce nœud
    ADMIN_TOKEN     si défini, exigé (en-tête X-Admin-Token) pour démarrer/arrêter le minage
    FRONTEND_DIR    dossier du portefeuille/explorateur à servir sur /app (optionnel)
"""
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import params
from .block import block_hash
from .chain import Blockchain, InvalidTx, outpoint
from .crypto import PrivateKey, is_valid_address
from .miner import Miner
from .p2p import P2PNetwork
from .tx import is_coinbase, txid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("kincoin.node")

VERSION = "1.0.0"
NODE_NAME = os.environ.get("NODE_NAME", "kincoin-node")
DATA_DIR = os.environ.get("DATA_DIR", "./data")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", "")

chain = Blockchain(DATA_DIR)


def _miner_address() -> str:
    addr = os.environ.get("MINER_ADDRESS", "").strip()
    if addr:
        if not is_valid_address(addr):
            raise SystemExit(f"MINER_ADDRESS invalide : {addr}")
        return addr
    path = os.path.join(DATA_DIR, "node_key.json")
    if os.path.exists(path):
        with open(path) as f:
            return PrivateKey.from_hex(json.load(f)["private_key"]).address()
    key = PrivateKey.generate()
    with open(path, "w") as f:
        json.dump({"private_key": key.to_hex(), "address": key.address()}, f)
    os.chmod(path, 0o600)
    log.info("clé du mineur créée dans %s", path)
    return key.address()


def _node_id() -> str:
    path = os.path.join(DATA_DIR, "node_id")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(8))
    with open(path) as f:
        return f.read().strip()


network = P2PNetwork(
    chain,
    node_id=_node_id(),
    # Render et Fly.io fournissent l'URL publique automatiquement.
    public_url=os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    or (f"https://{os.environ['FLY_APP_NAME']}.fly.dev" if os.environ.get("FLY_APP_NAME") else ""),
    seeds=os.environ.get("PEERS", "").split(","),
    transport=os.environ.get("P2P_TRANSPORT", "ws"),
)
miner = Miner(chain, _miner_address(), on_block=network.broadcast_block_threadsafe,
              message=os.environ.get("MINER_MESSAGE", f"mined by {NODE_NAME}"))


@asynccontextmanager
async def lifespan(app):
    await network.start()
    if os.environ.get("MINING", "0") == "1":
        miner.start()
    log.info("%s prêt : hauteur %d, pairs %s", NODE_NAME, chain.height, network.seeds)
    yield
    miner.stop()
    await network.stop()


app = FastAPI(title="KinCoin node", version=VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ utilitaires
def _require_admin(request: Request):
    if ADMIN_TOKEN and request.headers.get("x-admin-token") != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="jeton d'administration requis")


def _tx_view(tx: dict, block: dict | None) -> dict:
    """Transaction enrichie pour l'explorateur : adresses et montants des entrées, frais."""
    inputs = []
    for i in tx["inputs"]:
        src = chain.utxo.get(outpoint(i["txid"], i["vout"])) or chain._spent_output(i["txid"], i["vout"])
        inputs.append({**i, "address": src and src["address"], "amount": src and src["amount"]})
    total_in = sum(i["amount"] or 0 for i in inputs)
    total_out = sum(o["amount"] for o in tx["outputs"])
    view = {
        "txid": txid(tx),
        "coinbase": is_coinbase(tx),
        "message": tx.get("message"),
        "timestamp": tx["timestamp"],
        "inputs": inputs,
        "outputs": tx["outputs"],
        "total_out": total_out,
        "fee": 0 if is_coinbase(tx) else total_in - total_out,
        "status": "mempool",
        "block": None,
        "height": None,
        "confirmations": 0,
    }
    if block:
        h = block["header"]["height"]
        view.update(status="confirmée", block=block_hash(block), height=h,
                    confirmations=chain.height - h + 1)
    return view


def _block_summary(block: dict) -> dict:
    hd, txs = block["header"], block["transactions"]
    target = int(hd["target"], 16)
    return {
        "hash": block_hash(block),
        "height": hd["height"],
        "timestamp": hd["timestamp"],
        "tx_count": len(txs),
        "miner": txs[0]["outputs"][0]["address"],
        "reward": sum(o["amount"] for o in txs[0]["outputs"]),
        "zero_bits": 256 - target.bit_length(),
        "difficulty": params.INITIAL_TARGET / target,
        "message": txs[0].get("message"),
    }


# ------------------------------------------------------------------------ routes
@app.get("/")
async def root(request: Request):
    if FRONTEND_DIR and os.path.isdir(FRONTEND_DIR):
        return RedirectResponse("/app/")
    return {"name": NODE_NAME, "kincoin": VERSION, "docs": "/docs", "info": "/info"}


@app.get("/health")
async def health(request: Request):
    return {"ok": True, "height": chain.height}


@app.get("/info")
async def info(request: Request):
    return {
        "name": NODE_NAME,
        "version": VERSION,
        "node_id": network.node_id,
        "public_url": network.public_url,
        **chain.stats(),
        "peers": len(network.unique_peers()),
        "mining": miner.running,
        "miner_address": miner.address,
        "local_hashrate": miner.hashrate(),
        "blocks_found": miner.blocks_found,
        "time": int(time.time()),
    }


@app.get("/blocks")
async def blocks(request: Request):
    limit = min(int(request.query_params.get("limit", 20)), 100)
    before = request.query_params.get("before")
    end = chain.height + 1 if before is None else max(0, min(int(before), chain.height + 1))
    start = max(0, end - limit)
    with chain.lock:
        hashes = chain.main[start:end]
        return [_block_summary(chain.blocks[h]) for h in reversed(hashes)]


@app.get("/block/{ident}")
async def block(request: Request, ident: str):
    with chain.lock:
        b = chain.block_at(ident)
        if b is None:
            raise HTTPException(status_code=404, detail="bloc introuvable")
        h = block_hash(b)
        main = chain.is_main(h)
        height = b["header"]["height"]
        nxt = chain.main[height + 1] if main and height + 1 < len(chain.main) else None
        return {
            **_block_summary(b),
            "header": b["header"],
            "in_main_chain": main,
            "confirmations": chain.height - height + 1 if main else 0,
            "next_hash": nxt,
            "transactions": [_tx_view(tx, b if main else None) for tx in b["transactions"]],
        }


@app.get("/tx/{tx_id}")
async def get_tx(request: Request, tx_id: str):
    found = chain.find_tx(tx_id)
    if not found:
        raise HTTPException(status_code=404, detail="transaction introuvable")
    with chain.lock:
        return _tx_view(*found)


@app.get("/address/{address}")
async def address(request: Request, address: str):
    if not is_valid_address(address):
        raise HTTPException(status_code=400, detail="adresse invalide")
    return chain.address_info(address)


@app.get("/mempool")
async def mempool(request: Request):
    with chain.lock:
        return [_tx_view(tx, None) for tx in chain.mempool.values()]


@app.post("/tx")
async def submit_tx(request: Request):
    try:
        tx = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON invalide")
    try:
        t = chain.add_transaction(tx)
    except InvalidTx as e:
        raise HTTPException(status_code=400, detail=str(e))
    await network.broadcast({"type": "tx", "tx": tx})
    return {"txid": t, "status": "mempool"}


@app.get("/search/{q}")
async def search(request: Request, q: str):
    q = q.strip()
    if q.isdigit() and int(q) <= chain.height:
        return {"type": "block", "id": chain.main[int(q)]}
    if is_valid_address(q):
        return {"type": "address", "id": q}
    if chain.block_at(q):
        return {"type": "block", "id": q}
    if chain.find_tx(q):
        return {"type": "tx", "id": q}
    raise HTTPException(status_code=404, detail="aucun bloc, transaction ou adresse ne correspond")


@app.get("/peers")
async def peers(request: Request):
    return {"node_id": network.node_id, "transport": network.transport,
            "peers": [p.describe() for p in network.unique_peers()],
            "known_urls": sorted(network.known_urls)}


@app.post("/peers")
async def add_peer(request: Request):
    _require_admin(request)
    body = await request.json()
    network._dial(body.get("url", ""))
    return {"ok": True}


@app.post("/mining/start")
async def mining_start(request: Request):
    _require_admin(request)
    miner.start()
    return {"mining": True, "address": miner.address}


@app.post("/mining/stop")
async def mining_stop(request: Request):
    _require_admin(request)
    miner.stop()
    return {"mining": False}


@app.websocket("/p2p")
async def p2p_ws(websocket: WebSocket):
    await network.serve_ws(websocket)


@app.post("/p2p/message")
async def p2p_http(request: Request):
    await network.receive_http(await request.json())
    return {"ok": True}


if FRONTEND_DIR and os.path.isdir(FRONTEND_DIR):
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="app")
