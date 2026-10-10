# Changelog

## [0.4.2] - 2026-10-10

### Added
- **Guide d'installation** `INSTALL.md` : prérequis, installation depuis un clone ou avec `uv tool install`, recherche et sections du fichier de configuration, ordre de priorité avec les variables d'environnement.
- **Stockage des secrets** documenté : ordre de recherche du mot de passe du serveur et de la passphrase de la clé, création des fichiers `chmod 600`, limites sous WSL (`/mnt/c`) et sous Windows natif, fichiers créés par l'outil.
- **Rapport de démonstration** `scripts/demo_report.py` : rapport généré à partir de postes et d'un dépôt fictifs, confrontés à l'index public du store, sans serveur.

### Changed
- README : capture d'écran du rapport, section Installation réduite à un démarrage rapide renvoyant vers `INSTALL.md`.

### Fixed
- Documentation de l'ordre de priorité des fichiers de secrets : `password_file` / `--password-file` passent avant `$WAPT_PASSWORD_FILE` (idem pour la passphrase), contrairement à ce qu'indiquait le README.

## [0.4.1] - 2026-10-10

### Added
- Variable d'environnement `WAPT_KEY_PASSWORD_FILE` pour le fichier de passphrase de la clé de signature, en complément de `[signing] key_password_file` et `--key-password-file` (même contrôle `chmod 600` que le mot de passe du serveur).

### Changed
- README : tableau des commandes et cycle d'entretien type (`report` → `import` → `import --update --cleanup`), tableaux d'options de `import` et `cleanup`, section dédiée à `import --update`.

## [0.4.0] - 2026-10-10

### Added
- Commande `cleanup` : supprime du dépôt les versions qu'aucun poste ne peut plus installer, parce qu'une version plus récente les couvre entièrement (OS, architecture, locale, maturité, plage de versions d'OS). Garde-fous : dépendances à version précise, préfixe, `--keep N`, `[cleanup] exclude`. Simulation par défaut.
- `import --cleanup` : nettoyage des versions remplacées, enchaîné juste après l'upload.

## [0.3.0] - 2026-10-09

### Added
- Profil d'éditeurs `oem` : les logiciels constructeurs sans équivalent sont repliés dans l'onglet « Sans équivalent » (affichables à la demande) ; configurable avec `fold_profiles` / `fold_publishers`.
- Rapport HTML : cases à cocher sur les paquets proposés et barre de sélection générant la commande `import` (regroupée par OS, option `--apply`), synchronisées entre les onglets.

### Fixed
- Import depuis WSL avec l'agent Windows : la signature des gros paquets (> ~150 Mo) se bloquait indéfiniment, les écritures de waptpython vers `\\wsl.localhost` restant en attente. Le dossier de travail est désormais sur le disque Windows (`%LOCALAPPDATA%\wapt-analyzer\import`), et la barre de progression affiche l'étape en cours (vérification, signature).
- Rapport HTML : le tri d'un tableau utilisait l'index de colonne de toute la page au lieu de celui du tableau.
- Rapprochement logiciel ↔ paquet : les éditions (Office 2016 / 2019 / 2024, Visual C++ 2005 / v14…) ne sont plus confondues ; le rapport liste les autres éditions disponibles quand celle installée n'existe pas.
- Nom d'éditeur générique en tête (« Microsoft … ») essayé sans l'éditeur : .NET Framework, Silverlight, VSTA, Office LTSC désormais reconnus.

## [0.2.0] - 2026-10-09

### Added
- `import --update` : met à jour les paquets du dépôt pour lesquels le store propose une version plus récente (même OS, même architecture, version complète), avec `update_exclude` pour protéger les paquets maison.
- Onglet « Mises à jour » : distingue les nouvelles versions des révisions de paquet ; même détection que `import --update`.

## [0.1.0] - 2026-10-09

### Added
- Commande `report` : paquets manquants, logiciels à importer, logiciels hors WAPT, paquets sans équivalent, mises à jour disponibles.
- Sorties HTML, JSON et CSV.
- Configuration TOML, variables d'environnement, mode `--offline`.
- Commande `import` : import de paquets du store, avec vérification de la signature d'origine (source et confiance paramétrables : empreintes épinglées, certificats locaux ; Tranquil IT épinglé par défaut pour son store), renommage au préfixe local, signature avec la clé de l'utilisateur via `waptpython` (passphrase demandée une seule fois), résolution des dépendances et upload en streaming. Simulation par défaut.
- Barres de progression (téléchargement, signature, upload) pendant l'import.
- Paquets réservés aux abonnés (`wapt_enterprise`) signalés dans le rapport et ignorés par l'import (configurable).
- Analyse par famille d'OS (Windows, macOS, Linux) : variantes de paquets par `target_os`, filtres d'architecture par OS, exclusions propres à macOS.
