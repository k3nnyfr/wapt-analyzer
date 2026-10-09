# Changelog

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
