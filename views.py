"""Vues et composants Discord (modals, selects, boutons) pour le bot."""
import discord
from discord import ui
import constants

# Découpage des centres d'intérêt en catégories pour les proposer par petits groupes
INTEREST_CATEGORIES = {
    "Divertissement": constants.INTERESTS[0:11],
    "Sport & bien-être": constants.INTERESTS[11:22],
    "Créativité": constants.INTERESTS[22:29],
    "Style de vie": constants.INTERESTS[29:36],
    "Tech & savoir": constants.INTERESTS[36:43],
    "Social": constants.INTERESTS[43:48],
}

# Stocke l'état d'inscription en cours par utilisateur (en mémoire)
# { user_id: {"data": {...}, "step": int} }
REGISTRATION_SESSIONS = {}


class BasicInfoModal(ui.Modal, title="Ton profil — Infos de base"):
    prenom = ui.TextInput(label="Prénom", max_length=30)
    age = ui.TextInput(label="Âge", max_length=3)
    localisation = ui.TextInput(label="Ville / région", max_length=50)
    description = ui.TextInput(
        label="Décris-toi en quelques mots", style=discord.TextStyle.paragraph, max_length=300
    )
    icebreaker = ui.TextInput(
        label="Une question à poser à ton match", style=discord.TextStyle.paragraph,
        max_length=200, required=False,
    )

    def __init__(self, on_complete):
        super().__init__()
        self.on_complete = on_complete

    async def on_submit(self, interaction: discord.Interaction):
        try:
            age_int = int(self.age.value)
        except ValueError:
            await interaction.response.send_message(
                "L'âge doit être un nombre. Relance /inscription pour réessayer.", ephemeral=True
            )
            return

        if age_int < constants.MIN_AGE:
            await interaction.response.send_message(
                "Ce service est réservé aux personnes majeures (18 ans et plus). "
                "Ton inscription ne peut pas continuer.",
                ephemeral=True,
            )
            REGISTRATION_SESSIONS.pop(interaction.user.id, None)
            return

        data = {
            "prenom": self.prenom.value.strip(),
            "age": age_int,
            "localisation": self.localisation.value.strip(),
            "description": self.description.value.strip(),
            "icebreaker": self.icebreaker.value.strip(),
        }
        await self.on_complete(interaction, data)


class SingleChoiceSelect(ui.Select):
    def __init__(self, options_list, placeholder, on_complete):
        options = [discord.SelectOption(label=o) for o in options_list]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)
        self.on_complete = on_complete

    async def callback(self, interaction: discord.Interaction):
        await self.on_complete(interaction, self.values[0])


class SingleChoiceView(ui.View):
    def __init__(self, options_list, placeholder, on_complete):
        super().__init__(timeout=600)
        self.add_item(SingleChoiceSelect(options_list, placeholder, on_complete))


class InterestCategorySelect(ui.Select):
    def __init__(self, category_name, items, on_complete):
        options = [discord.SelectOption(label=i) for i in items]
        super().__init__(
            placeholder=f"{category_name} (optionnel)",
            min_values=0,
            max_values=len(options),
            options=options,
        )
        self.on_complete = on_complete

    async def callback(self, interaction: discord.Interaction):
        await self.on_complete(interaction, self.values)


class InterestCategoryView(ui.View):
    def __init__(self, category_name, items, on_complete):
        super().__init__(timeout=600)
        self.add_item(InterestCategorySelect(category_name, items, on_complete))


class LikePassView(ui.View):
    """Boutons proposés sous un profil suggéré."""

    def __init__(self, target_user_id: int, shown_user_id: int, on_like, on_pass):
        super().__init__(timeout=86400)
        self.target_user_id = target_user_id
        self.shown_user_id = shown_user_id
        self.on_like = on_like
        self.on_pass = on_pass

    @ui.button(label="❤️ Like", style=discord.ButtonStyle.success)
    async def like(self, interaction: discord.Interaction, button: ui.Button):
        await self.on_like(interaction, self.target_user_id, self.shown_user_id)
        self.disable_all_items()
        await interaction.message.edit(view=self)

    @ui.button(label="Passer", style=discord.ButtonStyle.secondary)
    async def pass_(self, interaction: discord.Interaction, button: ui.Button):
        await self.on_pass(interaction, self.target_user_id, self.shown_user_id)
        self.disable_all_items()
        await interaction.message.edit(view=self)

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True


class RevealConfirmView(ui.View):
    """Boutons pour accepter ou refuser de révéler son pseudo à son match."""

    def __init__(self, match_id: int, side: int, on_accept, on_decline):
        super().__init__(timeout=None)
        self.match_id = match_id
        self.side = side
        self.on_accept = on_accept
        self.on_decline = on_decline

    @ui.button(label="Je suis d'accord pour me révéler", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        await self.on_accept(interaction, self.match_id, self.side)

    @ui.button(label="Pas encore", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: ui.Button):
        await self.on_decline(interaction, self.match_id, self.side)


def build_profile_embed(profile: dict) -> discord.Embed:
    embed = discord.Embed(title=f"{profile['prenom']}, {profile['age']} ans", color=0xE91E63)
    embed.add_field(name="Localisation", value=profile["localisation"] or "Non précisé", inline=True)
    embed.add_field(name="Recherche", value=profile["relation_type"], inline=True)
    if profile["interests"]:
        embed.add_field(
            name="Centres d'intérêt", value=", ".join(profile["interests"]), inline=False
        )
    if profile["description"]:
        embed.add_field(name="En quelques mots", value=profile["description"], inline=False)
    if profile.get("icebreaker"):
        embed.add_field(name="💬 Pour briser la glace", value=profile["icebreaker"], inline=False)
    return embed
