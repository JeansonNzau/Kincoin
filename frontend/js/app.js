// KinCoin — portefeuille et explorateur (page unique, navigation par #/…).
import * as K from "./kincoin-crypto.js";

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} },
};

// ------------------------------------------------------------------ nœuds
const servedByNode = location.pathname.startsWith("/app");
const nodes = [...new Set([...(servedByNode ? [location.origin] : []), ...(window.KINCOIN_NODES || [])].map((u) => u.replace(/\/$/, "")))];
let node = store.get("kin.node");
if (!nodes.includes(node)) node = nodes[0];

const select = $("#node-select");
function fillNodes() {
  select.innerHTML = nodes.map((u) => `<option value="${esc(u)}"${u === node ? " selected" : ""}>${esc(u.replace(/^https?:\/\//, ""))}</option>`).join("")
    + `<option value="__add">Ajouter un nœud…</option>`;
}
fillNodes();
select.addEventListener("change", () => {
  if (select.value === "__add") {
    const u = prompt("URL du nœud (ex. https://kincoin-node-1.onrender.com)");
    if (u && /^https?:\/\//.test(u.trim())) { nodes.push(u.trim().replace(/\/$/, "")); node = nodes.at(-1); }
  } else node = select.value;
  store.set("kin.node", node);
  fillNodes();
  refresh(true);
});

async function api(path, opts = {}) {
  const res = await fetch(node + path, { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `le nœud a répondu ${res.status}`);
  return body;
}

// ----------------------------------------------------------------- affichage
const kin = (m) => `${K.formatKin(m)} KIN`;
const ago = (ts) => {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return `il y a ${s} s`;
  if (s < 3600) return `il y a ${Math.floor(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
  return new Date(ts * 1000).toLocaleDateString("fr-FR");
};
const date = (ts) => new Date(ts * 1000).toLocaleString("fr-FR");
const short = (h, n = 10) => (h && h.length > 2 * n ? `${h.slice(0, n)}…${h.slice(-6)}` : h);
// Les zéros de tête du hash sont la preuve de travail : on les met en évidence.
function hashHtml(h, n) {
  const z = h.match(/^0*/)[0];
  const rest = n ? short(h.slice(z.length), n) : h.slice(z.length);
  return `<span class="hash"><span class="zeros">${z}</span>${esc(rest)}</span>`;
}
const linkBlock = (h, label) => `<a href="#/block/${esc(h)}">${label ?? hashHtml(h, 8)}</a>`;
const linkTx = (t) => `<a class="mono" href="#/tx/${esc(t)}">${esc(short(t, 8))}</a>`;
const linkAddr = (a) => (a ? `<a class="mono" href="#/address/${esc(a)}">${esc(a)}</a>` : `<span class="muted">—</span>`);
const hashrate = (h) => (h >= 1e6 ? `${(h / 1e6).toFixed(2)} MH/s` : h >= 1e3 ? `${(h / 1e3).toFixed(1)} kH/s` : `${Math.round(h)} H/s`);

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3200);
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copié dans le presse-papiers"); }
  catch { prompt("Copiez le texte :", text); }
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-copy]");
  if (b) copy(b.dataset.copy);
});

// ---------------------------------------------------------- bande de blocs
let lastTip = null;
async function renderStrip(info) {
  if (info.tip === lastTip) return;
  const blocks = await api("/blocks?limit=12");
  const fresh = lastTip !== null;
  $("#strip").innerHTML = blocks.map((b, i) => `
    <li class="${fresh && i === 0 ? "new" : ""}">
      <a class="blk" href="#/block/${esc(b.hash)}">
        <div class="h">#${b.height}</div>
        ${hashHtml(b.hash, 5)}
        <div class="meta">${b.tx_count} tx, ${ago(b.timestamp)}</div>
      </a>
    </li>`).join("");
  lastTip = info.tip;
}

// ------------------------------------------------------------------- vues
const views = {
  async explorer() {
    const [info, blocks, mempool] = await Promise.all([api("/info"), api("/blocks?limit=15"), api("/mempool")]);
    const toHalving = info.next_halving - info.height - 1;
    const supplyPct = (100 * info.supply) / info.max_supply;
    return `
      <h1>Le réseau KinCoin en direct</h1>
      <p class="muted">Données lues sur le nœud ${esc(info.name)}, relié à ${info.peers} pair${info.peers > 1 ? "s" : ""}.
        Un bloc est visé toutes les ${info.block_time_target} secondes.</p>
      <dl class="stats">
        <div class="stat"><dt>Hauteur de la chaîne</dt><dd>${info.height.toLocaleString("fr-FR")}</dd></div>
        <div class="stat"><dt>Difficulté</dt><dd>${info.difficulty.toLocaleString("fr-FR", { maximumFractionDigits: 2 })} <small>${info.zero_bits} bits à zéro</small></dd></div>
        <div class="stat"><dt>Temps moyen par bloc</dt><dd>${info.avg_block_time ? info.avg_block_time.toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " s" : "—"}
          <small>prochain ajustement au bloc ${info.next_adjustment}</small></dd></div>
        <div class="stat"><dt>Puissance du réseau</dt><dd>${hashrate(info.hashrate)}</dd></div>
        <div class="stat"><dt>Récompense actuelle</dt><dd>${kin(info.reward)}
          <small>halving dans ${toHalving} bloc${toHalving > 1 ? "s" : ""}</small></dd></div>
        <div class="stat"><dt>Monnaie en circulation</dt><dd>${K.formatKin(info.supply, 2)} <small>sur ${K.formatKin(info.max_supply, 0)} KIN</small></dd>
          <div class="bar" aria-hidden="true"><i style="width:${supplyPct.toFixed(2)}%"></i></div></div>
        <div class="stat"><dt>Transactions en attente</dt><dd>${info.mempool}</dd></div>
        <div class="stat"><dt>Minage sur ce nœud</dt><dd>${info.mining ? hashrate(info.local_hashrate) : "arrêté"}</dd></div>
      </dl>

      <h2>Derniers blocs</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Hauteur</th><th>Hash</th><th class="hide-sm">Mineur</th><th class="num">Tx</th><th class="num">Récompense</th><th class="num">Âge</th></tr></thead>
        <tbody>${blocks.map((b) => `<tr>
          <td>${linkBlock(b.hash, "#" + b.height)}</td><td>${linkBlock(b.hash)}</td>
          <td class="hide-sm">${linkAddr(b.miner)}</td><td class="num">${b.tx_count}</td>
          <td class="num">${kin(b.reward)}</td><td class="num">${ago(b.timestamp)}</td></tr>`).join("")}</tbody>
      </table></div>

      <h2>Mempool</h2>
      ${mempool.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Transaction</th><th class="num">Montant</th><th class="num">Frais</th><th class="num">Reçue</th></tr></thead>
        <tbody>${mempool.map((t) => `<tr><td>${linkTx(t.txid)}</td><td class="num">${kin(t.total_out)}</td>
          <td class="num">${K.formatKin(t.fee)}</td><td class="num">${ago(t.timestamp)}</td></tr>`).join("")}</tbody>
      </table></div>` : `<p class="empty">Aucune transaction en attente. Envoyez des KIN depuis le portefeuille pour en voir une apparaître ici.</p>`}`;
  },

  async block(id) {
    const b = await api(`/block/${encodeURIComponent(id)}`);
    const h = b.header;
    return `
      <h1>Bloc #${h.height}</h1>
      <p>${hashHtml(b.hash)}</p>
      <dl class="kv">
        <dt>Statut</dt><dd>${b.in_main_chain ? `<span class="tag ok">${b.confirmations} confirmation${b.confirmations > 1 ? "s" : ""}</span>` : `<span class="tag">Branche abandonnée</span>`}</dd>
        <dt>Horodatage</dt><dd>${date(h.timestamp)} (${ago(h.timestamp)})</dd>
        <dt>Bloc précédent</dt><dd>${h.height ? linkBlock(h.prev_hash) : `<span class="muted">aucun, c'est le bloc genèse</span>`}</dd>
        <dt>Bloc suivant</dt><dd>${b.next_hash ? linkBlock(b.next_hash) : `<span class="muted">pas encore miné</span>`}</dd>
        <dt>Racine de Merkle</dt><dd class="mono">${esc(h.merkle_root)}</dd>
        <dt>Cible</dt><dd>${hashHtml(h.target)}<br><span class="muted">Le hash du bloc doit être inférieur ou égal à cette valeur : ${b.zero_bits} bits à zéro, difficulté ${b.difficulty.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}.</span></dd>
        <dt>Nonce</dt><dd class="mono">${h.nonce.toLocaleString("fr-FR")}</dd>
        <dt>Mineur</dt><dd>${linkAddr(b.miner)}</dd>
        ${b.message ? `<dt>Message du mineur</dt><dd>${esc(b.message)}</dd>` : ""}
      </dl>
      <h2>${b.tx_count} transaction${b.tx_count > 1 ? "s" : ""}</h2>
      ${b.transactions.map(txCard).join("")}`;
  },

  async tx(id) {
    const t = await api(`/tx/${encodeURIComponent(id)}`);
    return `
      <h1>Transaction</h1>
      <p class="mono">${esc(t.txid)}</p>
      <dl class="kv">
        <dt>Statut</dt><dd>${t.block ? `<span class="tag ok">${t.confirmations} confirmation${t.confirmations > 1 ? "s" : ""}</span> dans le bloc ${linkBlock(t.block, "#" + t.height)}` : `<span class="tag">En attente dans le mempool</span>`}</dd>
        <dt>Créée</dt><dd>${date(t.timestamp)}</dd>
        <dt>Total des sorties</dt><dd>${kin(t.total_out)}</dd>
        <dt>Frais</dt><dd>${t.coinbase ? `<span class="muted">aucun, transaction de récompense</span>` : kin(t.fee)}</dd>
      </dl>
      <h2>Entrées et sorties</h2>
      ${txCard(t)}`;
  },

  async address(a) {
    const info = await api(`/address/${encodeURIComponent(a)}`);
    return `
      <h1>Adresse</h1>
      <div class="addr-row"><span class="mono">${esc(a)}</span><button class="ghost" data-copy="${esc(a)}">Copier</button></div>
      <dl class="stats">
        <div class="stat"><dt>Solde confirmé</dt><dd>${kin(info.balance)}</dd></div>
        <div class="stat"><dt>Sorties non dépensées (UTXO)</dt><dd>${info.utxos.length}</dd></div>
      </dl>
      <h2>Historique</h2>
      ${historyTable(info.history)}`;
  },

  async wallet() {
    const priv = store.get("kin.key");
    if (!priv) return walletSetup();
    const addr = await K.addressFromPublicKey(K.publicKey(priv));
    const info = await api(`/address/${addr}`);
    const available = info.utxos.reduce((n, u) => n + u.amount, 0);
    return `
      <h1>Mon portefeuille</h1>
      <div class="wallet-head">
        <div class="card">
          <div class="muted">Solde</div>
          <div class="balance" id="w-balance">${K.formatKin(info.balance)} <small>KIN</small></div>
          <p class="muted" id="w-available">${available === info.balance ? "Tout le solde est disponible." : `${kin(available)} disponibles, le reste attend une confirmation.`}</p>
          <div class="muted">Mon adresse, à communiquer pour recevoir des KIN</div>
          <div class="addr-row"><span class="mono">${esc(addr)}</span><button class="ghost" data-copy="${esc(addr)}">Copier</button></div>
        </div>
        <div class="card">
          <h2 style="margin-top:0">Envoyer des KIN</h2>
          <form class="stack" id="send">
            <label>Adresse du destinataire<input name="to" class="mono" required autocomplete="off" spellcheck="false" placeholder="K…"></label>
            <label>Montant en KIN<input name="amount" required inputmode="decimal" placeholder="10,5"></label>
            <label>Frais en KIN <span class="hint">Le mineur choisit d'abord les transactions qui paient le plus.</span><input name="fee" value="0,00001" inputmode="decimal"></label>
            <div class="actions"><button type="submit">Signer et envoyer</button></div>
            <p class="error" id="send-error" role="alert"></p>
          </form>
        </div>
      </div>
      <h2>Historique</h2>
      <div id="w-history">${historyTable(info.history)}</div>
      <h2>Sauvegarde de la clé</h2>
      <p>La clé privée est enregistrée uniquement dans ce navigateur. Les transactions sont signées ici : la clé n'est jamais envoyée au nœud.</p>
      <div class="actions">
        <button class="ghost" id="show-key">Afficher la clé privée</button>
        <button class="danger" id="forget">Retirer le portefeuille de ce navigateur</button>
      </div>
      <p class="mono" id="key-out" hidden></p>`;
  },
};

function walletSetup() {
  return `
    <h1>Créer ou importer un portefeuille</h1>
    <p>Un portefeuille KinCoin est une clé privée secp256k1. Elle est générée dans votre navigateur et n'en sort pas.</p>
    <div class="wallet-head">
      <div class="card">
        <h2 style="margin-top:0">Nouveau portefeuille</h2>
        <p class="muted">Une clé aléatoire est créée, puis son adresse est calculée à partir de la clé publique.</p>
        <button id="create">Créer un portefeuille</button>
      </div>
      <div class="card">
        <h2 style="margin-top:0">Importer une clé</h2>
        <form class="stack" id="import">
          <label>Clé privée (64 caractères hexadécimaux)<textarea name="key" class="mono" rows="2" required spellcheck="false"></textarea></label>
          <div class="actions"><button type="submit" class="ghost">Importer</button></div>
          <p class="error" id="import-error" role="alert"></p>
        </form>
      </div>
    </div>
    <p class="notice">Réseau de démonstration : ne réutilisez pas cette clé pour un vrai portefeuille.</p>`;
}

function txCard(t) {
  const ins = t.coinbase
    ? `<li><span class="tag ok">Nouveaux KIN créés</span><div class="muted">Récompense du bloc et frais des transactions</div></li>`
    : t.inputs.map((i) => `<li>${linkAddr(i.address)}<div>${i.amount != null ? kin(i.amount) : ""} <span class="muted">sortie ${linkTx(i.txid)}:${i.vout}</span></div></li>`).join("");
  const outs = t.outputs.map((o) => `<li>${linkAddr(o.address)}<div>${kin(o.amount)}</div></li>`).join("");
  return `<div class="card" style="margin-bottom:12px">
    <p style="margin-top:0">${linkTx(t.txid)} ${t.fee ? `<span class="muted">frais ${kin(t.fee)}</span>` : ""}</p>
    <div class="io"><ul>${ins}</ul><div class="arrow" aria-hidden="true">⟶</div><ul>${outs}</ul></div></div>`;
}

function historyTable(history) {
  if (!history.length) return `<p class="empty">Aucune transaction pour l'instant. Partagez votre adresse ou lancez le minage vers elle.</p>`;
  return `<div class="table-wrap"><table>
    <thead><tr><th>Transaction</th><th>Bloc</th><th class="num">Montant</th><th class="num">Date</th></tr></thead>
    <tbody>${history.map((h) => `<tr><td>${linkTx(h.txid)}</td>
      <td>${h.height == null ? `<span class="tag">en attente</span>` : `<a href="#/block/${h.height}">#${h.height}</a>`}</td>
      <td class="num ${h.delta >= 0 ? "pos" : "neg"}">${h.delta >= 0 ? "+" : ""}${kin(h.delta)}</td>
      <td class="num">${ago(h.timestamp)}</td></tr>`).join("")}</tbody></table></div>`;
}

// ---------------------------------------------------------- interactions
function bindWallet() {
  $("#create")?.addEventListener("click", () => {
    store.set("kin.key", K.randomPrivateKey());
    toast("Portefeuille créé");
    route();
  });
  $("#import")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const key = e.target.key.value.trim().toLowerCase();
    try {
      if (!/^[0-9a-f]{64}$/.test(key)) throw new Error("la clé doit compter 64 caractères hexadécimaux");
      K.publicKey(key);
      store.set("kin.key", key);
      toast("Portefeuille importé");
      route();
    } catch (err) { $("#import-error").textContent = err.message; }
  });
  $("#send")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, btn = f.querySelector("button"), out = $("#send-error");
    out.textContent = "";
    btn.disabled = true;
    btn.textContent = "Signature en cours…";
    try {
      const priv = store.get("kin.key");
      const addr = await K.addressFromPublicKey(K.publicKey(priv));
      const to = f.to.value.trim();
      if (to === addr) throw new Error("c'est votre propre adresse");
      const amount = K.parseKin(f.amount.value), fee = K.parseKin(f.fee.value || "0");
      const info = await api(`/address/${addr}`);
      const tx = await K.buildTransaction(priv, info.utxos, to, amount, fee);
      const res = await api("/tx", { method: "POST", body: JSON.stringify(tx) });
      toast("Transaction envoyée, en attente du prochain bloc");
      location.hash = `#/tx/${res.txid}`;
    } catch (err) {
      out.textContent = err.message.startsWith("solde") || err.message.includes("dépensée")
        ? `${err.message}. Si vous venez d'envoyer une transaction, attendez qu'elle soit confirmée.` : err.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "Signer et envoyer";
    }
  });
  $("#show-key")?.addEventListener("click", () => {
    const p = $("#key-out");
    p.hidden = !p.hidden;
    p.textContent = store.get("kin.key");
  });
  $("#forget")?.addEventListener("click", () => {
    if (confirm("Sans sauvegarde de la clé privée, les KIN de cette adresse seront perdus. Retirer le portefeuille ?")) {
      store.set("kin.key", null);
      route();
    }
  });
}

