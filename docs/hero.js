/* Le robot qui suit la souris en bas de la page (lot L16).
 *
 * Ce n'est pas une animation « dans l'esprit » du produit : c'est **sa
 * démarche**, recopiée de `pet/anim/locomotion.py`. Mêmes phases, mêmes durées,
 * mêmes amplitudes, mêmes courbes. Un visiteur qui installe Desky doit
 * reconnaître ce qu'il a vu sur la page, et la seule façon d'en être sûr est de
 * ne rien réinventer ici.
 *
 *   accroupissement 0,10 s  →  vol 0,30 s  →  encaissement 0,13 s  →  pause
 *
 * Les poses du regard viennent de `tools/site_hero.py`, qui les rend hors écran
 * en laissant converger les trois ressorts du §10.2. La planche est un atlas :
 * COLS × ROWS directions, empilées une fois les yeux ouverts puis fermés.
 *
 * **L'écrasement conserve le volume.** `flex` négatif écrase : le robot devient
 * plus court *et* plus large. Le faire seulement plus court donnerait un robot
 * qui maigrit en atterrissant, ce qui est le défaut que le lot L10 a corrigé
 * dans l'application. Le facteur en racine reprend cette conservation.
 */

(function () {
  "use strict";

  var base = (document.currentScript && document.currentScript.src) ||
             (location.origin + location.pathname);
  var SHEET = new URL("assets/hero.webp", base).href;

  // À reporter depuis la sortie de `python -m tools.site_hero`.
  var COLS = 9, ROWS = 3, CELL_W = 178, CELL_H = 200;
  var DX = 2.4, DY = 1.2;        // amplitude du regard, en hauteurs de robot

  // --- La démarche, telle quelle depuis `pet/anim/locomotion.py` -----------
  var HOP_DISTANCE = 1.00;       // portée horizontale d'un saut, en hauteurs
  var HOP_HEIGHT = 0.28;         // hauteur de l'arc
  var HOP_CROUCH = 0.11;         // accroupissement d'anticipation
  var HOP_SQUASH = 0.065;        // écrasement à l'atterrissage
  var CROUCH_TIME = 0.10;
  var AIR_TIME = 0.30;
  var LAND_TIME = 0.13;
  var PAUSE_MIN = 0.04, PAUSE_MAX = 0.16;

  // Zone morte, en hauteurs de robot. En dessous il est déjà à côté, et
  // repartir serait du tremblement (c'est `FOLLOW_NEAR` de `actions.py`).
  var PROCHE = 0.9;

  // Taille affichée du robot, en pixels CSS, et marge aux bords.
  var HAUTEUR = [96, 132];
  var MARGE = 24;

  // Clignement : intervalle et durée, repris de `layers.BLINK_INTERVAL`.
  var CLIN_MIN = 2.4, CLIN_MAX = 6.8, CLIN_DUREE = 0.11;

  var canvas = document.getElementById("heros");
  if (!canvas) { return; }
  var ctx = canvas.getContext("2d");

  var planche = new Image();
  var prete = false;
  var largeur = 0, hauteur = 0, dpr = 1, taille = HAUTEUR[0];
  var dernier = 0, boucle = null;

  var calme = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false };

  // État du robot. `x` est le centre au sol, `arc` la hauteur au-dessus de lui.
  var bot = {
    x: 0, cible: 0, arc: 0,
    phase: "pause", t: 0, pause: 0.12,
    depart: 0, arrivee: 0,
    flex: 0, lift: 0,
    regard: [0, 0],
    clin: 0, prochainClin: 3.0
  };

  var souris = null;             // null tant qu'elle n'a pas bougé

  function easeInOut(t) { return t * t * (3 - 2 * t); }

  function easeOutBack(t) {
    var u = t - 1, o = 1.9;
    return 1 + u * u * ((o + 1) * u + o);
  }

  function mesurer() {
    var rect = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    largeur = rect.width;
    hauteur = rect.height;
    canvas.width = Math.round(largeur * dpr);
    canvas.height = Math.round(hauteur * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Le robot grandit avec la page, entre deux bornes : à 96 px il reste
    // lisible sur un téléphone, à 132 il ne prend pas toute la bande.
    taille = Math.max(HAUTEUR[0], Math.min(HAUTEUR[1], largeur * 0.11));
    if (!bot.x) { bot.x = largeur * 0.5; bot.cible = bot.x; }
  }

  function bornes(x) {
    var demi = taille * 0.5;
    return Math.max(MARGE + demi, Math.min(largeur - MARGE - demi, x));
  }

  /* Où regarde-t-il. Le décalage est exprimé en hauteurs de robot, exactement
   * comme `window._anim_context` le calcule dans l'application : c'est ce qui
   * rend la pose indépendante de la taille d'affichage.
   *
   * **Le vertical est inversé, et c'est la règle du produit** : « le y de
   * l'écran descend, celui du regard monte ». Passer le delta brut donne un
   * robot qui baisse la tête quand la souris monte — le défaut s'est vu tout de
   * suite à l'usage, et pas du tout en relisant les signes. */
  function viser() {
    if (!souris) { return [0, 0]; }
    var rect = canvas.getBoundingClientRect();
    var tete = rect.top + hauteur - taille * 0.75;
    return [(souris.x - (rect.left + bot.x)) / taille,
            (tete - souris.y) / taille];
  }

  function caseDuRegard() {
    var dx = Math.max(-DX, Math.min(DX, bot.regard[0]));
    var dy = Math.max(-DY, Math.min(DY, bot.regard[1]));
    var col = Math.round((dx + DX) / (2 * DX) * (COLS - 1));
    var row = Math.round((dy + DY) / (2 * DY) * (ROWS - 1));
    return [col, row];
  }

  /* La machine à phases de `Locomotion._update_hop`, à l'identique. */
  function avancerDemarche(dt) {
    bot.t += dt;
    bot.flex = 0;
    bot.lift = 0;
    var portee = HOP_DISTANCE * taille;

    if (bot.phase === "pause") {
      if (bot.t >= bot.pause) {
        // Il ne repart que s'il a une raison d'aller quelque part. Sans cette
        // condition il sautille sur place indéfiniment, ce qui est fatigant à
        // regarder et n'est pas ce que fait le vrai.
        if (Math.abs(bot.cible - bot.x) > PROCHE * taille) {
          bot.phase = "crouch";
          bot.t = 0;
        } else {
          bot.t = 0;
        }
      }
      return;
    }

    if (bot.phase === "crouch") {
      var c = easeInOut(Math.min(1, bot.t / CROUCH_TIME));
      bot.lift = -HOP_CROUCH * c;
      bot.flex = -HOP_SQUASH * c;
      if (bot.t >= CROUCH_TIME) {
        var reste = bot.cible - bot.x;
        var pas = Math.sign(reste) * Math.min(portee, Math.abs(reste));
        bot.depart = bot.x;
        bot.arrivee = bornes(bot.x + pas);
        bot.phase = "air";
        bot.t = 0;
      }
      return;
    }

    if (bot.phase === "air") {
      var a = Math.min(1, bot.t / AIR_TIME);
      bot.x = bot.depart + (bot.arrivee - bot.depart) * a;
      // Arc parabolique : du vertical vrai, ni sinusoïde ni interpolation.
      bot.arc = HOP_HEIGHT * taille * 4 * a * (1 - a);
      // En vol il s'étire dans l'axe du mouvement, et l'étirement cesse au
      // sommet : c'est le contraste avec l'écrasement qui donne le choc.
      bot.flex = HOP_SQUASH * 0.55 * Math.abs(1 - 2 * a);
      if (bot.t >= AIR_TIME) {
        bot.x = bot.arrivee;
        bot.arc = 0;
        bot.phase = "land";
        bot.t = 0;
      }
      return;
    }

    if (bot.phase === "land") {
      var l = Math.min(1, bot.t / LAND_TIME);
      var amorti = 1 - easeOutBack(l);
      bot.flex = -HOP_SQUASH * amorti;
      bot.lift = -HOP_CROUCH * 0.5 * amorti;
      if (bot.t >= LAND_TIME) {
        bot.phase = "pause";
        bot.t = 0;
        bot.pause = PAUSE_MIN + Math.random() * (PAUSE_MAX - PAUSE_MIN);
      }
    }
  }

  function clignoter(dt) {
    bot.prochainClin -= dt;
    if (bot.prochainClin <= 0) {
      bot.clin = CLIN_DUREE;
      bot.prochainClin = CLIN_MIN + Math.random() * (CLIN_MAX - CLIN_MIN);
    }
    if (bot.clin > 0) { bot.clin -= dt; }
  }

  function avancer(dt) {
    if (souris) { bot.cible = bornes(souris.x - canvas.getBoundingClientRect().left); }

    // Le regard rattrape sa cible de façon amortie. Les poses sont figées dans
    // la planche ; c'est ce lissage qui évite de sauter de case en case.
    var vise = viser();
    var k = Math.min(1, dt * 9);
    bot.regard[0] += (vise[0] - bot.regard[0]) * k;
    bot.regard[1] += (vise[1] - bot.regard[1]) * k;

    avancerDemarche(dt);
    clignoter(dt);
  }

  function dessiner() {
    ctx.clearRect(0, 0, largeur, hauteur);
    if (!prete) { return; }

    var cell = caseDuRegard();
    var etage = bot.clin > 0 ? 1 : 0;
    var sx = cell[0] * CELL_W;
    var sy = (etage * ROWS + cell[1]) * CELL_H;

    // Conservation du volume : écraser élargit, étirer amincit.
    var ech = 1 + bot.flex;
    var echX = 1 / Math.sqrt(Math.max(0.2, ech));
    var w = taille * (CELL_W / CELL_H) * echX;
    var h = taille * ech;

    var sol = hauteur - MARGE * 0.5;
    var bas = sol - bot.arc + bot.lift * taille;

    // Ombre de contact : elle rétrécit et pâlit avec la hauteur. C'est elle qui
    // dit à quelle hauteur il est ; sans elle un saut se lit comme un
    // grandissement.
    var haut = bot.arc / (HOP_HEIGHT * taille);
    var ro = taille * 0.30 * (1 - 0.35 * haut);
    ctx.save();
    ctx.globalAlpha = 0.16 * (1 - 0.5 * haut);
    ctx.fillStyle = "#1b3b44";
    ctx.beginPath();
    ctx.ellipse(bot.x, sol - 2, ro, ro * 0.26, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    ctx.drawImage(planche, sx, sy, CELL_W, CELL_H,
                  bot.x - w * 0.5, bas - h, w, h);
  }

  function image(maintenant) {
    boucle = window.requestAnimationFrame(image);
    if (!dernier) { dernier = maintenant; }
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
    if (boucle !== null) { window.cancelAnimationFrame(boucle); boucle = null; }
  }

  function poser() {
    // Mode calme : il se tient là, sans sauter. Il regarde quand même la
    // souris — c'est un mouvement d'un dixième de seconde, pas une animation
    // continue, et c'est ce qui donne sa présence au personnage.
    arreter();
    bot.arc = 0; bot.flex = 0; bot.lift = 0; bot.phase = "pause";
    var vise = viser();
    bot.regard[0] = vise[0];
    bot.regard[1] = vise[1];
    dessiner();
  }

  planche.onload = function () {
    prete = true;
    mesurer();
    if (calme.matches) { poser(); } else { demarrer(); }
  };
  planche.onerror = function () { canvas.style.display = "none"; };
  planche.src = SHEET;

  window.addEventListener("mousemove", function (e) {
    souris = { x: e.clientX, y: e.clientY };
    if (calme.matches) { poser(); }
  }, { passive: true });

  // La souris quitte la fenêtre : il cesse de suivre plutôt que de rester figé
  // sur la dernière position connue, qui se lirait comme un bug.
  document.addEventListener("mouseleave", function () { souris = null; });

  var minuteur = null;
  window.addEventListener("resize", function () {
    window.clearTimeout(minuteur);
    minuteur = window.setTimeout(function () {
      mesurer();
      bot.x = bornes(bot.x);
      if (calme.matches) { poser(); }
    }, 150);
  });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { arreter(); } else { demarrer(); }
  });

  if (calme.addEventListener) {
    calme.addEventListener("change", function () {
      if (calme.matches) { poser(); } else { demarrer(); }
    });
  }
})();
