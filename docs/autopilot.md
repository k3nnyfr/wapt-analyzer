# Pilote automatique

[Documentation](README.md) · commande `autopilot`

`autopilot` enchaîne l'entretien courant du dépôt et des postes, pour être lancé chaque jour par cron ou un timer systemd :

1. **rapport** : écrit le rapport (HTML, JSON, CSV selon `[report]`) et enrichit l'[historique des déploiements](report.md#historique) ;
2. **mises à jour** : importe les nouvelles versions du store des paquets du dépôt, comme [`import --update`](import.md), puis supprime les versions remplacées ([`cleanup`](cleanup.md)) ;
3. **postes** : demande aux postes connectés qui ont ces paquets de se mettre à jour tout de suite ([`upgrade`](upgrade.md)) ;
4. **récapitulatif** : un seul message par les destinations de [`[notify]`](scheduling.md), avec ce qui a été fait en tête, suivi du résumé habituel du rapport.

```bash
uv run wapt-analyzer autopilot            # simulation : rapport et mises à jour prévues, rien d'autre
uv run wapt-analyzer autopilot --apply    # entretien réel, à mettre dans cron
```

Sans `--apply`, seul le rapport est écrit : rien n'est importé, aucun poste n'est sollicité, aucun message n'est envoyé.

## Garde-fous

| Réglage | Effet |
|---|---|
| `packages` | Seuls ces paquets sont mis à jour (nom sans préfixe) ; vide : tous les paquets du dépôt, hors `[import] exclude` et `update_exclude` |
| `max_updates` | Au-delà de ce nombre de mises à jour en une fois (10 par défaut), rien n'est importé et le message demande un examen : une avalanche de mises à jour mérite un coup d'œil |
| `cleanup` | Supprime ou non les versions remplacées après l'import |
| `upgrade` | `imported` (défaut) : postes ayant les paquets mis à jour ; `pending` : tous les postes ayant des installations en attente ; `none` : aucun |
| `notify` | Envoie ou non le récapitulatif |

Deux exécutions ne se chevauchent jamais : un verrou (`autopilot.lock` dans le cache) fait échouer la seconde tant que la première tourne. Les paquets importés restent vérifiés (signature d'origine) et signés avec votre clé, comme avec `import`.

```toml
[autopilot]
packages = ["firefox", "7zip", "vlc", "notepadplusplus"]   # liste blanche
max_updates = 5
upgrade = "imported"
```

## Planification

L'autopilote tourne sans terminal : le mot de passe du serveur, la passphrase de la clé de signature et le compte doivent être disponibles sans saisie (fichiers `chmod 600`, voir [Authentification et secrets](secrets.md)). Un compte qui exige un code TOTP ne convient pas.

```cron
# Tous les jours ouvrés à 7 h 30
30 7 * * 1-5  cd /opt/wapt-analyzer && uv run wapt-analyzer autopilot --apply >> ~/.cache/wapt-analyzer/autopilot.log 2>&1
```

Le timer systemd décrit dans [Planifier l'exécution](scheduling.md#avec-un-timer-systemd-utilisateur) convient aussi, de même que les solutions [sous WSL](scheduling.md#sous-wsl) : remplacez `report --notify` par `autopilot --apply`. Le code de sortie est non nul si une étape a échoué ou si la limite `max_updates` a bloqué l'import.

| Option | Rôle |
|---|---|
| `--apply` | Exécute réellement l'entretien |
| `--no-notify` | N'envoie pas le récapitulatif |
| `--certificate`, `--private-key`, `--key-password-file`, `--wapt-python` | Clé de signature, comme pour `import` |
