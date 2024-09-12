import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import random
import aiohttp
from discord.ui import Button, View
from discord import ButtonStyle


# Configurações do bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Necessário para eventos de membros

class MyBot(commands.Bot):
    async def setup_hook(self):
        self.loop.create_task(check_voice_connection())

bot = MyBot(command_prefix='!', intents=intents)

# Remover o comando de ajuda padrão
bot.remove_command('help')

# Configuração do YouTube DL
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,  # Permitir playlists
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'  # Necessário se tiver problemas de IP
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_query(cls, query, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch:{query}", download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries']
        else:
            data = [data]
        sources = []
        for entry in data:
            filename = entry['url'] if stream else ytdl.prepare_filename(entry)
            sources.append(cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=entry))
        return sources

# Fila de músicas
queue = []
loop_queue = False

# Executor para multithreading
executor = ThreadPoolExecutor(max_workers=64)

# Configuração de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Painel de Controle com botões
class MusicControlView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    @discord.ui.button(label='⏯️ Play/Pause', style=discord.ButtonStyle.green)
    async def play_pause(self, button: discord.ui.Button, interaction: discord.Interaction):
        vc = self.ctx.voice_client
        if vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Música retomada!", ephemeral=True)
        elif vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Música pausada!", ephemeral=True)

    @discord.ui.button(label='⏭️ Pular', style=discord.ButtonStyle.blurple)
    async def skip(self, button: discord.ui.Button, interaction: discord.Interaction):
        vc = self.ctx.voice_client
        if vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏭️ Música pulada!", ephemeral=True)

    @discord.ui.button(label='⏹️ Parar', style=discord.ButtonStyle.red)
    async def stop(self, button: discord.ui.Button, interaction: discord.Interaction):
        vc = self.ctx.voice_client
        if vc.is_playing():
            vc.stop()
            await vc.disconnect()
            await interaction.response.send_message("⏹️ Música parada e desconectado do canal de voz!", ephemeral=True)

# Comando para tocar música
@bot.command(name='play', help='Toca uma música do YouTube. Use o comando: !play <nome da música>')
async def play(ctx, *, query: str):
    try:
        if not ctx.author.voice:
            await ctx.send("Você precisa estar em um canal de voz para tocar música!")
            return

        if not ctx.voice_client:
            channel = ctx.author.voice.channel
            await channel.connect()

        async with ctx.typing():
            player = await YTDLSource.from_query(query, loop=bot.loop, stream=True)
            ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop) if not e else None)

        await ctx.send(f'Agora tocando: {player.title}', view=MusicControlView(ctx))

    except Exception as e:
        await ctx.send("Ocorreu um erro ao tentar tocar música.")
        print(f'Erro ao tentar tocar música: {e}')

# Comando para sair do canal de voz
@bot.command(name='leave', help='Desconecta o bot do canal de voz.')
async def leave(ctx):
    if not ctx.voice_client:
        return await ctx.send("Não estou conectado a um canal de voz.")
    
    await ctx.voice_client.disconnect()
    await ctx.send("Bot desconectado do canal de voz.")

# Comando para pausar a música
@bot.command(name='pause', help='Pausa a música que está tocando')
async def pause(ctx):
    voice_client = ctx.voice_client
    if voice_client.is_playing():
        voice_client.pause()
        await ctx.send("Música pausada!")
    else:
        await ctx.send("Nenhuma música está tocando no momento.")

# Comando para continuar a música pausada
@bot.command(name='resume', help='Continua a música que está pausada')
async def resume(ctx):
    voice_client = ctx.voice_client
    if voice_client.is_paused():
        voice_client.resume()
        await ctx.send("Música retomada!")
    else:
        await ctx.send("Nenhuma música está pausada no momento.")

# Comando para pular a música atual
@bot.command(name='skip', help='Pula para a próxima música')
async def skip(ctx):
    voice_client = ctx.voice_client
    if voice_client.is_playing():
        voice_client.stop()
        await ctx.send("Música pulada!")
    else:
        await ctx.send("Nenhuma música está tocando no momento.")

