# KinCoin : une monnaie électronique pair-à-pair à preuve de travail

**Livre blanc, version 1.0 — octobre 2026**
Groupe 01 : Akossa Dole Elvis, Massevo Lenzo Delss, Nimy Bianga Descartes, Nzau Umba Jeanson
Université de Kinshasa

## Résumé

KinCoin est une cryptomonnaie expérimentale qui reprend, à une échelle pédagogique, les mécanismes décrits par Satoshi Nakamoto dans le livre blanc de Bitcoin (2008). Elle permet à deux personnes d'échanger de la valeur sans tiers de confiance : les transactions sont signées avec l'algorithme ECDSA sur la courbe secp256k1, regroupées dans des blocs chaînés par leur hash, et l'ordre des blocs est fixé par une preuve de travail. Le réseau se compose d'au moins trois nœuds indépendants qui vérifient chacun toutes les règles et s'échangent blocs et transactions par WebSocket. Un portefeuille web et un explorateur de blocs complètent le système.

## 1. Le problème

Une monnaie numérique se heurte à la **double dépense** : un fichier se copie, donc rien n'empêche *a priori* de dépenser deux fois la même pièce. La solution classique est une banque centrale qui tient le registre. KinCoin remplace ce tiers par un registre public, répliqué sur tous les nœuds, dont l'historique ne peut être réécrit qu'au prix d'une quantité de calcul supérieure à celle du reste du réseau.

## 2. Transactions et modèle UTXO

KinCoin n'a pas de comptes. Chaque transaction consomme des **sorties non dépensées** (UTXO, *Unspent Transaction Outputs*) et en crée de nouvelles :

```json
{
  "version": 1,
  "timestamp": 1793037277,
  "inputs":  [{ "txid": "78f5…66e0", "vout": 0, "pubkey": "02ab…", "signature": "3044…" }],
  "outputs": [{ "address": "KCUS…bDDe", "amount": 375000000 },
              { "address": "KJHL…FqALo", "amount": 4624999000 }]
}
```

- Une entrée désigne une sortie existante par `(txid, vout)`. La clé publique fournie doit correspondre à l'adresse propriétaire de cette sortie.
- Toutes les entrées signent le même condensé : le SHA-256 double de la transaction dont les signatures sont vides. Modifier un montant ou un destinataire après signature rend donc la transaction invalide.
- La somme des sorties ne peut pas dépasser celle des entrées. La différence constitue les **frais**, versés au mineur.
- La monnaie rendue revient à l'expéditeur dans une seconde sortie, comme on rend la monnaie sur un billet.
- Le solde d'une adresse est la somme de ses UTXO.

Les montants sont des entiers exprimés en **makuta** : 1 KIN = 100 000 000 makuta. Le nom reprend celui de l'ancienne subdivision monétaire du Zaïre. Les entiers évitent les erreurs d'arrondi des nombres à virgule.

## 3. Cryptographie

| Usage | Choix | Raison |
| --- | --- | --- |
| Signature | ECDSA sur secp256k1, signatures « low-S », encodage DER | Courbe de Bitcoin ; « low-S » empêche de modifier une signature sans la clé (malléabilité) |
| Hash des blocs et des transactions | SHA-256 appliqué deux fois | Comme Bitcoin |
| Adresse | Base58Check(0x2D ‖ 20 premiers octets de SHA256d(clé publique)) | Lisible, avec somme de contrôle contre les fautes de frappe ; l'octet 0x2D fait commencer les adresses par « K » |
| Sérialisation | JSON canonique (clés triées, sans espaces, ASCII) | Le navigateur et le nœud produisent exactement les mêmes octets à signer |

Bitcoin utilise RIPEMD-160 pour les adresses. Cette fonction n'existe pas dans l'API WebCrypto des navigateurs ; KinCoin la remplace par un SHA-256 double tronqué à 20 octets, de sécurité équivalente pour cet usage.

Le portefeuille web signe dans le navigateur, avec un nonce déterministe (RFC 6979) : la clé privée ne quitte jamais l'appareil de l'utilisateur.

## 4. Blocs et arbre de Merkle

Un bloc contient un en-tête et une liste de transactions. L'en-tête comprend la hauteur, le hash du bloc précédent, la racine de Merkle des transactions, l'horodatage, la cible de difficulté et le nonce.

La **racine de Merkle** résume toutes les transactions en un seul hash : on hache les identifiants deux à deux jusqu'à n'en garder qu'un. Changer une seule transaction change la racine, donc l'en-tête, donc le hash du bloc. Un client léger peut aussi prouver qu'une transaction est dans un bloc avec seulement log₂(n) hash (fonction `merkle_proof`).

Chaque bloc référence le hash du précédent. Modifier un bloc ancien oblige à recalculer la preuve de travail de tous les blocs suivants.

## 5. Preuve de travail et ajustement de la difficulté

Un bloc est valide si le SHA-256 double de son en-tête, lu comme un entier de 256 bits, est **inférieur ou égal à la cible**. Le seul moyen de trouver un tel bloc est d'essayer des nonces un par un. Les zéros en tête du hash, mis en évidence en vert dans l'explorateur, sont la trace visible de ce travail.

Tous les **10 blocs**, chaque nœud recalcule la cible à partir du temps réellement mis pour miner les blocs précédents :

```
nouvelle cible = ancienne cible × temps réel / temps visé      (variation bornée à ×4 ou ÷4)
```

