"""Constantes utilisées par le bot : listes de choix pour les formulaires."""

INTERESTS = [
    # Divertissement
    "Cinéma", "Séries", "Anime/Manga", "Musique", "Concerts/Festivals",
    "Théâtre", "Humour/Stand-up", "Jeux vidéo", "Jeux de société", "Lecture", "Podcasts",
    # Sport et bien-être
    "Fitness/Musculation", "Course à pied", "Yoga", "Randonnée", "Sports collectifs",
    "Sports de combat", "Vélo", "Natation", "Escalade", "Danse", "Méditation",
    # Créativité
    "Dessin/Peinture", "Photographie", "Écriture", "Instrument de musique",
    "Bricolage/DIY", "Mode/Stylisme", "Décoration",
    # Style de vie
    "Cuisine", "Voyage", "Nature/Plein air", "Animaux", "Spiritualité",
    "Développement personnel", "Écologie",
    # Tech et savoir
    "Esport", "Informatique/Tech", "Sciences", "Histoire", "Langues étrangères",
    "Entrepreneuriat", "Crypto/Finance",
    # Social
    "Soirées/Fêtes", "Bars/Restaurants", "Bénévolat", "Débats/Philosophie", "Astrologie",
]

SEXES = ["Homme", "Femme", "Non-binaire", "Autre"]

ORIENTATIONS = ["Hétéro", "Homo", "Bi", "Pan", "Autre"]

RELATION_TYPES = ["Relation sérieuse", "Plus léger", "Je ne sais pas encore", "Amitié"]

# Nombre de messages (de chaque côté) avant de proposer la révélation des pseudos
MESSAGES_BEFORE_REVEAL = 20

# Nombre de profils proposés par jour, et heures d'envoi (heure du serveur)
PROFILES_PER_DAY = 3
SEND_HOURS_UTC = [8, 13, 19]  # à ajuster selon le fuseau horaire visé

MIN_AGE = 18
