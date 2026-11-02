"""Paramètres du protocole KinCoin.

Les valeurs par défaut sont des « paramètres de démonstration » : blocs rapides
et halving fréquent, pour que le jury voie le mécanisme pendant l'exposé.
Chaque valeur peut être changée par variable d'environnement, mais TOUS les
nœuds d'un même réseau doivent utiliser les mêmes valeurs (sinon ils
rejettent les blocs les uns des autres).
"""
import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


# Unité : 1 KIN = 100 000 000 makuta (comme 1 BTC = 100 000 000 satoshis).
COIN = 100_000_000

# Temps visé entre deux blocs (secondes).
BLOCK_TIME = _int("KIN_BLOCK_TIME", 15)

# La difficulté est recalculée tous les N blocs.
ADJUST_INTERVAL = _int("KIN_ADJUST_INTERVAL", 10)

# Facteur maximal de variation de la difficulté à chaque ajustement (règle de Bitcoin : 4).
MAX_ADJUST_FACTOR = 4

# Récompense initiale du mineur, divisée par deux tous les HALVING_INTERVAL blocs.
INITIAL_REWARD = _int("KIN_INITIAL_REWARD", 50) * COIN
HALVING_INTERVAL = _int("KIN_HALVING_INTERVAL", 50)

# Difficulté initiale exprimée en nombre de bits à zéro au début du hash.
# 18 bits ≈ 262 000 essais en moyenne, quelques secondes en Python.
INITIAL_ZERO_BITS = _int("KIN_INITIAL_BITS", 18)
INITIAL_TARGET = 2 ** (256 - INITIAL_ZERO_BITS) - 1
# Cible la plus facile autorisée (la difficulté ne peut pas descendre en dessous).
MAX_TARGET = 2 ** (256 - 8) - 1

# Règles de validité.
MAX_TX_PER_BLOCK = 500
MAX_FUTURE_DRIFT = 120          # un bloc ne peut pas être daté de plus de 2 min dans le futur
MEDIAN_TIME_SPAN = 11           # horodatage > médiane des 11 blocs précédents
MIN_FEE = 0                     # frais minimum (en makuta) pour entrer dans le mempool

# Octet de version des adresses (Base58Check). 0x2D donne des adresses commençant par « K ».
ADDRESS_VERSION = 0x2D

# Bloc genèse : identique sur tous les nœuds, codé en dur.
GENESIS_TIMESTAMP = 1792972800  # 26/10/2026 00:00 UTC
GENESIS_MESSAGE = "Kinshasa 26/10/2026 - KinCoin, projet Groupe 01, UNIKIN"


def block_reward(height: int) -> int:
    """Récompense (en makuta) d'un bloc à la hauteur donnée."""
    halvings = height // HALVING_INTERVAL
    if halvings >= 64:
        return 0
    return INITIAL_REWARD >> halvings


def max_supply() -> int:
    """Offre totale maximale (en makuta) : somme de toutes les récompenses futures."""
    total, h = 0, 0
    while True:
        r = block_reward(h)
        if r == 0:
            return total
        total += r * HALVING_INTERVAL
        h += HALVING_INTERVAL
