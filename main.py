"""Bot Discord de rencontre par centres d'intérêt — fichier principal."""
import os
import asyncio
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
 
import constants
import database as db
import matching
import views
 
TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = int(os.environ.get("GUILD_ID", "0")) or None
MATCH_CATEGORY_NAME = "💌 Matchs"
ROLE_NOUVEAU = "👤 Nouveau"
ROLE_MEMBRE = "❤️ Membre vérifié"
SALON_SIGNALEMENTS = "🚨signalements"
SALON_SIGNALER = "🚨signaler"
 
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
 
bot = commands.Bot(command_prefix="!", intents=intents)
 
 
# --------------------------------------------------------------------------
# BIENVENUE ET RÔLES AUTOMATIQUES
# --------------------------------------------------------------------------
 
@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    role_nouveau = discord.utils.get(guild.roles, name=ROLE_NOUVEAU)
    if role_nouveau:
        try:
            await member.add_roles(role_nouveau)
        except discord.Forbidden:
            pass
    try:
        await member.send(
            f"Bienvenue sur **MatchMind**, {member.display_name} ! 💘\n\n"
            "MatchMind est un serveur de rencontre différent : pas de photo, juste tes centres "
            "d'intérêt et ta personnalité. On se découvre d'abord, on se révèle ensuite.\n\n"
            "Pour commencer, lis le règlement sur le serveur, puis tape `/inscription` "
            "dans le salon **✨inscription** pour créer ton profil.\n\n"
            "On a hâte de te faire découvrir des personnes qui te correspondent vraiment ! ✨"
        )
    except discord.Forbidden:
        pass
 
 
async def assign_membre_verifie(user_id: int, guild: discord.Guild):
    try:
        member = await guild.fetch_member(user_id)
    except discord.NotFound:
        member = None
    if not member:
        return
    role_nouveau = discord.utils.get(guild.roles, name=ROLE_NOUVEAU)
    role_membre = discord.utils.get(guild.roles, name=ROLE_MEMBRE)
    try:
        if role_nouveau and role_nouveau in member.roles:
            await member.remove_roles(role_nouveau)
        if role_membre and role_membre not in member.roles:
            await member.add_roles(role_membre)
    except Exception as e:
        print(f"Erreur role: {e}")
 
 
# --------------------------------------------------------------------------
# SIGNALEMENT
# --------------------------------------------------------------------------
 
MOTIFS_SIGNALEMENT = [
    "Harcèlement / comportement inapproprié",
    "Contenu interdit (photo non sollicitée, contenu sexuel...)",
    "Suspicion de mineur",
    "Faux profil / arnaque",
    "Autre",
]
 
 
class SignalementModal(ui.Modal, title="Signalement"):
    motif = ui.TextInput(
        label="Motif du signalement",
        placeholder="Harcèlement, contenu inapproprié, faux profil...",
        max_length=100,
    )
    description = ui.TextInput(
        label="Décris le problème",
        style=discord.TextStyle.paragraph,
        placeholder="Décris précisément ce qui s'est passé...",
        max_length=500,
    )
    personne = ui.TextInput(
        label="Pseudo ou ID de la personne concernée",
        placeholder="Ex: Pseudo#1234 ou laisse vide si inconnu",
        required=False,
        max_length=100,
    )
 
    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        salon = discord.utils.get(guild.text_channels, name=SALON_SIGNALEMENTS)
 
        if salon is None:
            await interaction.response.send_message(
                "Ton signalement a bien été reçu, un modérateur va s'en occuper.",
                ephemeral=True,
            )
            return
 
        embed = discord.Embed(
            title="🚨 Nouveau signalement",
            color=0xFF0000,
        )
        embed.add_field(name="Motif", value=self.motif.value, inline=False)
        embed.add_field(name="Description", value=self.description.value, inline=False)
        if self.personne.value:
            embed.add_field(name="Personne concernée", value=self.personne.value, inline=True)
        embed.add_field(
            name="Salon",
            value=interaction.channel.mention if interaction.channel else "Inconnu",
            inline=True,
        )
        embed.set_footer(text=f"Signalement anonyme — reçu le {discord.utils.utcnow().strftime('%d/%m/%Y à %H:%M')}")
 
        await salon.send(embed=embed)
        await interaction.response.send_message(
            "Ton signalement a bien été transmis aux modérateurs de façon anonyme. "
            "Merci de contribuer à la sécurité de MatchMind. 🛡️",
            ephemeral=True,
        )
 
 
@bot.tree.command(name="signaler", description="Signaler un problème ou un comportement inapproprié")
async def signaler(interaction: discord.Interaction):
    await interaction.response.send_modal(SignalementModal())
 
 
