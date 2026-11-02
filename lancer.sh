#!/bin/sh
# Linux / macOS : lance les 3 noeuds en arriere-plan (journaux dans data/N.log).
cd "$(dirname "$0")"
mkdir -p data
for N in 1 2 3; do
  PEERS=""
  for M in 1 2 3; do [ "$M" != "$N" ] && PEERS="$PEERS,http://127.0.0.1:800$M"; done
  MINING=1; [ "$N" = 3 ] && MINING=0
  NODE_NAME=noeud-$N DATA_DIR=data/$N PUBLIC_URL=http://127.0.0.1:800$N PEERS=${PEERS#,} \
  MINING=$MINING FRONTEND_DIR=frontend \
    python3 -m uvicorn kincoin.node:app --host 127.0.0.1 --port 800$N > data/$N.log 2>&1 &
done
echo "Noeuds lances. Ouvrez http://127.0.0.1:8001/app/  (arret : pkill -f kincoin.node)"
