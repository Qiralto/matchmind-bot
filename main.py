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
ROLE_FONDATEUR = "👑 Fondateur"
ROLE_SUSPENDU = "🚫 Suspendu"

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
    # Message public dans #présentation
    for ch in member.guild.text_channels:
        if "presentation" in ch.name.lower() or "présentation" in ch.name.lower():
            try:
                embed = discord.Embed(
                    description=f"👋 **{member.display_name}** vient de rejoindre MatchMind ! Bienvenue parmi nous 💘",
                    color=0xE91E8C
                )
                embed.set_footer(text=f"Membre #{member.guild.member_count} sur MatchMind")
                await ch.send(embed=embed)
            except discord.Forbidden:
                pass
            break

    try:
        await member.send(
            f"Bienvenue sur **MatchMind**, {member.display_name} ! 💘\n\n"
            "Tu rejoins l'aventure au tout début de MatchMind, et c'est une chance ! "
            "Les premiers membres sont ceux qui vont construire cette communauté et en profiter en premier. "
            "Merci d'être là ! 🌟\n\n"
            "MatchMind est un serveur de rencontre différent : pas de photo, pas de jugement sur l'apparence. "
            "On se découvre par nos centres d'intérêt et notre personnalité. "
            "On discute anonymement, et on se révèle quand on est prêt(e).\n\n"
            "Pour commencer :\n"
            "1️⃣ Lis le règlement dans **#📜règles**\n"
            "2️⃣ Tape `/inscription` dans **#✨inscription** pour créer ton profil\n"
            "3️⃣ Laisse le bot faire la magie ! 🤖\n\n"
            "Des questions ? Pose-les dans **#💬discussions**. On est là pour toi ! 💌"
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

        # Si le signalement vient d'un salon de match, copier le transcript
        if interaction.channel:
            match = await db.get_match_by_channel(interaction.channel.id)
            if match:
                # Récupérer les vrais pseudos pour la modération
                try:
                    user1 = await bot.fetch_user(match["user1_id"])
                    user2 = await bot.fetch_user(match["user2_id"])
                    label1 = f"{user1.name} (ID:{user1.id})"
                    label2 = f"{user2.name} (ID:{user2.id})"
                except Exception:
                    label1 = f"User ID:{match['user1_id']}"
                    label2 = f"User ID:{match['user2_id']}"

                # Lire les deux salons et combiner dans l'ordre chronologique
                all_messages = []
                guild_obj = interaction.guild

                channel1_obj = guild_obj.get_channel(match["channel1_id"])
                channel2_obj = guild_obj.get_channel(match["channel2_id"])

                # On lit uniquement le salon A :
                # - messages directs = personne A
                # - messages webhook = personne B (relayés depuis salon B)
                if channel1_obj:
                    async for msg in channel1_obj.history(limit=100, oldest_first=True):
                        if not msg.author.bot and not msg.webhook_id:
                            all_messages.append((msg.created_at, f"[{msg.created_at.strftime('%H:%M')}] {label1} : {msg.content}"))
                        elif msg.webhook_id and msg.content and not msg.content.startswith("🎉") and "Signaler" not in msg.content:
                            all_messages.append((msg.created_at, f"[{msg.created_at.strftime('%H:%M')}] {label2} : {msg.content}"))

                all_messages.sort(key=lambda x: x[0])
                messages = [m[1] for m in all_messages]

                if messages:
                    transcript = "\n".join(messages)
                    if len(transcript) > 3900:
                        transcript = transcript[-3900:] + "\n[... messages précédents tronqués]"
                    transcript_embed = discord.Embed(
                        title="📋 Transcript de la conversation",
                        description=f"```{transcript}```",
                        color=0xFF6B6B,
                    )
                    transcript_embed.add_field(
                        name="Identités (modération uniquement)",
                        value=f"Salon A : {label1}\nSalon B : {label2}",
                        inline=False
                    )
                    transcript_embed.set_footer(text="⚠️ Confidentiel — usage modération uniquement")
                    await salon.send(embed=transcript_embed)

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


class MatchActionsView(ui.View):
    def __init__(self, match_id: int):
        super().__init__(timeout=None)
        self.match_id = match_id

    @ui.button(label="🚨 Signaler", style=discord.ButtonStyle.danger, custom_id="btn_match_signaler_v2")
    async def signaler(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SignalementModal())

    @ui.button(label="❌ Fermer ce match", style=discord.ButtonStyle.secondary, custom_id="btn_fermer_match_v2")
    async def fermer(self, interaction: discord.Interaction, button: ui.Button):
        match = await db.get_match_by_channel(interaction.channel.id)
        if not match:
            await interaction.response.send_message("Salon introuvable.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Es-tu sûr(e) de vouloir fermer ce match ? Cette action est définitive et supprimera les deux salons.",
            view=ConfirmerFermetureView(match["match_id"]),
            ephemeral=True
        )



@bot.event
async def on_member_remove(member: discord.Member):
    """Supprime le profil d'un membre quand il quitte le serveur."""
    await db.delete_profile(member.id)
    print(f"Profil supprimé pour {member.name} (ID:{member.id}) — a quitté le serveur")

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

    # Permissions strictes : seuls les deux membres et le bot ont accès
    # L'owner est explicitement bloqué sur son compte personnel
    OWNER_ID = 364449220461199370
    owner = guild.get_member(OWNER_ID)

    overwrites1 = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            read_message_history=True, manage_webhooks=True
        ),
    }
    if member1:
        overwrites1[member1] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )
    if owner and owner != member1:
        overwrites1[owner] = discord.PermissionOverwrite(view_channel=False)

    overwrites2 = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            read_message_history=True, manage_webhooks=True
        ),
    }
    if member2:
        overwrites2[member2] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )
    if owner and owner != member2:
        overwrites2[owner] = discord.PermissionOverwrite(view_channel=False)

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
        "Merci de rester respectueux·se. Utilise les boutons ci-dessous si besoin."
    )
    await channel1.send(intro, view=MatchActionsView(match_id))
    await channel2.send(intro, view=MatchActionsView(match_id))

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
                    files=[await a.to_file() for a in message.attachments] if message.attachments else [],
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

        # Annonce anonyme dans #temoignages
        salon_temoignages = None
        for ch in guild.text_channels:
            name = ch.name.lower().replace("é", "e").replace("è", "e").replace("ê", "e")
            if "temoignage" in name:
                salon_temoignages = ch
                break
        if salon_temoignages:
            msg = (
                "\U0001f498 Un nouveau match vient d'etre revele sur MatchMind...\n"
                "Qui sait ce que l'avenir leur reserve ? \U0001f31f"
            )
            embed = discord.Embed(description=msg, color=0xE91E8C)
            embed.set_footer(text="Inscris-toi et trouve ta moitié 💌")
            await salon_temoignages.send(embed=embed)


