# Documentation de wapt-analyzer

[← Retour au README](../README.md)

## Mise en route

| Page | Contenu |
|---|---|
| [Installation](installation.md) | Prérequis, installation depuis un clone ou en outil global, agent WAPT, mise à jour |
| [Configuration](configuration.md) | Fichier `wapt-analyzer.toml`, sections, ordre de priorité, fichiers créés par l'outil |
| [Authentification et secrets](secrets.md) | Mot de passe du serveur, double authentification (TOTP), certificat client, clé de signature : variables, fichiers `chmod 600`, saisie |

## Commandes

| Page | Commande | Contenu |
|---|---|---|
| [Le rapport](report.md) | `report` | Onglets du rapport, options, rapprochement logiciel ↔ paquet, multi-OS |
| [Importer et mettre à jour](import.md) | `import` | Import depuis le store, mises à jour, sélection interactive, signature, confiance dans la source |
| [Nettoyer le dépôt](cleanup.md) | `cleanup` | Suppression des versions qu'aucun poste ne peut plus installer |
| [Paquets machine](hosts.md) | `hosts` | Recréer et compléter les paquets machine, reprendre les logiciels installés hors WAPT |
| [Rapport planifié et notifications](scheduling.md) | `report --notify` | Envoi par mail et webhook, cron, timer systemd, WSL |

## Projet

| Page | Contenu |
|---|---|
| [Développement](development.md) | Tests, organisation du code, rapport de démonstration, captures d'écran |
| [Changelog](../CHANGELOG.md) | Historique des versions |
| [Roadmap](../ROADMAP.md) | Fonctionnalités livrées et à venir |