# Comando para desconectar o bot
@bot.command(name='disconnect', help='Desconecta o bot do canal de voz')
async def disconnect(ctx):
    await ctx.voice_client.disconnect()
    await ctx.send("Bot desconectado do canal de voz!")

# Comando para adicionar música à fila
@bot.command(name='queue', help='Adiciona uma música ou playlist à fila. Use o comando: !queue <nome da música ou URL>')
async def add_to_queue(ctx, *, query: str):
    async with ctx.typing():
        sources = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
        queue.extend(sources)
    await ctx.send(f'{len(sources)} música(s) adicionada(s) à fila!')

# Comando para mostrar a fila
@bot.command(name='show_queue', help='Mostra as músicas na fila')
async def show_queue(ctx):
    if queue:
        message = "\n".join([f'{i+1}. {source.title}' for i, source in enumerate(queue)])
        await ctx.send(f'Músicas na fila:\n{message}')
    else:
        await ctx.send('A fila está vazia.')

# Comando para tocar a próxima música da fila
async def play_next(ctx):
    if queue:
        player = queue.pop(0)
        ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop) if not e else None)
        await ctx.send(f'Tocando agora: {player.title}')
    else:
        await ctx.send('A fila está vazia.')

# Comando para ajustar o volume
@bot.command(name='volume', help='Ajusta o volume da música. Use o comando: !volume <valor de 0 a 100>')
async def volume(ctx, volume: int):
    if ctx.voice_client is None:
        return await ctx.send("Não estou conectado a um canal de voz.")
    
    ctx.voice_client.source.volume = volume / 100
    await ctx.send(f"Volume ajustado para {volume}%")

# Comando para parar a música e limpar a fila
@bot.command(name='stop', help='Para a música e limpa a fila')
async def stop(ctx):
    queue.clear()
    if ctx.voice_client.is_playing():
        ctx.voice_client.stop()
    await ctx.send("Música parada e fila limpa!")

# Comando para ativar/desativar o loop da fila
@bot.command(name='loop', help='Ativa/Desativa o loop da fila')
async def loop(ctx):
    global loop_queue
    loop_queue = not loop_queue
    await ctx.send(f'Loop {"ativado" if loop_queue else "desativado"}!')

