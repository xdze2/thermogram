# Cool Inertia — Proposition

App web mobile-first, en français, qui répond à : _« Comment je rafraîchis ma pièce ce soir avec de la ventilation naturelle ? »_

Ton : weather app rencontre jouet de physique. Inspiration Bret Victor (dynamic medium). Pas un outil d'audit énergétique.

## L'idée centrale

Rendre visible la chose contre-intuitive : **l'air est une plume, les murs sont un camion**. Tout découle de là.

Ancres d'ordre de grandeur (pièce 4×5×2.4 m, briques) :

- Masse d'air : **~58 kg**
- Masse active des murs (peau de 12 cm) : **~10 000 kg**
- Rapport : **~200×**
- Énergie à extraire pour ΔT=10°C : **~23 kWh** (≈ une journée de frigo)
- Constante de temps τ avec ventilation correcte : **~5 h**

## Physique (volontairement simple)

1. **Épaisseur active** (profondeur de pénétration sur cycle 24h) :
   `d = √(α·T/π)` → ~12 cm pour brique, ~7 cm bois, ~15 cm béton.

2. **Masse active** : `m = ρ · A_murs · d`. Capacité thermique : `C = m·c`.

3. **Couche limite** : seuil ~1 m/s le long des parois.
   - Lent (laminaire) : h ≈ 2 W/m²·K
   - Turbulent : h ≈ 10 W/m²·K
   - Facteur 5 — c'est le levier le plus contre-intuitif.

4. **Décroissance exponentielle** :
   `T_int(t) = T_ext + (T_int₀ - T_ext) · exp(-t/τ)`
   avec `τ = (m·c) / (h·A)`.

5. **T_ext variable** (plus tard) : ODE simple, Euler explicite pas de 5 min,
   `dT_int/dt = (T_ext(t) - T_int) / τ`.

## Entrées (minimales)

- Pièce : a, b, h (3 nombres)
- Type de mur : léger (plâtre/bois) / brique / pierre-béton
- T° intérieure actuelle
- T° extérieure de la nuit

## Sorties

- Débit d'air nécessaire (m³/h) et renouvellement d'air (vol/h)
- Équivalent en ventilateurs concrets (voir échelle ci-dessous)
- Courbe T_int(t) sur la nuit
- Valeurs physiques brutes toujours visibles

## Garder visible les valeurs physiques

Principe : ne jamais cacher derrière une jauge. Toujours afficher :

```
Murs actifs
  Masse :           9 880 kg
  Capacité therm. : 8 300 kJ/K     (= m·c)
  Surface :         43 m²
  Épaisseur active : 12 cm
  Énergie à extraire (ΔT=10°) : 83 MJ ≈ 23 kWh

Air de la pièce
  Volume : 48 m³
  Masse :  58 kg
  Capacité therm. : 58 kJ/K
```

Visuellement : barres côte à côte pour `masse (kg)` et `capacité thermique (kJ/K)`. Les rapports diffèrent (c_brique ≠ c_air) — ça se voit.

## Échelle de ventilateurs (ordres de grandeur)

À montrer comme une frise, du plus faible au plus fort :

| Engin                                      | Débit ≈      |
| ------------------------------------------ | ------------ |
| Aération naturelle (fenêtre entrouverte)   | ~30 m³/h     |
| VMC simple flux (extraction salle de bain) | ~90 m³/h     |
| 1 ventilo PC 140mm                         | ~90 m³/h     |
| Ventilateur de table                       | ~500 m³/h    |
| Brasseur d'air plafond                     | ~2 000 m³/h  |
| Brasseur drum 30 cm (type Domair)          | ~3 300 m³/h  |
| Extracteur gaine industriel                | ~5 000+ m³/h |

Le calcul affiche le débit cible et **surligne où on tombe** sur cette frise. Ça ancre les m³/h dans des objets concrets.

## Décomposition mur par mur

**Pas dans le MVP.** Mais préparer le code pour l'ajouter.

La question physique utile n'est pas « sol / plafond / murs » mais **« quelles surfaces ont un puits froid de l'autre côté ? »** :

- Sol dalle béton : couplé au sol froid → aide
- Plafond toit : ennemi (chaud toute la nuit)
- Murs extérieurs sud/ouest : cuits toute la journée
- Murs intérieurs : pas de ΔT, ne participent quasi pas

V2 : toggle par surface (`extérieur / intérieur / sol / toit`) qui ajuste l'aire effective et α/c selon le matériau.

## T_ext variable

**Pas dans le MVP.** Roadmap :

