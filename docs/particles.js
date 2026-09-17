/* Le champ de Deskys qui flottent derrière le logo (lot L16).
 *
 * Les particules sont des robots réellement générés par le moteur du produit —
 * voir `tools/site_deskys.py` — et non des dessins faits pour la vitrine.
 *
 * **Une planche par châssis**, chacune un atlas de `cols` colonnes en cases
 * `cw × ch`. Deux familles vivent dans le produit depuis le lot L17, et le champ
 * doit les montrer toutes les deux. Une particule tire sa case **uniformément
 * parmi toutes les cases de toutes les planches** : la composition du champ est
 * donc celle des planches, et elle est réglée pour valoir celle du tirage réel
 * du génome — 38 % de monoblocs. Pondérer autrement montrerait une famille plus
 * rare, ou plus commune, qu'elle ne l'est à l'installation.
 *
 * Trois règles portent tout l'effet :
 *
 *   1. Rien ne passe **sous le contenu**. La zone interdite est le rectangle
 *      réel de la carte, mesuré dans le DOM et non deviné : le logo fourni peut
 *      changer de taille, et une exclusion codée en dur finirait fausse.
 *   2. Petit = loin = pâle. C'est la seule profondeur dont on dispose, et elle
 *      suffit à empêcher le champ de ressembler à des autocollants.
 *   3. Rien ne tourne. Un robot incliné sur le côté a l'air cassé, pas flottant.
 *      Le mouvement est une dérive lente plus un balancement vertical.
 *
 * L'animation s'arrête quand l'onglet passe en arrière-plan. Un site qui vend un
 * logiciel tenu à moins de 4 % d'un cœur ne peut pas faire tourner une boucle de
 * rendu dans un onglet que personne ne regarde.
 */