async def on_reveal_decline(interaction: discord.Interaction, match_id: int, side: int):
    await interaction.response.send_message(
        "Pas de souci, vous restez anonymes pour l'instant.", ephemeral=True
    )




@bot.tree.command(name="voir-match", description="[ADMIN] Accéder temporairement à un salon de match")
@app_commands.describe(salon="Le salon de match à consulter")
async def voir_match(interaction: discord.Interaction, salon: discord.TextChannel):
    guild = interaction.guild
    fondateur = discord.utils.get(guild.roles, name=ROLE_FONDATEUR)
    if not fondateur or fondateur not in interaction.user.roles:
        await interaction.response.send_message(
            "Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    # Vérifier que c'est bien un salon de match
    match = await db.get_match_by_channel(salon.id)
    if not match:
        await interaction.response.send_message(
            "Ce salon n'est pas un salon de match.", ephemeral=True
        )
        return

    # Donner accès temporaire
    await salon.set_permissions(interaction.user, view_channel=True, send_messages=False, read_message_history=True)
    await interaction.response.send_message(
        f"Tu as maintenant accès en lecture à {salon.mention}. Utilise `/quitter-match` pour en sortir.",
        ephemeral=True
    )


@bot.tree.command(name="quitter-match", description="[ADMIN] Quitter un salon de match consulté")
@app_commands.describe(salon="Le salon de match à quitter")
async def quitter_match(interaction: discord.Interaction, salon: discord.TextChannel):
    guild = interaction.guild
    fondateur = discord.utils.get(guild.roles, name=ROLE_FONDATEUR)
    if not fondateur or fondateur not in interaction.user.roles:
        await interaction.response.send_message(
            "Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    # Retirer l'accès
    await salon.set_permissions(interaction.user, view_channel=False)
    await interaction.response.send_message(
        f"Tu n'as plus accès à {salon.mention}.",
        ephemeral=True
    )


class FermerMatchView(ui.View):
    def __init__(self, match_id: int):
        super().__init__(timeout=None)
        self.match_id = match_id

    @ui.button(label="❌ Fermer ce match", style=discord.ButtonStyle.danger, custom_id="btn_fermer_match")
    async def fermer(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Es-tu sûr(e) de vouloir fermer ce match ? Cette action est définitive.",
            view=ConfirmerFermetureView(self.match_id),
            ephemeral=True
        )


class ConfirmerFermetureView(ui.View):
    def __init__(self, match_id: int):
        super().__init__(timeout=60)
        self.match_id = match_id

    @ui.button(label="Oui, fermer le match", style=discord.ButtonStyle.danger)
    async def confirmer(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Match fermé. Bonne continuation !", ephemeral=True)
        guild = interaction.guild
        match = await db.get_match_by_channel(interaction.channel.id)
        if not match:
            return

        channel1 = guild.get_channel(match["channel1_id"])
        channel2 = guild.get_channel(match["channel2_id"])

        msg_fermeture = "Ce match a été fermé. Les salons vont être supprimés dans 10 secondes."
        if channel1:
            await channel1.send(msg_fermeture)
        if channel2:
            await channel2.send(msg_fermeture)

        import asyncio
        await asyncio.sleep(10)

        if channel1:
            try:
                await channel1.delete()
            except Exception:
                pass
        if channel2:
            try:
                await channel2.delete()
            except Exception:
                pass

    @ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def annuler(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Fermeture annulée.", ephemeral=True)


# --------------------------------------------------------------------------
# SYSTÈME DE TÉMOIGNAGES
# --------------------------------------------------------------------------

class TemoignageModal(ui.Modal, title="Partager mon témoignage"):
    temoignage = ui.TextInput(
        label="Ton témoignage",
        style=discord.TextStyle.paragraph,
        placeholder="Raconte ton expérience sur MatchMind...",
        max_length=500,
    )
    anonyme = ui.TextInput(
        label="Anonyme ? (oui/non)",
        placeholder="Tape 'oui' pour rester anonyme, 'non' pour afficher ton pseudo",
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        role_membre = discord.utils.get(guild.roles, name=ROLE_MEMBRE)
        if not role_membre or role_membre not in interaction.user.roles:
            await interaction.response.send_message(
                "Tu dois avoir complété ton inscription pour partager un témoignage.",
                ephemeral=True
            )
            return

        salon = None
        for ch in guild.text_channels:
            name = ch.name.lower().replace("é", "e").replace("è", "e").replace("ê", "e")
            if "temoignage" in name:
                salon = ch
                break

        if not salon:
            await interaction.response.send_message(
                "Salon introuvable.", ephemeral=True
            )
            return

        est_anonyme = self.anonyme.value.lower().strip() in ("oui", "o", "yes", "y")
        auteur = "Anonyme ✨" if est_anonyme else f"{interaction.user.display_name} 💌"

        embed = discord.Embed(
            title="💝 Témoignage",
            description=f'"{self.temoignage.value}"',
            color=0xE91E8C
        )
        embed.set_footer(text=f"— {auteur}")
        await salon.send(embed=embed)
        await interaction.response.send_message(
            "Ton témoignage a été partagé, merci ! 💌",
            ephemeral=True
        )


class TemoignageView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="📝 Partager mon témoignage",
        style=discord.ButtonStyle.primary,
        custom_id="btn_temoignage"
    )
    async def partager(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(TemoignageModal())


async def post_temoignage_button(guild: discord.Guild):
    """Poste le message avec le bouton dans #témoignages au démarrage."""
    salon = None
    for ch in guild.text_channels:
        name = ch.name.lower().replace("é", "e").replace("è", "e").replace("ê", "e")
        if "temoignage" in name:
            salon = ch
            break
    if not salon:
        return

    async for message in salon.history(limit=20):
        if message.author == guild.me and message.components:
            return

    embed = discord.Embed(
        title="💝 Témoignages MatchMind",
        description=(
            "Tu as vécu une belle expérience sur MatchMind ?\n"
            "Un match qui s'est bien passé, une conversation qui t'a surpris(e) ?\n\n"
            "Partage ton histoire avec la communauté ! Tu peux rester **anonyme** si tu préfères.\n\n"
            "⚠️ Réservé aux membres ayant complété leur inscription."
        ),
        color=0xE91E8C
    )
    await salon.send(embed=embed, view=TemoignageView())


# --------------------------------------------------------------------------
# SYSTÈME DE SUGGESTIONS PREMIUM
# --------------------------------------------------------------------------

SALON_SUGGESTIONS = "💡suggestions-vip"
SALON_SUGGESTIONS_RECUES = "📋suggestions-reçues"
ROLE_PREMIUM = "💎Premium"


class SuggestionModal(ui.Modal, title="Faire une suggestion"):
    suggestion = ui.TextInput(
        label="Ta suggestion",
        style=discord.TextStyle.paragraph,
        placeholder="Décris ton idée pour améliorer MatchMind...",
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        role_premium = discord.utils.get(guild.roles, name=ROLE_PREMIUM)
        if not role_premium or role_premium not in interaction.user.roles:
            await interaction.response.send_message(
                "Ce salon est réservé aux membres Premium.",
                ephemeral=True
            )
            return

        salon_recues = None
        for ch in guild.text_channels:
            name = ch.name.lower().replace("é", "e").replace("è", "e").replace("ê", "e").replace("ç", "c")
            if "suggestion" in name and ("recu" in name or "recue" in name):
                salon_recues = ch
                break

        if not salon_recues:
            await interaction.response.send_message(
                "Erreur lors de l'envoi de la suggestion.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="💡 Nouvelle suggestion Premium",
            description=self.suggestion.value,
            color=0x9B59B6
        )
        embed.set_footer(text=f"Par {interaction.user.display_name} (ID:{interaction.user.id}) — {discord.utils.utcnow().strftime('%d/%m/%Y à %H:%M')}")
        await salon_recues.send(embed=embed)

        await interaction.response.send_message(
            "Ta suggestion a bien été transmise à l'équipe MatchMind, merci ! 💎",
            ephemeral=True
        )


class SuggestionView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="💡 Faire une suggestion",
        style=discord.ButtonStyle.primary,
        custom_id="btn_suggestion"
    )
    async def suggerer(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SuggestionModal())



async def post_avantages_premium(guild: discord.Guild):
    """Poste le message des avantages Premium au démarrage."""
    salon = None
    for ch in guild.text_channels:
        if "avantage" in ch.name.lower():
            salon = ch
            break
    if not salon:
        return

    async for message in salon.history(limit=10):
        if message.author == guild.me:
            return

    embed = discord.Embed(
        title="💎 Avantages Premium",
        description=(
            "En devenant membre **Premium** sur MatchMind, tu accèdes à des avantages exclusifs !\n\n"
            "**🚀 Matching amélioré**\n"
            "Reçois plus de suggestions de profils compatibles chaque jour.\n\n"
            "**💬 Lounge exclusif**\n"
            "Accès à un salon de discussion privé réservé aux membres Premium.\n\n"
            "**🎙️ Vocal VIP**\n"
            "Un salon vocal exclusif pour les membres Premium.\n\n"
            "**💡 Suggestions prioritaires**\n"
            "Propose des idées pour améliorer MatchMind, ton avis compte vraiment !\n\n"
            "**🌟 Rôle exclusif**\n"
            "Un rôle visible sur le serveur qui te distingue des autres membres.\n\n"
            "**🔔 Accès anticipé**\n"
            "Tu seras le premier informé des nouvelles fonctionnalités de MatchMind.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Pour devenir Premium, contacte un modérateur ! 💌"
        ),
        color=0x9B59B6
    )
    embed.set_footer(text="MatchMind Premium — Trouve quelqu'un qui te ressemble vraiment 💘")
    await salon.send(embed=embed)

async def post_suggestion_button(guild: discord.Guild):
    """Poste le message avec le bouton dans #suggestions-vip au démarrage."""
    salon = discord.utils.get(guild.text_channels, name=SALON_SUGGESTIONS)
    if not salon:
        return

    async for message in salon.history(limit=20):
        if message.author == guild.me and message.components:
            return

    embed = discord.Embed(
        title="💡 Suggestions Premium",
        description=(
            "Tu as une idée pour améliorer MatchMind ?\n"
            "Une nouvelle fonctionnalité, une amélioration du bot, une idée d'animation ?\n\n"
            "En tant que membre **Premium**, ton avis compte vraiment !\n"
            "Clique sur le bouton ci-dessous pour partager ta suggestion. 💎"
        ),
        color=0x9B59B6
    )
    await salon.send(embed=embed, view=SuggestionView())

# --------------------------------------------------------------------------
# COMMANDE DE TEST (ADMIN UNIQUEMENT)
# --------------------------------------------------------------------------

@bot.tree.command(name="test-match", description="[ADMIN] Forcer un match entre deux membres pour tester")
@app_commands.describe(membre1="Premier membre", membre2="Deuxième membre")
async def test_match(interaction: discord.Interaction, membre1: discord.Member, membre2: discord.Member):
    guild = interaction.guild
    fondateur = discord.utils.get(guild.roles, name=ROLE_FONDATEUR)
    if not fondateur or fondateur not in interaction.user.roles:
        await interaction.response.send_message(
            "Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    if membre1.id == membre2.id:
        await interaction.response.send_message(
            "Les deux membres doivent être différents.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"Création d'un match de test entre {membre1.display_name} et {membre2.display_name}...", ephemeral=True
    )

    await db.add_like(membre1.id, membre2.id)
    await db.add_like(membre2.id, membre1.id)
    await create_match_channels(membre1.id, membre2.id)

    await interaction.followup.send(
        f"Match de test créé entre {membre1.display_name} et {membre2.display_name} ! Vérifie la catégorie 💌 Matchs.", ephemeral=True
    )


# --------------------------------------------------------------------------
# CITATIONS DU JOUR VIA API CLAUDE
# --------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
SALON_CITATIONS = "✨citations-du-jour"


async def generer_citation():
    """Génère une belle citation sur l'amour et les rencontres via l'API Claude."""
    import aiohttp
    
    themes = [
        "l'amour authentique", "la patience en amour", "se découvrir avant de se montrer",
        "la confiance dans une relation", "l'importance des valeurs communes",
        "la connexion émotionnelle", "la sincérité en amour", "les rencontres inattendues",
        "prendre le temps de se connaître", "l'amour qui dure"
    ]
    import random
    theme = random.choice(themes)

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-haiku-4-5",
        "max_tokens": 150,
        "messages": [{
            "role": "user",
            "content": f"Génère une belle citation originale et poétique sur le thème : {theme}. "
                      f"La citation doit être courte (1-2 phrases max), inspirante et universelle. "
                      f"Réponds UNIQUEMENT avec la citation entre guillemets français (« »), "
                      f"suivie d'un saut de ligne et d'un auteur (réel ou 'Anonyme'). "
                      f"Aucun autre texte."
        }]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload
        ) as resp:
            data = await resp.json()
            return data["content"][0]["text"].strip()


@tasks.loop(minutes=1)
async def envoyer_citation():
    """Envoie une citation à 8h, 13h et 19h (heure de Paris)."""
    from datetime import datetime, timezone, timedelta
    paris = timezone(timedelta(hours=2))
    now = datetime.now(paris)
    if now.hour in (8, 13, 19) and now.minute == 0:
        guild = bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None)
        if not guild:
            return
        salon = discord.utils.get(guild.text_channels, name=SALON_CITATIONS)
        if not salon:
            return
        try:
            citation = await generer_citation()
            embed = discord.Embed(
                description=f"✨ **Citation du jour**\n\n{citation}",
                color=0xE91E8C
            )
            embed.set_footer(text="MatchMind — Trouve quelqu'un qui te ressemble vraiment 💘")
            await salon.send(embed=embed)
        except Exception as e:
            print(f"Erreur génération citation : {e}")


@envoyer_citation.before_loop
async def before_envoyer_citation():
    await bot.wait_until_ready()


@bot.tree.command(name="test-citation", description="[ADMIN] Forcer l'envoi d'une citation maintenant")
async def test_citation(interaction: discord.Interaction):
    fondateur = discord.utils.get(interaction.guild.roles, name=ROLE_FONDATEUR)
    if not fondateur or fondateur not in interaction.user.roles:
        await interaction.response.send_message("Permission refusée.", ephemeral=True)
        return
    await interaction.response.send_message("Génération de la citation...", ephemeral=True)
    await envoyer_citation()
    await interaction.followup.send("Citation envoyée !", ephemeral=True)


# --------------------------------------------------------------------------
# QUESTION DU JOUR VIA API CLAUDE
# --------------------------------------------------------------------------

SALON_QUESTIONS = "❓question-du-jour"


async def generer_question():
    """Génère une question du jour sur les rencontres et la personnalité via Claude."""
    import aiohttp
    import random

    themes = [
        "les valeurs en amour", "la compatibilité dans un couple",
        "les premiers rendez-vous", "ce qui attire vraiment dans quelqu'un",
        "la différence entre amour et amitié", "les deal-breakers en relation",
        "la communication dans un couple", "les habitudes de vie en couple",
        "les rêves et ambitions en amour", "la jalousie et la confiance",
        "les langages de l'amour", "ce qu'on apprend de ses relations passées",
        "l'importance des centres d'intérêt communs", "la distance en amour",
        "le bon moment pour se mettre en couple"
    ]
    theme = random.choice(themes)

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-haiku-4-5",
        "max_tokens": 200,
        "messages": [{
            "role": "user",
            "content": f"Génère une question du jour originale sur le thème : {theme}. "
                      f"La question doit être courte, intrigante, et inviter les gens à débattre ou réfléchir. "
                      f"Elle doit être adaptée à une communauté de rencontre. "
                      f"Réponds UNIQUEMENT avec la question, sans aucun autre texte ni explication."
        }]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload
        ) as resp:
            data = await resp.json()
            return data["content"][0]["text"].strip()


@tasks.loop(minutes=1)
async def envoyer_question():
    """Envoie une question du jour à 10h (heure de Paris)."""
    from datetime import datetime, timezone, timedelta
    paris = timezone(timedelta(hours=2))
    now = datetime.now(paris)
    if now.hour == 10 and now.minute == 0:
        guild = bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None)
        if not guild:
            return
        salon = discord.utils.get(guild.text_channels, name=SALON_QUESTIONS)
        if not salon:
            return
        try:
            question = await generer_question()
            embed = discord.Embed(
                title="❓ Question du jour",
                description=question,
                color=0x3498DB
            )
            embed.set_footer(text="Réponds dans #💬discussions et partage ton avis ! 💬")
            await salon.send(embed=embed)
        except Exception as e:
            print(f"Erreur génération question : {e}")


@envoyer_question.before_loop
async def before_envoyer_question():
    await bot.wait_until_ready()


@bot.tree.command(name="test-question", description="[ADMIN] Forcer l'envoi d'une question maintenant")
async def test_question(interaction: discord.Interaction):
    fondateur = discord.utils.get(interaction.guild.roles, name=ROLE_FONDATEUR)
    if not fondateur or fondateur not in interaction.user.roles:
        await interaction.response.send_message("Permission refusée.", ephemeral=True)
        return
    await interaction.response.send_message("Génération de la question...", ephemeral=True)
    await envoyer_question()
    await interaction.followup.send("Question envoyée !", ephemeral=True)


# --------------------------------------------------------------------------
# SONDAGE HEBDOMADAIRE VIA API CLAUDE
# --------------------------------------------------------------------------

SALON_SONDAGES = "📊sondages"


async def generer_sondage():
    """Génère un sondage hebdomadaire via Claude."""
    import aiohttp
    import random

    themes = [
        "les rencontres amoureuses", "la personnalité et le caractère",
        "les habitudes de vie en couple", "ce qui attire dans quelqu'un",
        "les premiers rendez-vous", "l'amour et l'amitié",
        "les centres d'intérêt communs", "la communication en couple"
    ]
    theme = random.choice(themes)

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-haiku-4-5",
        "max_tokens": 150,
        "messages": [{
            "role": "user",
            "content": f"Génère un sondage fun et court sur le thème : {theme}. "
                      f"Format EXACT à respecter (rien d'autre) :\n"
                      f"QUESTION: [la question]\n"
                      f"OPTION1: [emoji] [option 1]\n"
                      f"OPTION2: [emoji] [option 2]\n"
                      f"La question doit inviter au débat, les options doivent être courtes et opposées."
        }]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload
        ) as resp:
            data = await resp.json()
            return data["content"][0]["text"].strip()


@tasks.loop(minutes=1)
async def envoyer_sondage():
    """Envoie un sondage chaque lundi à 12h (heure de Paris)."""
    from datetime import datetime, timezone, timedelta
    paris = timezone(timedelta(hours=2))
    now = datetime.now(paris)
    if now.weekday() == 0 and now.hour == 12 and now.minute == 0:
        guild = bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None)
        if not guild:
            return
        salon = discord.utils.get(guild.text_channels, name=SALON_SONDAGES)
        if not salon:
            return
        try:
            raw = await generer_sondage()
            lines = raw.strip().split("\n")
            question = lines[0].replace("QUESTION:", "").strip()
            option1 = lines[1].replace("OPTION1:", "").strip()
            option2 = lines[2].replace("OPTION2:", "").strip()

            embed = discord.Embed(
                title="📊 Sondage de la semaine",
                description=f"**{question}**\n\n{option1}\n{option2}",
                color=0x9B59B6
            )
            embed.set_footer(text="Vote avec les réactions ci-dessous ! 👇")
            msg = await salon.send(embed=embed)

            emoji1 = option1.split()[0]
            emoji2 = option2.split()[0]
            await msg.add_reaction(emoji1)
            await msg.add_reaction(emoji2)
        except Exception as e:
            print(f"Erreur génération sondage : {e}")