$("#search").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = e.target.q.value.trim();
  if (!q) return;
  try {
    const r = await api(`/search/${encodeURIComponent(q)}`);
    location.hash = `#/${r.type}/${r.id}`;
    e.target.q.value = "";
  } catch (err) { toast(err.message); }
});

// --------------------------------------------------------------- routeur
let current = "";
async function route() {
  const [, name = "explorer", arg] = location.hash.split("/");
  const view = views[name] ? name : "explorer";
  current = location.hash;
  document.querySelectorAll(".tabs a").forEach((a) => a.toggleAttribute("aria-current", a.dataset.tab === (view === "wallet" ? "wallet" : "explorer")));
  document.querySelectorAll(".tabs a[aria-current]").forEach((a) => a.setAttribute("aria-current", "page"));
  const main = $("#view");
  try {
    const html = await views[view](decodeURIComponent(arg || ""));
    if (current !== location.hash) return;      // l'utilisateur a changé de page entre-temps
    main.innerHTML = html;
    bindWallet();
  } catch (err) {
    main.innerHTML = `<h1>Impossible d'afficher cette page</h1><p class="error">${esc(err.message)}</p>
      <p>Vérifiez que le nœud ${esc(node)} est en ligne, ou choisissez-en un autre en haut à droite.</p>`;
  }
}
window.addEventListener("hashchange", () => { route(); window.scrollTo(0, 0); });

// Rafraîchissement périodique : la bande de blocs, et la page si elle n'a pas de formulaire en cours.
async function refresh(force = false) {
  const dot = $("#node-dot");
  try {
    const info = await api("/info");
    dot.className = "dot ok";
    dot.title = `${info.name} en ligne`;
    if (force) lastTip = null;
    const changed = info.tip !== lastTip;
    await renderStrip(info);
    const busy = document.activeElement?.closest("form");
    const view = location.hash.split("/")[1] || "explorer";
    if (force || (changed && !busy && ["explorer", "wallet", "address", "tx", "block"].includes(view))) route();
  } catch {
    dot.className = "dot down";
    dot.title = "Nœud injoignable";
    const next = nodes[(nodes.indexOf(node) + 1) % nodes.length];
    if (force && next !== node) { node = next; fillNodes(); toast(`Nœud injoignable, bascule vers ${node}`); }
  }
}

route();
refresh();
setInterval(refresh, 4000);
