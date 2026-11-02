// Liste des nœuds KinCoin utilisés par le portefeuille et l'explorateur.
//
// En local ou en réseau Wi-Fi : rien à changer. Si la page est ouverte depuis un nœud
// (http://<adresse>:8001/app/), les 3 nœuds sont cherchés à cette même adresse,
// ce qui permet aux autres PC du réseau d'ouvrir http://<IP du PC des nœuds>:8001/app/.
//
// Après un déploiement en ligne (Vercel), remplacez la liste par les URL publiques
// des nœuds, par exemple :
//   window.KINCOIN_NODES = ["https://kincoin-noeud-1.onrender.com", "https://kincoin-noeud-2.onrender.com"];
(function () {
  var host = location.pathname.indexOf("/app") === 0 ? location.hostname : "127.0.0.1";
  window.KINCOIN_NODES = [1, 2, 3].map(function (n) { return "http://" + host + ":800" + n; });
})();