@envoyer_sondage.before_loop
async def before_envoyer_sondage():
    await bot.wait_until_ready()


@bot.tree.command(name="test-sondage", description="[ADMIN] Forcer l'envoi d'un sondage maintenant")
async def test_sondage(interaction: discord.Interaction):
    fondateur = discord.utils.get(interaction.guild.roles, name=ROLE_FONDATEUR)
    if not fondateur or fondateur not in interaction.user.roles:
        await interaction.response.send_message("Permission refusée.", ephemeral=True)
        return
    await interaction.response.send_message("Génération du sondage...", ephemeral=True)
    guild = interaction.guild
    salon = discord.utils.get(guild.text_channels, name=SALON_SONDAGES)
    if not salon:
        await interaction.followup.send("Salon sondages introuvable.", ephemeral=True)
        return
    try:
        raw = await generer_sondage()
        lines = raw.strip().split("\n")
        question = lines[0].replace("QUESTION:", "").strip()
        option1 = lines[1].replace("OPTION1:", "").strip()
        option2 = lines[2].replace("OPTION2:", "").strip()
        embed = discord.Embed(
            title="📊 Sondage de la semaine",
            description=f"**{question}**\n\n{option1}\n{option2}",
            color=0x9B59B6
        )
        embed.set_footer(text="Vote avec les réactions ci-dessous ! 👇")
        msg = await salon.send(embed=embed)
        emoji1 = option1.split()[0]
        emoji2 = option2.split()[0]
        await msg.add_reaction(emoji1)
        await msg.add_reaction(emoji2)
        await interaction.followup.send("Sondage envoyé !", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Erreur : {e}", ephemeral=True)


# --------------------------------------------------------------------------
# JEU DU JOUR VIA API CLAUDE
# --------------------------------------------------------------------------

SALON_JEU = "🎮jeu-du-jour"
JEU_TYPES = ["devinette", "ce ou cela", "culture générale", "complète la phrase"]
jeu_index = 0


async def generer_jeu(type_jeu: str):
    """Génère un jeu du jour via Claude."""
    import aiohttp

    prompts = {
        "devinette": (
            "Génère une devinette fun et originale adaptée à une communauté de rencontres. "
            "Format EXACT:\n"
            "TITRE: 🤔 Devinette du jour\n"
            "JEU: [la devinette]\n"
            "REPONSE: [la réponse]\n"
            "Garde la réponse courte."
        ),
        "ce ou cela": (
            "Génère un 'ce ou cela' fun avec deux options opposées liées aux rencontres ou à la vie quotidienne. "
            "Format EXACT:\n"
            "TITRE: 🎯 Ce ou cela ?\n"
            "JEU: [option 1] ou [option 2] ?\n"
            "REPONSE: Dis-nous ton choix en réaction !"
        ),
        "culture générale": (
            "Génère une question de culture générale fun et pas trop difficile. "
            "Format EXACT:\n"
            "TITRE: 🧠 Culture générale\n"
            "JEU: [la question]\n"
            "REPONSE: [la réponse]"
        ),
        "complète la phrase": (
            "Génère une phrase à compléter fun et légère liée aux rencontres ou à la personnalité. "
            "Format EXACT:\n"
            "TITRE: 💭 Complète la phrase\n"
            "JEU: [phrase avec ... à la fin]\n"
            "REPONSE: Réponds dans le fil de discussion !"
        ),
    }

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-haiku-4-5",
        "max_tokens": 200,
        "messages": [{"role": "user", "content": prompts[type_jeu]}]
    }

    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload
        ) as resp:
            data = await resp.json()
            return data["content"][0]["text"].strip()


