# Live Transcript - Guide d'installation

## Prérequis

### 1. Python 3.8+
```bash
python --version
```

### 2. Dépendances Python
```bash
cd d:\dev\PIM\backend
pip install -r requirements.txt
```

## Lancer le serveur

```bash
cd d:\dev\PIM\backend
python app_live_flutter.py
```

Le serveur démarre sur: http://127.0.0.1:5000

## Utilisation dans l'app Flutter

### Microphone Local
1. Lancez l'app Flutter
2. Cliquez sur "Microphone Local"
3. Cliquez sur "Démarrer"
4. Parlez dans votre microphone
5. La transcription s'affiche en temps réel

### Live Stream (YouTube, Twitch...)
1. Lancez l'app Flutter
2. Cliquez sur "Live Stream"
3. Entrez l'URL du live (YouTube, Twitch, Facebook, etc.)
   - Exemple: `https://www.youtube.com/watch?v=...`
4. Cliquez sur "Démarrer"
5. Attendez 5-10 secondes pour que la transcription commence
6. La transcription du live s'affiche en temps réel

## Dépannage

### "yt-dlp not found"
```bash
pip install --upgrade yt-dlp
```

### Le stream ne marche pas
- Vérifiez que l'URL est valide (YouTube, Twitch, Facebook, etc.)
- Attendez 10-15 secondes pour que la connection s'établisse
- Pour YouTube: l'URL doit être publique (pas en privé)
- Vérifiez les erreurs dans la console du serveur

### La transcription est lente
C'est normal car Whisper traite l'audio localement. Les modèles plus gros sont plus précis mais plus lents.

### Mon microphone ne marche baguette
Vérifiez que votre microphone est bien connecté et sélectionné dans les paramètres Windows.

```bash
# Pour voir les appareils audio disponibles:
python -c "import sounddevice as sd; print(sd.query_devices())"
```

