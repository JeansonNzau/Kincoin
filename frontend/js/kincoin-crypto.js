// KinCoin — cryptographie côté navigateur (aucune dépendance externe).
//
// - SHA-256 et HMAC-SHA256 via WebCrypto (crypto.subtle) ;
// - ECDSA secp256k1 écrit en JavaScript (BigInt) avec nonce déterministe RFC 6979
//   et normalisation « low-S », compatible avec la vérification du nœud Python ;
// - JSON canonique, Base58Check et construction de transactions identiques au nœud.
//
// Remarque de sécurité : cette implémentation est pédagogique (le calcul n'est pas
// en temps constant). Pour un vrai produit, utiliser une bibliothèque auditée
// comme @noble/secp256k1 — l'interface ci-dessous resterait la même.

export const COIN = 100_000_000n;
export const ADDRESS_VERSION = 0x2d;

// ------------------------------------------------------------------ octets
export const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
export function fromHex(h) {
  if (h.length % 2 || /[^0-9a-f]/i.test(h)) throw new Error("hexadécimal invalide");
  const out = new Uint8Array(h.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(h.slice(2 * i, 2 * i + 2), 16);
  return out;
}
const concat = (...arrs) => {
  const out = new Uint8Array(arrs.reduce((n, a) => n + a.length, 0));
  let o = 0;
  for (const a of arrs) { out.set(a, o); o += a.length; }
  return out;
};
const bytesToBig = (b) => (b.length ? BigInt("0x" + hex(b)) : 0n);
const bigToBytes = (n, len = 32) => fromHex(n.toString(16).padStart(len * 2, "0"));

// -------------------------------------------------------------------- hash
// WebCrypto (crypto.subtle) n'existe que sur une page sûre : HTTPS, localhost ou 127.0.0.1.
// Ouverte depuis un autre PC en http://10.x.x.x, la page utilise cette version JavaScript.
const SUBTLE = globalThis.crypto && globalThis.crypto.subtle;
const K256 = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);
function sha256js(data) {
  const len = data.length, total = Math.ceil((len + 9) / 64) * 64;
  const m = new Uint8Array(total);
  m.set(data);
  m[len] = 0x80;
  const bits = len * 8;
  const dv = new DataView(m.buffer);
  dv.setUint32(total - 8, Math.floor(bits / 2 ** 32));
  dv.setUint32(total - 4, bits >>> 0);
  const h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
  const w = new Uint32Array(64);
  const rotr = (x, n) => (x >>> n) | (x << (32 - n));
  for (let off = 0; off < total; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(off + 4 * i);
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, hh] = h;
    for (let i = 0; i < 64; i++) {
      const t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K256[i] + w[i]) >>> 0;
      const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
      hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }
  const out = new Uint8Array(32);
  const ov = new DataView(out.buffer);
  for (let i = 0; i < 8; i++) ov.setUint32(4 * i, h[i]);
  return out;
}
function hmacjs(key, data) {
  if (key.length > 64) key = sha256js(key);
  const k = new Uint8Array(64);
  k.set(key);
  const ipad = k.map((b) => b ^ 0x36), opad = k.map((b) => b ^ 0x5c);
  return sha256js(concat(opad, sha256js(concat(ipad, data))));
}
export async function sha256(bytes) {
  if (!SUBTLE) return sha256js(bytes);
  return new Uint8Array(await SUBTLE.digest("SHA-256", bytes));
}
export async function sha256d(bytes) {
  return sha256(await sha256(bytes));
}
async function hmac(key, data) {
  if (!SUBTLE) return hmacjs(key, data);
  const k = await SUBTLE.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await SUBTLE.sign("HMAC", k, data));
}