@tasks.loop(minutes=1)
async def envoyer_jeu():
    """Envoie un jeu du jour à 11h (heure de Paris)."""
    global jeu_index
    from datetime import datetime, timezone, timedelta
    paris = timezone(timedelta(hours=2))
    now = datetime.now(paris)
    if now.hour == 11 and now.minute == 0:
        guild = bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None)
        if not guild:
            return
        salon = discord.utils.get(guild.text_channels, name=SALON_JEU)
        if not salon:
            return
        try:
            type_jeu = JEU_TYPES[jeu_index % len(JEU_TYPES)]
            jeu_index += 1
            raw = await generer_jeu(type_jeu)
            lines = raw.strip().split("\n")
            titre = lines[0].replace("TITRE:", "").strip()
            jeu = lines[1].replace("JEU:", "").strip()
            reponse = lines[2].replace("REPONSE:", "").strip()

            embed = discord.Embed(
                title=titre,
                description=jeu,
                color=0x2ECC71
            )
            if type_jeu not in ("ce ou cela", "complète la phrase"):
                embed.set_footer(text=f"Réponse : {reponse}")
            else:
                embed.set_footer(text="Réponds avec une réaction ou dans le fil ! 👇")
            msg = await salon.send(embed=embed)
            if type_jeu == "ce ou cela":
                await msg.add_reaction("1️⃣")
                await msg.add_reaction("2️⃣")
            elif type_jeu == "complète la phrase":
                await msg.add_reaction("💬")
            elif type_jeu == "devinette":
                await msg.add_reaction("🤔")
            elif type_jeu == "culture générale":
                await msg.add_reaction("🧠")
        except Exception as e:
            print(f"Erreur génération jeu : {e}")


