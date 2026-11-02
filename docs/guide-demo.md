# Guide de l'exposé

Proposition de déroulé pour environ 20 minutes, partagé entre les quatre membres. Adaptez la répartition à ce que chacun a codé ou étudié.

## Avant l'exposé

- **Une heure avant** : ouvrez l'explorateur et vérifiez que les 3 nœuds répondent (point vert en haut à droite, « relié à 2 pairs »). Sur Render, la première requête peut prendre une minute si un nœud dormait.
- Créez deux portefeuilles à l'avance dans deux navigateurs différents (ou une fenêtre privée) : « Alice » et « Bob ». Mettez l'adresse d'Alice en `MINER_ADDRESS` sur un nœud pour qu'elle ait déjà des KIN.
- **Plan B** : un ordinateur avec Docker et `docker compose up` déjà lancé (http://localhost:8001/app/), et une courte vidéo de la démo enregistrée la veille.

## Déroulé

| Durée | Qui | Contenu |
| --- | --- | --- |
| 3 min | Membre 1 | Le problème de la double dépense, l'idée de Bitcoin, ce qu'est KinCoin |
| 5 min | Membre 1 | Cœur : transactions UTXO, signatures ECDSA secp256k1, arbre de Merkle (montrer `tx.py` et `merkle.py`) |
| 5 min | Membre 2 | Minage : preuve de travail, cible, ajustement de la difficulté, récompense et halving (montrer `block.py` et `expected_target` dans `chain.py`) |
| 4 min | Membre 3 | Réseau : 3 nœuds, WebSocket, synchronisation par localisateur, gestion des forks (montrer `p2p.py`) |
| 6 min | Membre 4 | Démo en direct (voir ci-dessous), puis livre blanc et tokenomics |
| reste | Tous | Questions |

## Démo en direct

1. **L'explorateur.** Montrer la bande de blocs : chaque nouveau bloc apparaît à gauche. Faire remarquer les zéros verts en tête des hash : c'est la preuve de travail. Ouvrir un bloc : cible, nonce, racine de Merkle, lien vers le bloc précédent.
2. **La difficulté.** Montrer « prochain ajustement au bloc N » et le nombre de bits à zéro, puis comparer avec un bloc d'avant l'ajustement.
3. **Le halving.** Montrer « halving dans N blocs » ; s'il a lieu pendant l'exposé, ouvrir un bloc avant et après (50 puis 25 KIN).
4. **Une transaction.** Dans le portefeuille d'Alice, envoyer 10 KIN à Bob. La transaction apparaît « en attente dans le mempool », puis est confirmée dans le bloc suivant. Ouvrir la transaction : entrée d'Alice, sortie de Bob, monnaie rendue à Alice, frais.
5. **La décentralisation.** Changer de nœud dans le menu en haut à droite : les trois nœuds montrent le même dernier bloc. Si possible, arrêter un nœud (`POST /mining/stop` ou arrêt du service) : le réseau continue, et le nœud se resynchronise à son retour.
6. **La sécurité (optionnel, avec un terminal).** Lancer `python -m unittest discover -s tests -v` : on voit refuser une signature falsifiée, une double dépense, une coinbase trop gourmande et une preuve de travail insuffisante.

## Questions probables du jury

**Pourquoi le modèle UTXO plutôt que des comptes ?**
Chaque pièce a un historique vérifiable indépendamment, la double dépense se détecte simplement (une sortie ne peut être dépensée qu'une fois) et les transactions sans entrée commune peuvent être validées en parallèle.

**Que se passe-t-il si deux mineurs trouvent un bloc en même temps ?**
La chaîne se divise temporairement. Chaque nœud garde la branche qui a le plus de travail cumulé ; dès qu'un bloc s'ajoute à l'une des branches, tous les nœuds la suivent et les transactions de l'autre retournent dans le mempool (fonction `add_block`, cas « reorg »).

**Pourquoi « low-S » ?**
Pour toute signature (r, s) valide, (r, n − s) est aussi valide. Sans règle, n'importe qui pourrait modifier une signature et donc l'identifiant d'une transaction. On impose s ≤ n/2.

**Comment le portefeuille signe-t-il sans envoyer la clé ?**
Le navigateur calcule le condensé de la transaction, le signe localement en JavaScript, et n'envoie au nœud que la transaction signée et la clé publique. Le nœud vérifie la signature avec la bibliothèque `cryptography`.

**Pourquoi les blocs toutes les 15 secondes et pas 10 minutes ?**
Paramètres de démonstration, pour voir un ajustement et un halving pendant l'exposé. Le livre blanc donne les paramètres de production ; il suffit de changer des variables d'environnement.

**Votre réseau est-il sûr ?**
Pas contre une attaque des 51 % : avec trois nœuds de faible puissance, un seul ordinateur plus puissant pourrait réécrire l'historique. La sécurité de la preuve de travail vient de la taille du réseau.

**Pourquoi un SHA-256 double plutôt que RIPEMD-160 pour les adresses ?**
RIPEMD-160 n'est pas disponible dans l'API WebCrypto des navigateurs. Tronquer SHA-256 à 160 bits offre la même résistance aux collisions pour cet usage.
