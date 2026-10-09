# Roadmap

## v0.1 — Rapport (lecture seule)
- [x] Lecture des index `Packages` (dépôt local et store Tranquil IT), avec cache HTTP
- [x] Collecte de l'inventaire des postes via l'API du serveur (login et mot de passe)
- [x] Paquets manquants par rapport aux paquets installés sur les postes
- [x] Rapprochement des logiciels installés hors WAPT avec les paquets du store
- [x] Rapport HTML autonome, export JSON et CSV
- [x] Configuration par TOML, variables d'environnement et CLI
- [x] Prise en charge multi-OS (Windows, macOS, Linux)

## v0.2 — Import depuis le store
- [x] `wapt-analyzer import` : téléchargement, vérification de la signature Tranquil IT, changement de préfixe, signature avec la clé de l'utilisateur, upload
- [x] Simulation par défaut, action effective seulement avec `--apply`
- [x] Entrées possibles : `--from-report rapport.json` (avec `--only`) ou noms de paquets
- [x] Réutilisation du `waptpython` d'un agent WAPT installé (y compris l'agent Windows depuis WSL)
- [x] Prise en compte des dépendances (`depends`) des paquets importés
- [x] Clé déverrouillée une seule fois par import

## v0.3 — Confort au quotidien
- [x] `import --update` : mise à jour des paquets en retard sur le store
- [ ] Cases à cocher dans le rapport HTML pour générer la commande d'import
- [ ] Liste d'exclusions OEM optionnelle (HP, Canon, Epson, Intel…)
- [ ] Rapprochement d'Office tenant compte de l'année

## v0.4 — Authentification
- [ ] Authentification MFA (TOTP)
- [ ] Authentification par certificat client

## Plus tard
- [ ] Mode planifié (cron) avec envoi du rapport (mail ou webhook)
- [ ] Sélection interactive des paquets dans le terminal
- [ ] Publication sur PyPI (`uvx wapt-analyzer`)
