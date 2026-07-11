import discord
import wakeonlan #type: ignore
from discord.ext import commands
from discord import app_commands
from wakeonlan import send_magic_packet #type: ignore
from dotenv import load_dotenv
import os

load_dotenv()
intents = discord.Intents.default()
intents.message_content = True
queue_channel_id = int(os.getenv("QUEUE_CHANNEL_ID", 0)) 
bot = commands.Bot(command_prefix="/", intents=intents)
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try: 
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)

@bot.tree.command(name="wake", description="Start PC and a server")
@app_commands.describe(target_server="Which server to start (default: survival)")
@app_commands.choices(target_server=[
app_commands.Choice(name="survival", value="survival"),
app_commands.Choice(name="creative", value="creative"),
])
async def wake(interaction: discord.Interaction, target_server: str = "survival"):
    try: 
        await interaction.response.send_message(f"FurberBot is sleeping... I wake him up!")
        send_magic_packet(os.getenv("MAC_ADDRESS"))
        channel = bot.get_channel(queue_channel_id)
        if isinstance(channel, discord.TextChannel): 
            await channel.send(f"pending:{target_server}")
    except Exception as e:
        print(e)

token = os.getenv("DISCORD_TOKEN")
if not token: 
    raise ValueError("DISCORD_TOKEN not set in .env")
bot.run(token)