@envoyer_jeu.before_loop
async def before_envoyer_jeu():
    await bot.wait_until_ready()


@bot.tree.command(name="test-jeu", description="[ADMIN] Forcer l'envoi d'un jeu maintenant")
async def test_jeu(interaction: discord.Interaction):
    global jeu_index
    fondateur = discord.utils.get(interaction.guild.roles, name=ROLE_FONDATEUR)
    if not fondateur or fondateur not in interaction.user.roles:
        await interaction.response.send_message("Permission refusée.", ephemeral=True)
        return
    await interaction.response.send_message("Génération du jeu...", ephemeral=True)
    guild = interaction.guild
    salon = discord.utils.get(guild.text_channels, name=SALON_JEU)
    if not salon:
        await interaction.followup.send("Salon jeu introuvable.", ephemeral=True)
        return
    try:
        type_jeu = JEU_TYPES[jeu_index % len(JEU_TYPES)]
        jeu_index += 1
        raw = await generer_jeu(type_jeu)
        lines = raw.strip().split("\n")
        titre = lines[0].replace("TITRE:", "").strip()
        jeu = lines[1].replace("JEU:", "").strip()
        reponse = lines[2].replace("REPONSE:", "").strip()
        embed = discord.Embed(title=titre, description=jeu, color=0x2ECC71)
        if type_jeu not in ("ce ou cela", "complète la phrase"):
            embed.set_footer(text=f"Réponse : {reponse}")
        else:
            embed.set_footer(text="Réponds avec une réaction ou dans le fil ! 👇")
        msg = await salon.send(embed=embed)
        if type_jeu == "ce ou cela":
            await msg.add_reaction("1️⃣")
            await msg.add_reaction("2️⃣")
        elif type_jeu == "complète la phrase":
            await msg.add_reaction("💬")
        elif type_jeu == "devinette":
            await msg.add_reaction("🤔")
        elif type_jeu == "culture générale":
            await msg.add_reaction("🧠")
        await interaction.followup.send("Jeu envoyé !", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Erreur : {e}", ephemeral=True)


# --------------------------------------------------------------------------
# MESSAGES AUTOMATIQUES MATIN/SOIR
# --------------------------------------------------------------------------

@tasks.loop(minutes=1)
async def messages_ambiance():
    """Envoie un message de bonjour à 8h et bonne nuit à 22h."""
    from datetime import datetime, timezone, timedelta
    paris = timezone(timedelta(hours=2))
    now = datetime.now(paris)
    
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None)
    if not guild:
        return
    
    salon = discord.utils.get(guild.text_channels, name="💬discussions")
    if not salon:
        for ch in guild.text_channels:
            if "discussion" in ch.name.lower():
                salon = ch
                break
    if not salon:
        return

    if now.hour == 8 and now.minute == 0:
        embed = discord.Embed(
            description="☀️ **Bonjour MatchMind !**\nUne nouvelle journée commence, de nouvelles rencontres t'attendent ! 💘",
            color=0xF1C40F
        )
        await salon.send(embed=embed)

    elif now.hour == 22 and now.minute == 0:
        embed = discord.Embed(
            description="🌙 **Bonne nuit MatchMind !**\nQui sait ce que demain te réserve... 💌",
            color=0x9B59B6
        )
        await salon.send(embed=embed)

    elif now.weekday() == 4 and now.hour == 19 and now.minute == 0:
        embed = discord.Embed(
            description="😏 **C'est vendredi !**\nQui cherche un match pour le weekend ? Le bot est prêt à faire des étincelles 💘",
            color=0xE74C3C
        )
        await salon.send(embed=embed)

    elif now.weekday() == 6 and now.hour == 20 and now.minute == 0:
        embed = discord.Embed(
            description="💫 **Nouvelle semaine qui arrive...**\nDe nouvelles rencontres t'attendent sur MatchMind 💘 Lance-toi !",
            color=0x3498DB
        )
        await salon.send(embed=embed)