1. **MVP** : T_ext constante (un seul nombre saisi).
2. **V2** : scénario sinusoïdal — `T_ext(t) = T_moy + A·cos(2π(t-t_pic)/24)`, deux sliders (amplitude, heure de pic). C'est le jouet Bret Victor — on tire l'amplitude, on voit l'intérieur s'amortir et déphaser.
3. **V3** : Open-Meteo (gratuit, sans clé), liste de villes en dur (Paris, Lyon, Marseille, Toulouse, Bordeaux, Lille, Strasbourg, Nantes, Montpellier, Nice…). Endpoint `hourly=temperature_2m`, prochaines 24h.

Bonus pédagogique V2/V3 : indiquer **quand ouvrir/fermer** — fan ON quand T_ext < T_int, OFF sinon.

## UI mobile (vertical, pile)

```
┌──────────────────────┐
│ Inertie nocturne     │
├──────────────────────┤
│ Pièce                │
│ 4m × 5m × 2.4m  [✎]  │
│                      │
│ Murs : ◯léger        │
│        ●brique       │
│        ◯pierre       │
├──────────────────────┤
│ [SVG : coupe pièce,  │
│  peau active brille] │
├──────────────────────┤
│ Air     │ Murs       │
│ 58 kg   │ 9 880 kg   │
│ ▏       │ ███████    │
├──────────────────────┤
│ T_int : 28°C  [slider]│
│ T_ext : 18°C  [slider]│
├──────────────────────┤
│ Ventilateur :        │
│ ▬▬▬●────  500 m³/h   │
│ ≈ ventilo de table   │
│                      │
│ τ = 5.4 h            │
│ ┌────────────────┐   │
│ │╲___            │   │ ← T_int(t)
│ │    ╲___        │   │
│ └────────────────┘   │
│                      │
│ Dans 6h : 22.3°C     │
│ Énergie sortie : 18 kWh│
└──────────────────────┘
```

Cibles tap larges, sliders plutôt que knobs, tout en français, unités SI.

## Stack

**Vanilla JS.** Un seul fichier HTML, un peu de CSS, SVG inline pour les graphes. ~300 lignes. Pas de build, pas de framework, pas de dépendances.

Pourquoi pas Svelte : pour cette taille (3 sliders, 2 courbes, ~10 nombres dérivés), le reactivity à la main est trivial — `recompute()` sur chaque `input`. Svelte ajoute un build step pour zéro gain. À reconsidérer si V2/V3 fait gonfler les états.

Hébergement : statique pur, n'importe quel S3 / Pages / Netlify.

## Plan d'itérations

**v0** — fait ✅ : un fichier HTML, sliders partout, mobile-first.

- 3 sliders pièce + sélecteur matériau
- 2 sliders température (T_int, T_ext constants)
- 1 slider ventilateur en m³/h
- Calculs : épaisseur active, masses, τ, énergie
- Courbe exponentielle T_int(t) sur 12h
- Frise des ventilateurs avec marqueur
- Tous les nombres physiques affichés

Décisions prises pendant l'implémentation :

- `A_walls` = murs verticaux seuls (pas sol/plafond) pour coller aux ancres du doc. Sol/plafond reviennent en V2 via la décomposition par surface.
- Régime laminaire/turbulent piloté par le taux de renouvellement (≥ 5 vol/h → turbulent), pas par une vitesse fictive d'air. Proxy grossier — la vraie vitesse près des parois dépend de l'orientation du brasseur. À raffiner avec l'encart « couche limite » de V1.

**v0.1** — fait ✅ : ergonomie tablette.

- Layout 2 colonnes (entrées à gauche, valeurs dérivées à droite), pile à <760 px
- Sliders remplacés par des chips presets + popup « Personnalisé » pour pièce, matériau, ventilation
- Chaque chip matériau affiche `ρ` et `d` inline
- Valeurs dérivées affichées en regard du titre de chaque bloc (taille → V, matériau → peau, T → ΔT, ventilation → m³/h + vol/h)
- Températures restent en sliders (continu, pas de preset forcé)
- Composant popup générique réutilisable

**v0.2** — fait ✅ : physique honnête + ergonomie.

