"""Bot Discord de rencontre par centres d'intérêt — fichier principal."""
import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks

import constants
import database as db
import matching
import views

TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = int(os.environ.get("GUILD_ID", "0")) or None
MATCH_CATEGORY_NAME = "💌 Matchs"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


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

    await interaction.followup.send(
        "Ton profil est enregistré ! Tu recevras des suggestions de profils compatibles "
        "directement ici en messages privés, plusieurs fois par jour.",
        ephemeral=True,
    )


# --------------------------------------------------------------------------
# SUGGESTIONS QUOTIDIENNES
# --------------------------------------------------------------------------

async def on_like(interaction: discord.Interaction, target_user_id: int, shown_user_id: int):
    """target_user_id = celui qui like, shown_user_id = la personne likée."""
    await db.add_like(target_user_id, shown_user_id)
    await interaction.response.send_message("Like envoyé ❤️", ephemeral=True)

    mutual = await db.has_liked(shown_user_id, target_user_id)
    if mutual:
        await create_match_channels(target_user_id, shown_user_id)
    else:
        # Notifie la personne likée, sans révéler qui
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
                break  # DMs fermés, on arrête pour cet utilisateur


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
        return  # déjà créé

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
        "Merci de rester respectueux·se. En cas de souci, contactez un modérateur."
    )
    await channel1.send(intro)
    await channel2.send(intro)

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
            side, other_webhook_url, my_count_side = 1, match["webhook2_url"], 1
        elif message.channel.id == match["channel2_id"]:
            side, other_webhook_url, my_count_side = 2, match["webhook1_url"], 2
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

    print(f"Connecté en tant que {bot.user}")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("La variable d'environnement DISCORD_TOKEN n'est pas définie.")
    bot.run(TOKEN)
