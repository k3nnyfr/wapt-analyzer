# Mettre à jour les postes

[Documentation](README.md) · commande `upgrade`

Après un import ou une mise à jour du dépôt, les agents n'installent les nouvelles versions qu'à leur prochain cycle. `upgrade` leur demande de le faire tout de suite, comme le bouton « Mettre à jour les paquets » de la console WAPT :

```bash
uv run wapt-analyzer upgrade                         # simulation : postes ciblés, connectés ou non
uv run wapt-analyzer upgrade --apply                 # postes ayant des installations en attente
uv run wapt-analyzer upgrade --packages firefox,7zip --apply   # postes ayant ces paquets
uv run wapt-analyzer upgrade PC-COMPTA-02 --wake --apply       # réveille le poste s'il est éteint
uv run wapt-analyzer import --update --apply --upgrade-hosts   # mise à jour du dépôt puis des postes
```

L'action envoyée est celle de la console : l'agent rafraîchit son index de paquets, télécharge puis installe ce qui est en attente. Avec `--update-only`, il ne fait que rafraîchir son index : les mises à jour apparaissent alors dans l'onglet [Déploiements](report.md#suivi-des-déploiements) du rapport, sans être installées.

## Postes ciblés

| Choix | Postes |
|---|---|
| *(défaut)* | Postes ayant des installations ou mises à jour en attente dans l'inventaire (onglet Déploiements) |
| `--packages a,b` | Postes ayant l'un de ces paquets (`firefox` ou `tsi-firefox`), quel que soit son état |
| `--all` | Tous les postes |
| `HOST…` | Restreint à ces postes (nom court, FQDN ou uuid) |
| `import --upgrade-hosts` | Postes ayant l'un des paquets qui viennent d'être envoyés |

## Postes connectés et réveil

Le serveur ne relaie une action qu'aux agents **connectés** à cet instant (colonne « joignable » de la console). Les autres sont signalés et ignorés. Avec `--wake`, `upgrade` leur envoie d'abord un paquet Wake-on-LAN depuis le serveur, puis attend qu'ils se connectent (`--wait`, 180 secondes par défaut) : ceux qui se sont connectés à temps reçoivent l'action, les autres sont signalés. Le Wake-on-LAN doit être activé dans le BIOS des postes et le serveur doit pouvoir joindre leur réseau.

## Signature des actions

Un agent n'exécute une action que si elle est signée par un certificat auquel il fait confiance : celui qui signe vos paquets convient. `upgrade` utilise donc la même clé que `import` (voir [Authentification et secrets](secrets.md#clé-de-signature-et-passphrase)), déverrouillée une fois par le `waptpython` de l'agent WAPT installé, comme pour la signature des paquets.

| Option | Rôle |
|---|---|
| `HOST…`, `--all`, `--packages` | Postes ciblés (voir plus haut) |
| `--update-only` | Rafraîchit seulement l'index des agents, sans installer |
| `--wake`, `--wait SECONDES` | Réveille les postes déconnectés et les attend |
| `--apply`, `-y` | Envoie réellement l'action ; `-y` saute la confirmation |
| `--certificate`, `--private-key`, `--key-password-file`, `--wapt-python` | Clé de signature, comme pour `import` |