async def post_signalement_button(guild: discord.Guild):
    """Poste le message permanent avec le bouton Signaler dans #🚨signaler."""
    salon = discord.utils.get(guild.text_channels, name=SALON_SIGNALER)
    if salon is None:
        return
 
    async for message in salon.history(limit=10):
        if message.author == guild.me:
            return
 
    class SignalerView(ui.View):
        def __init__(self):
            super().__init__(timeout=None)
 
        @ui.button(label="🚨 Signaler un problème", style=discord.ButtonStyle.danger, custom_id="btn_signaler")
        async def signaler_btn(self, interaction: discord.Interaction, button: ui.Button):
            await interaction.response.send_modal(SignalementModal())
 
    embed = discord.Embed(
        title="🛡️ Signaler un problème",
        description=(
            "Tu as été témoin ou victime d'un comportement inapproprié ?\n\n"
            "Clique sur le bouton ci-dessous pour envoyer un signalement **anonyme** "
            "directement aux modérateurs.\n\n"
            "Exemples : harcèlement, contenu interdit, faux profil, suspicion de mineur..."
        ),
        color=0xFF6B6B,
    )
    embed.set_footer(text="Ton signalement restera anonyme et confidentiel.")
    await salon.send(embed=embed, view=SignalerView())
 
 
class SignalerPersistentView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
 
    @ui.button(label="🚨 Signaler un problème", style=discord.ButtonStyle.danger, custom_id="btn_signaler")
    async def signaler_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SignalementModal())
 
 
# --------------------------------------------------------------------------
# BOUTON SIGNALEMENT DANS LES SALONS DE MATCH
# --------------------------------------------------------------------------
 
class MatchSignalerView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
 
    @ui.button(label="🚨 Signaler ce match", style=discord.ButtonStyle.danger, custom_id="btn_match_signaler")
    async def signaler_match(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SignalementModal())
 
 
# --------------------------------------------------------------------------
# INSCRIPTION
# --------------------------------------------------------------------------
 
@bot.tree.command(name="inscription", description="Crée ou met à jour ton profil de rencontre")
async def inscription(interaction: discord.Interaction):
    views.REGISTRATION_SESSIONS[interaction.user.id] = {"data": {}, "interests": []}
 
    async def after_basic_info(modal_interaction: discord.Interaction, data: dict):
        views.REGISTRATION_SESSIONS[modal_interaction.user.id]["data"].update(data)
        await modal_interaction.response.send_message(
            "Question suivante : ton sexe.",
            view=views.SingleChoiceView(constants.SEXES, "Choisis ton sexe", make_sexe_handler()),
            ephemeral=True,
        )
 
    modal = views.BasicInfoModal(after_basic_info)
    await interaction.response.send_modal(modal)
 
 
def make_sexe_handler():
    async def handler(interaction: discord.Interaction, value: str):
        views.REGISTRATION_SESSIONS[interaction.user.id]["data"]["sexe"] = value
        await interaction.response.send_message(
            "Question suivante : ton orientation.",
            view=views.SingleChoiceView(
                constants.ORIENTATIONS, "Choisis ton orientation", make_orientation_handler()
            ),
            ephemeral=True,
        )
    return handler
 
 
def make_orientation_handler():
    async def handler(interaction: discord.Interaction, value: str):
        views.REGISTRATION_SESSIONS[interaction.user.id]["data"]["orientation"] = value
        await interaction.response.send_message(
            "Question suivante : que recherches-tu ?",
            view=views.SingleChoiceView(
                constants.RELATION_TYPES, "Type de relation recherchée", make_relation_handler()
            ),
            ephemeral=True,
        )
    return handler
 
 
def make_relation_handler():
    async def handler(interaction: discord.Interaction, value: str):
        views.REGISTRATION_SESSIONS[interaction.user.id]["data"]["relation_type"] = value
        await interaction.response.send_message(
            "Dernière étape : choisis tes centres d'intérêt, catégorie par catégorie.\n"
            "Tu peux n'en sélectionner aucun dans certaines catégories.",
            ephemeral=True,
        )
        await send_next_interest_category(interaction, list(views.INTEREST_CATEGORIES.items()), 0)
    return handler
 
 
async def send_next_interest_category(interaction, categories, index):
    user_id = interaction.user.id
 
    if index >= len(categories):
        await finalize_registration(interaction)
        return
 
    category_name, items = categories[index]
 
    async def handler(select_interaction: discord.Interaction, selected: list):
        views.REGISTRATION_SESSIONS[user_id]["interests"].extend(selected)
        await select_interaction.response.send_message(
            f"Catégorie suivante...", ephemeral=True
        )
        await send_next_interest_category(select_interaction, categories, index + 1)
 
    await interaction.followup.send(
        f"**{category_name}**",
        view=views.InterestCategoryView(category_name, items, handler),
        ephemeral=True,
    )
 
 
