import discord
from discord.ext import commands
from dotenv import load_dotenv
from mcrcon import MCRcon 
import os


load_dotenv("../.env")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)

@bot.tree.command(name="status", description="Check the survival server status")
async def status(interaction: discord.Interaction):
    try:
        with MCRcon("127.0.0.1", os.getenv("RCON_PASSWORD"), port=25575) as rcon:
            response = rcon.command("list")
            await interaction.response.send_message(f"Server is online!\n{response}")
    except Exception as e:
        await interaction.response.send_message(f"Server is offline or unreachable. You can use /wake to turn it on :D")

bot.run(os.getenv("DISCORD_TOKEN"))