Si les mineurs deviennent plus nombreux, les blocs arrivent trop vite, la cible baisse et la difficulté monte. Le temps entre deux blocs revient ainsi vers la valeur visée de **15 secondes**.

Quand deux mineurs trouvent un bloc presque en même temps, la chaîne se divise. Chaque nœud suit la branche qui a le **plus de travail cumulé**. Dès qu'une branche devient plus lourde, les nœuds se réorganisent : les transactions de la branche abandonnée retournent dans le mempool.

## 6. Règles de validation

Un nœud n'accepte un bloc que si toutes ces conditions sont réunies :

1. le hash est inférieur ou égal à la cible, et la cible est exactement celle prévue par la règle d'ajustement ;
2. l'horodatage est postérieur à la médiane des 11 blocs précédents, et pas plus de 2 minutes dans le futur ;
3. la première transaction, et elle seule, est une coinbase portant la hauteur du bloc ;
4. la racine de Merkle correspond aux transactions ;
5. chaque transaction dépense des UTXO existants, non déjà dépensés, avec une signature valide de leur propriétaire ;
6. la coinbase ne réclame pas plus que la récompense plus les frais.

## 7. Réseau pair-à-pair

Chaque nœud est à la fois serveur et client WebSocket. À la connexion, les nœuds échangent leur hauteur et leur travail cumulé. Celui qui est en retard envoie un **localisateur** (les hash de ses blocs à hauteur −1, −2, −4, −8, …) et reçoit les blocs manquants depuis le dernier ancêtre commun. Un bloc ou une transaction nouvellement acceptés sont relayés à tous les autres pairs, et jamais deux fois.

Les nœuds s'échangent aussi leurs listes de pairs : il suffit d'en connaître un pour découvrir le reste du réseau. Un transport HTTP de secours est prévu pour les hébergeurs qui coupent les WebSocket.

## 8. Tokenomics

| Paramètre | Réseau de démonstration | Paramètres de production proposés |
| --- | --- | --- |
| Temps visé entre deux blocs | 15 s | 2 min 30 s |
| Ajustement de la difficulté | tous les 10 blocs | tous les 2 016 blocs (environ 3,5 jours) |
| Récompense initiale | 50 KIN | 50 KIN |
| Halving | tous les 50 blocs (environ 12 min) | tous les 210 000 blocs (environ 1 an) |
| Offre maximale | environ 5 000 KIN | environ 21 000 000 KIN |
| Subdivision | 1 KIN = 100 000 000 makuta | identique |

Les paramètres de démonstration sont accélérés pour que le jury voie un halving et un ajustement de la difficulté pendant l'exposé. Le code est le même ; seules les variables d'environnement changent.

**Émission.** Il n'y a ni prévente ni réserve pour l'équipe : tous les KIN sont créés par le minage, au même rythme pour tout le monde. La récompense est divisée par deux à chaque halving. L'offre totale est la somme d'une suite géométrique :

```
offre maximale = 50 × intervalle de halving × (1 + 1/2 + 1/4 + …) ≈ 100 × intervalle de halving
```

Avec un intervalle de 210 000 blocs, on obtient environ 21 millions de KIN. Quand la récompense devient nulle, les mineurs sont rémunérés uniquement par les frais.

**Bloc genèse.** Le bloc 0 est codé en dur dans tous les nœuds. Sa coinbase contient le message « Kinshasa 26/10/2026 - KinCoin, projet Groupe 01, UNIKIN » et envoie ses 50 KIN à une adresse dont personne ne possède la clé : ces KIN sont définitivement inutilisables, comme ceux du bloc genèse de Bitcoin.

## 9. Sécurité et limites

- **Attaque des 51 %.** Avec trois nœuds, quiconque dépasse leur puissance de calcul cumulée peut réécrire l'historique. C'est une limite de tout petit réseau à preuve de travail.
- **Simplifications assumées.** Pas de maturité des coinbase (Bitcoin attend 100 blocs), pas de chaînage de transactions non confirmées, pas de langage de script, et une reconstruction complète de l'ensemble UTXO à chaque réorganisation.
- **Portefeuille web.** La clé privée est conservée dans le stockage local du navigateur. Notre implémentation de secp256k1 en JavaScript est pédagogique et ne s'exécute pas en temps constant ; un produit réel utiliserait une bibliothèque auditée.
- **Hébergement gratuit.** Les offres gratuites peuvent mettre les nœuds en veille et effacer leur disque. Les nœuds se réveillent mutuellement et se resynchronisent entre eux ; un réseau réel aurait besoin de nœuds permanents.

## 10. Conclusion

KinCoin montre qu'avec des briques connues (signatures à courbe elliptique, fonctions de hachage, preuve de travail et diffusion pair-à-pair), trois machines qui ne se font pas confiance arrivent à tenir ensemble un registre cohérent et infalsifiable. Le prototype est complet de la clé privée jusqu'au bloc miné.

## Références

1. S. Nakamoto, *Bitcoin: A Peer-to-Peer Electronic Cash System*, 2008.
2. A. M. Antonopoulos, *Mastering Bitcoin*, O'Reilly, 2e éd., 2017.
3. Standards for Efficient Cryptography Group, *SEC 2: Recommended Elliptic Curve Domain Parameters* (secp256k1), 2010.
4. T. Pornin, *RFC 6979 — Deterministic Usage of DSA and ECDSA*, IETF, 2013.
