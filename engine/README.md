# Chindu Clips — moteur vidéo personnel

Ce moteur exécute le traitement réel. Le site publié reste en mode démonstration tant qu'aucun moteur n'est connecté. Il n'y a pas d'API de clipping payante : yt-dlp récupère la vidéo, Whisper transcrit localement et FFmpeg produit les MP4. La sélection est un classement heuristique éditorial, pas un modèle capable de prédire la viralité. Elle privilégie les accroches, les questions, la densité et les fins de phrase ; vérifiez les extraits dans leur contexte.

## Installation avec Docker Desktop (Windows, Mac) ou Docker Compose (Linux)

1. Décompressez cette archive dans un dossier.
2. Créez un fichier `.env` dans ce dossier contenant une clé privée aléatoire de 32 caractères au minimum :

   CLIP_API_KEY=REMPLACEZ_PAR_VOTRE_CLE_PRIVEE_ALEATOIRE

   Pour générer une clé, utilisez votre gestionnaire de mots de passe. Sous Linux : `openssl rand -hex 32`. Ne partagez pas cette clé ; elle donne accès à tous vos projets.
3. Dans ce dossier, exécutez :

   docker compose up -d --build

4. Ouvrez http://localhost:8080 sur CET ordinateur. Le studio est également inclus dans l'image Docker : il fonctionne sans le site publié.
5. Cliquez « Connecter le moteur » et saisissez http://localhost:8080 et votre clé.
6. Collez un lien YouTube ou importez une vidéo, puis cliquez « Générer mes clips ».

Le premier traitement télécharge le modèle Whisper « small » (environ 500 Mo, ordre de grandeur). Il faut une connexion Internet pour ce téléchargement et pour YouTube. Les modèles déjà téléchargés et fichiers importés se traitent ensuite localement. Une machine avec 4 Go de RAM minimum et idéalement 8 Go est recommandée. Sur CPU, une vidéo longue peut prendre plusieurs dizaines de minutes. Les fichiers et modèles restent dans les volumes Docker nommés.

## Utiliser le site publié depuis n'importe quel appareil

Le moteur doit être hébergé sur un ordinateur allumé ou un VPS Linux et exposé par une URL HTTPS valide. Le site publié ne peut pas héberger FFmpeg ou Whisper : son hébergement n'exécute pas de processus vidéo natifs.

- Installez ce même conteneur sur un VPS ; le port 8080 reste lié à 127.0.0.1.
- Faites pointer un sous-domaine (par exemple clips.votre-domaine.com) vers le VPS.
- Installez un reverse proxy HTTPS comme Caddy. Exemple de Caddyfile (remplacez le domaine) :

  clips.votre-domaine.com {
      request_body {
          max_size 410MB
      }
      reverse_proxy 127.0.0.1:8080
  }

- Autorisez les connexions entrantes aux ports 80 et 443 de ce VPS.
- Le domaine du studio publié est déjà inclus dans ALLOWED_ORIGINS dans compose.yaml. Si vous hébergez le studio ailleurs, ajoutez son origine exacte à cette variable dans `.env`, puis relancez `docker compose up -d`.
- Dans le site publié, indiquez l'URL HTTPS de ce moteur et votre clé privée. Ne mettez pas la clé dans une URL ou dans le code source.

L'hébergement, le domaine et l'électricité ne sont pas fournis. Aucun serveur externe n'a été provisionné par la création du site. Pour utiliser un hébergement existant, il faut y installer ce conteneur. Ce moteur est prévu pour un propriétaire ; ce n'est pas un service public multi-utilisateur.

## Fonctionnement et limites

- Entrée : lien HTTPS youtube.com/watch, youtu.be, shorts ou live, ou fichier vidéo importé. Durée maximale : 60 minutes. Taille maximale : 400 Mo.
- Les vidéos privées, les directs encore en cours, les restrictions territoriales et les blocages anti-bot peuvent empêcher yt-dlp de fonctionner. Le moteur ne contourne pas ces protections. Importez un fichier que vous possédez dans ces cas.
- yt-dlp évolue fréquemment. Pour le mettre à jour, reconstruisez l'image : `docker compose build --no-cache && docker compose up -d`.
- Les extraits sont classés et sélectionnés pour limiter leur chevauchement. Le nombre demandé est un maximum : une vidéo courte ou peu parlée peut donner moins de clips.
- Sous-titres en groupes d'environ six mots, modifiables dans l'éditeur. La langue automatique et le swahili dépendent de la qualité du modèle ; relisez toujours les noms propres.
- L'aperçu lit la vidéo source. Le recadrage et les sous-titres définitifs sont calculés lors de l'export. Les exports utilisent un fond flouté pour conserver l'intégralité de l'image, sans suivi automatique de visage.
- Formats 9:16 (720×1280), 1:1 (720×720), 16:9 (1280×720), MP4 H.264/AAC, SRT séparé disponible. Aucun filigrane ajouté.
- Chaque coupe ajustée doit durer au maximum 180 secondes et rester dans la vidéo.
- La clé n'est conservée que dans l'onglet. La liste des projets et leurs textes est aussi conservée dans le navigateur local. Les vidéos, les transcriptions et les rendus sont stockés sur votre moteur. La suppression depuis Mes projets efface ces fichiers du moteur. Il n'y a pas d'effacement automatique : surveillez l'espace disque.
- Un seul traitement d'analyse s'exécute à la fois, trois projets maximum en attente. Les exports de sélection sont séquentiels ; le navigateur peut demander d'autoriser les téléchargements multiples.
- Une reprise du moteur marque les analyses interrompues en erreur. Relancez la vidéo pour recommencer.
- Le moteur expose une API protégée par une clé unique. Utilisez un reverse proxy HTTPS et réservez l'accès aux appareils de confiance. Aucun achat, abonnement ou serveur payant n'est créé automatiquement.

## Dépannage

`docker compose logs --tail 100` affiche les erreurs du moteur. Aucun journal HTTP ne contient votre clé. Vérifiez la mémoire, le téléchargement du modèle et la présence d'une piste audio.

Si « Moteur inaccessible » apparaît, vérifiez l'URL, le certificat HTTPS et ALLOWED_ORIGINS. Le studio local http://localhost:8080 évite les restrictions du navigateur vers des réseaux locaux depuis une page HTTPS distante.

## API

Toutes les routes /api requièrent `Authorization: Bearer VOTRE_CLE`.

GET /api/health — état du moteur
GET /api/jobs — liste des projets
POST /api/jobs — JSON {url, language, min_duration, max_duration, count}
POST /api/upload?name=video.mp4&language=auto&min_duration=20&max_duration=45&count=6 — corps vidéo brut, Content-Type video/mp4
GET /api/jobs/{id} — état, transcription, extraits
POST /api/export/{id} — JSON {start,end,cues:[{start,end,text}],aspect,style,subtitles}
GET /api/files/{id}/{fichier} — source ou export
DELETE /api/jobs/{id} — suppression (uniquement après le traitement)
