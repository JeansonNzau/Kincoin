"""Tests du cœur de KinCoin.  Lancement :  python -m unittest discover -s tests -v

On abaisse la difficulté (8 bits) pour que les tests minent instantanément.
"""
import os
import sys
import tempfile
import unittest

os.environ.setdefault("KIN_INITIAL_BITS", "10")
os.environ.setdefault("KIN_HALVING_INTERVAL", "5")
os.environ.setdefault("KIN_ADJUST_INTERVAL", "5")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kincoin import params  # noqa: E402
from kincoin.block import PowSearch, block_hash, genesis_block  # noqa: E402
from kincoin.chain import Blockchain, InvalidBlock, InvalidTx  # noqa: E402
from kincoin.crypto import PrivateKey, is_valid_address, verify  # noqa: E402
from kincoin.merkle import merkle_proof, merkle_root, verify_proof  # noqa: E402
from kincoin.tx import build_transaction, sighash  # noqa: E402


def mine(chain: Blockchain, address: str, ts_offset: int = 0) -> dict:
    b = chain.block_template(address)
    b["header"]["timestamp"] += ts_offset
    b["header"]["nonce"] = PowSearch(b["header"]).search(0, 10_000_000)
    return b


class CryptoTests(unittest.TestCase):
    def test_sign_verify(self):
        k = PrivateKey.generate()
        msg = b"\x01" * 32
        sig = k.sign(msg)
        self.assertTrue(verify(k.public_key_hex(), sig, msg))
        self.assertFalse(verify(k.public_key_hex(), sig, b"\x02" * 32))
        other = PrivateKey.generate()
        self.assertFalse(verify(other.public_key_hex(), sig, msg))

    def test_address(self):
        a = PrivateKey.generate().address()
        self.assertTrue(a.startswith("K"))
        self.assertTrue(is_valid_address(a))
        broken = a[:-1] + ("a" if a[-1] != "a" else "b")
        self.assertFalse(is_valid_address(broken))

    def test_known_vector(self):
        # Clé privée = 1 → clé publique = point générateur G (vecteur de test classique).
        k = PrivateKey.from_hex("01")
        self.assertEqual(k.public_key_hex(),
                         "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798")