// ---------------------------------------------------------- JSON canonique
// Même sortie que json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).
export function canonical(value) {
  if (value === null || typeof value !== "object") {
    if (typeof value === "number" && !Number.isSafeInteger(value)) throw new Error("nombre non entier");
    return JSON.stringify(value).replace(/[\u0080-￿]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  }
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  return "{" + Object.keys(value).sort().map((k) => canonical(k) + ":" + canonical(value[k])).join(",") + "}";
}
const utf8 = (s) => new TextEncoder().encode(s);

// -------------------------------------------------------------- secp256k1
const P = 0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffefffffc2fn;
const N = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n;
const G = [
  0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798n,
  0x483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8n,
];
const mod = (a, m = P) => ((a % m) + m) % m;
function inv(a, m = P) {
  let [r0, r1, s0, s1] = [mod(a, m), m, 1n, 0n];
  while (r1) { const q = r0 / r1; [r0, r1] = [r1, r0 - q * r1]; [s0, s1] = [s1, s0 - q * s1]; }
  return mod(s0, m);
}
function add(p, q) {
  if (!p) return q;
  if (!q) return p;
  if (p[0] === q[0] && mod(p[1] + q[1]) === 0n) return null;
  const l = p[0] === q[0] && p[1] === q[1]
    ? mod(3n * p[0] * p[0] * inv(2n * p[1]))
    : mod((q[1] - p[1]) * inv(q[0] - p[0]));
  const x = mod(l * l - p[0] - q[0]);
  return [x, mod(l * (p[0] - x) - p[1])];
}
function mul(k, p = G) {
  let r = null;
  for (; k > 0n; k >>= 1n, p = add(p, p)) if (k & 1n) r = add(r, p);
  return r;
}

export function randomPrivateKey() {
  for (;;) {
    const k = bytesToBig(crypto.getRandomValues(new Uint8Array(32)));
    if (k > 0n && k < N) return k.toString(16).padStart(64, "0");
  }
}
export function publicKey(privHex) {
  const d = BigInt("0x" + privHex);
  if (d <= 0n || d >= N) throw new Error("clé privée hors de l'intervalle autorisé");
  const [x, y] = mul(d);
  return concat(new Uint8Array([y & 1n ? 3 : 2]), bigToBytes(x));
}

// Nonce déterministe RFC 6979 : pas besoin d'un bon générateur aléatoire pour signer.
async function rfc6979(d, h1) {
  const x = bigToBytes(d), hb = bigToBytes(mod(bytesToBig(h1), N));
  let v = new Uint8Array(32).fill(1), k = new Uint8Array(32);
  k = await hmac(k, concat(v, [0], x, hb)); v = await hmac(k, v);
  k = await hmac(k, concat(v, [1], x, hb)); v = await hmac(k, v);
  for (;;) {
    v = await hmac(k, v);
    const t = bytesToBig(v);
    if (t > 0n && t < N) return t;
    k = await hmac(k, concat(v, [0])); v = await hmac(k, v);
  }
}

function der(r, s) {
  const enc = (n) => {
    let b = fromHex(n.toString(16).padStart(n.toString(16).length + (n.toString(16).length % 2), "0"));
    if (b[0] & 0x80) b = concat([0], b);
    return concat([0x02, b.length], b);
  };
  const body = concat(enc(r), enc(s));
  return concat([0x30, body.length], body);
}

/** Signe un condensé de 32 octets ; renvoie la signature DER en hexadécimal. */
export async function sign(digest32, privHex) {
  const d = BigInt("0x" + privHex), e = bytesToBig(digest32);
  for (;;) {
    const k = await rfc6979(d, digest32);
    const r = mod(mul(k)[0], N);
    let s = mod(inv(k, N) * (e + r * d), N);
    if (r === 0n || s === 0n) continue;
    if (s > N / 2n) s = N - s;                 // low-S, exigé par les nœuds
    return hex(der(r, s));
  }
}

// ---------------------------------------------------------------- adresses
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
function b58encode(bytes) {
  let n = bytesToBig(bytes), out = "";
  while (n > 0n) { out = B58[Number(n % 58n)] + out; n /= 58n; }
  for (const b of bytes) { if (b) break; out = "1" + out; }
  return out;
}
function b58decode(s) {
  let n = 0n;
  for (const c of s) {
    const i = B58.indexOf(c);
    if (i < 0) throw new Error("caractère Base58 invalide");
    n = n * 58n + BigInt(i);
  }
  const body = n ? fromHex(n.toString(16).padStart(n.toString(16).length + (n.toString(16).length % 2), "0")) : new Uint8Array();
  const pad = s.length - s.replace(/^1+/, "").length;
  return concat(new Uint8Array(pad), body);
}
export async function addressFromPublicKey(pub) {
  const payload = concat([ADDRESS_VERSION], (await sha256d(pub)).slice(0, 20));
  return b58encode(concat(payload, (await sha256d(payload)).slice(0, 4)));
}
export async function isValidAddress(addr) {
  try {
    const raw = b58decode(addr);
    if (raw.length !== 25 || raw[0] !== ADDRESS_VERSION) return false;
    return hex((await sha256d(raw.slice(0, 21))).slice(0, 4)) === hex(raw.slice(21));
  } catch { return false; }
}

// ----------------------------------------------------------- transactions
export async function txid(tx) {
  return hex(await sha256d(utf8(canonical(tx))));
}
export async function sighash(tx) {
  const unsigned = structuredClone(tx);
  for (const i of unsigned.inputs) i.signature = "";
  return sha256d(utf8(canonical(unsigned)));
}

/** Convertit « 12,5 » ou « 12.5 » KIN en makuta (entier), sans erreur d'arrondi. */
export function parseKin(text) {
  const t = String(text).trim().replace(",", ".");
  if (!/^\d+(\.\d{1,8})?$/.test(t)) throw new Error("montant invalide (8 décimales au maximum)");
  const [ent, dec = ""] = t.split(".");
  return Number(BigInt(ent) * COIN + BigInt(dec.padEnd(8, "0")));
}
export function formatKin(makuta, digits = 8) {
  const neg = makuta < 0, v = BigInt(Math.abs(makuta));
  const ent = (v / COIN).toLocaleString("fr-FR");
  let dec = (v % COIN).toString().padStart(8, "0").slice(0, digits).replace(/0+$/, "");
  return (neg ? "−" : "") + ent + (dec ? "," + dec : "");
}

/**
 * Construit et signe une transaction (même algorithme que kincoin/tx.py).
 * utxos : [{txid, vout, amount}] appartenant à la clé ; la monnaie est rendue à l'expéditeur.
 */
export async function buildTransaction(privHex, utxos, to, amount, fee = 0) {
  if (!(amount > 0)) throw new Error("le montant doit être positif");
  if (!(await isValidAddress(to))) throw new Error("adresse de destination invalide");
  const pub = hex(publicKey(privHex));
  const from = await addressFromPublicKey(publicKey(privHex));
  const selected = [];
  let total = 0;
  for (const u of [...utxos].sort((a, b) => b.amount - a.amount)) {
    selected.push(u);
    total += u.amount;
    if (total >= amount + fee) break;
  }
  if (total < amount + fee) throw new Error("solde disponible insuffisant");
  const tx = {
    version: 1,
    timestamp: Math.floor(Date.now() / 1000),
    inputs: selected.map((u) => ({ txid: u.txid, vout: u.vout, pubkey: pub, signature: "" })),
    outputs: [{ address: to, amount }],
  };
  const change = total - amount - fee;
  if (change > 0) tx.outputs.push({ address: from, amount: change });
  const digest = await sighash(tx);
  for (const i of tx.inputs) i.signature = await sign(digest, privHex);
  return tx;
}
