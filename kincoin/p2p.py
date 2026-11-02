"""Réseau pair-à-pair de KinCoin.

Chaque nœud est à la fois serveur (route WebSocket /p2p) et client (il se
connecte aux pairs listés dans PEERS). Les messages sont des objets JSON :

    hello       {node_id, url, height, tip, chainwork}   présentation, envoyée à la connexion
    get_blocks  {locator: [hash, …]}                     « envoie-moi ce qui suit le premier hash connu »
    blocks      {blocks: [bloc, …]}                      réponse (200 blocs max)
    block       {block}                                  annonce d'un nouveau bloc miné
    tx          {tx}                                     annonce d'une nouvelle transaction
    get_peers / peers {peers: [url, …]}                  découverte de pairs

Propagation (« gossip ») : un nœud qui accepte un bloc ou une transaction
nouveaux le relaie à tous ses autres pairs. Un bloc déjà connu n'est jamais
relayé, ce qui arrête la propagation.

Deux transports : WebSocket (par défaut) et HTTP (P2P_TRANSPORT=http), utile
si un hébergeur coupe les WebSocket sortants. La logique est la même.
"""
import asyncio
import json
import logging
import time
import urllib.request

from .block import block_hash
from .chain import Blockchain, InvalidBlock, InvalidTx

log = logging.getLogger("kincoin.p2p")
MAX_BATCH = 200


def normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


class Peer:
    def __init__(self, network: "P2PNetwork", url: str | None, outbound: bool):
        self.network = network
        self.url = url
        self.outbound = outbound
        self.node_id = None
        self.height = 0
        self.chainwork = 0
        self.connected_at = time.time()
        self.last_seen = time.time()

    async def send(self, msg: dict):
        raise NotImplementedError

    def describe(self) -> dict:
        return {"node_id": self.node_id, "url": self.url, "height": self.height,
                "direction": "sortant" if self.outbound else "entrant",
                "transport": self.transport, "last_seen": int(self.last_seen)}


class WsPeer(Peer):
    transport = "websocket"

    def __init__(self, network, ws, url, outbound, kind):
        super().__init__(network, url, outbound)
        self.ws, self.kind = ws, kind   # kind : "client" (lib websockets) ou "server" (Starlette)

    async def send(self, msg: dict):
        data = json.dumps(msg, separators=(",", ":"))
        if self.kind == "server":
            await self.ws.send_text(data)
        else:
            await self.ws.send(data)