# Comando para mostrar a música atual
@bot.command(name='now_playing', help='Mostra a música que está tocando no momento')
async def now_playing(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        await ctx.send(f'Agora tocando: {ctx.voice_client.source.title}')
    else:
        await ctx.send("Nenhuma música está tocando no momento.")

# Comando para mover uma música na fila
@bot.command(name='move', help='Move uma música na fila. Use o comando: !move <posição atual> <nova posição>')
async def move(ctx, current_pos: int, new_pos: int):
    if 0 < current_pos <= len(queue) and 0 < new_pos <= len(queue):
        song = queue.pop(current_pos - 1)
        queue.insert(new_pos - 1, song)
        await ctx.send(f'Música movida para a posição {new_pos}')
    else:
        await ctx.send('Posições inválidas.')

# Comando para remover uma música da fila
@bot.command(name='remove', help='Remove uma música da fila. Use o comando: !remove <posição>')
async def remove(ctx, pos: int):
    if 0 < pos <= len(queue):
        removed_song = queue.pop(pos - 1)
        await ctx.send(f'Música removida da posição {pos}')
    else:
        await ctx.send('Posição inválida.')

# Comando de busca
@bot.command(name='search', help='Busca músicas no YouTube. Use o comando: !search <termo de busca>')
async def search(ctx, *, query: str):
    async with ctx.typing():
        data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch5:{query}", download=False))
        if 'entries' in data:
            entries = data['entries']
            search_results = "\n".join([f"{i+1}. {entry['title']}" for i, entry in enumerate(entries)])
            await ctx.send(f"Resultados da busca:\n{search_results}\nUse !queue <número> para adicionar à fila.")
            bot.search_results = entries
        else:
            await ctx.send("Nenhum resultado encontrado.")

@bot.command(name='queue_search', help='Adiciona uma música da busca à fila. Use o comando: !queue_search <número>')
async def queue_search(ctx, index: int):
    if hasattr(bot, 'search_results') and 0 < index <= len(bot.search_results):
        entry = bot.search_results[index - 1]
        source = await YTDLSource.from_url(entry['url'], loop=bot.loop, stream=True)
        queue.append(source)
        await ctx.send(f'Música {entry["title"]} adicionada à fila!')
    else:
        await ctx.send("Índice inválido ou nenhum resultado de busca disponível.")

# Desconectar automaticamente após um período de inatividade
async def auto_disconnect(ctx):
    await asyncio.sleep(30)  # 1 minutos
    if not ctx.voice_client.is_playing():
        await ctx.voice_client.disconnect()
        await ctx.send("Desconectado por inatividade.")

# Verificar periodicamente se o bot está desconectado e reconectar se necessário
async def check_voice_connection():
    await bot.wait_until_ready()
    while not bot.is_closed():
        for guild in bot.guilds:
            if guild.voice_client and not guild.voice_client.is_connected():
                try:
                    await guild.voice_client.connect()
                except Exception as e:
                    logger.error(f'Erro ao tentar reconectar: {e}')
        await asyncio.sleep(60)  # Verificar a cada minuto

# Tratar eventos de erro
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send('Comando não encontrado. Use !help para ver a lista de comandos.')
    else:
        await ctx.send(f'Ocorreu um erro: {error}')
        logger.error(f'Erro no comando: {error}')

# Comando de ajuda personalizado
@bot.command(name='help', help='Mostra esta mensagem de ajuda')
async def custom_help(ctx):
    help_message = """
        **Comandos do Bot de Música:**
        play <nome da música> - Toca uma música do YouTube.
        pause - Pausa a música que está tocando.
        resume - Continua a música que está pausada.
        skip - Pula para a próxima música.
        disconnect - Desconecta o bot do canal de voz.
        queue <nome da música ou URL> - Adiciona uma música ou playlist à fila.
        show_queue - Mostra as músicas na fila.
        volume <valor de 0 a 100> - Ajusta o volume da música.
        stop - Para a música e limpa a fila.
        loop - Ativa/Desativa o loop da fila.
        now_playing - Mostra a música que está tocando no momento.
        move <posição atual> <nova posição> - Move uma música na fila.
        remove <posição> - Remove uma música da fila.
        search <termo de busca> - Busca músicas no YouTube.
        queue_search <número> - Adiciona uma música da busca à fila.
        join - Conecta o bot ao canal de voz.
        
        **Outros Comandos:**
        ping - Verifica a latência do bot.
        serverinfo - Mostra informações sobre o servidor.
        userinfo <usuário> - Mostra informações sobre um usuário.
        clear <número> - Limpa um número específico de mensagens.
        announce <canal> <mensagem> - Faz um anúncio em um canal específico.
        welcome <mensagem> - Define uma mensagem de boas-vindas.
        goodbye <mensagem> - Define uma mensagem de despedida.
        level - Mostra o nível do usuário.
        giveaway <prêmio> - Realiza um sorteio.
        poll <pergunta> <opções> - Cria uma enquete.
        timer <tempo> - Define um temporizador.
        avatar <usuário> - Mostra o avatar de um usuário.
        meme - Envia um meme aleatório.
        joke - Envia uma piada aleatória.
    """
    await ctx.send(help_message)

# Comando para conectar o bot ao canal de voz
@bot.command(name='join', help='Conecta o bot ao canal de voz')
async def join(ctx):
    if ctx.author.voice is None:
        await ctx.send("Você não está em um canal de voz!")
        return
    voice_channel = ctx.author.voice.channel
    if ctx.voice_client is not None:
        return await ctx.voice_client.move_to(voice_channel)
    await voice_channel.connect()
    await ctx.send(f"Conectado ao canal de voz: {voice_channel}")

# Comando de Ping
@bot.command(name='ping', help='Verifica a latência do bot')
async def ping(ctx):
    await ctx.send(f'Pong! Latência: {round(bot.latency * 1000)}ms')

# Comando de Informações do Servidor
@bot.command(name='serverinfo', help='Mostra informações sobre o servidor')
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=f"Informações do Servidor - {guild.name}", color=discord.Color.blue())
    embed.add_field(name="ID do Servidor", value=guild.id, inline=True)
    embed.add_field(name="Dono do Servidor", value=guild.owner, inline=True)
    embed.add_field(name="Membros", value=guild.member_count, inline=True)
    embed.add_field(name="Canais de Texto", value=len(guild.text_channels), inline=True)
    embed.add_field(name="Canais de Voz", value=len(guild.voice_channels), inline=True)
    embed.set_thumbnail(url=guild.icon.url)
    await ctx.send(embed=embed)