async def finalize_registration(interaction: discord.Interaction):
    user_id = interaction.user.id
    session = views.REGISTRATION_SESSIONS.pop(user_id, None)
    if not session:
        return
 
    data = session["data"]
    data["interests"] = session["interests"]
 
    await db.upsert_profile(user_id, **data)
 
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None)
    if guild:
        await assign_membre_verifie(user_id, guild)
 
    await interaction.followup.send(
        "Ton profil est enregistré ! Bienvenue dans MatchMind ❤️\n"
        "Tu recevras des suggestions de profils compatibles directement en messages privés, "
        "plusieurs fois par jour.",
        ephemeral=True,
    )
 
 
# --------------------------------------------------------------------------
# SUGGESTIONS QUOTIDIENNES
# --------------------------------------------------------------------------
 
async def on_like(interaction: discord.Interaction, target_user_id: int, shown_user_id: int):
    await db.add_like(target_user_id, shown_user_id)
    await interaction.response.send_message("Like envoyé ❤️", ephemeral=True)
 
    mutual = await db.has_liked(shown_user_id, target_user_id)
    if mutual:
        await create_match_channels(target_user_id, shown_user_id)
    else:
        try:
            liked_user = await bot.fetch_user(shown_user_id)
            await liked_user.send(
                "✨ Quelqu'un s'intéresse à toi ! Découvre qui dans tes prochaines "
                "suggestions de profils du jour."
            )
        except discord.Forbidden:
            pass
 
 
async def on_pass(interaction: discord.Interaction, target_user_id: int, shown_user_id: int):
    await interaction.response.send_message("Profil passé.", ephemeral=True)
 
 
@tasks.loop(hours=8)
async def send_daily_suggestions():
    profiles = await db.get_all_active_profiles()
    for profile in profiles:
        try:
            user = await bot.fetch_user(profile["user_id"])
        except discord.NotFound:
            continue
 
        candidates = await db.get_all_active_profiles(exclude_user_id=profile["user_id"])
        seen_ids = await db.get_seen_ids(profile["user_id"])
        best = matching.find_best_matches(
            profile, candidates, seen_ids, limit=constants.PROFILES_PER_DAY
        )
 
        for candidate in best:
            await db.mark_seen(profile["user_id"], candidate["user_id"])
            embed = views.build_profile_embed(candidate)
            view = views.LikePassView(profile["user_id"], candidate["user_id"], on_like, on_pass)
            try:
                await user.send(embed=embed, view=view)
            except discord.Forbidden:
                break
 
 
@send_daily_suggestions.before_loop
async def before_send_daily_suggestions():
    await bot.wait_until_ready()
 
 
# --------------------------------------------------------------------------
# CRÉATION DES SALONS DE MATCH ANONYMES
# --------------------------------------------------------------------------
 
async def get_or_create_match_category(guild: discord.Guild):
    category = discord.utils.get(guild.categories, name=MATCH_CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(MATCH_CATEGORY_NAME)
    return category
 
 
async def create_match_channels(user1_id: int, user2_id: int):
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else bot.guilds[0]
    if guild is None:
        return
 
    existing = await db.get_existing_match(user1_id, user2_id)
    if existing and existing.get("channel1_id"):
        return
 
    match_id = existing["match_id"] if existing else await db.create_match(user1_id, user2_id)
 
    category = await get_or_create_match_category(guild)
    member1 = guild.get_member(user1_id)
    member2 = guild.get_member(user2_id)
 
    overwrites1 = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True),
    }
    if member1:
        overwrites1[member1] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
 
    overwrites2 = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True),
    }
    if member2:
        overwrites2[member2] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
 
    channel1 = await guild.create_text_channel(
        f"match-{match_id}-a", category=category, overwrites=overwrites1
    )
    channel2 = await guild.create_text_channel(
        f"match-{match_id}-b", category=category, overwrites=overwrites2
    )
 
    webhook1 = await channel1.create_webhook(name="Match anonyme")
    webhook2 = await channel2.create_webhook(name="Match anonyme")
 
    await db.set_match_channels(match_id, channel1.id, channel2.id, webhook1.url, webhook2.url)
 
    intro = (
        "🎉 **C'est un match !**\n"
        "Vous pouvez maintenant discuter ici de façon anonyme : votre pseudo Discord "
        "n'est pas visible par l'autre personne. Après quelques échanges, vous pourrez "
        "choisir ensemble de révéler vos profils si vous le souhaitez.\n\n"
        "Merci de rester respectueux·se. En cas de souci, utilise le bouton ci-dessous."
    )
    await channel1.send(intro, view=MatchSignalerView())
    await channel2.send(intro, view=MatchSignalerView())
 
    if member1:
        embed = views.build_profile_embed(await db.get_profile(user2_id))
        await channel1.send("Voici un rappel du profil de ton match :", embed=embed)
    if member2:
        embed = views.build_profile_embed(await db.get_profile(user1_id))
        await channel2.send("Voici un rappel du profil de ton match :", embed=embed)
 
 