@messages_ambiance.before_loop
async def before_messages_ambiance():
    await bot.wait_until_ready()


@bot.tree.command(name="bannir-profil", description="[ADMIN] Bannir quelqu'un du système de matching sans le kick")
@app_commands.describe(membre="Le membre à bannir du matching")
async def bannir_profil(interaction: discord.Interaction, membre: discord.Member):
    fondateur = discord.utils.get(interaction.guild.roles, name=ROLE_FONDATEUR)
    if not fondateur or fondateur not in interaction.user.roles:
        await interaction.response.send_message("Permission refusée.", ephemeral=True)
        return

    await db.delete_profile(membre.id)

    role_membre = discord.utils.get(interaction.guild.roles, name=ROLE_MEMBRE)
    role_nouveau = discord.utils.get(interaction.guild.roles, name=ROLE_NOUVEAU)
    role_suspendu = discord.utils.get(interaction.guild.roles, name=ROLE_SUSPENDU)
    try:
        if role_membre and role_membre in membre.roles:
            await membre.remove_roles(role_membre)
        if role_nouveau and role_nouveau in membre.roles:
            await membre.remove_roles(role_nouveau)
        if role_suspendu and role_suspendu not in membre.roles:
            await membre.add_roles(role_suspendu)
    except discord.Forbidden:
        pass

    try:
        await membre.send(
            "Ton profil sur MatchMind a été suspendu par la modération suite à un signalement. "
            "Tu restes membre du serveur mais tu n'as plus accès au système de matching. "
            "Contacte un modérateur si tu penses que c'est une erreur."
        )
    except discord.Forbidden:
        pass

    await interaction.response.send_message(
        f"Le profil de {membre.display_name} a été supprimé du système de matching. "
        f"Il reste membre du serveur mais ne peut plus matcher.",
        ephemeral=True
    )