# Comando de Informações do Usuário
@bot.command(name='userinfo', help='Mostra informações sobre um usuário')
async def userinfo(ctx, member: discord.Member):
    embed = discord.Embed(title=f"Informações do Usuário - {member}", color=discord.Color.green())
    embed.add_field(name="ID do Usuário", value=member.id, inline=True)
    embed.add_field(name="Nome", value=member.display_name, inline=True)
    embed.add_field(name="Conta Criada em", value=member.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=True)
    embed.add_field(name="Entrou no Servidor em", value=member.joined_at.strftime("%d/%m/%Y %H:%M:%S"), inline=True)
    embed.set_thumbnail(url=member.avatar.url)
    await ctx.send(embed=embed)

# Comando de Limpeza de Mensagens
@bot.command(name='clear', help='Limpa um número específico de mensagens. Use o comando: !clear <número>')
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f'{amount} mensagens limpas!', delete_after=5)

# Comando de Anúncio
@bot.command(name='announce', help='Faz um anúncio em um canal específico. Use o comando: !announce <canal> <mensagem>')
@commands.has_permissions(administrator=True)
async def announce(ctx, channel: discord.TextChannel, *, message: str):
    await channel.send(message)
    await ctx.send(f'Anúncio enviado para {channel.mention}')



# Sistema de Boas-vindas
@bot.event
async def on_member_join(member):
    channel = discord.utils.get(member.guild.text_channels, name='geral')  # Substitua 'geral' pelo nome do seu canal de boas-vindas
    if channel:
        await channel.send(f'Bem-vindo ao servidor, {member.mention}!')

# Sistema de Despedida
@bot.event
async def on_member_remove(member):
    channel = discord.utils.get(member.guild.text_channels, name='geral')  # Substitua 'geral' pelo nome do seu canal de despedida
    if channel:
                await channel.send(f'{member.mention} saiu do servidor. Sentiremos sua falta!')

# Sistema de Níveis
user_levels = {}

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    if user_id not in user_levels:
        user_levels[user_id] = {'level': 1, 'xp': 0}

    user_levels[user_id]['xp'] += 10
    if user_levels[user_id]['xp'] >= user_levels[user_id]['level'] * 100:
        user_levels[user_id]['xp'] = 0
        user_levels[user_id]['level'] += 1
        await message.channel.send(f'Parabéns {message.author.mention}, você subiu para o nível {user_levels[user_id]["level"]}!')

    await bot.process_commands(message)

@bot.command(name='level', help='Mostra o nível do usuário')
async def level(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_id = member.id
    if user_id in user_levels:
        level = user_levels[user_id]['level']
        xp = user_levels[user_id]['xp']
        await ctx.send(f'{member.mention} está no nível {level} com {xp} XP.')
    else:
        await ctx.send(f'{member.mention} ainda não tem um nível.')

# Comando de Sorteio
@bot.command(name='giveaway', help='Realiza um sorteio. Use o comando: !giveaway <prêmio>')
async def giveaway(ctx, *, prize: str):
    await ctx.send(f'Sorteio iniciado! Prêmio: {prize}')
    await asyncio.sleep(10)  # Tempo para os usuários reagirem
    participants = [user for user in ctx.guild.members if not user.bot]
    winner = random.choice(participants)
    await ctx.send(f'Parabéns {winner.mention}, você ganhou o sorteio! Prêmio: {prize}')

# Comando de Enquete
@bot.command(name='poll', help='Cria uma enquete. Use o comando: !poll <pergunta> <opções>')
async def poll(ctx, question: str, *options: str):
    if len(options) < 2:
        await ctx.send('Você deve fornecer pelo menos duas opções.')
        return
    if len(options) > 10:
        await ctx.send('Você não pode fornecer mais de 10 opções.')
        return

    embed = discord.Embed(title=question, color=discord.Color.blue())
    reactions = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    for i, option in enumerate(options):
        embed.add_field(name=f'Opção {i+1}', value=option, inline=False)
    poll_message = await ctx.send(embed=embed)
    for i in range(len(options)):
        await poll_message.add_reaction(reactions[i])

# Comando de Temporizador
@bot.command(name='timer', help='Define um temporizador. Use o comando: !timer <tempo em segundos>')
async def timer(ctx, seconds: int):
    if seconds < 1:
        await ctx.send("O tempo deve ser maior que 0 segundos.")
        return
    await ctx.send(f"Temporizador definido para {seconds} segundos.")
    await asyncio.sleep(seconds)
    await ctx.send(f"{ctx.author.mention}, o tempo acabou!")    

# Comando de Avatar
@bot.command(name='avatar', help='Mostra o avatar de um usuário. Use o comando: !avatar <usuário>')
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title=f'Avatar de {member}', color=discord.Color.green())
    embed.set_image(url=member.avatar.url)
    await ctx.send(embed=embed)

