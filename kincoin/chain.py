"""État de la blockchain : chaîne principale, ensemble UTXO, mempool, forks.

Règle de consensus : on suit la chaîne qui a le plus de travail cumulé
(« la plus longue » au sens de Bitcoin). Quand une branche concurrente devient
plus lourde, on réorganise : on rejoue toute la nouvelle branche depuis la
genèse pour reconstruire l'ensemble UTXO (simple et sûr pour une petite chaîne).
"""
import json
import os
import statistics
import threading
import time

from . import params
from .block import block_hash, genesis_block, target_hex, work
from .crypto import pubkey_to_address, verify
from .merkle import merkle_root
from .tx import check_structure, is_coinbase, make_coinbase, sighash, txid


class InvalidBlock(ValueError):
    pass


class InvalidTx(ValueError):
    pass


def outpoint(tx_id: str, vout: int) -> str:
    return f"{tx_id}:{vout}"


class Blockchain:
    def __init__(self, data_dir: str | None = None):
        self.lock = threading.RLock()
        self.data_dir = data_dir
        self.blocks: dict[str, dict] = {}       # tous les blocs connus (y compris branches secondaires)
        self.meta: dict[str, dict] = {}         # hash -> {height, prev, chainwork}
        self.main: list[str] = []               # hash des blocs de la chaîne principale
        self.utxo: dict[str, dict] = {}         # "txid:vout" -> {address, amount, height, coinbase}
        self.tx_index: dict[str, tuple[str, int]] = {}  # txid -> (hash du bloc, position)
        self.mempool: dict[str, dict] = {}
        self.mempool_spent: set[str] = set()
        self.orphans: dict[str, dict] = {}      # blocs dont le parent est inconnu (hash -> bloc)
        self.listeners = []                     # fonctions appelées à chaque nouveau tip

        g = genesis_block()
        gh = block_hash(g)
        self.blocks[gh] = g
        self.meta[gh] = {"height": 0, "prev": None, "chainwork": work(int(g["header"]["target"], 16))}
        self.main = [gh]
        self.utxo, self.tx_index = self._replay(self.main)
        self._load()

    # ------------------------------------------------------------------ helpers
    @property
    def tip(self) -> str:
        return self.main[-1]

    @property
    def height(self) -> int:
        return len(self.main) - 1

    def header(self, h: str) -> dict:
        return self.blocks[h]["header"]

    def _path_to(self, h: str) -> list[str]:
        """Liste des hash de la genèse jusqu'au bloc h inclus."""
        path = []
        while h is not None:
            path.append(h)
            h = self.meta[h]["prev"]
        return path[::-1]

    def expected_target(self, path: list[str]) -> int:
        """Cible que doit avoir le bloc suivant le dernier bloc de `path`.

        Tous les ADJUST_INTERVAL blocs, on compare le temps réellement écoulé
        au temps visé, et on ajuste la cible proportionnellement (borné à x4).
        """
        height = len(path)
        prev_target = int(self.header(path[-1])["target"], 16)
        if height % params.ADJUST_INTERVAL != 0:
            return prev_target
        # La genèse a une date fixe, sans rapport avec le début réel du minage :
        # on l'exclut de la mesure du premier intervalle.
        start = max(height - params.ADJUST_INTERVAL, 1)
        first = self.header(path[start])
        last = self.header(path[height - 1])
        gaps = height - 1 - start
        if gaps <= 0:
            return prev_target
        expected = gaps * params.BLOCK_TIME
        actual = last["timestamp"] - first["timestamp"]
        actual = max(expected // params.MAX_ADJUST_FACTOR, min(actual, expected * params.MAX_ADJUST_FACTOR))
        new_target = prev_target * actual // expected
        return max(1, min(new_target, params.MAX_TARGET))

    def median_time_past(self, path: list[str]) -> int:
        times = [self.header(h)["timestamp"] for h in path[-params.MEDIAN_TIME_SPAN:]]
        return int(statistics.median_low(times))

    # --------------------------------------------------------------- validation
    @staticmethod
    def check_block_standalone(block: dict) -> None:
        """Vérifications qui ne dépendent pas du reste de la chaîne."""
        if not isinstance(block, dict) or set(block) != {"header", "transactions"}:
            raise InvalidBlock("bloc mal formé")
        hd, txs = block["header"], block["transactions"]
        keys = {"version", "height", "prev_hash", "merkle_root", "timestamp", "target", "nonce"}
        if not isinstance(hd, dict) or set(hd) != keys:
            raise InvalidBlock("en-tête mal formé")
        if not all(isinstance(hd[k], int) for k in ("version", "height", "timestamp", "nonce")):
            raise InvalidBlock("champ numérique invalide dans l'en-tête")
        if hd["version"] != 1 or hd["nonce"] < 0:
            raise InvalidBlock("version ou nonce invalide")
        if not (isinstance(hd["target"], str) and len(hd["target"]) == 64):
            raise InvalidBlock("cible invalide")
        if int(block_hash(block), 16) > int(hd["target"], 16):
            raise InvalidBlock("preuve de travail insuffisante (hash > cible)")
        if hd["timestamp"] > time.time() + params.MAX_FUTURE_DRIFT:
            raise InvalidBlock("bloc daté dans le futur")
        if not isinstance(txs, list) or not txs or len(txs) > params.MAX_TX_PER_BLOCK:
            raise InvalidBlock("nombre de transactions invalide")
        for i, tx in enumerate(txs):
            try:
                check_structure(tx)
            except ValueError as e:
                raise InvalidBlock(f"transaction {i} : {e}") from e
            if is_coinbase(tx) != (i == 0):
                raise InvalidBlock("la coinbase doit être la première et unique transaction de ce type")
        if txs[0]["coinbase"] != hd["height"]:
            raise InvalidBlock("hauteur de la coinbase incorrecte")
        ids = [txid(t) for t in txs]
        if len(set(ids)) != len(ids):
            raise InvalidBlock("transaction en double dans le bloc")
        if merkle_root(ids) != hd["merkle_root"]:
            raise InvalidBlock("racine de Merkle incorrecte")

    def _check_header_context(self, block: dict, path: list[str]) -> None:
        """Vérifie l'en-tête par rapport à ses ancêtres (`path` = genèse..parent)."""
        hd = block["header"]
        if hd["height"] != len(path):
            raise InvalidBlock("hauteur incorrecte")
        if int(hd["target"], 16) != self.expected_target(path):
            raise InvalidBlock("difficulté incorrecte (cible inattendue)")
        if hd["timestamp"] <= self.median_time_past(path):
            raise InvalidBlock("horodatage trop ancien (<= médiane des 11 derniers blocs)")

    @staticmethod
    def check_tx_inputs(tx: dict, utxo: dict, spent: set) -> int:
        """Vérifie les entrées d'une transaction ordinaire ; renvoie les frais."""
        digest = sighash(tx)
        total_in = 0
        for i in tx["inputs"]:
            op = outpoint(i["txid"], i["vout"])
            coin = utxo.get(op)
            if coin is None or op in spent:
                raise InvalidTx(f"sortie {op[:16]}… inexistante ou déjà dépensée")
            try:
                owner = pubkey_to_address(bytes.fromhex(i["pubkey"]))
            except ValueError:
                raise InvalidTx("clé publique invalide")
            if owner != coin["address"]:
                raise InvalidTx("la clé publique ne correspond pas au propriétaire de la sortie")
            if not verify(i["pubkey"], i["signature"], digest):
                raise InvalidTx("signature ECDSA invalide")
            total_in += coin["amount"]
        total_out = sum(o["amount"] for o in tx["outputs"])
        if total_out > total_in:
            raise InvalidTx("les sorties dépassent les entrées")
        return total_in - total_out

    def _connect(self, block: dict, utxo: dict, tx_index: dict) -> None:
        """Valide les transactions d'un bloc et les applique à `utxo` (modifié sur place)."""
        h = block_hash(block)
        height = block["header"]["height"]
        spent: set[str] = set()
        fees = 0
        txs = block["transactions"]
        for tx in txs[1:]:
            try:
                fees += self.check_tx_inputs(tx, utxo, spent)
            except InvalidTx as e:
                raise InvalidBlock(f"transaction invalide : {e}") from e
            spent.update(outpoint(i["txid"], i["vout"]) for i in tx["inputs"])
        cb_out = sum(o["amount"] for o in txs[0]["outputs"])
        if height > 0 and cb_out > params.block_reward(height) + fees:
            raise InvalidBlock("la coinbase réclame plus que récompense + frais")
        for op in spent:
            del utxo[op]
        for pos, tx in enumerate(txs):
            t = txid(tx)
            if t in tx_index:
                raise InvalidBlock("transaction déjà présente dans la chaîne")
            tx_index[t] = (h, pos)
            for vout, o in enumerate(tx["outputs"]):
                utxo[outpoint(t, vout)] = {"address": o["address"], "amount": o["amount"],
                                           "height": height, "coinbase": pos == 0}

    def _replay(self, path: list[str]) -> tuple[dict, dict]:
        utxo, tx_index = {}, {}
        for h in path:
            self._connect(self.blocks[h], utxo, tx_index)
        return utxo, tx_index

    # ----------------------------------------------------------- ajout de blocs
    def add_block(self, block: dict, persist: bool = True) -> str:
        """Ajoute un bloc reçu ou miné. Renvoie 'exists', 'orphan', 'side',
        'added' ou 'reorg'. Lève InvalidBlock si le bloc est invalide."""
        with self.lock:
            h = block_hash(block)
            if h in self.blocks:
                return "exists"
            self.check_block_standalone(block)
            prev = block["header"]["prev_hash"]
            if prev not in self.blocks:
                if len(self.orphans) > 200:
                    self.orphans.clear()
                self.orphans[h] = block
                return "orphan"
            path = self.main if prev == self.tip else self._path_to(prev)
            self._check_header_context(block, path)
            chainwork = self.meta[prev]["chainwork"] + work(int(block["header"]["target"], 16))

            if prev == self.tip:
                utxo, tx_index = dict(self.utxo), dict(self.tx_index)
                self._connect(block, utxo, tx_index)
                self._store(h, block, prev, chainwork, persist)
                self.main.append(h)
                self.utxo, self.tx_index = utxo, tx_index
                self._refresh_mempool(extra=[])
                result = "added"
            elif chainwork > self.meta[self.tip]["chainwork"]:
                new_path = path + [h]
                self.blocks[h] = block        # nécessaire pour rejouer
                self.meta[h] = {"height": len(path), "prev": prev, "chainwork": chainwork}
                try:
                    utxo, tx_index = self._replay(new_path)
                except InvalidBlock:
                    del self.blocks[h], self.meta[h]
                    raise
                fork_point = 0
                while fork_point < len(self.main) and fork_point < len(new_path) \
                        and self.main[fork_point] == new_path[fork_point]:
                    fork_point += 1
                dropped = [tx for bh in self.main[fork_point:]
                           for tx in self.blocks[bh]["transactions"][1:]]
                self._store(h, block, prev, chainwork, persist)
                self.main, self.utxo, self.tx_index = new_path, utxo, tx_index
                self._refresh_mempool(extra=dropped)
                result = "reorg"
            else:
                self._store(h, block, prev, chainwork, persist)
                return "side"

            # Un parent manquant vient peut-être d'arriver : on rattache les orphelins.
            for oh, ob in list(self.orphans.items()):
                if ob["header"]["prev_hash"] == h:
                    del self.orphans[oh]
                    try:
                        self.add_block(ob, persist)
                    except InvalidBlock:
                        pass
        for fn in self.listeners:
            fn(result, h)
        return result

    def _store(self, h, block, prev, chainwork, persist):
        self.blocks[h] = block
        self.meta[h] = {"height": block["header"]["height"], "prev": prev, "chainwork": chainwork}
        if persist and self.data_dir:
            with open(os.path.join(self.data_dir, "blocks.jsonl"), "a") as f:
                f.write(json.dumps(block, separators=(",", ":")) + "\n")

    def _load(self):
        if not self.data_dir:
            return
        try:
            os.makedirs(self.data_dir, exist_ok=True)
        except OSError as e:
            raise SystemExit(f"Impossible de créer le dossier de données {os.path.abspath(self.data_dir)} : {e}. "
                             "Choisissez un autre dossier avec la variable DATA_DIR.") from e
        path = os.path.join(self.data_dir, "blocks.jsonl")
        if not os.path.exists(path):
            return
        with open(path) as f:
            for line in f:
                try:
                    self.add_block(json.loads(line), persist=False)
                except (InvalidBlock, ValueError, KeyError):
                    continue

    # ------------------------------------------------------------------ mempool
    def add_transaction(self, tx: dict) -> str:
        """Ajoute une transaction au mempool après validation complète. Renvoie son txid."""
        with self.lock:
            try:
                check_structure(tx)
            except ValueError as e:
                raise InvalidTx(str(e)) from e
            if is_coinbase(tx):
                raise InvalidTx("une coinbase ne peut pas être diffusée seule")
            t = txid(tx)
            if t in self.mempool or t in self.tx_index:
                return t
            if len(self.mempool) >= 5000:
                raise InvalidTx("mempool plein")
            fee = self.check_tx_inputs(tx, self.utxo, self.mempool_spent)
            if fee < params.MIN_FEE:
                raise InvalidTx(f"frais insuffisants (minimum {params.MIN_FEE} makuta)")
            self.mempool[t] = tx
            self.mempool_spent.update(outpoint(i["txid"], i["vout"]) for i in tx["inputs"])
            return t

    def _refresh_mempool(self, extra: list):
        """Après un nouveau bloc : retire les transactions incluses ou devenues invalides."""
        candidates = list(self.mempool.values()) + extra
        self.mempool, self.mempool_spent = {}, set()
        for tx in candidates:
            try:
                self.add_transaction(tx)
            except InvalidTx:
                pass

    def tx_fee(self, tx: dict) -> int:
        if is_coinbase(tx):
            return 0
        total_in = 0
        for i in tx["inputs"]:
            op = outpoint(i["txid"], i["vout"])
            coin = self.utxo.get(op) or self._spent_output(i["txid"], i["vout"])
            total_in += coin["amount"] if coin else 0
        return total_in - sum(o["amount"] for o in tx["outputs"])

    def _spent_output(self, tx_id, vout):
        loc = self.tx_index.get(tx_id)
        if not loc:
            return None
        tx = self.blocks[loc[0]]["transactions"][loc[1]]
        return tx["outputs"][vout] if vout < len(tx["outputs"]) else None

    # ------------------------------------------------------------------- minage
    def block_template(self, miner_address: str, message: str = "") -> dict:
        """Prépare un bloc candidat (sans nonce valide) à partir du mempool."""
        with self.lock:
            height = self.height + 1
            spent, chosen, fees = set(), [], 0
            by_fee = sorted(self.mempool.values(), key=self.tx_fee, reverse=True)
            for tx in by_fee[: params.MAX_TX_PER_BLOCK - 1]:
                try:
                    fees += self.check_tx_inputs(tx, self.utxo, spent)
                except InvalidTx:
                    continue
                spent.update(outpoint(i["txid"], i["vout"]) for i in tx["inputs"])
                chosen.append(tx)
            ts = max(int(time.time()), self.median_time_past(self.main) + 1)
            cb = make_coinbase(height, miner_address, params.block_reward(height) + fees, ts, message)
            txs = [cb] + chosen
            header = {
                "version": 1,
                "height": height,
                "prev_hash": self.tip,
                "merkle_root": merkle_root([txid(t) for t in txs]),
                "timestamp": ts,
                "target": target_hex(self.expected_target(self.main)),
                "nonce": 0,
            }
            return {"header": header, "transactions": txs}

    # --------------------------------------------------------------- requêtes
    def locator(self) -> list[str]:
        """Hash de référence pour la synchronisation : tip, tip-1, -2, -4, -8… genèse."""
        with self.lock:
            out, step, i = [], 1, self.height
            while i > 0:
                out.append(self.main[i])
                if len(out) >= 10:
                    step *= 2
                i -= step
            out.append(self.main[0])
            return out

    def blocks_after(self, locator: list[str], limit: int = 200) -> list[dict]:
        """Blocs de la chaîne principale qui suivent le premier hash connu du localisateur."""
        with self.lock:
            positions = {h: i for i, h in enumerate(self.main)}
            start = 0
            for h in locator:
                if h in positions:
                    start = positions[h] + 1
                    break
            return [self.blocks[h] for h in self.main[start:start + limit]]

    def block_at(self, ident: str) -> dict | None:
        with self.lock:
            if ident.isdigit():
                i = int(ident)
                return self.blocks[self.main[i]] if i < len(self.main) else None
            return self.blocks.get(ident)

    def is_main(self, h: str) -> bool:
        m = self.meta.get(h)
        return m is not None and m["height"] < len(self.main) and self.main[m["height"]] == h

    def find_tx(self, t: str) -> tuple[dict, dict | None] | None:
        """Renvoie (transaction, bloc ou None si dans le mempool)."""
        with self.lock:
            if t in self.mempool:
                return self.mempool[t], None
            loc = self.tx_index.get(t)
            if loc:
                block = self.blocks[loc[0]]
                return block["transactions"][loc[1]], block
            return None

    def address_info(self, address: str) -> dict:
        with self.lock:
            utxos = [{"txid": op.split(":")[0], "vout": int(op.split(":")[1]), **c}
                     for op, c in self.utxo.items() if c["address"] == address]
            pending_out = sum(1 for op in self.mempool_spent if self.utxo.get(op, {}).get("address") == address)
            history = []
            for h in reversed(self.main):
                b = self.blocks[h]
                for tx in b["transactions"]:
                    received = sum(o["amount"] for o in tx["outputs"] if o["address"] == address)
                    sent = sum((self._spent_output(i["txid"], i["vout"]) or {}).get("amount", 0)
                               for i in tx["inputs"]
                               if (self._spent_output(i["txid"], i["vout"]) or {}).get("address") == address)
                    if received or sent:
                        history.append({"txid": txid(tx), "height": b["header"]["height"],
                                        "timestamp": tx["timestamp"], "delta": received - sent})
                if len(history) >= 100:
                    break
            for t, tx in self.mempool.items():
                received = sum(o["amount"] for o in tx["outputs"] if o["address"] == address)
                sent = sum(self.utxo[outpoint(i["txid"], i["vout"])]["amount"] for i in tx["inputs"]
                           if self.utxo[outpoint(i["txid"], i["vout"])]["address"] == address)
                if received or sent:
                    history.insert(0, {"txid": t, "height": None, "timestamp": tx["timestamp"],
                                       "delta": received - sent})
            return {
                "address": address,
                "balance": sum(u["amount"] for u in utxos),
                "utxos": [u for u in utxos if outpoint(u["txid"], u["vout"]) not in self.mempool_spent],
                "locked_in_mempool": pending_out,
                "history": history,
            }

    def stats(self) -> dict:
        with self.lock:
            tip = self.header(self.tip)
            target = self.expected_target(self.main)
            recent = self.main[-(params.ADJUST_INTERVAL + 1):]
            hashrate = 0.0
            avg_time = None
            if len(recent) > 1:
                span = self.header(recent[-1])["timestamp"] - self.header(recent[0])["timestamp"]
                total_work = sum(work(int(self.header(h)["target"], 16)) for h in recent[1:])
                if span > 0:
                    hashrate = total_work / span
                    avg_time = span / (len(recent) - 1)
            next_height = self.height + 1
            return {
                "height": self.height,
                "tip": self.tip,
                "chainwork": format(self.meta[self.tip]["chainwork"], "x"),
                "target": target_hex(target),
                "difficulty": params.INITIAL_TARGET / target,
                "zero_bits": 256 - target.bit_length(),
                "hashrate": hashrate,
                "avg_block_time": avg_time,
                "block_time_target": params.BLOCK_TIME,
                "adjust_interval": params.ADJUST_INTERVAL,
                "next_adjustment": next_height + (-next_height % params.ADJUST_INTERVAL),
                "reward": params.block_reward(next_height),
                "next_halving": (next_height // params.HALVING_INTERVAL + 1) * params.HALVING_INTERVAL,
                "halving_interval": params.HALVING_INTERVAL,
                "supply": sum(c["amount"] for c in self.utxo.values()),
                "max_supply": params.max_supply(),
                "mempool": len(self.mempool),
                "utxo_count": len(self.utxo),
                "last_block_time": tip["timestamp"],
            }