# --------------------------------------------------------------------------
# VÉRIFICATION PREMIUM VIA API WHOP
# --------------------------------------------------------------------------

WHOP_API_KEY = os.environ.get("WHOP_API_KEY")
WHOP_PRODUCT_ID = "matchmind-premium"


async def get_whop_members():
    """Récupère la liste des membres avec un abonnement actif sur Whop."""
    import aiohttp
    if not WHOP_API_KEY:
        return []
    
    headers = {
        "Authorization": f"Bearer {WHOP_API_KEY}",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://api.whop.com/api/v2/memberships?product_id={WHOP_PRODUCT_ID}&status=active&per=100",
            headers=headers
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", [])
            else:
                print(f"Erreur API Whop : {resp.status}")
                return []


@tasks.loop(minutes=30)
async def verifier_premium_whop():
    """Vérifie toutes les 30 minutes les abonnements Whop actifs."""
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None)
    if not guild:
        return

    role_premium = discord.utils.get(guild.roles, name=ROLE_PREMIUM)
    if not role_premium:
        return

    try:
        membres_actifs = await get_whop_members()
        discord_ids_actifs = set()

        for membre in membres_actifs:
            discord_id = membre.get("discord", {}).get("id")
            if discord_id:
                discord_ids_actifs.add(int(discord_id))

        for member in guild.members:
            a_role_premium = role_premium in member.roles
            a_abonnement_actif = member.id in discord_ids_actifs

            if a_abonnement_actif and not a_role_premium:
                await member.add_roles(role_premium)
                try:
                    await member.send(
                        "💎 Ton abonnement MatchMind Premium a été activé ! "
                        "Bienvenue dans l'espace exclusif 🌟"
                    )
                except discord.Forbidden:
                    pass
                print(f"Rôle Premium ajouté à {member.name}")

            elif not a_abonnement_actif and a_role_premium:
                await member.remove_roles(role_premium)
                try:
                    await member.send(
                        "Ton abonnement MatchMind Premium a expiré. "
                        "Tu peux te réabonner à tout moment sur whop.com/matchmind-8b4e/matchmind-premium/ 💌"
                    )
                except discord.Forbidden:
                    pass
                print(f"Rôle Premium retiré à {member.name}")

    except Exception as e:
        print(f"Erreur vérification Whop : {e}")