- Contraste augmenté (`--dim` → couleur plus claire) pour lisibilité
- Sliders de température alignés (labels élargis à 150 px)
- **Ventilateurs en single-select** (multiselect essayé puis abandonné — trop d'états, UX confuse, bugs sur le toggle/custom).
- **Frise à double axe** : m³/h en haut, **m/s avec étiquettes Beaufort indoor** en bas (calme / à peine perceptible / brise légère / vent agréable / papiers s'envolent). Marqueur bleu = débit, marqueur orange = vitesse d'air estimée près des parois.
- **Modèle de convection refait** :
  - chaque preset ventilateur porte une `v_typ` (m/s, vitesse typique près des parois)
  - dilution par `(V_ref / V)^(1/3)` — une plus grande pièce dissipe le brassage (V_ref = 48 m³)
  - `h = 5.7 + 3.8·v` (corrélation Jürges, simple et continue), `h → 5.7` quand `v → 0` (convection naturelle)
- **Sanity checks console** : 6 assertions vérifient les ordres de grandeur (τ par défaut 4–10 h, plus grande pièce → τ plus long, brasseur plafond → τ ≈ 5 h, fenêtre seule → τ > 8 h, pierre > léger, ratio masse air/murs 100–300×). À ouvrir avec la console développeur.

Décisions à noter :

- L'ancien proxy `ACH ≥ 5 vol/h → turbulent` ne respectait pas l'intuition « plus grande pièce → moins efficace ». Le nouveau modèle traite `v_air` comme une **caractéristique du brassage**, pas du débit pur — un brasseur plafond à 2000 m³/h fait plus de brassage qu'une fenêtre à 2000 m³/h.
- Les valeurs `v_typ` par preset sont des **estimations à calibrer**. C'est le maillon faible.
- Au défaut (table fan + brique standard), τ ≈ 6.5 h. Avec un brasseur plafond, τ ≈ 4.8 h. Cohérent avec le doc.

**V1** — peaufinage visuel :

- Coupe SVG de la pièce avec peau active animée
- Barres masse / capacité thermique côte à côte
- Petit encart « couche limite » : laminaire vs turbulent, le saut de h ×5
- Icônes SVG sur les chips (matériaux, ventilateurs) — inline, single-file
- Bloc « coût » : puissance ventilateur (W) → kWh/nuit → € (tarif éditable, défaut 0,25 €/kWh)

**V2** — T_ext sinusoïdale :

- Sliders amplitude + heure de pic
- ODE Euler explicite
- Indicateur ouvrir/fermer fenêtre
- Préparer hooks pour décomposition par surface (sol, plafond, murs ext/int)

**V3** — données réelles :

- Liste de villes en dur
- Open-Meteo fetch
- État partageable via URL

**V4** (peut-être) — décomposition mur par mur, matériau par surface.

## Idées en attente

- **Coût électrique** : chaque preset ventilateur a une puissance typique (VMC ~20 W, brasseur plafond ~70 W, drum ~150 W). Affiche kWh sur la nuit + € au tarif courant. Trois lignes max sous la frise, pas une section.
- **Icônes/pictogrammes** sur les chips : un par matériau (brique empilée, planche, pierre) et un par ventilateur (fenêtre, gaine VMC, ventilo de table, pales plafond, drum, extracteur). SVG inline pour rester en un seul fichier.
- **Mode « explication »** avec formules au clic (τ → `τ = m·c/h·A`). TBD — peut-être un toggle global plutôt que des popups par valeur.
- **Vérification des constantes matériaux** : les triplets `(ρ, c, α)` sont des valeurs textbook raisonnables, à recouper avec une source sérieuse (CSTB, ADEME).
- **Calibration des `v_typ` des ventilateurs** : valeurs actuelles à l'œil (fenêtre 0.05, VMC 0.10, table 0.50, brasseur plafond 1.20, drum 1.80, extracteur 2.50 m/s). Idéalement mesurer à l'anémomètre, ou se rabattre sur des plaques techniques constructeur.
- **Validation contre un cas de référence** : trouver un papier ou cas instrumenté (ventilation nocturne, géométrie connue, courbe T_int(t) mesurée) et vérifier que notre τ est dans 30 % de la mesure. C'est la vraie épreuve.
- **Modèle de convection** : la corrélation Jürges (`h = 5.7 + 3.8·v`) est valable jusqu'à ~5 m/s. Au-delà, autre régime. La sommation quadratique des `v_typ` suppose des sources indépendantes — un brasseur plafond + un ventilo de table dans la même pièce ne sont pas réellement indépendants. Approximation.

## Questions ouvertes

- Nommer le projet ? `cool_inertia` est sympa en interne, mais titre français pour l'UI ? « Inertie nocturne » / « Fraîcheur de nuit » / « Ventiler malin » ? → **« Inertie nocturne »**
- Pour la frise ventilateurs, garder les marques (Domair, Arctic) ou rester génériques ? → **génériques**
- Mode « explication » avec les formules visibles (clic sur τ → popup `τ = m·c/h·A`) ou rester silencieux ? TBD
- Cible principale : mobile ou tablette/desktop ? → **tablette** (touch + densité d'info), avec fallback mobile en pile
