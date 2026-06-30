"""Logique de compatibilité sexe/orientation et calcul du score de matching."""


def is_orientation_compatible(p1, p2):
    """Vérifie une compatibilité de base sexe/orientation entre deux profils.
    Logique simplifiée et inclusive : on regarde si l'orientation de chacun
    n'exclut pas explicitement le sexe de l'autre.
    """
    def accepts(profile, other_sexe):
        orientation = profile["orientation"]
        sexe = profile["sexe"]
        if orientation in ("Bi", "Pan", "Autre"):
            return True
        if orientation == "Hétéro":
            # Hétéro : accepte le sexe "opposé" au sens binaire classique,
            # reste permissif pour les profils non-binaires/autres.
            if sexe == "Homme":
                return other_sexe in ("Femme", "Autre", "Non-binaire")
            if sexe == "Femme":
                return other_sexe in ("Homme", "Autre", "Non-binaire")
            return True
        if orientation == "Homo":
            if sexe in ("Homme", "Femme"):
                return other_sexe == sexe or other_sexe in ("Autre", "Non-binaire")
            return True
        return True

    return accepts(p1, p2["sexe"]) and accepts(p2, p1["sexe"])


def compatibility_score(p1, p2):
    """Calcule un score de compatibilité entre deux profils (plus haut = meilleur)."""
    score = 0

    # Centres d'intérêt communs
    common_interests = set(p1["interests"]) & set(p2["interests"])
    score += len(common_interests) * 10

    # Type de relation recherché identique
    if p1["relation_type"] == p2["relation_type"]:
        score += 15

    # Écart d'âge : pénalité progressive
    age_diff = abs(p1["age"] - p2["age"])
    score -= age_diff * 2

    # Même localisation (bonus simple, comparaison de texte insensible à la casse)
    if p1["localisation"].strip().lower() == p2["localisation"].strip().lower():
        score += 10

    return score


def find_best_matches(target_profile, candidates, seen_ids, limit=3):
    """Retourne les `limit` meilleurs candidats compatibles non encore vus."""
    scored = []
    for candidate in candidates:
        if candidate["user_id"] == target_profile["user_id"]:
            continue
        if candidate["user_id"] in seen_ids:
            continue
        if not is_orientation_compatible(target_profile, candidate):
            continue
        score = compatibility_score(target_profile, candidate)
        scored.append((score, candidate))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:limit]]