@verifier_premium_whop.before_loop
async def before_verifier_premium_whop():
    await bot.wait_until_ready()

# --------------------------------------------------------------------------
# DÉMARRAGE
# --------------------------------------------------------------------------

@bot.event
async def on_ready():
    await db.init_db()
    bot.add_view(SignalerPersistentView())
    bot.add_view(MatchSignalerView())
    bot.add_view(FermerMatchView(0))
    bot.add_view(MatchActionsView(0))
    bot.add_view(TemoignageView())
    bot.add_view(SuggestionView())
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
    if not envoyer_citation.is_running():
        envoyer_citation.start()
    if not envoyer_question.is_running():
        envoyer_question.start()
    if not envoyer_sondage.is_running():
        envoyer_sondage.start()
    if not envoyer_jeu.is_running():
        envoyer_jeu.start()
    if not messages_ambiance.is_running():
        messages_ambiance.start()
    if not verifier_premium_whop.is_running():
        verifier_premium_whop.start()

    guild = bot.get_guild(GUILD_ID) if GUILD_ID else (bot.guilds[0] if bot.guilds else None)
    if guild:
        await post_signalement_button(guild)
        await post_temoignage_button(guild)
        await post_suggestion_button(guild)
        await post_avantages_premium(guild)

    print(f"Connecté en tant que {bot.user}")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("La variable d'environnement DISCORD_TOKEN n'est pas définie.")
    bot.run(TOKEN)
