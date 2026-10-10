# Changelog

## [0.9.0] - 2026-10-10

### Added
- **Commande `groups`** : recrée les paquets groupe installés sur des postes mais disparus du dépôt, à partir de leur version installée la plus récente. Les dépendances absentes du dépôt sont écartées et signalées (`--keep-missing` pour les garder). Un groupe identique garde sa version. Simulation par défaut, `--apply` pour signer et envoyer.
- **Groupes suggérés** : par OS, un groupe « socle commun » des paquets du dépôt installés sur la plupart des postes (60 %, au moins 3) et absents des groupes existants ; `groups --create-suggested` les crée.
- **`hosts --groups`** : ajoute aux paquets machine les groupes du dépôt dont le poste a déjà la plupart des paquets (80 %), pour affecter un groupe nouvellement créé.
- Onglet **« Paquets groupe »** dans le rapport, colonne « Groupes » dans « Paquets machine » ; section `[groups]` de la configuration ; page `docs/groups.md` et sa capture d'écran.

### Changed
- `hosts` ajoute au paquet machine les groupes installés sur le poste et présents dans le dépôt, et signale ceux qui manquent. Les paquets fournis par un groupe ne sont plus ajoutés un par un.

## [0.8.1] - 2026-10-10

### Changed
- **Documentation restructurée** dans `docs/` : installation, configuration, authentification et secrets, une page par commande (`report`, `import`, `cleanup`, `hosts`, `report --notify`), développement, et un sommaire. `INSTALL.md` est réparti dans ces pages.
- **README raccourci** : rôle des commandes, démarrage rapide, cycle d'entretien type, liens vers la documentation.
- Captures d'écran dans `docs/images/`, dont l'onglet « Paquets machine » ; les postes de démonstration ont des paquets machine.

### Added
- `scripts/screenshots.py` : régénère les captures d'écran à partir du rapport de démonstration (Chrome ou Chromium sans interface, Chrome de Windows depuis WSL).
- Test des liens entre les pages de documentation (fichiers et ancres).

## [0.8.0] - 2026-10-10

### Added
- **Commande `hosts`** : complète le paquet machine de chaque poste avec les paquets WAPT qui y sont installés mais qu'il ne liste pas (ni dépendance d'un autre paquet, ni fournis par un groupe), ramenés à votre préfixe. Aucune dépendance n'est jamais retirée. Simulation par défaut, `--apply` pour signer et envoyer.
- **Recréation des paquets machine** absents du serveur, à partir des dépendances du paquet machine installé sur le poste, avec la version suivante.
- **Reprise des logiciels installés hors WAPT** (`hosts --adopt`) : ajout des paquets du dépôt correspondants, pour que WAPT les installe puis les tienne à jour.
- Paquets machine construits comme dans la console WAPT (attributs du control conservés, version incrémentée), signés avec votre clé et envoyés via `api/v3/upload_hosts` (chiffrement côté serveur conservé) ; `-i` pour choisir les ajouts, `--no-upload` pour signer sans envoyer, `[hosts] exclude`.
- Onglet **« Paquets machine »** dans le rapport : ajouts proposés par poste, paquets machine absents du serveur, paquets installés absents du dépôt.

### Fixed
- Signature avec une clé privée non chiffrée : la passphrase vide n'est plus transmise à `waptcrypto`, qui la refusait.
- Clé chiffrée sans passphrase : erreur explicite au lieu d'un blocage de `waptpython` en attente d'une saisie.

### Changed
- Capture d'écran du README régénérée.

## [0.7.0] - 2026-10-10

### Added
- **Sélection interactive** : `import -i` / `--interactive` présente les paquets demandés (noms, candidats de `--from-report` ou mises à jour de `--update`) dans une liste à cocher, avant le plan d'import.
- Filtre au clavier (nom, version, OS, description), Espace pour cocher, Ctrl+A / Ctrl+D pour les lignes visibles, Entrée pour valider, Échap pour annuler.
- Chaque ligne indique la version (ancienne → nouvelle pour une mise à jour), l'OS, l'architecture, la taille, les postes concernés et le nom du logiciel ; les paquets réservés aux abonnés ou exclus par la configuration sont grisés avec leur raison.
- Tout est coché au départ avec `--update` ou des noms, rien avec `--from-report`.

### Changed
- Nouvelle dépendance : `prompt_toolkit`.

## [0.6.0] - 2026-10-10

### Added
- **Notifications** : `report --notify` envoie le résumé du rapport aux destinations de la section `[notify]`.
- **Envoi par mail** (SMTP, STARTTLS/SSL, login facultatif), avec le rapport HTML en pièce jointe et un sujet paramétrable.
- **Webhooks** (plusieurs possibles) aux formats `json`, `slack` (Mattermost, Rocket.Chat) et `teams` (carte Adaptive Card pour les Workflows), avec en-têtes facultatifs et URL lisible dans un fichier `chmod 600`.
- **Nouveautés depuis le dernier envoi** dans le résumé (mises à jour, paquets manquants, logiciels à importer) ; `when = "changes"` n'envoie que s'il y a du nouveau.
- Mot de passe SMTP via `$WAPT_SMTP_PASSWORD`, `[notify.email] password_file` ou `$WAPT_SMTP_PASSWORD_FILE`.
- `report -q` / `--quiet` : aucune sortie hors erreurs, pour cron.
- Documentation de la planification : cron, timer systemd utilisateur, WSL.

## [0.5.0] - 2026-10-10

### Added
- **Double authentification (TOTP)** : le code est demandé uniquement quand le serveur le réclame, via `--totp`, `$WAPT_TOTP` ou saisie, et transmis comme le font la console WAPT et `wapt-get` (`motdepasse{code}`).
- **Certificat client TLS** : `[server] client_certificate` / `client_private_key` (`--client-certificate`, `--client-private-key`), présenté pour l'API et l'index du dépôt ; clé chiffrée déverrouillée en mémoire (`$WAPT_CLIENT_KEY_PASSWORD`, `client_key_password_file` ou saisie).
- Documentation : sections « Double authentification (TOTP) » et « Certificat client » dans `INSTALL.md`, lien vers le miroir GitHub dans le README et `INSTALL.md`.

### Changed
- `import --apply` se connecte au serveur avant les téléchargements et la signature, et non plus juste avant l'upload, pour qu'un code TOTP soit encore valable.

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
