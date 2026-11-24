# VisualSearch — Content-Based Image Retrieval (CBIR)

> **Application web de gestion d'images, d'extraction de caractéristiques visuelles et de recherche par similarité avec retour de pertinence Re-weighting Type-1.**

VisualSearch est une application de vision par ordinateur qui recherche des images à partir de leur contenu visuel (couleur et texture), et non uniquement à partir de leur nom ou de mots-clés. Elle associe une galerie web, une API REST indépendante de calcul des descripteurs et un moteur de recherche CBIR avec retour de pertinence interactif.

Ce dépôt contient le **code source**, les tests et la documentation. Les images GHIM-10K, les fichiers originaux de l'utilisateur, la base SQLite et le stockage généré sont volontairement exclus de l'archive Git/ZIP.

---

## Sommaire

1. [Objectifs et périmètre](#1-objectifs-et-périmètre)
2. [Fonctionnalités](#2-fonctionnalités)
3. [Architecture](#3-architecture)
4. [Technologies](#4-technologies)
5. [Structure du dépôt](#5-structure-du-dépôt)
6. [Prérequis](#6-prérequis)
7. [Installation sous Windows](#7-installation-sous-windows)
8. [Installation sous Linux/macOS](#8-installation-sous-linuxmacos)
9. [Configurer les données GHIM-10K](#9-configurer-les-données-ghim-10k)
10. [Conserver une base déjà indexée](#10-conserver-une-base-déjà-indexée)
11. [Lancement de l'application](#11-lancement-de-lapplication)
12. [Guide utilisateur](#12-guide-utilisateur)
13. [API REST descripteurs](#13-api-rest-descripteurs)
14. [Extraction des caractéristiques](#14-extraction-des-caractéristiques)
15. [Recherche CBIR](#15-recherche-cbir)
16. [Re-weighting Type-1](#16-re-weighting-type-1)
17. [Évaluation expérimentale](#17-évaluation-expérimentale)
18. [Tests automatisés](#18-tests-automatisés)
19. [Sécurité et bonnes pratiques](#19-sécurité-et-bonnes-pratiques)
20. [Dépannage](#20-dépannage)
21. [Limites connues et évolutions](#21-limites-connues-et-évolutions)
22. [Références](#22-références)

---

## 1. Objectifs et périmètre

Le projet répond aux deux volets du mini-projet de recherche d'images.

### Tâche 1 — Gestion de galerie et descripteurs

- Authentification des utilisateurs.
- Import, consultation, téléchargement et suppression d'images.
- Opérations par lot : import multiple, téléchargement ZIP, déplacement et suppression multiple.
- Organisation des images dans une hiérarchie de catégories.
- Création d'images dérivées par transformation, sans écraser l'original.
- Consommation d'une API REST Python développée avec Flask et Flask-RESTful.
- Calcul et visualisation de descripteurs de couleur et de texture.

### Tâche 2 — Recherche d'images similaires

- Sélection d'une image requête.
- Recherche simple par distance entre vecteurs visuels.
- Retour de pertinence interactif.
- Ré-estimation des poids par **Re-weighting Type-1**.
- Comparaison expérimentale des résultats à plusieurs itérations.

### Positionnement scientifique

Le système appartient à la famille des méthodes **Content-Based Image Retrieval (CBIR)**. Il représente chaque image par un vecteur numérique de caractéristiques de bas niveau, puis compare ces vecteurs dans un espace commun.

Il ne s'agit pas d'un système de reconnaissance sémantique par réseau neuronal : les descripteurs sont explicitement calculés à partir des pixels. Cette approche rend les calculs et les décisions du moteur interprétables et permet d'étudier directement l'influence de la couleur et de la texture.

---

## 2. Fonctionnalités

### Gestion de la galerie

- Inscription, connexion et déconnexion.
- Import d'une ou plusieurs images.
- Contrôle du type de fichier et vérification du contenu image.
- Vignettes pour accélérer l'affichage de la galerie.
- Recherche par nom, pagination et filtres par catégorie.
- Catégories imbriquées avec fil d'Ariane.
- Création, renommage et suppression de catégories.
- Déplacement de plusieurs images.
- Téléchargement individuel ou en archive ZIP.
- Suppression individuelle ou multiple.
- Page de détail avec dimensions, taille, catégorie et image source éventuelle.

### Transformations

Les opérations disponibles sont définies dans `webapp/services/transforms.py`. Elles comprennent notamment le recadrage, le redimensionnement, la rotation, les miroirs, les niveaux de gris, le flou, l'accentuation, la luminosité, le contraste, la saturation et le négatif.

Chaque transformation produit un **nouveau fichier**. L'original est conservé et la relation parent/enfant est stockée dans la base de données. Les descripteurs de l'image transformée sont recalculés via le service de descripteurs.

### Analyse visuelle

La page de détail présente :
- l'histogramme de couleur HSV ;
- les moments de couleur ;
- les couleurs dominantes ;
- les propriétés GLCM ;
- l'histogramme LBP.

### Recherche et feedback

L'utilisateur lance une recherche simple, marque les résultats qu'il juge pertinents, puis déclenche le retour de pertinence. Les poids appris sont affichés pour les blocs de caractéristiques.

### Tableau de bord

La vue d'ensemble présente le volume d'images, le nombre d'images indexées, les catégories, l'espace disque utilisé, les derniers ajouts et l'état de l'API.

---

## 3. Architecture

```text
                         NAVIGATEUR
                    HTML / CSS / JavaScript
                              |
                              | HTTP
                              v
                  APPLICATION WEB — Flask
                  Authentification / CSRF
                  Galerie / Catégories
                  Upload / Transformations
                  Recherche / Dashboard
                       |             |
                       | SQL         | HTTP multipart
                       v             v
                  SQLite       API REST Flask
                  users        Flask-RESTful
                  categories        |
                  images            v
                  descriptors   descriptors.py
                       |        Couleur + Texture
                       |
                       v
              STOCKAGE SUR DISQUE
              Images originales
              Images transformées
              Vignettes
```

### Pourquoi séparer l'API ?

La consigne demande de consommer une API REST écrite en Python avec Flask et Flask-RESTful. Le calcul des caractéristiques est donc isolé du serveur web.

Avantages :
- le service de calcul peut être testé indépendamment ;
- un autre client peut consommer les mêmes endpoints ;
- le serveur web ne duplique pas le code d'extraction ;
- les deux services peuvent être lancés et surveillés séparément.

Lors d'un import web, l'application envoie les images à l'API. Si l'API est indisponible, les images restent stockées et pourront être indexées ultérieurement avec l'action de recalcul des descripteurs manquants.

### Stockage

- **SQLite** conserve les utilisateurs, catégories, métadonnées et descripteurs.
- Les fichiers image ne sont pas stockés en BLOB dans SQLite : ils sont conservés sur le disque.
- Les vecteurs de caractéristiques sont enregistrés en BLOB `float32`.
- Les détails nécessaires à l'affichage sont enregistrés en JSON.

### Moteur de recherche

Le moteur charge les vecteurs d'un utilisateur dans une matrice NumPy et met cette matrice en cache. Le cache est reconstruit lorsque le nombre, l'identifiant maximal ou la somme des identifiants des descripteurs change.

Pour une base d'environ 10 000 images et 97 dimensions, une recherche exhaustive est raisonnable et évite d'introduire une infrastructure d'indexation approximative inutile pour ce périmètre.

---

## 4. Technologies

| Domaine | Technologie | Utilisation |
|---|---|---|
| Langage | Python | Backend et traitement d'images |
| Backend web | Flask | Application web |
| API | Flask-RESTful | Endpoints de descripteurs |
| Image | Pillow | Lecture, conversion et transformations |
| Calcul scientifique | NumPy | Vecteurs, normalisation et distances |
| Vision par ordinateur | scikit-image | GLCM et LBP |
| Machine learning classique | scikit-learn | K-Means pour les couleurs dominantes |
| Base de données | SQLite | Métadonnées et vecteurs |
| Frontend | HTML, CSS, JavaScript | Interface et feedback interactif |
| Graphiques | Chart.js (embarqué) | Visualisation des histogrammes |

---

## 5. Structure du dépôt

```text
VisualSearch-CBIR/
├── api/                    API REST (Flask-RESTful)
│   ├── app.py              fabrique create_app(), clé d'API, limites
│   └── descriptors.py      calcul pur des descripteurs (sans Flask)
├── webapp/
│   ├── __init__.py         fabrique create_app(profil)
│   ├── config.py           profils development / production / testing
│   ├── db.py               schéma, migrations (user_version), requêtes hiérarchiques
│   ├── security.py         CSRF, en-têtes HTTP/CSP, limiteur de connexions
│   ├── core.py             utilitaires partagés (login_required, own_image…)
│   ├── blueprints/         auth · gallery · images · search
│   ├── services/           api_client · imagestore · transforms · retrieval
│   ├── templates/          pages Jinja2
│   └── static/             CSS, JS, Chart.js et polices embarqués (aucun CDN)
├── scripts/                index_dataset.py · evaluate.py · make_figures.py
├── tests/                  suite pytest (144 tests)
├── docs/                   build_report.py (rapport Word/PDF) · diagrams.py
├── wsgi.py · run_all.py    points d'entrée
├── Dockerfile · docker-compose.yml · Makefile · pyproject.toml
├── requirements.txt · requirements-dev.txt · .env.example
└── .github/workflows/ci.yml
```

Les dossiers `webapp/instance/`, `data/`, `results/`, les environnements virtuels et les caches sont exclus du dépôt.

---

## 6. Prérequis

- Python 3.10 ou supérieur.
- pip.
- Environ 1 à 2 Go d'espace libre pour le code, l'environnement et les dépendances (hors dataset et images indexées).
- Pour indexer 10 000 images : espace disque supplémentaire selon la taille des fichiers et des vignettes.
- Une connexion Internet est nécessaire à l'installation initiale des dépendances. Chart.js et les polices sont embarqués : l'application fonctionne ensuite hors ligne.

**Configuration matérielle modeste :** l'indexation est parallèle. Sur une machine disposant de 8 Go de RAM, commencer avec deux workers (`--workers 2`) plutôt qu'avec tous les cœurs CPU. Le nombre de workers doit être choisi selon la mémoire disponible.

---

## 7. Installation sous Windows

Ouvrir PowerShell dans le dossier du projet :

```powershell
cd chemin\vers\photo_gallery

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si PowerShell bloque l'activation du venv, utiliser :

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Configurer une clé de session de développement :

```powershell
$env:SECRET_KEY = "remplacer-par-une-cle-aleatoire-longue"
```

La variable est valable dans le terminal courant. Pour un déploiement, utiliser un gestionnaire de secrets ou une variable d'environnement persistante.

---

## 8. Installation sous Linux/macOS

```bash
cd photo_gallery
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

export SECRET_KEY="replace-with-a-long-random-secret"
```

---

## 9. Configurer les données GHIM-10K

Le dataset GHIM-10K est disponible sur Kaggle :

<https://www.kaggle.com/datasets/mcpython/ghim-10k>

Après téléchargement et extraction, repérer le dossier qui contient réellement les images. Exemple d'organisation :

```text
photo_gallery/
├── data/
│   └── ghim-10k/
│       ├── 0.jpg
│       ├── 1.jpg
│       ├── ...
│       └── 9999.jpg
└── ...
```

Le dossier peut être différent selon la structure de l'archive Kaggle. Il faut passer au script le dossier qui contient les images, directement ou dans ses sous-dossiers.

### Vérifier le contenu avant indexation

Sous PowerShell :

```powershell
Get-ChildItem .\data -Recurse -File |
  Where-Object { $_.Extension -match '^\.(jpg|jpeg|png|bmp|gif|webp|tif|tiff)$' } |
  Measure-Object
```

Pour visualiser quelques noms :

```powershell
Get-ChildItem .\data -Recurse -File |
  Where-Object { $_.Extension -match '^\.(jpg|jpeg|png|bmp|webp|tif|tiff)$' } |
  Select-Object -First 20 FullName
```

**Important concernant les catégories :**

- Si le dataset contient des sous-dossiers représentant des classes, le script reprend ces dossiers comme catégories.
- Si les images sont dans un seul dossier plat, le script peut créer des catégories par groupes de 500 images avec `--group-size 500`.
- Ce découpage par numéro n'est valide comme vérité terrain que si l'ordre des noms de fichiers correspond réellement aux classes du dataset. Vérifier les annotations et l'organisation de l'archive avant de l'utiliser pour une évaluation scientifique.

Ne pas considérer automatiquement `Classe 00`, `Classe 01`, etc. comme des labels sémantiques si le dataset ne garantit pas cette correspondance.

### Indexation d'un petit échantillon

Avant les 10 000 images, tester avec 100 ou 200 fichiers :

```powershell
python scripts/index_dataset.py --folder .\data\ghim-10k --username admin --password "motdepasse" --limit 200 --workers 2
```

### Indexation complète

```powershell
python scripts/index_dataset.py --folder .\data\ghim-10k --username admin --password "motdepasse" --workers 2
```

Le script :
1. parcourt le dossier ;
2. ignore les fichiers déjà importés (chemin relatif déjà présent pour l'utilisateur) ;
3. calcule les descripteurs en parallèle ;
4. copie les images dans le stockage de l'application ;
5. génère les vignettes ;
6. enregistre les métadonnées et le vecteur ;
7. effectue des commits périodiques.

Le script est relançable. Il ne faut pas lancer deux indexations simultanées sur la même base SQLite.

### Options

```powershell
python scripts/index_dataset.py --help
```

| Option | Description |
|---|---|
| `--folder` | Dossier source des images (obligatoire) |
| `--username` | Compte auquel rattacher les images |
| `--password` | Mot de passe utilisé uniquement si le compte doit être créé |
| `--group-size` | Taille des groupes si le dossier est plat ; `0` désactive ce regroupement |
| `--workers` | Nombre de processus de calcul |
| `--limit` | Limite temporaire pour un test |

Le nom de stockage généré à partir du chemin relatif inclut un identifiant déterministe pour éviter les collisions entre deux fichiers portant le même nom dans des dossiers différents.

---

## 10. Conserver une base déjà indexée

Si les 10 000 images ont déjà été indexées dans une ancienne version du projet, il n'est normalement **pas nécessaire de les recalculer** pour utiliser cette version : le schéma SQLite et la dimension du vecteur restent compatibles (la version 2 du schéma n'ajoute que des index, appliqués automatiquement au démarrage).

Avant de remplacer l'ancien dossier du projet :

1. arrêter les serveurs ;
2. sauvegarder le dossier `webapp/instance/` de l'ancien projet ;
3. conserver également le dossier `data/` ;
4. décompresser la nouvelle version dans un nouveau dossier ;
5. recopier `webapp/instance/` dans le nouveau projet, en conservant son contenu ;
6. ne pas exécuter le script d'indexation si la base et les images sont déjà présentes ;
7. lancer l'application et vérifier la galerie.

Exemple de structure après restauration :

```text
photo_gallery/
├── data/
│   └── ghim-10k/
├── webapp/
│   └── instance/
│       ├── gallery.db
│       └── storage/
│           └── ...
└── ...
```

Les chemins de configuration peuvent être modifiés avec `GALLERY_DB` et `GALLERY_STORAGE`. Les chemins par défaut sont définis dans `webapp/config.py`.

**Sauvegarde recommandée :** copier ensemble la base SQLite et le stockage d'images pendant que l'application est arrêtée. Copier uniquement `gallery.db` ne suffit pas, car les fichiers image sont stockés séparément.

---

## 11. Lancement de l'application

### Développement

```bash
python run_all.py          # API (5001) + application (5000) dans un seul terminal
```

ou séparément :

```bash
python -m api.app                          # terminal 1 : API sur http://127.0.0.1:5001
python -m flask --app wsgi:app run         # terminal 2 : application sur http://127.0.0.1:5000
```

Vérifier l'API : <http://127.0.0.1:5001/api/health> (réponse : `status: ok`, `vector_dim: 97`).
Sonde de l'application : <http://127.0.0.1:5000/healthz>.

> `python -m api.app` fonctionne aussi, mais `python -m api.app` (depuis la racine) est la forme recommandée.

### Production

```bash
export APP_ENV=production
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export DESCRIPTOR_API_KEY=$(python -c "import secrets; print(secrets.token_hex(16))")

gunicorn -w 2 -b 127.0.0.1:5001 --timeout 300 "api.app:create_app()"   # API
gunicorn -w 2 --threads 4 -b 0.0.0.0:5000 wsgi:app                       # application
```

Sous Windows : `waitress-serve --port=5000 wsgi:app`.

### Docker

```bash
SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))") \
DESCRIPTOR_API_KEY=$(python -c "import secrets;print(secrets.token_hex(16))") \
docker compose up --build
```

L'API n'est pas exposée hors du réseau Docker ; la base et les images sont dans le volume `gallery-data` (à sauvegarder ensemble). Derrière un proxy HTTPS, définir `SESSION_COOKIE_SECURE=true`.

### Configuration

Un fichier `.env` placé à la racine est chargé automatiquement (voir `.env.example`). En mode `production`, l'application **refuse de démarrer** sans `SECRET_KEY` d'au moins 32 caractères.

---

## 12. Guide utilisateur

### 12.1 Créer un compte

Ouvrir l'application et sélectionner l'inscription. Les mots de passe sont hachés avant stockage.

### 12.2 Tableau de bord

La page Vue d'ensemble fournit une synthèse de la collection :
- nombre total d'images ;
- nombre d'images disposant de descripteurs ;
- nombre de catégories ;
- volume total des fichiers ;
- ajouts récents ;
- disponibilité de l'API.

### 12.3 Importer des images

Dans la galerie :
1. sélectionner un ou plusieurs fichiers ;
2. choisir éventuellement une catégorie ;
3. cliquer sur Importer ;
4. consulter le message de résultat.

Si l'API n'est pas disponible, les fichiers restent présents mais sans vecteur de caractéristiques. Après avoir relancé l'API, utiliser l'action « Calculer les descripteurs manquants ».

### 12.4 Organiser les images

Créer une catégorie racine ou une sous-catégorie. La navigation latérale affiche l'arbre. Sélectionner plusieurs images pour les déplacer vers une catégorie ou les supprimer.

### 12.5 Transformer une image

Ouvrir une image, choisir une transformation et ses paramètres, puis valider. Le résultat est ajouté comme nouvelle image, lié à son parent et analysé à nouveau.

### 12.6 Consulter les descripteurs

La page de détail affiche les informations du fichier et les représentations calculées. Les histogrammes aident à comprendre la distribution des caractéristiques.

### 12.7 Recherche simple

Depuis la galerie ou la page de détail, choisir une image comme requête puis lancer « Recherche simple ». Les images les plus proches sont classées en fonction de la distance calculée.

### 12.8 Retour de pertinence

1. lancer la recherche simple ;
2. cliquer sur les images que l'on juge pertinentes (elles sont marquées en vert) ;
3. cliquer sur « Retour de pertinence » ;
4. observer les nouveaux résultats et les poids relatifs ;
5. répéter si nécessaire.

Le retour de pertinence nécessite au moins une image pertinente supplémentaire à l'image requête. La requête est incluse dans l'ensemble des images pertinentes utilisé pour estimer la nouvelle requête.

---

## 12 bis. Design de l'interface

- **Identité** : l'application travaille sur la couleur, le spectre (roue de teintes) est donc sa signature : logo, graphique « Les couleurs de votre galerie » (teintes réelles calculées depuis les histogrammes HSV), histogrammes colorés avec les teintes qu'ils représentent.
- **Thèmes clair et sombre** (bouton dans la barre latérale, choix mémorisé ; suit la préférence du système par défaut).
- **Typographie** Sora (titres) et DM Sans (texte), embarquées dans `webapp/static/fonts/`.
- **Galerie** : zone de dépôt par glisser-déposer, tri (récentes, anciennes, nom, taille), sélection multiple avec compteur.
- **Recherche** : résultats sélectionnables à la souris ou au clavier, barre de similarité, poids appris affichés par famille de descripteurs.
- **Responsive** (barre latérale compacte sur mobile), focus clavier visible, animations désactivées si `prefers-reduced-motion`.
- Les jetons de design (couleurs, rayons, polices) sont regroupés en tête de `webapp/static/style.css`.

---

## 13. API REST descripteurs

Base URL locale : `http://127.0.0.1:5001`.

| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Vérifier l'état du service et la dimension du vecteur |
| POST | `/api/descriptors` | Calcul complet : couleur, texture et vecteur |
| POST | `/api/descriptors/color` | Descripteurs couleur uniquement |
| POST | `/api/descriptors/texture` | Descripteurs texture uniquement |

Les endpoints POST attendent `multipart/form-data` avec un champ `images` répétable.

### Exemple : calcul complet

```bash
curl -X POST \
  -F "images=@sample.jpg" \
  http://127.0.0.1:5001/api/descriptors
```

### Exemple : plusieurs images

```bash
curl -X POST \
  -F "images=@image1.jpg" \
  -F "images=@image2.png" \
  http://127.0.0.1:5001/api/descriptors
```

### Exemple de structure de réponse

```json
{
  "count": 1,
  "results": [
    {
      "filename": "sample.jpg",
      "color": {
        "histogram": {
          "bins": {"h": 8, "s": 3, "v": 3},
          "values": ["... 72 valeurs ..."]
        },
        "moments": {"H": {}, "S": {}, "V": {}},
        "dominant_colors": []
      },
      "texture": {
        "glcm": {},
        "lbp_histogram": ["... 10 valeurs ..."]
      },
      "vector": ["... 97 valeurs ..."]
    }
  ]
}
```

Une erreur de lecture sur un fichier ne bloque pas nécessairement le lot complet : l'entrée concernée contient un champ `error`. Une requête sans fichier reçoit un statut HTTP 400.

---

## 14. Extraction des caractéristiques

Les images sont converties en RGB et réduites de manière proportionnelle : le plus grand côté est limité à 256 pixels. Les descripteurs sont calculés sur cette représentation réduite afin de limiter le coût de calcul.

### 14.1 Histogramme de couleur HSV — 72 dimensions

L'image est convertie dans l'espace HSV :
- H : teinte ;
- S : saturation ;
- V : valeur/luminosité.

La quantification utilise :
- 8 intervalles pour H ;
- 3 intervalles pour S ;
- 3 intervalles pour V.

Nombre total de bins :

\[
8 \times 3 \times 3 = 72
\]

L'histogramme est normalisé par le nombre de pixels comptabilisés. Sa somme vaut donc 1, ce qui le rend indépendant de la résolution de l'image.

### 14.2 Moments de couleur — 9 dimensions

Pour chacun des trois canaux H, S et V, le système calcule :
- la moyenne \(\mu\) ;
- l'écart-type \(\sigma\) ;
- l'asymétrie standardisée (*skewness*).

\[
\mu = \frac{1}{N}\sum_{j=1}^{N}x_j
\]

\[
\sigma = \sqrt{\frac{1}{N}\sum_{j=1}^{N}(x_j-\mu)^2}
\]

\[
skewness = \frac{1}{N}\sum_{j=1}^{N}
\left(\frac{x_j-\mu}{\sigma}\right)^3
\]

Lorsque l'écart-type est nul ou quasi nul, l'asymétrie est fixée à zéro afin d'éviter une division par zéro.

On obtient 3 canaux × 3 moments = 9 valeurs. La teinte est une grandeur circulaire ; son traitement comme variable linéaire constitue une approximation de cette représentation.

### 14.3 Couleurs dominantes — affichage

Les couleurs dominantes sont estimées avec K-Means sur les pixels RGB. Le calcul utilise un échantillon de pixels lorsque l'image est grande et une graine fixe pour améliorer la reproductibilité.

Jusqu'à cinq centres sont affichés avec :
- leur code RGB ;
- leur code hexadécimal ;
- leur proportion approximative dans l'échantillon.

Ce bloc est **affiché séparément** et n'est pas concaténé au vecteur de recherche. Les centres K-Means n'ont pas d'ordre sémantique stable d'une image à l'autre ; les comparer directement composante par composante serait donc délicat.

### 14.4 GLCM — 6 dimensions

La matrice de co-occurrence des niveaux de gris décrit les fréquences de paires de niveaux de gris séparés par une distance et une orientation données.

Paramètres :
- conversion en niveaux de gris ;
- quantification sur 32 niveaux ;
- distance 1 ;
- quatre orientations : 0°, 45°, 90° et 135° ;
- matrice symétrique et normalisée ;
- moyenne des propriétés sur les orientations.

Caractéristiques :
1. Contraste : mesure les différences locales de niveaux de gris.
2. Corrélation : mesure la dépendance statistique entre niveaux voisins.
3. Énergie : mesure l'uniformité de la matrice.
4. Homogénéité : favorise les paires proches de la diagonale.
5. Dissimilarité : mesure les écarts absolus.
6. Entropie : mesure la dispersion de la distribution des co-occurrences.

Les petites valeurs négatives d'entropie pouvant provenir des arrondis numériques sont ramenées à zéro.

### 14.5 LBP — 10 dimensions

Le Local Binary Pattern compare le pixel central à ses voisins et encode le motif local obtenu.

Paramètres :
- \(P=8\) voisins ;
- \(R=1\) pixel ;
- méthode `uniform`.

L'histogramme compte les motifs uniformes et est normalisé. Le nombre de bins est \(P+2=10\).

### 14.6 Vecteur global

Le vecteur utilisé par le moteur de recherche est la concaténation :

\[
X = [H_{HSV}^{72}\;|\;M_{HSV}^{9}\;|\;GLCM^{6}\;|\;LBP^{10}]
\]

\[
\boxed{\dim(X)=72+9+6+10=97}
\]

Les couleurs dominantes sont exclues de cette concaténation.

---

## 15. Recherche CBIR

### 15.1 Normalisation

Les caractéristiques n'ont pas toutes la même échelle. Le moteur applique une normalisation Z-score par composante :

\[
Z_{ij} = \frac{X_{ij}-\mu_j}{\sigma_j}
\]

où \(\mu_j\) et \(\sigma_j\) sont calculés sur les images indexées de l'utilisateur.

Si une composante est constante, son écart-type est remplacé par 1 pour éviter la division par zéro.

### 15.2 Équilibrage des blocs

Les blocs n'ont pas le même nombre de dimensions. Pour ne pas laisser l'histogramme de 72 dimensions dominer automatiquement les autres blocs, un poids de base est associé à chaque composante :

\[
b_i = \frac{1}{n_g}
\]

où \(n_g\) est le nombre de dimensions du bloc auquel appartient la composante.

Les poids de base ne sont pas les poids appris par le retour de pertinence : ils servent à équilibrer les blocs.

### 15.3 Distance euclidienne pondérée

Pour deux vecteurs normalisés \(Z_x\) et \(Z_y\), le moteur utilise :

\[
D(Z_x,Z_y)=
\sqrt{
\frac{\sum_i w_i b_i (Z_{x,i}-Z_{y,i})^2}
{\sum_i w_i b_i}
}
\]

- \(w_i\) : poids appris ; initialement égal à 1 ;
- \(b_i\) : poids de base du bloc ;
- la racine carrée conserve l'interprétation d'une distance euclidienne.

La recherche classe les images par distance croissante. L'image requête est exclue des résultats.

---

## 16. Re-weighting Type-1

### 16.1 Principe

Le retour de pertinence (*Relevance Feedback*) permet à l'utilisateur de corriger les résultats du système. Les descripteurs de bas niveau ne correspondent pas toujours exactement à l'intention sémantique de l'utilisateur. Les jugements de pertinence fournissent des exemples supplémentaires pour adapter la recherche.

La technique imposée est **Re-weighting Type-1**.

### 16.2 Notations

À l'itération \(k\) :
- \(R\) : ensemble des images jugées pertinentes, auquel on ajoute l'image requête ;
- \(N_r\) : ensemble des images retournées à l'itération précédente ;
- \(\sigma_{rel,i}^{(k)}\) : écart-type de la composante \(i\) dans \(R\) ;
- \(\sigma_{Nr,i}^{(k)}\) : écart-type de la composante \(i\) dans \(N_r\) ;
- \(\varepsilon\) : petite constante positive.

### 16.3 Formule Type-1

\[
w_i^{(k+1)} =
\frac{\varepsilon+\sigma_{Nr,i}^{(k)}}
{\varepsilon+\sigma_{rel,i}^{(k)}}
\]

Dans l'implémentation :

\[
\varepsilon = 10^{-4}
\]

**Intuition :** si une caractéristique varie peu parmi les images pertinentes, elle peut être discriminante pour le concept recherché. Son poids augmente relativement à la variabilité observée dans les résultats retournés.

### 16.4 Mise à jour de la requête

Le nouveau vecteur requête est la moyenne des vecteurs normalisés pertinents :

\[
Q^{(k+1)} = \frac{1}{|R|}\sum_{x\in R} Z_x
\]

### 16.5 Déroulement

```text
1. L'utilisateur choisit une image requête.
2. Recherche simple avec poids uniformes.
3. Le système retourne les K images les plus proches.
4. L'utilisateur marque les images pertinentes.
5. Le système ajoute ces images aux exemples pertinents cumulés.
6. Il calcule les écarts-types des images pertinentes et retournées.
7. Il met à jour les poids avec la formule Type-1.
8. Il calcule le nouveau vecteur requête.
9. Il relance le classement.
10. L'utilisateur peut répéter le processus.
```

### 16.6 Garde-fous d'implémentation

Certains paramètres pratiques sont nécessaires pour stabiliser le calcul avec peu d'exemples :

1. **Au moins une image pertinente en plus de la requête** : avec une seule observation, l'écart-type des pertinents est nul pour toutes les composantes.
2. **Bornage des poids** : les poids sont limités autour de leur médiane avec `MAX_WEIGHT_RATIO` (20 par défaut). Cela évite qu'une composante reçoive un poids extrême à cause d'un petit échantillon.
3. **Normalisation des poids** : leur somme est ramenée à la dimension du vecteur (97).
4. **Pertinents cumulés** : les images pertinentes sélectionnées aux itérations précédentes restent prises en compte.
5. **Requête exclue du classement** : elle est utilisée pour apprendre, mais ne revient pas comme résultat.
6. **Ensemble retourné vérifié** : le calcul des écarts-types s'appuie sur les identifiants connus du moteur et ignore la requête.

Les garde-fous et le choix de normalisation sont des décisions d'implémentation ; ils doivent être distingués de la formule mathématique Type-1 elle-même dans une présentation scientifique.

### 16.7 Affichage des poids

L'interface présente le poids moyen de chaque bloc relativement à la moyenne globale :
- valeur supérieure à 1 : bloc plus influent que la moyenne ;
- valeur proche de 1 : influence moyenne ;
- valeur inférieure à 1 : influence plus faible que la moyenne.

Ces valeurs sont des indicateurs par bloc, pas les 97 poids individuels.

---

## 17. Évaluation expérimentale

Le script `scripts/evaluate.py` compare la recherche simple et les itérations de retour de pertinence.

### 17.1 Vérité terrain

Le script utilise la catégorie de l'image comme proxy de pertinence : deux images sont considérées pertinentes si elles appartiennent à la même catégorie.

Un utilisateur simulé marque automatiquement comme pertinentes les images retournées appartenant à la catégorie de la requête.

**Limite scientifique :** ce protocole représente un utilisateur idéal qui connaît les labels. Il ne remplace pas des jugements humains. La qualité des résultats dépend directement de la fiabilité des catégories.

### 17.2 Métriques

| Métrique | Interprétation |
|---|---|
| Precision@K | Proportion des K résultats jugés pertinents |
| Recall@K | Proportion des images pertinentes retrouvées dans les K résultats |
| MAP@K | Moyenne de la précision aux rangs où une image pertinente apparaît |
| nDCG@K | Qualité du classement en tenant compte de la position des résultats |

Les métriques sont calculées pour l'itération 0 (recherche simple), puis après chaque itération de feedback.

### 17.2 bis Deux protocoles de comptage

| Protocole | Option | Principe |
|---|---|---|
| Classique | (défaut) | les images déjà jugées pertinentes peuvent réapparaître dans les K résultats ; reflète une interface réelle mais **gonfle** les métriques |
| Strict | `--exclude-judged` | les images déjà jugées sont retirées du classement : seules les images **nouvelles** sont comptées ; c'est le protocole à utiliser pour affirmer que le retour de pertinence améliore le classement |

Rapporter les deux dans le rapport et expliquer l'écart.

### 17.3 Exécuter l'évaluation

Après indexation et vérification des catégories :

```powershell
python scripts/evaluate.py --username admin --queries 200 --scope 25 --iterations 5
```

Paramètres :
- `--username` : compte à évaluer ;
- `--queries` : nombre maximal de requêtes échantillonnées ;
- `--scope` : nombre de résultats K ;
- `--iterations` : nombre d'itérations de feedback ;
- `--seed` : graine de sélection des requêtes ;
- `--exclude-judged` : protocole strict ;
- `--output` : chemin du CSV détaillé (un fichier `*_summary.csv` moyenné par itération est écrit à côté).

Exemple avec sortie personnalisée :

```powershell
python scripts/evaluate.py --queries 500 --scope 25 --iterations 5 --output results/eval_classic.csv
python scripts/evaluate.py --queries 500 --scope 25 --iterations 5 --exclude-judged --output results/eval_strict.csv
python scripts/make_figures.py results/eval_classic_summary.csv results/eval_strict_summary.csv
```

### 17.4 Interpréter les résultats

Le terminal affiche la moyenne des quatre métriques à chaque itération. Le CSV conserve les résultats par requête et par itération afin de permettre des graphiques et une analyse plus détaillée.

Pour le rapport :
1. indiquer le nombre réel de requêtes évaluées ;
2. préciser K et le nombre d'itérations ;
3. décrire la construction des catégories ;
4. présenter les métriques réelles ;
5. comparer l'évolution des métriques ;
6. discuter les cas où le feedback n'améliore pas le classement.

Ne jamais présenter un résultat attendu, simulé ou obtenu sur des données synthétiques comme une mesure réalisée sur GHIM-10K. Le feedback peut aussi faire baisser une métrique sur certaines requêtes : l'analyse doit rester honnête.

---

## 17 bis. Rapport

`docs/build_report.py` génère le rapport (Word + PDF si LibreOffice est installé) : théorie, architecture, implémentation, sécurité, évaluation. Les chiffres d'évaluation sont **lus dans vos CSV** ; sans CSV, la section affiche un encadré « à insérer » au lieu de valeurs inventées.

```bash
python docs/build_report.py --group G6 --authors "Nom1, Nom2, Nom3" --supervisor "Pr. X" --institution "École Y" \
    --results results/eval_classic_summary.csv --strict results/eval_strict_summary.csv --screens docs/screens
```

Captures d'écran attendues dans `docs/screens/` : `dashboard.png`, `gallery.png`, `detail.png`, `search.png`, `feedback.png`.

---

## 18. Tests automatisés

La suite compte **144 tests** (couverture ≈ 94 % de `api/`, `webapp/` et `scripts/`) : descripteurs, API, moteur Type-1 (formule recalculée indépendamment), application web de bout en bout, sécurité, indexation et évaluation.

```bash
pip install -r requirements-dev.txt
pytest                                         # ~15 s
pytest --cov=api --cov=webapp --cov=scripts    # avec couverture
ruff check .                                   # analyse statique
```

Les tests n'ont pas besoin du réseau ni du jeu GHIM-10K : l'appel HTTP vers l'API est remplacé par un appel direct au même code de calcul, et l'API est testée séparément. Ils ne remplacent pas une recette manuelle dans un navigateur sur les 10 000 images.

---

## 19. Sécurité et bonnes pratiques

Mesures implémentées (vérifiées par `tests/test_security.py` et `tests/test_webapp.py`) :

- mots de passe hachés (8 caractères minimum) ; vérification d'un hash factice pour les comptes inconnus ;
- limitation des tentatives de connexion (5 échecs / 5 min par IP + identifiant → HTTP 429) ;
- sessions signées, régénérées à la connexion, cookies `HttpOnly` / `SameSite=Lax` / `Secure` (production), durée 8 h ;
- protection CSRF sur tous les POST, y compris les appels JSON (en-tête `X-CSRF-Token`) ;
- CSP stricte `script-src 'self'` (aucun script inline, Chart.js et polices embarqués), `X-Frame-Options: DENY`, `nosniff`, HSTS en production ;
- échappement Jinja2 et échappement explicite dans le JavaScript (le nom de fichier est une donnée non fiable) ;
- requêtes SQL paramétrées, `LIKE` échappé ;
- fichiers : décodage réel par Pillow, format autorisé, nombre de pixels borné (bombe de décompression), nom de stockage UUID, extension dérivée du format détecté ;
- isolation stricte par utilisateur (404 sur les ressources d'autrui) ;
- redirections limitées aux chemins locaux ;
- API : clé optionnelle `X-API-Key` (comparaison en temps constant), nombre d'images par requête borné ;
- paramètres de transformation bornés (NaN/∞ refusés, 40 Mpx maximum).

### Limites connues

- le limiteur de connexions est en mémoire : avec plusieurs workers, utiliser un stockage partagé (Redis) ;
- SQLite convient à un usage mono-site, pas à une forte charge d'écriture concurrente ;
- il n'y a pas de réinitialisation de mot de passe ni de rôles administrateur.

---

## 20. Dépannage

| Problème | Cause possible | Solution |
|---|---|---|
| `/api/health` inaccessible | API arrêtée ou mauvais port | Lancer `python -m api.app` |
| Bandeau API indisponible | URL incorrecte ou service arrêté | Vérifier `DESCRIPTOR_API_URL` |
| Images sans descripteurs | API arrêtée pendant l'import | Relancer l'API puis recalculer les descripteurs manquants |
| Recherche impossible | Moins de deux images indexées | Indexer au moins deux images avec descripteurs |
| Résultats peu pertinents | Catégories incorrectes ou descripteurs peu discriminants | Vérifier les labels et les métriques |
| Import lent | Trop peu de ressources ou trop d'images | Utiliser le script d'indexation et ajuster `--workers` |
| Mémoire saturée | Trop de processus parallèles | Utiliser `--workers 1` ou `--workers 2` |
| Vignettes absentes | Stockage déplacé ou incomplet | Restaurer le dossier `storage` avec la base |
| Graphiques absents | Fichier `static/vendor/chart.umd.js` manquant | Restaurer le dossier `webapp/static/` |
| Connexion refusée (429) | Trop d'échecs consécutifs | Attendre 5 minutes |
| Erreur CSRF | Session expirée | Recharger la page et se reconnecter |
| Mauvaise classification des classes | Découpage arbitraire d'un dossier plat | Vérifier les annotations originales du dataset |

---

## 21. Limites connues et évolutions

### Limites actuelles

- Les descripteurs restent des caractéristiques de bas niveau : ils ne comprennent pas directement les concepts sémantiques.
- La teinte HSV est traitée comme une variable linéaire dans les moments.
- Les couleurs dominantes sont visualisées, mais ne participent pas à la distance.
- Le protocole automatique d'évaluation utilise les catégories comme proxy de pertinence.
- L'API REST peut être protégée par une clé (`DESCRIPTOR_API_KEY`) mais n'a pas de gestion de comptes propre.
- Le moteur effectue une recherche exhaustive dans la matrice des vecteurs.
- La galerie utilise un traitement synchrone pour l'import web ; le script batch est préférable pour une grande collection.

### Évolutions envisageables

1. Ajouter une évaluation humaine sur un sous-ensemble de requêtes.
2. Ajouter des courbes Precision-Recall et des intervalles de confiance.
3. Comparer plusieurs pondérations couleur/texture.
4. Ajouter des descripteurs de forme comme HOG.
5. Étudier une recherche hybride avec embeddings CNN comme baseline complémentaire, sans remplacer l'approche classique.
6. Ajouter un index ANN/FAISS si le nombre d'images augmente fortement.
7. Mettre en place une file de tâches pour l'indexation asynchrone.
8. Ajouter un système de suivi des expériences et de versionnement des paramètres.
9. Déployer une démo avec des données autorisées et un stockage adapté.

Ces évolutions sont des pistes, pas des fonctionnalités à considérer comme déjà implémentées.

---

## 22. Références

- Renuka Devi S. M., *Reweighing Strategies for Relevance Feedback in CBIR*, IJARCCE, vol. 5, n° 11, 2016. Référence de la méthode de retour de pertinence à confronter au document scientifique fourni dans le cadre du cours.
- Haralick, R. M., Shanmugam, K., Dinstein, I. (1973). *Textural Features for Image Classification*.
- Ojala, T., Pietikäinen, M., Mäenpää, T. (2002). *Multiresolution Gray-Scale and Rotation Invariant Texture Classification with Local Binary Patterns*.
- Rui, Y., Huang, T. S., Mehrotra, S. (1997). *Content-Based Image Retrieval with Relevance Feedback in MARS*.
- Documentation officielle : [Flask](https://flask.palletsprojects.com/), [Flask-RESTful](https://flask-restful.readthedocs.io/), [NumPy](https://numpy.org/doc/), [scikit-image](https://scikit-image.org/docs/stable/), [scikit-learn](https://scikit-learn.org/stable/), [Pillow](https://pillow.readthedocs.io/).

---

## Licence et données

Ce dépôt est un projet académique. Vérifier les conditions de licence du dataset GHIM-10K avant de redistribuer les images ou de publier une démonstration contenant des images du dataset.
