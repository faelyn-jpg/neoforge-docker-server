import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from mcrcon import MCRcon
import os
import docker
import asyncio
import time
import json 

with open("../config/config.json") as f:
    config = json.load(f)

client = docker.from_env()
load_dotenv("../.env")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

idle_counts = {
        "survival": 0,
        "creative": 0,
        }

async def wait_for_server(container, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        logs = container.logs(tail=20).decode("utf-8")
        if "Dedicated server took" in logs:
            return True
        await asyncio.sleep(3)
    return False

async def is_server_empty(target_server):
    try:
        port = config["servers"][target_server]["rcon_port"]
        with MCRcon("127.0.0.1", os.getenv("RCON_PASSWORD"), port=port) as rcon:
            response= rcon.command("list")
            player_count = int(response.split()[2])
            return player_count == 0
    except Exception as e:
        print (e)
        return "offline"

async def handle_idle_server(target_server):
    server_empty = await is_server_empty(target_server)
    if server_empty == "offline": 
        return
    elif server_empty:
       idle_counts[target_server] += 1 
    else: 
        idle_counts[target_server] = 0
    if idle_counts[target_server] >= 5:
        idle_counts[target_server] = 0
        client.containers.get(target_server).stop(timeout=30)
        return "stop server"

@tasks.loop(seconds=300)
async def poll_survival():
    try:
        await handle_idle_server("survival")
    except Exception as e:
        print(e)

@tasks.loop(seconds=300)
async def poll_creative():
    try:
        await handle_idle_server("creative")
    except Exception as e:
        print(e)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
        poll_survival.start()
        poll_creative.start()
    except Exception as e:
        print(e)

@bot.tree.command(name="status", description="Check the survival server status")
async def status(interaction: discord.Interaction):
    try:
        with MCRcon("127.0.0.1", os.getenv("RCON_PASSWORD"), port=25575) as rcon:
            response = rcon.command("list")
            await interaction.response.send_message(f"Server is online!\n{response}")
    except Exception as e:
        print(e)
        await interaction.response.send_message(f"Server is offline or unreachable. You can use /wake to turn it on :D")

@bot.tree.command(name="start", description="Start a server")
@app_commands.describe(target_server="Which server to start (default: survival)")
@app_commands.choices(target_server=[
    app_commands.Choice(name="survival", value="survival"),
    app_commands.Choice(name="creative", value="creative"),
])
async def start(interaction: discord.Interaction, target_server: str = "survival"):
    try:
        container = client.containers.get(target_server) 
        if container.status == "running":
            await interaction.response.send_message(f"The {target_server} server is already running, go join!")
        else:
            container.start()
            await interaction.response.send_message(f"Starting {target_server} server..... :3")
            success = await wait_for_server(container)
            if success:
                await interaction.followup.send("Server is online! Have fun :D")
            else:
                await interaction.followup.send("Server failed to start in time...")
                container.stop(timeout=20)
        
    except Exception as e:
        print(e)
        await interaction.response.send_message(f"Oops! Something went wrong....")

@bot.tree.command(name="stop", description="Stop a server")
@app_commands.default_permissions(discord.Permissions(administrator=True))
@app_commands.describe(target_server="Which server to start (default: survival)")
@app_commands.choices(target_server=[
    app_commands.Choice(name="survival", value="survival"),
    app_commands.Choice(name="creative", value="creative"),
])
async def stop(interaction: discord.Interaction, target_server: str = "survival"):
    try:
        container = client.containers.get(target_server)
        if container.status == "exited":
            await interaction.response.send_message(f"The {target_server} server isn't running.")
        else: 
            await interaction.response.send_message(f"Stopping {target_server} server.")
            container.stop(timeout=60)
    except Exception as e:
        print(e)
        await interaction.response.send_message(f"Oops! Something went wrong.")

bot.run(os.getenv("DISCORD_TOKEN"))
