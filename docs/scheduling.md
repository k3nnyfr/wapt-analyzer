# Rapport planifié et notifications

[Documentation](README.md) · commande `report --notify`

`report --notify` envoie un résumé du rapport aux destinations de la section `[notify]` :
- **par mail** (SMTP), avec le rapport HTML en pièce jointe ;
- **par webhook**, en JSON brut, au format Slack (compatible Mattermost, Rocket.Chat…) ou en carte Microsoft Teams (Workflows). On peut déclarer plusieurs webhooks.

Le résumé reprend les compteurs du rapport, dont ceux des [déploiements](report.md#suivi-des-déploiements) (postes en erreur, installations en attente, postes muets), puis les **nouveautés depuis le dernier envoi** : erreurs de déploiement, mises à jour disponibles, paquets manquants, logiciels à importer (dix par rubrique au plus).

```toml
[notify]
when = "changes"           # n'envoyer que s'il y a du nouveau (défaut : always)
report_url = "https://intranet.example.org/wapt-report.html"   # lien ajouté au message, facultatif

[notify.email]
smtp_host = "smtp.example.org"
user = "wapt-analyzer"
password_file = "~/.config/wapt-analyzer/smtp-password"
from = "wapt-analyzer@example.org"
to = ["admin@example.org"]

[[notify.webhook]]
format = "slack"
url_file = "~/.config/wapt-analyzer/webhook-url"
```

Avec `when = "changes"`, le premier envoi a toujours lieu. Les suivants n'ont lieu que si une entrée nouvelle apparaît. Si aucune destination n'a pu être jointe, l'état n'est pas mémorisé, et les mêmes nouveautés seront proposées la fois suivante.

Pour tester la configuration sans interroger le serveur : `uv run wapt-analyzer report --offline --notify`.

Pour planifier le rapport, avec cron ou un timer systemd, voir [Planifier l'exécution](#planifier-lexécution). `-q` / `--quiet` supprime toute sortie hors erreurs, pour que cron n'envoie pas de mail à chaque exécution.

| Option | Rôle |
|---|---|
| `--notify` | Envoie le résumé aux destinations de `[notify]` |
| `-q`, `--quiet` | N'affiche que les erreurs |

## Planifier l'exécution

Lancé régulièrement, `report --notify` prévient des nouveautés du parc sans avoir à ouvrir le rapport.

### Prérequis

Une tâche planifiée tourne sans terminal : rien ne peut être saisi au clavier.

- Le mot de passe du serveur doit venir d'un fichier (`[server] password_file`) ou de l'environnement.
- Le compte ne doit pas exiger de code TOTP : prévoyez un compte dédié, sans MFA, limité aux droits nécessaires. `report` ne fait que lire.
- Une clé de certificat client chiffrée demande un fichier de passphrase (`client_key_password_file`).
- Le mot de passe SMTP éventuel vient de `[notify.email] password_file` ou de `WAPT_SMTP_PASSWORD`.
- Une URL de webhook contient souvent un jeton : rangez-la dans un fichier `chmod 600` désigné par `url_file`, plutôt qu'en clair dans `url`.

```bash
install -m 600 /dev/null ~/.config/wapt-analyzer/smtp-password    # puis y écrire le mot de passe SMTP
install -m 600 /dev/null ~/.config/wapt-analyzer/webhook-url      # puis y écrire l'URL du webhook
```

Validez la configuration à la main avant de planifier, sans interroger le serveur : `uv run wapt-analyzer report --offline --notify`.

### Avec cron

`crontab -e`, pour un rapport du lundi au vendredi à 7 h 30 :

```cron
30 7 * * 1-5  $HOME/.local/bin/uv run --directory $HOME/wapt-analyzer wapt-analyzer report --notify --quiet
```

- Le `PATH` de cron est réduit : donnez le chemin complet de `uv` (`which uv`). Avec une installation par `uv tool install`, appelez directement `$HOME/.local/bin/wapt-analyzer`.
- `--directory` pointe vers le clone. La configuration est alors lue dans `./wapt-analyzer.toml` du clone, sinon dans `~/.config/wapt-analyzer/config.toml`.
- `--quiet` n'affiche que les erreurs : cron n'envoie un mail que si quelque chose échoue.
- Pour publier le rapport HTML sur un serveur web, ajoutez `-o /var/www/wapt/wapt-report.html` et renseignez `[notify] report_url`.

### Avec un timer systemd (utilisateur)

`~/.config/systemd/user/wapt-analyzer.service` :

```ini
[Unit]
Description=Rapport wapt-analyzer

[Service]
Type=oneshot
WorkingDirectory=%h/wapt-analyzer
ExecStart=%h/.local/bin/uv run wapt-analyzer report --notify --quiet
```

`~/.config/systemd/user/wapt-analyzer.timer` :

```ini
[Unit]
Description=Rapport wapt-analyzer en semaine

[Timer]
OnCalendar=Mon..Fri 07:30
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now wapt-analyzer.timer
loginctl enable-linger "$USER"        # pour que le timer tourne sans session ouverte
journalctl --user -u wapt-analyzer    # journal des exécutions
```

`Persistent=true` rattrape une exécution manquée, par exemple si la machine était éteinte à l'heure prévue.

### Sous WSL

Ni cron ni systemd ne tournent par défaut dans WSL. Deux possibilités :
- activer systemd dans la distribution (`[boot] systemd=true` dans `/etc/wsl.conf`, puis `wsl --shutdown`), et utiliser le timer ci-dessus ;
- ou créer une tâche dans le Planificateur de tâches Windows qui lance `wsl.exe -d <distribution> -- bash -lc "cd ~/wapt-analyzer && ~/.local/bin/uv run wapt-analyzer report --notify --quiet"`.
