# Roadmap

## v0.1.0 — Rapport et import depuis le store
- [x] Lecture des index `Packages` (dépôt local et store Tranquil IT), avec cache HTTP
- [x] Collecte de l'inventaire des postes via l'API du serveur (login et mot de passe)
- [x] Paquets manquants par rapport aux paquets installés sur les postes
- [x] Rapprochement des logiciels installés hors WAPT avec les paquets du store
- [x] Rapport HTML autonome, export JSON et CSV
- [x] Configuration par TOML, variables d'environnement et CLI
- [x] Prise en charge multi-OS (Windows, macOS, Linux)
- [x] `wapt-analyzer import` : téléchargement, vérification de la signature d'origine, changement de préfixe, signature avec la clé de l'utilisateur, upload
- [x] Simulation par défaut, action effective seulement avec `--apply`
- [x] Entrées possibles : `--from-report rapport.json` (avec `--only`) ou noms de paquets
- [x] Réutilisation du `waptpython` d'un agent WAPT installé (y compris l'agent Windows depuis WSL)
- [x] Prise en compte des dépendances (`depends`) des paquets importés
- [x] Clé déverrouillée une seule fois par import

## v0.2.0 — Mises à jour
- [x] `import --update` : mise à jour des paquets en retard sur le store

## v0.3.0 — Confort au quotidien
- [x] Cases à cocher dans le rapport HTML pour générer la commande d'import
- [x] Logiciels constructeurs (HP, Canon, Epson, Intel…) repliés dans « Sans équivalent »
- [x] Rapprochement tenant compte des éditions (Office 2016 / 2024, Visual C++…)
- [x] Import fiable des gros paquets sous WSL (dossier de travail sur le disque Windows)

## v0.4.0 — Maintenance du dépôt
- [x] Mode `cleanup` post-import : supprimer du dépôt les paquets qui ne sont plus la dernière version disponible (par paquet, OS, architecture, locale et maturité), et qui ne seront donc plus proposés aux postes
- [x] Vérification avant suppression : aucune dépendance ne cible explicitement une version précise (`tsi-foo(=1.2-3)`)
- [x] Simulation par défaut, `--apply` pour supprimer, option pour conserver les N versions précédentes (retour arrière)
- [x] Enchaînement possible après une mise à jour : `import --update --cleanup`

## v0.4.1 — Confort
- [x] Fichier de passphrase de la clé de signature via `$WAPT_KEY_PASSWORD_FILE`
- [x] README : import, mises à jour et nettoyage mieux documentés

## v0.4.2 — Documentation
- [x] Guide d'installation et de configuration (`INSTALL.md`), stockage des secrets
- [x] Capture d'écran du rapport dans le README, générée à partir de données fictives

## v0.5.0 — Authentification
- [x] Authentification MFA (TOTP)
- [x] Authentification par certificat client

## v0.6.0 — Rapport planifié
- [x] Mode planifié (cron, timer systemd) avec envoi du rapport par mail et par webhook
- [x] Envoi seulement en cas de nouveautés (`when = "changes"`)

## v0.7.0 — Sélection interactive
- [x] Sélection interactive des paquets dans le terminal (`import -i`)

## v0.8.0 — Paquets machine
- [x] Recréer et compléter les paquets machine à partir des paquets installés sur chaque poste
- [x] Suggérer les paquets du dépôt pour les logiciels installés hors WAPT, afin de normaliser le parc et suivre leurs mises à jour

## v0.8.1 — Documentation
- [x] Documentation structurée dans `docs/`, README raccourci
- [x] Captures d'écran régénérables (`scripts/screenshots.py`)

## v0.9.0 — Paquets groupe
- [x] Recréer les paquets groupe déployés mais disparus du dépôt
- [x] Suggérer des groupes « socle commun » et les affecter aux postes (`hosts --groups`)

## v0.10.0 — Espace disque
- [x] Purge des paquets téléchargés et signés une fois envoyés au serveur (`--keep-files` pour les garder)
- [x] Commande `purge` pour vider le dossier de travail à la demande

## Plus tard
- [ ] Publication sur PyPI (`uvx wapt-analyzer`)
