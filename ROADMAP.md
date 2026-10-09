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

## v0.4 — Maintenance du dépôt
- [ ] Mode `cleanup` post-import : supprimer du dépôt les paquets qui ne sont plus la dernière version disponible (par paquet, OS, architecture, locale et maturité), et qui ne seront donc plus proposés aux postes
- [ ] Vérification avant suppression : aucune dépendance ne cible explicitement une version précise (`tsi-foo(=1.2-3)`)
- [ ] Simulation par défaut, `--apply` pour supprimer, option pour conserver les N versions précédentes (retour arrière)
- [ ] Enchaînement possible après une mise à jour : `import --update --cleanup`

## v0.5 — Authentification
- [ ] Authentification MFA (TOTP)
- [ ] Authentification par certificat client

## Plus tard
- [ ] Mode planifié (cron) avec envoi du rapport (mail ou webhook)
- [ ] Sélection interactive des paquets dans le terminal
- [ ] Publication sur PyPI (`uvx wapt-analyzer`)
