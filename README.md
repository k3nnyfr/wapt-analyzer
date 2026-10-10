# wapt-analyzer

Outil en ligne de commande pour entretenir le dépôt de paquets d'un serveur [WAPT](https://www.wapt.fr). Il compare ce dépôt, le store public Tranquil IT et l'inventaire des postes, puis aide à combler les écarts.

Sources : [Gitea](https://git.k3nny.fr/k3nny/wapt-analyzer) (dépôt principal) · [GitHub](https://github.com/k3nnyfr/wapt-analyzer) (miroir) · Licence [GPL-3.0-or-later](LICENSE), comme WAPT.

![Rapport de démonstration : onglet « À importer », quatre paquets sélectionnés et la commande d'import correspondante](docs/images/report-import.png)

## Ce que fait l'outil

| Commande | Rôle | Écrit sur le serveur ? |
|---|---|---|
| [`report`](docs/report.md) | Analyse le parc et produit un rapport HTML : paquets manquants, logiciels installés hors WAPT, mises à jour disponibles, paquets machine à compléter | Non |
| [`import`](docs/import.md) | Importe des paquets du store (signature d'origine vérifiée, renommés à votre préfixe, signés avec **votre** clé) ou met à jour ceux du dépôt (`--update`) | Avec `--apply` |
| [`cleanup`](docs/cleanup.md) | Supprime les anciennes versions qu'aucun poste ne peut plus installer | Avec `--apply` |
| [`hosts`](docs/hosts.md) | Recrée et complète le paquet machine de chaque poste, reprend en gestion les logiciels installés hors WAPT (`--adopt`) | Avec `--apply` |
| [`report --notify`](docs/scheduling.md) | Envoie le résumé du rapport par mail ou webhook, depuis cron ou un timer systemd | Non |

Les commandes qui modifient le serveur fonctionnent **en simulation par défaut** : elles affichent leur plan et n'agissent qu'avec `--apply`. `import` et `hosts` proposent aussi une liste à cocher dans le terminal (`-i`).

## Démarrage rapide

Il faut Python 3.10 ou plus récent et [uv](https://docs.astral.sh/uv/). Pour `import` et `hosts`, il faut aussi un agent WAPT sur la machine et votre clé de signature.

```bash
git clone https://git.k3nny.fr/k3nny/wapt-analyzer && cd wapt-analyzer
cp wapt-analyzer.example.toml wapt-analyzer.toml   # renseigner [server] url et user, [repo] prefix
uv run wapt-analyzer report                        # mot de passe demandé, puis ouvrir wapt-report.html
```

Un cycle d'entretien type :

```bash
uv run wapt-analyzer report --json wapt-report.json                  # 1. analyser le parc
uv run wapt-analyzer import --from-report wapt-report.json -i        # 2. choisir les paquets à importer (simulation)
uv run wapt-analyzer import --from-report wapt-report.json --apply   #    puis importer
uv run wapt-analyzer import --update --apply --cleanup               # 3. mettre à jour, nettoyer les anciennes versions
uv run wapt-analyzer hosts --adopt -i --apply                        # 4. compléter les paquets machine
```

## Documentation

- **Mise en route** : [installation](docs/installation.md), [configuration](docs/configuration.md), [authentification et secrets](docs/secrets.md) (mot de passe, TOTP, certificat client, clé de signature)
- **Commandes** : [rapport](docs/report.md), [import et mises à jour](docs/import.md), [nettoyage du dépôt](docs/cleanup.md), [paquets machine](docs/hosts.md), [rapport planifié et notifications](docs/scheduling.md)
- **Projet** : [développement](docs/development.md), [changelog](CHANGELOG.md), [roadmap](ROADMAP.md)

Le sommaire complet est dans [docs/](docs/README.md).

## Limites

- Le serveur WAPT ne conserve que l'état **actuel** des paquets sur chaque poste : l'historique est partiel.
- Kerberos n'est pas pris en charge. Une tâche planifiée ne peut pas fournir de code TOTP : il lui faut un compte sans double authentification.
