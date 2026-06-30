# Bot Discord de rencontre — Guide de mise en route

## 1. Créer l'application Discord

1. Va sur https://discord.com/developers/applications et clique sur **New Application**.
2. Donne-lui un nom (ex : le nom de ton serveur de rencontre).
3. Dans le menu de gauche, va dans **Bot** → clique sur **Add Bot**.
4. Toujours dans l'onglet **Bot**, active ces deux options sous "Privileged Gateway Intents" :
   - **Server Members Intent**
   - **Message Content Intent**
5. Clique sur **Reset Token** pour générer ton token, et copie-le précieusement (tu en auras besoin à l'étape 4). Ne le partage jamais publiquement.

## 2. Inviter le bot sur ton serveur

1. Dans le menu de gauche, va dans **OAuth2 → URL Generator**.
2. Coche **bot** et **applications.commands**.
3. Dans les permissions du bot, coche au minimum :
   - Manage Channels
   - Manage Webhooks
   - Send Messages
   - Embed Links
   - Read Message History
   - View Channels
4. Copie l'URL générée en bas de page, ouvre-la dans ton navigateur, et choisis ton serveur pour inviter le bot.

## 3. Récupérer l'identifiant de ton serveur (GUILD_ID)

1. Dans Discord, va dans **Paramètres utilisateur → Avancés** et active le **Mode développeur**.
2. Fais un clic droit sur le nom de ton serveur dans la liste à gauche, puis **Copier l'identifiant du serveur**.

## 4. Héberger le bot sur Railway (gratuit pour démarrer)

1. Crée un compte sur https://railway.app (tu peux te connecter avec GitHub).
2. Mets ce dossier de code dans un nouveau dépôt GitHub (tu peux faire glisser les fichiers directement sur github.com si tu ne connais pas Git).
3. Sur Railway, clique sur **New Project → Deploy from GitHub repo** et sélectionne ton dépôt.
4. Une fois le projet créé, va dans l'onglet **Variables** et ajoute :
   - `DISCORD_TOKEN` = le token copié à l'étape 1
   - `GUILD_ID` = l'identifiant copié à l'étape 3
5. Railway va automatiquement détecter le `Procfile` et lancer le bot. Vérifie dans l'onglet **Deployments → Logs** que tu vois bien `Connecté en tant que ...`.

## 5. Tester le bot

1. Sur ton serveur Discord, tape `/inscription` dans n'importe quel salon.
2. Une fenêtre de formulaire doit s'ouvrir pour remplir prénom, âge, localisation, description.
3. Continue à répondre aux questions suivantes (sexe, orientation, type de relation, centres d'intérêt).
4. Une fois inscrit, le bot enverra automatiquement des suggestions de profils par message privé (toutes les 8 heures dans cette version de démarrage).

## Limitations connues de cette première version (MVP)

- **Fréquence d'envoi** : le bot envoie des suggestions toutes les 8 heures à partir de son démarrage, plutôt qu'à des heures fixes précises (8h/13h/19h). C'est suffisant pour tester, et ajustable facilement plus tard.
- **Vérification d'âge** : basée sur la déclaration de l'utilisateur (pas de vérification d'identité). À renforcer si le serveur grandit.
- **Un seul serveur Discord** : le bot est pensé pour fonctionner sur un seul serveur à la fois (celui défini par `GUILD_ID`).
- **Modération** : il n'y a pas encore de bouton "signaler" dans les salons de match. Les modérateurs peuvent voir les salons via la catégorie "💌 Matchs" si besoin d'intervenir.

## Prochaines améliorations possibles

- Bouton de signalement dans chaque salon de match
- Fermeture automatique des salons inactifs après X jours
- Vérification d'âge renforcée
- Statistiques d'utilisation pour toi (nombre d'inscrits, de matchs, etc.)
