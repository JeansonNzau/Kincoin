"""Mineur : un fil d'exécution qui cherche un nonce valide en continu.

Il prépare un bloc candidat (coinbase + transactions du mempool), essaie les
nonces par paquets et recommence dès que la chaîne change (nouveau bloc reçu
d'un pair) ou que le mempool contient de nouvelles transactions.
"""
import threading
import time

from .block import PowSearch
from .chain import Blockchain, InvalidBlock

BATCH = 20_000


class Miner:
    def __init__(self, chain: Blockchain, address: str, on_block, message: str = ""):
        self.chain = chain
        self.address = address
        self.on_block = on_block          # appelé avec le bloc trouvé (depuis le fil du mineur)
        self.message = message
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self.hashes = 0
        self.started_at = None
        self.blocks_found = 0

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def start(self):
        if self.running:
            return
        self._running.set()
        self.started_at = time.time()
        self.hashes = 0
        self._thread = threading.Thread(target=self._loop, name="miner", daemon=True)
        self._thread.start()

    def stop(self):
        self._running.clear()

    def hashrate(self) -> float:
        if not self.running or not self.started_at:
            return 0.0
        return self.hashes / max(time.time() - self.started_at, 1e-6)

    def _loop(self):
        while self.running:
            template = self.chain.block_template(self.address, self.message)
            tip, mempool_size = template["header"]["prev_hash"], len(self.chain.mempool)
            search = PowSearch(template["header"])
            nonce, started = 0, time.time()
            while self.running:
                found = search.search(nonce, BATCH)
                self.hashes += BATCH
                if found is not None:
                    template["header"]["nonce"] = found
                    try:
                        self.chain.add_block(template)
                        self.blocks_found += 1
                        self.on_block(template)
                    except InvalidBlock:
                        pass
                    break
                nonce += BATCH
                # Nouveau tip, nouvelles transactions ou horodatage vieux de 10 s : on reconstruit.
                if (self.chain.tip != tip or len(self.chain.mempool) != mempool_size
                        or time.time() - started > 10):
                    break
                time.sleep(0)  # laisse la main au serveur web (GIL)