class HttpPeer(Peer):
    transport = "http"

    async def send(self, msg: dict):
        body = json.dumps({"from_url": self.network.public_url, "node_id": self.network.node_id,
                           "msg": msg}).encode()
        req = urllib.request.Request(self.url + "/p2p/message", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            await asyncio.to_thread(urllib.request.urlopen, req, timeout=10)
        except Exception as e:   # pair injoignable : on réessaiera plus tard
            log.debug("envoi HTTP vers %s impossible : %s", self.url, e)


class P2PNetwork:
    def __init__(self, chain: Blockchain, node_id: str, public_url: str, seeds: list[str],
                 transport: str = "ws"):
        self.chain = chain
        self.node_id = node_id
        self.public_url = normalize_url(public_url) if public_url else ""
        self.transport = transport
        self.seeds = [normalize_url(s) for s in seeds if s.strip()]
        self.known_urls: set[str] = set(self.seeds)
        self.peers: list[Peer] = []
        self.http_peers: dict[str, HttpPeer] = {}
        self.dialing: set[str] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.tasks: list[asyncio.Task] = []

    # ---------------------------------------------------------------- démarrage
    async def start(self):
        self.loop = asyncio.get_running_loop()
        for url in self.seeds:
            self._dial(url)
        self.tasks.append(asyncio.create_task(self._maintenance()))

    async def stop(self):
        for t in self.tasks:
            t.cancel()

    def _dial(self, url: str):
        url = normalize_url(url)
        if not url or url == self.public_url or url in self.dialing:
            return
        self.known_urls.add(url)
        if self.transport == "http":
            peer = self.http_peers.get(url)
            if peer is None:
                peer = self.http_peers[url] = HttpPeer(self, url, outbound=True)
                self.peers.append(peer)
            asyncio.create_task(peer.send(self.hello()))
            return
        self.dialing.add(url)
        self.tasks.append(asyncio.create_task(self._ws_client(url)))

    async def _ws_client(self, url: str):
        """Connexion sortante persistante, rétablie automatiquement en cas de coupure."""
        import websockets   # fourni par uvicorn[standard]
        ws_url = url.replace("https://", "wss://").replace("http://", "ws://") + "/p2p"
        delay = 2
        while True:
            try:
                async with websockets.connect(ws_url, max_size=16 * 2 ** 20, open_timeout=20,
                                              ping_interval=20, ping_timeout=40) as ws:
                    delay = 2
                    peer = WsPeer(self, ws, url, outbound=True, kind="client")
                    self.peers.append(peer)
                    log.info("connecté au pair %s", url)
                    try:
                        await peer.send(self.hello())
                        async for raw in ws:
                            await self.handle(peer, raw)
                    finally:
                        self._remove(peer)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.info("pair %s injoignable (%s), nouvel essai dans %ss", url, type(e).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def serve_ws(self, ws):
        """Connexion entrante (appelée par la route WebSocket /p2p du serveur)."""
        await ws.accept()
        peer = WsPeer(self, ws, None, outbound=False, kind="server")
        self.peers.append(peer)
        try:
            await peer.send(self.hello())
            while True:
                raw = await ws.receive_text()
                await self.handle(peer, raw)
        except Exception:
            pass
        finally:
            self._remove(peer)

    async def receive_http(self, payload: dict):
        """Message reçu via le transport HTTP (route POST /p2p/message)."""
        url = normalize_url(payload.get("from_url") or "")
        if not url:
            return
        peer = self.http_peers.get(url)
        if peer is None:
            peer = self.http_peers[url] = HttpPeer(self, url, outbound=False)
            self.peers.append(peer)
            self.known_urls.add(url)
        await self.handle(peer, payload["msg"])

    def _remove(self, peer: Peer):
        if peer in self.peers:
            self.peers.remove(peer)

    async def _maintenance(self):
        """Toutes les 30 s : on redonne notre état aux pairs (ce qui déclenche une
        synchronisation si quelqu'un est en retard) et on « réveille » les pairs
        hébergés sur des offres gratuites qui s'endorment sans trafic HTTP."""
        while True:
            await asyncio.sleep(30)
            await self.broadcast(self.hello())
            for url in list(self.known_urls):
                asyncio.create_task(asyncio.to_thread(self._ping_http, url))

    @staticmethod
    def _ping_http(url: str):
        try:
            urllib.request.urlopen(url + "/health", timeout=15).read()
        except Exception:
            pass

    # ------------------------------------------------------------------ envoi
    def hello(self) -> dict:
        return {"type": "hello", "node_id": self.node_id, "url": self.public_url,
                "height": self.chain.height, "tip": self.chain.tip,
                "chainwork": format(self.chain.meta[self.chain.tip]["chainwork"], "x")}

    def unique_peers(self) -> list[Peer]:
        """Un seul pair par nœud distant (deux nœuds peuvent être reliés dans les deux sens)."""
        seen, out = set(), []
        for p in self.peers:
            key = p.node_id or id(p)
            if key not in seen and p.node_id != self.node_id:
                seen.add(key)
                out.append(p)
        return out

    async def broadcast(self, msg: dict, exclude: Peer | None = None):
        targets = [p for p in self.unique_peers() if p is not exclude
                   and (exclude is None or p.node_id is None or p.node_id != exclude.node_id)]
        await asyncio.gather(*(self._safe_send(p, msg) for p in targets))

    async def _safe_send(self, peer: Peer, msg: dict):
        try:
            await peer.send(msg)
        except Exception:
            self._remove(peer)

    def broadcast_block_threadsafe(self, block: dict):
        """Appelé par le fil du mineur quand il trouve un bloc."""
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast({"type": "block", "block": block}), self.loop)

    async def request_sync(self, peer: Peer):
        await self._safe_send(peer, {"type": "get_blocks", "locator": self.chain.locator()})

    # -------------------------------------------------------------- réception
    async def handle(self, peer: Peer, raw):
        try:
            msg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            kind = msg.get("type")
        except (ValueError, AttributeError):
            return
        peer.last_seen = time.time()

        if kind == "hello":
            if msg.get("node_id") == self.node_id:      # connexion à soi-même
                self._remove(peer)
                return
            peer.node_id = msg.get("node_id")
            peer.height = int(msg.get("height", 0))
            peer.chainwork = int(msg.get("chainwork", "0"), 16)
            url = normalize_url(msg.get("url") or "")
            if url:
                peer.url = peer.url or url
                if url not in self.known_urls and url != self.public_url:
                    self._dial(url)                    # découverte d'un nouveau pair
            if peer.chainwork > self.chain.meta[self.chain.tip]["chainwork"]:
                await self.request_sync(peer)
            if self.transport == "http" and not peer.outbound and not msg.get("reply"):
                await self._safe_send(peer, {**self.hello(), "reply": True})
            await self._safe_send(peer, {"type": "get_peers"})

        elif kind == "get_blocks":
            blocks = self.chain.blocks_after(msg.get("locator") or [], MAX_BATCH)
            await self._safe_send(peer, {"type": "blocks", "blocks": blocks})

        elif kind == "blocks":
            blocks = msg.get("blocks") or []
            need_more = False
            for b in blocks:
                try:
                    if self.chain.add_block(b) == "orphan":
                        need_more = True
                except (InvalidBlock, KeyError, TypeError, ValueError) as e:
                    log.warning("bloc rejeté pendant la synchronisation : %s", e)
                    break
            if blocks and (len(blocks) >= MAX_BATCH or need_more):
                await self.request_sync(peer)

        elif kind == "block":
            b = msg.get("block")
            try:
                result = self.chain.add_block(b)
            except (InvalidBlock, KeyError, TypeError, ValueError) as e:
                log.warning("bloc rejeté : %s", e)
                return
            if result in ("added", "reorg", "side"):
                log.info("bloc %s reçu (%s)", block_hash(b)[:16], result)
                await self.broadcast({"type": "block", "block": b}, exclude=peer)
            elif result == "orphan":
                await self.request_sync(peer)

        elif kind == "tx":
            tx = msg.get("tx")
            try:
                before = len(self.chain.mempool)
                self.chain.add_transaction(tx)
            except (InvalidTx, KeyError, TypeError, ValueError):
                return
            if len(self.chain.mempool) > before:
                await self.broadcast({"type": "tx", "tx": tx}, exclude=peer)

        elif kind == "get_peers":
            urls = [u for u in self.known_urls | {self.public_url} if u]
            await self._safe_send(peer, {"type": "peers", "peers": urls[:50]})

        elif kind == "peers":
            for url in (msg.get("peers") or [])[:50]:
                url = normalize_url(str(url))
                if url and url not in self.known_urls and url != self.public_url:
                    self._dial(url)