class MerkleTests(unittest.TestCase):
    def test_proofs(self):
        ids = [format(i, "064x") for i in range(7)]
        root = merkle_root(ids)
        for i, t in enumerate(ids):
            self.assertTrue(verify_proof(t, merkle_proof(ids, i), root))
        self.assertFalse(verify_proof(ids[0], merkle_proof(ids, 1), root))


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.chain = Blockchain(self.dir)
        self.alice = PrivateKey.generate()
        self.bob = PrivateKey.generate()

    def test_genesis_identical(self):
        self.assertEqual(block_hash(genesis_block()), self.chain.main[0])

    def test_mine_and_reward(self):
        b = mine(self.chain, self.alice.address())
        self.assertEqual(self.chain.add_block(b), "added")
        info = self.chain.address_info(self.alice.address())
        self.assertEqual(info["balance"], params.block_reward(1))

    def test_bad_pow_rejected(self):
        b = self.chain.block_template(self.alice.address())
        b["header"]["target"] = format(1, "064x")
        with self.assertRaises(InvalidBlock):
            self.chain.add_block(b)

    def test_wrong_target_rejected(self):
        b = self.chain.block_template(self.alice.address())
        b["header"]["target"] = format(params.MAX_TARGET, "064x")   # plus facile que prévu
        b["header"]["nonce"] = PowSearch(b["header"]).search(0, 10_000)
        with self.assertRaisesRegex(InvalidBlock, "difficulté"):
            self.chain.add_block(b)

    def test_greedy_coinbase_rejected(self):
        b = self.chain.block_template(self.alice.address())
        b["transactions"][0]["outputs"][0]["amount"] += 1
        from kincoin.merkle import merkle_root as mr
        from kincoin.tx import txid
        b["header"]["merkle_root"] = mr([txid(t) for t in b["transactions"]])
        b["header"]["nonce"] = PowSearch(b["header"]).search(0, 10_000_000)
        with self.assertRaisesRegex(InvalidBlock, "coinbase"):
            self.chain.add_block(b)

    def test_halving(self):
        self.assertEqual(params.block_reward(0), 50 * params.COIN)
        self.assertEqual(params.block_reward(5), 25 * params.COIN)
        self.assertEqual(params.block_reward(10), params.COIN * 25 // 2)

    def test_payment_flow(self):
        self.chain.add_block(mine(self.chain, self.alice.address()))
        utxos = self.chain.address_info(self.alice.address())["utxos"]
        tx = build_transaction(self.alice, utxos, self.bob.address(), 10 * params.COIN, fee=1000)
        self.chain.add_transaction(tx)
        # double dépense refusée par le mempool
        tx2 = build_transaction(self.alice, utxos, self.bob.address(), 5 * params.COIN)
        with self.assertRaises(InvalidTx):
            self.chain.add_transaction(tx2)
        self.chain.add_block(mine(self.chain, self.bob.address()))
        self.assertEqual(self.chain.address_info(self.bob.address())["balance"],
                         10 * params.COIN + params.block_reward(2) + 1000)
        self.assertEqual(self.chain.address_info(self.alice.address())["balance"],
                         params.block_reward(1) - 10 * params.COIN - 1000)
        self.assertEqual(len(self.chain.mempool), 0)

    def test_forged_signature_rejected(self):
        self.chain.add_block(mine(self.chain, self.alice.address()))
        utxos = self.chain.address_info(self.alice.address())["utxos"]
        tx = build_transaction(self.alice, utxos, self.bob.address(), params.COIN)
        tx["outputs"][0]["amount"] = 40 * params.COIN    # modifié après signature
        with self.assertRaisesRegex(InvalidTx, "signature"):
            self.chain.add_transaction(tx)
        # Bob signe en prétendant dépenser l'UTXO d'Alice
        tx = build_transaction(self.alice, utxos, self.bob.address(), params.COIN)
        tx["inputs"][0]["pubkey"] = self.bob.public_key_hex()
        tx["inputs"][0]["signature"] = self.bob.sign(sighash(tx))
        with self.assertRaisesRegex(InvalidTx, "propriétaire"):
            self.chain.add_transaction(tx)

    def test_reorg_to_heavier_chain(self):
        other = Blockchain()
        self.chain.add_block(mine(self.chain, self.alice.address()))
        for _ in range(3):
            other.add_block(mine(other, self.bob.address()))
        results = [self.chain.add_block(b) for b in other.blocks_after(self.chain.locator()[-1:])]
        self.assertIn("reorg", results)
        self.assertEqual(self.chain.tip, other.tip)
        self.assertEqual(self.chain.address_info(self.alice.address())["balance"], 0)

    def test_difficulty_adjusts_up_when_fast(self):
        t0 = self.chain.header(self.chain.tip)["target"]
        for _ in range(2 * params.ADJUST_INTERVAL):
            self.chain.add_block(mine(self.chain, self.alice.address()))
        t1 = self.chain.header(self.chain.tip)["target"]
        self.assertLess(int(t1, 16), int(t0, 16), "blocs trop rapides → cible plus petite")

    def test_persistence(self):
        for _ in range(3):
            self.chain.add_block(mine(self.chain, self.alice.address()))
        reloaded = Blockchain(self.dir)
        self.assertEqual(reloaded.tip, self.chain.tip)
        self.assertEqual(reloaded.utxo, self.chain.utxo)

    def test_sync_with_locator(self):
        for _ in range(4):
            self.chain.add_block(mine(self.chain, self.alice.address()))
        fresh = Blockchain()
        for b in self.chain.blocks_after(fresh.locator()):
            fresh.add_block(b)
        self.assertEqual(fresh.tip, self.chain.tip)


if __name__ == "__main__":
    unittest.main()