# --------------------------------------------------------------------------
# RELAIS DES MESSAGES ANONYMES
# --------------------------------------------------------------------------
 
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
 
    match = await db.get_match_by_channel(message.channel.id)
    if match and not match["revealed"]:
        if message.channel.id == match["channel1_id"]:
            side, other_webhook_url = 1, match["webhook2_url"]
        elif message.channel.id == match["channel2_id"]:
            side, other_webhook_url = 2, match["webhook1_url"]
        else:
            await bot.process_commands(message)
            return
 
        if other_webhook_url:
            webhook = discord.Webhook.from_url(other_webhook_url, client=bot)
            try:
                await webhook.send(
                    content=message.content or "(message vide)",
                    username="Match anonyme",
                    files=[await a.to_file() for a in message.attachments] if message.attachments else None,
                )
            except discord.HTTPException:
                pass
 
        await db.increment_message_count(match["match_id"], side)
        updated = await db.get_match_by_channel(message.channel.id)
 
        if updated["count1"] >= constants.MESSAGES_BEFORE_REVEAL and \
           updated["count2"] >= constants.MESSAGES_BEFORE_REVEAL and not updated["revealed"]:
            await propose_reveal(updated)
 
    await bot.process_commands(message)
 
 
async def propose_reveal(match: dict):
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else bot.guilds[0]
    channel1 = guild.get_channel(match["channel1_id"])
    channel2 = guild.get_channel(match["channel2_id"])
 
    if channel1 and not match["reveal_agree1"]:
        await channel1.send(
            "Vous semblez bien vous entendre ! Voulez-vous révéler vos pseudos Discord ?",
            view=views.RevealConfirmView(match["match_id"], 1, on_reveal_accept, on_reveal_decline),
        )
    if channel2 and not match["reveal_agree2"]:
        await channel2.send(
            "Vous semblez bien vous entendre ! Voulez-vous révéler vos pseudos Discord ?",
            view=views.RevealConfirmView(match["match_id"], 2, on_reveal_accept, on_reveal_decline),
        )
 
 
async def on_reveal_accept(interaction: discord.Interaction, match_id: int, side: int):
    await db.set_reveal_agree(match_id, side)
    await interaction.response.send_message("D'accord, en attente de l'autre personne...", ephemeral=True)
 
    match = await db.get_match_by_channel(interaction.channel.id)
    if match["reveal_agree1"] and match["reveal_agree2"]:
        await db.set_revealed(match_id)
        guild = interaction.guild
        channel1 = guild.get_channel(match["channel1_id"])
        channel2 = guild.get_channel(match["channel2_id"])
        user1_mention = f"<@{match['user1_id']}>"
        user2_mention = f"<@{match['user2_id']}>"
        if channel1:
            await channel1.send(f"Vous êtes tous les deux d'accord ! Voici qui tu parlais : {user2_mention}")
        if channel2:
            await channel2.send(f"Vous êtes tous les deux d'accord ! Voici qui tu parlais : {user1_mention}")
 
 
async def on_reveal_decline(interaction: discord.Interaction, match_id: int, side: int):
    await interaction.response.send_message(
        "Pas de souci, vous restez anonymes pour l'instant.", ephemeral=True
    )
 
 
# --------------------------------------------------------------------------
# DÉMARRAGE
# --------------------------------------------------------------------------
 
@bot.event
async def on_ready():
    await db.init_db()
    bot.add_view(SignalerPersistentView())
    bot.add_view(MatchSignalerView())
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
        else:
            synced = await bot.tree.sync()
        print(f"{len(synced)} commande(s) synchronisée(s) : {[c.name for c in synced]}")
    except Exception as e:
        print(f"Erreur de synchronisation des commandes : {e}")
 
    if not send_daily_suggestions.is_running():
        send_daily_suggestions.start()
 
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None)
    if guild:
        await post_signalement_button(guild)
 
    print(f"Connecté en tant que {bot.user}")
 
 
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("La variable d'environnement DISCORD_TOKEN n'est pas définie.")
    bot.run(TOKEN)