(function () {
  "use strict";

  // Résolu par rapport au **script** et non au document : la page anglaise vit
  // dans `/en/` et charge le même fichier, donc un chemin relatif ordinaire y
  // pointerait vers `/en/assets/`, qui n'existe pas.
  var base = (document.currentScript && document.currentScript.src) ||
             (location.origin + location.pathname);

  // À reporter depuis la sortie de `python -m tools.site_deskys`. Un test du
  // dépôt confronte ces cotes aux dimensions réelles des fichiers : une planche
  // régénérée avec d'autres réglages et un script oublié découperaient les
  // robots en morceaux.
  var PLANCHES = [
    { fichier: "deskys.webp",    COLS: 10, CELL_W: 139, CELL_H: 155, COUNT: 50 },
    { fichier: "monoblocs.webp", COLS: 10, CELL_W: 116, CELL_H: 156, COUNT: 30 }
  ];

  var VIVANTES = 15;          // particules simultanées
  var TAILLE = [34, 82];      // hauteur affichée, en pixels CSS
  var VIE = [4.0, 9.0];       // secondes
  var FONDU = [0.9, 1.4];     // entrée, sortie
  var ALPHA = [0.55, 1.00];   // opacité selon la taille
  var DERIVE = 7;             // pixels par seconde
  var BALANCE = [3, 9];       // amplitude du balancement vertical
  var MARGE_CARTE = 18;       // respiration autour du contenu

  var canvas = document.getElementById("champ");
  if (!canvas) { return; }
  var ctx = canvas.getContext("2d");
  var carte = document.querySelector(".carte");

  var pretes = [];            // planches chargées, dans l'ordre d'arrivée
  var total = 0;              // cases disponibles, toutes planches confondues
  var attendues = PLANCHES.length;
  var particules = [];
  var largeur = 0, hauteur = 0, dpr = 1;
  var interdit = null;
  var dernier = 0;
  var boucle = null;

  var calme = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false };

  function hasard(min, max) { return min + Math.random() * (max - min); }

  function mesurer() {
    var rect = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    largeur = rect.width;
    hauteur = rect.height;
    canvas.width = Math.round(largeur * dpr);
    canvas.height = Math.round(hauteur * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Le rectangle du contenu, ramené dans le repère du canvas.
    if (carte) {
      var c = carte.getBoundingClientRect();
      interdit = {
        x0: c.left - rect.left - MARGE_CARTE,
        y0: c.top - rect.top - MARGE_CARTE,
        x1: c.right - rect.left + MARGE_CARTE,
        y1: c.bottom - rect.top + MARGE_CARTE
      };
    }
  }

  function libre(x, y, taille) {
    if (!interdit) { return true; }
    var demi = taille * 0.5;
    return !(x + demi > interdit.x0 && x - demi < interdit.x1 &&
             y + demi > interdit.y0 && y - demi < interdit.y1);
  }

  function naitre(agee) {
    // Tirage dans une **ellipse** et non dans un cercle : le champ est plus
    // large que haut (cf. `#champ` dans la feuille de style), et un tirage
    // circulaire laisserait les deux flancs vides.
    var rx = largeur * 0.5, ry = hauteur * 0.5;
    var cx = largeur * 0.5, cy = hauteur * 0.5;
    var taille = hasard(TAILLE[0], TAILLE[1]);
    var x = 0, y = 0, trouve = false;

    // Tirage en disque, rejet de ce qui tombe sur la carte. Dix essais suffisent
    // très largement ; au-delà on renonce à faire naître celle-là plutôt que de
    // la poser de force sur le texte.
    for (var essai = 0; essai < 10 && !trouve; essai++) {
      var angle = Math.random() * Math.PI * 2;
      var d = Math.sqrt(hasard(0.06, 0.97));
      x = cx + Math.cos(angle) * d * rx;
      y = cy + Math.sin(angle) * d * ry;
      trouve = libre(x, y, taille);
    }
    if (!trouve) { return null; }

    // Tirage uniforme sur l'ensemble des cases : c'est le nombre de variantes
    // de chaque planche qui décide de la part de chaque famille, et non une
    // pondération écrite ici qu'il faudrait tenir à jour.
    var rang = Math.floor(Math.random() * total);
    var planche = pretes[0];
    for (var k = 0; k < pretes.length; k++) {
      if (rang < pretes[k].COUNT) { planche = pretes[k]; break; }
      rang -= pretes[k].COUNT;
    }

    var vie = hasard(VIE[0], VIE[1]);
    var part = (taille - TAILLE[0]) / (TAILLE[1] - TAILLE[0]);
    return {
      planche: planche,
      cell: rang,
      x: x, y: y,
      taille: taille,
      alpha: ALPHA[0] + (ALPHA[1] - ALPHA[0]) * part,
      vx: hasard(-DERIVE, DERIVE) * 0.5,
      // Dérive verticale **des deux côtés**. Une dérive uniquement ascendante
      // vide le bas du champ au fil des minutes : les particules naissent
      // partout mais meurent toutes en haut, et le déséquilibre s'installe sans
      // qu'on le voie arriver.
      vy: hasard(-DERIVE, DERIVE) * 0.4,
      balance: hasard(BALANCE[0], BALANCE[1]),
      phase: Math.random() * Math.PI * 2,
      entree: hasard(FONDU[0], FONDU[1] * 0.8),
      sortie: hasard(FONDU[0], FONDU[1]),
      vie: vie,
      // Au premier remplissage on répartit les âges : sans cela les quinze
      // premières apparaissent ensemble, puis disparaissent ensemble, et le
      // champ respire par à-coups pendant la première minute.
      age: agee ? Math.random() * vie : 0
    };
  }

  function remplir(agee) {
    if (!total) { return; }
    while (particules.length < VIVANTES) {
      var p = naitre(agee);
      if (!p) { break; }
      particules.push(p);
    }
  }

  function opacite(p) {
    var reste = p.vie - p.age;
    var f = 1;
    if (p.age < p.entree) { f = p.age / p.entree; }
    if (reste < p.sortie) { f = Math.min(f, Math.max(0, reste / p.sortie)); }
    // Adoucissement : une entrée linéaire se voit comme un clignotement.
    return p.alpha * f * f * (3 - 2 * f);
  }

  function dessiner() {
    ctx.clearRect(0, 0, largeur, hauteur);
    if (!total) { return; }

    // Les grandes devant : c'est ce qui donne l'étagement.
    var ordre = particules.slice().sort(function (a, b) {
      return a.taille - b.taille;
    });

    for (var i = 0; i < ordre.length; i++) {
      var p = ordre[i];
      var a = opacite(p);
      if (a <= 0.004) { continue; }
      // Chaque planche a ses propres cotes : un monobloc est nettement plus
      // étroit qu'une capsule coiffée, et leur imposer un même rapport les
      // écraserait tous les deux d'autant.
      var pl = p.planche;
      var w = p.taille * (pl.CELL_W / pl.CELL_H);
      var h = p.taille;
      var sx = (p.cell % pl.COLS) * pl.CELL_W;
      var sy = Math.floor(p.cell / pl.COLS) * pl.CELL_H;
      var oy = p.y + Math.sin(p.phase) * p.balance;
      ctx.globalAlpha = a;
      ctx.drawImage(pl.image, sx, sy, pl.CELL_W, pl.CELL_H,
                    p.x - w * 0.5, oy - h * 0.5, w, h);
    }
    ctx.globalAlpha = 1;
  }

  function avancer(dt) {
    for (var i = particules.length - 1; i >= 0; i--) {
      var p = particules[i];
      p.age += dt;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.phase += dt * 0.7;
      if (p.age >= p.vie) { particules.splice(i, 1); }
    }
    remplir(false);
  }

  function image(maintenant) {
    boucle = window.requestAnimationFrame(image);
    if (!dernier) { dernier = maintenant; }
    // Borné : un onglet réveillé après une minute ne doit pas téléporter le
    // champ d'un coup.
    var dt = Math.min(0.1, (maintenant - dernier) / 1000);
    dernier = maintenant;
    avancer(dt);
    dessiner();
  }

  function demarrer() {
    if (boucle !== null || calme.matches) { return; }
    dernier = 0;
    boucle = window.requestAnimationFrame(image);
  }

  function arreter() {
    if (boucle !== null) {
      window.cancelAnimationFrame(boucle);
      boucle = null;
    }
  }

  function poser() {
    // Mode calme : un champ figé, dessiné une fois. Le visiteur voit quand même
    // la variété des robots, ce qui est tout ce que la page en attend.
    particules = [];
    remplir(true);
    for (var i = 0; i < particules.length; i++) {
      particules[i].age = particules[i].entree;
    }
    dessiner();
  }

  // Les planches se chargent en parallèle et le champ démarre dès la première :
  // attendre la dernière laisserait un trou au moment précis où l'on découvre
  // la page. Celle qui arrive ensuite entre dans le tirage des naissances
  // suivantes, sans rien interrompre.
  function chargee(config, image) {
    config.image = image;
    pretes.push(config);
    total += config.COUNT;
    mesurer();
    if (calme.matches) {
      poser();
    } else {
      remplir(true);
      demarrer();
    }
  }

  function manquante() {
    // Une planche absente n'emporte pas les autres, et si toutes manquent la
    // page reste parfaitement utilisable : c'est un décor.
    if (--attendues <= 0 && !pretes.length) { canvas.style.display = "none"; }
  }

  PLANCHES.forEach(function (config) {
    var image = new Image();
    image.onload = function () { chargee(config, image); };
    image.onerror = manquante;
    image.src = new URL("assets/" + config.fichier, base).href;
  });

  var minuteur = null;
  window.addEventListener("resize", function () {
    window.clearTimeout(minuteur);
    minuteur = window.setTimeout(function () {
      mesurer();
      if (calme.matches) { poser(); }
    }, 150);
  });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { arreter(); } else { demarrer(); }
  });

  if (calme.addEventListener) {
    calme.addEventListener("change", function () {
      if (calme.matches) { arreter(); poser(); } else { demarrer(); }
    });
  }
})();