# Comando de Meme
@bot.command(name='meme', help='Envia um meme aleatório')
async def meme(ctx):
    async with aiohttp.ClientSession() as session:
        async with session.get('https://rapidapi.com/collection/meme') as response:
            data = await response.json()
            embed = discord.Embed(title=data['title'], color=discord.Color.purple())
            embed.set_image(url=data['url'])
            await ctx.send(embed=embed)

# Comando de Piada
@bot.command(name='joke', help='Envia uma piada aleatória')
async def joke(ctx):
    async with aiohttp.ClientSession() as session:
        async with session.get('https://official-joke-api.appspot.com/random_joke') as response:
            data = await response.json()
            await ctx.send(f'{data["setup"]} - {data["punchline"]}')


# Adicionando o comando para criar o painel de controle
@bot.command(name="panel", help="Cria um painel de controle para controlar o bot de música.")
async def control_panel(ctx):
    # Botões para o painel de controle
    pause_button = Button(label="Pause", style=ButtonStyle.primary, custom_id="pause")
    resume_button = Button(label="Resume", style=ButtonStyle.success, custom_id="resume")
    skip_button = Button(label="Skip", style=ButtonStyle.secondary, custom_id="skip")
    stop_button = Button(label="Stop", style=ButtonStyle.danger, custom_id="stop")


    # Função que será chamada quando o botão de pause for clicado
    async def pause_callback(interaction):
        voice_client = ctx.voice_client
        if voice_client.is_playing():
            voice_client.pause()
            await interaction.response.send_message("Música pausada!", ephemeral=True)
        else:
            await interaction.response.send_message("Nenhuma música está tocando no momento.", ephemeral=True)

    # Função que será chamada quando o botão de resume for clicado
    async def resume_callback(interaction):
        voice_client = ctx.voice_client
        if voice_client.is_paused():
            voice_client.resume()
            await interaction.response.send_message("Música retomada!", ephemeral=True)
        else:
            await interaction.response.send_message("Nenhuma música está pausada no momento.", ephemeral=True)

    
    # Função que será chamada quando o botão de skip for clicado
    async def skip_callback(interaction):
        voice_client = ctx.voice_client
        if voice_client.is_playing():
            voice_client.stop()
            await interaction.response.send_message("Música pulada!", ephemeral=True)
        else:
            await interaction.response.send_message("Nenhuma música está tocando no momento.", ephemeral=True)

    # Função que será chamada quando o botão de stop for clicado
    async def stop_callback(interaction):
        queue.clear()
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        await interaction.response.send_message("Música parada e fila limpa!", ephemeral=True)

    # Atribuir callbacks aos botões
    pause_button.callback = pause_callback
    resume_button.callback = resume_callback
    skip_button.callback = skip_callback
    stop_button.callback = stop_callback

    # Adicionando os botões ao painel
    view = View()
    view.add_item(pause_button)
    view.add_item(resume_button)
    view.add_item(skip_button)
    view.add_item(stop_button)


# Inicializar o bot

bot.run("")
