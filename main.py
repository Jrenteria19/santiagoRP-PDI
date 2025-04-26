import discord
from discord import ui, app_commands, Interaction, Permissions
from discord.ext import commands, tasks
from discord import Object
from dotenv import load_dotenv
import os
import re
import asyncio
import uuid
from datetime import datetime
import pytz
import mysql.connector
import datetime as dt

# Cargar variables de entorno
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
MYSQL_HOST = os.getenv('MYSQL_HOST')
MYSQL_USER = os.getenv('MYSQL_USER')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE')

# Configuración del bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  
bot = commands.Bot(command_prefix='!', intents=intents)

# Contador para nombres de canales (en memoria, no persistente)
ticket_counter = 0

# Constantes
class Colors:
    PRIMARY = 0x5865F2  # Discord blurple
    SUCCESS = 0x57F287  # Discord green
    DANGER = 0xED4245   # Discord red
    WARNING = 0xFEE75C  # Discord yellow
    WANTED = 0x8B0000   # Dark red for wanted poster

class Channels:
    PDI_INFO = 1345894050519056432
    SUGERIR_INPUT = 1345894050770845825
    SUGERIR_OUTPUT = 1345894050770845822
    TICKET = 1345894050351288347
    TICKET_LOG = 1365221112807555103
    BUSCA = 1365196649428684850
    SERVICIO = 1345894050770845824
    HORAS_SEMANALES = 1365387331254751346

class Categories:
    TICKET = 1365218685819813989

class Roles:
    SUGERIR_ALLOWED = 1345894049835384861  # Rol permitido para /sugerir
    TICKET_VIEW_1 = 1345894049848229964    # Rol con acceso a tickets (excepto Reportar Oficial y Postular PDI)
    TICKET_VIEW_2 = 1345894049848229968    # Rol con acceso a todos los tickets
    BUSCA_PING = 1345894049835384857       # Rol a pingear en /buscar-a
    HORAS_SEMANALES_ALLOWED = [1345894049848229964, 1345894049848229968]

# Configuración de la base de datos MySQL
def init_db():
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE
        )
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS service_records (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                start_time VARCHAR(255) NOT NULL,
                end_time VARCHAR(255),
                hours FLOAT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_hours (
                user_id BIGINT PRIMARY KEY,
                total_hours FLOAT NOT NULL DEFAULT 0
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS sanciones (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                oficial_id BIGINT NOT NULL,
                razon TEXT NOT NULL,
                tipo_sancion BIGINT NOT NULL,
                foto_prueba TEXT,
                timestamp VARCHAR(255) NOT NULL
            )
        ''')
        conn.commit()
        conn.close()
        print("Base de datos inicializada correctamente.")
    except mysql.connector.Error as err:
        print(f"Error al inicializar la base de datos: {err}")

# Inicializar base de datos al arrancar
init_db()

# Helper para crear embeds
def create_embed(title: str, description: str, color: int) -> discord.Embed:
    embed = discord.Embed(
        title=f"🌟 {title}",
        description=description,
        color=color,
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text="Santiago RP")
    return embed

def is_allowed_horas_semanales():
    async def predicate(interaction: Interaction) -> bool:
        if not interaction.user.roles:  # En caso de que no haya roles (DMs o error)
            await interaction.response.send_message(embed=create_embed(
                title="❌ Permiso Denegado",
                description="No tienes los roles necesarios para usar este comando.",
                color=Colors.DANGER
            ), ephemeral=True)
            return False
        allowed_roles = Roles.HORAS_SEMANALES_ALLOWED
        has_role = any(role.id in allowed_roles for role in interaction.user.roles)
        if not has_role:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Permiso Denegado",
                description="No tienes los roles necesarios para usar este comando.",
                color=Colors.DANGER
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# Decorador para verificar el canal de horas semanales
def is_horas_semanales_channel():
    async def predicate(interaction: Interaction) -> bool:
        if interaction.channel_id != Channels.HORAS_SEMANALES:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Canal Incorrecto",
                description=f"Este comando solo puede usarse en <#{Channels.HORAS_SEMANALES}>",
                color=Colors.DANGER
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

def is_sancionar_channel():
    async def predicate(interaction: Interaction) -> bool:
        if interaction.channel_id != Channels.SUGERIR_INPUT:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Canal Incorrecto",
                description=f"Este comando solo puede usarse en <#{Channels.SUGERIR_INPUT}>",
                color=Colors.DANGER
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

async def tipo_sancion_autocomplete(interaction: Interaction, current: str) -> list[app_commands.Choice[str]]:
    sanciones = [
        {"name": "Sanción 1", "value": "1345894049818611868"},
        {"name": "Sanción 2", "value": "1345894049818611867"},
        {"name": "Sanción 3", "value": "1345894049818611866"},
        {"name": "Sanción 4", "value": "1345894049818611865"}
    ]
    return [
        app_commands.Choice(name=sancion["name"], value=sancion["value"])
        for sancion in sanciones
        if current.lower() in sancion["name"].lower()
    ]

# Vista para el botón Terminar Servicio
class ServiceButtons(ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @ui.button(label="Terminar Servicio", style=discord.ButtonStyle.danger, emoji="🏁", custom_id="end_service")
    async def end_service_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Acción No Permitida",
                description="Solo el usuario que inició el servicio puede terminarlo.",
                color=Colors.DANGER
            ), ephemeral=True)
            return

        local_tz = pytz.timezone('America/Mazatlan')
        end_time = datetime.now(local_tz)
        try:
            conn = mysql.connector.connect(
                host=MYSQL_HOST,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE
            )
            c = conn.cursor()
            c.execute('SELECT start_time FROM service_records WHERE user_id = %s AND end_time IS NULL', (self.user_id,))
            result = c.fetchone()
            if not result:
                await interaction.response.send_message(embed=create_embed(
                    title="❌ Error",
                    description="No se encontró un servicio activo.",
                    color=Colors.DANGER
                ), ephemeral=True)
                conn.close()
                return

            start_time = datetime.fromisoformat(result[0]).astimezone(local_tz)
            hours = (end_time - start_time).total_seconds() / 3600
            minutes = hours * 60

            # Actualizar registro de servicio
            c.execute('UPDATE service_records SET end_time = %s, hours = %s WHERE user_id = %s AND end_time IS NULL',
                      (end_time.isoformat(), hours, self.user_id))
            
            # Actualizar horas totales del usuario
            c.execute('INSERT INTO user_hours (user_id, total_hours) VALUES (%s, %s) ON DUPLICATE KEY UPDATE total_hours = total_hours + %s',
                      (self.user_id, hours, hours))
            conn.commit()
            conn.close()

            # Enviar mensaje al canal
            channel = bot.get_channel(Channels.SERVICIO)
            embed = create_embed(
                title="⏰ Servicio Finalizado | Santiago RP",
                description=f"**{interaction.user.mention}** ha finalizado su servicio.",
                color=Colors.PRIMARY
            )
            embed.add_field(name="Usuario", value=interaction.user.mention, inline=True)
            embed.add_field(name="Hora de Entrada", value=start_time.strftime('%Y-%m-%d %H:%M:%S'), inline=True)
            embed.add_field(name="Hora de Salida", value=end_time.strftime('%Y-%m-%d %H:%M:%S'), inline=True)
            embed.add_field(name="Duración", value=f"{hours:.2f} horas ({minutes:.0f} minutos)", inline=True)
            embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)
            await channel.send(embed=embed)

            # Actualizar mensaje en DM para remover el botón
            try:
                await interaction.message.edit(view=None)
            except discord.HTTPException:
                pass  # Ignorar si no se puede editar el mensaje

            # Confirmación al usuario
            await interaction.response.send_message(embed=create_embed(
                title="✅ Servicio Terminado",
                description=f"Has terminado tu servicio. Duración: **{hours:.2f} horas** ({minutes:.0f} minutos).",
                color=Colors.SUCCESS
            ), ephemeral=True)
        except mysql.connector.Error as err:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Error",
                description=f"No se pudo terminar el servicio debido a un error en la base de datos: {err}",
                color=Colors.DANGER
            ), ephemeral=True)

# Tarea semanal para el oficial más activo
@tasks.loop(seconds=60)
async def weekly_leaderboard():
    local_tz = pytz.timezone('America/Mazatlan')
    now = datetime.now(local_tz)
    if now.weekday() == 0 and now.hour == 0 and now.minute == 0:  # Lunes a las 00:00 local
        try:
            conn = mysql.connector.connect(
                host=MYSQL_HOST,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE
            )
            c = conn.cursor()
            c.execute('SELECT user_id, total_hours FROM user_hours ORDER BY total_hours DESC LIMIT 1')
            result = c.fetchone()
            
            channel = bot.get_channel(Channels.SERVICIO)
            if result and channel:
                user_id, total_hours = result
                user = await bot.fetch_user(user_id)
                embed = create_embed(
                    title="🏆 Oficial Más Activo de la Semana",
                    description=f"¡Felicidades a **{user.display_name}** por ser el oficial más activo con **{total_hours:.2f} horas** de servicio esta semana! 🎉",
                    color=Colors.SUCCESS
                )
                embed.set_thumbnail(url=user.avatar.url if user.avatar else None)
                embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else None)
                await channel.send(embed=embed)

            # Reiniciar horas
            c.execute('UPDATE user_hours SET total_hours = 0')
            conn.commit()
            conn.close()
        except mysql.connector.Error as err:
            print(f"Error en weekly_leaderboard: {err}")

# Verificación de canal para iniciar-servicio
def is_servicio_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.channel_id != Channels.SUGERIR_INPUT:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Canal Incorrecto",
                description=f"Este comando solo puede usarse en <#{Channels.SUGERIR_INPUT}>.",
                color=Colors.DANGER
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# Comando /iniciar-servicio
@bot.tree.command(name="iniciar-servicio", description="Inicia un período de servicio y registra la hora de entrada")
@is_servicio_channel()
async def iniciar_servicio(interaction: discord.Interaction):
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE
        )
        c = conn.cursor()
        c.execute('SELECT id FROM service_records WHERE user_id = %s AND end_time IS NULL', (interaction.user.id,))
        if c.fetchone():
            await interaction.response.send_message(embed=create_embed(
                title="❌ Servicio Activo",
                description="Ya tienes un servicio activo. Termínalo en tus DMs antes de iniciar uno nuevo.",
                color=Colors.DANGER
            ), ephemeral=True)
            conn.close()
            return

        local_tz = pytz.timezone('America/Mazatlan')
        start_time = datetime.now(local_tz)
        c.execute('INSERT INTO service_records (user_id, start_time) VALUES (%s, %s)',
                  (interaction.user.id, start_time.isoformat()))
        conn.commit()
        conn.close()

        # Enviar DM al usuario
        embed = create_embed(
            title="🚨 Inicio de Servicio | Santiago RP",
            description=(
                f"Has iniciado tu servicio el **{start_time.strftime('%Y-%m-%d %H:%M:%S')}**.\n\n"
                "**Advertencias**:\n"
                "- Si no estás roleando durante este período, serás acreedor a una **sanción**.\n"
                "- Si no estás en el canal de radio (<https://discord.com/channels/1339386615147266108/1353854926220034099>), serás acreedor a una **sanción**.\n\n"
                "Usa el botón abajo para terminar tu servicio."
            ),
            color=Colors.PRIMARY
        )
        view = ServiceButtons(interaction.user.id)
        try:
            await interaction.user.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.response.send_message(embed=create_embed(
                title="⚠️ No se pudo enviar DM",
                description="No puedo enviarte un mensaje directo. Habilita los DMs del servidor para recibir detalles de tu servicio.",
                color=Colors.WARNING
            ), ephemeral=True)
            return

        await interaction.response.send_message(embed=create_embed(
            title="✅ Servicio Iniciado",
            description="Tu servicio ha comenzado. Revisa tus DMs para terminar el servicio.",
            color=Colors.SUCCESS
        ), ephemeral=True)
    except mysql.connector.Error as err:
        await interaction.response.send_message(embed=create_embed(
            title="❌ Error",
            description=f"No se pudo registrar el servicio debido a un error en la base de datos: {err}",
            color=Colors.DANGER
        ), ephemeral=True)

# Modals para tickets
class PostularPDIModal(ui.Modal, title="Postular a la PDI"):
    roblox_name = ui.TextInput(
        label="Nombre de Roblox",
        placeholder="Ej: RobloxUser123",
        required=True,
        max_length=100
    )
    motivation = ui.TextInput(
        label="Motivación para postular",
        placeholder="Describe por qué quieres unirte a PDI",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )
    experience = ui.TextInput(
        label="Experiencia previa (opcional)",
        placeholder="Ej: Experiencia en roleplay o servidores similares",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        await self.create_ticket(interaction, "postular-pdi")

    async def create_ticket(self, interaction: discord.Interaction, option: str):
        global ticket_counter
        ticket_counter += 1
        category = bot.get_channel(Categories.TICKET)
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                embed=create_embed(
                    title="❌ Error",
                    description="No se encontró la categoría de tickets.",
                    color=Colors.DANGER
                ),
                ephemeral=True
            )
            return

        channel_name = f"postular-pdi-{ticket_counter:03d}"
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(Roles.TICKET_VIEW_2): discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        ticket_channel = await interaction.guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites
        )

        embed = create_embed(
            title="🎫 Ticket Abierto | Postular a la PDI",
            description=f"**Abierto por**: {interaction.user.mention}\n\n**Detalles de la postulación:**",
            color=Colors.PRIMARY
        )
        embed.add_field(name="Nombre de Roblox", value=self.roblox_name.value, inline=False)
        embed.add_field(name="Motivación", value=self.motivation.value, inline=False)
        embed.add_field(name="Experiencia", value=self.experience.value or "No proporcionado", inline=False)
        view = TicketButtons()
        await ticket_channel.send(embed=embed, view=view)

        await interaction.response.send_message(
            embed=create_embed(
                title="✅ Ticket Abierto",
                description=f"Tu ticket ha sido abierto con éxito en {ticket_channel.mention}.",
                color=Colors.SUCCESS
            ),
            ephemeral=True
        )

        log_channel = bot.get_channel(Channels.TICKET_LOG)
        if log_channel:
            await log_channel.send(embed=create_embed(
                title="📝 Ticket Abierto",
                description=f"**Usuario**: {interaction.user.mention}\n**Opción**: Postular a la PDI\n**Canal**: {ticket_channel.mention}",
                color=Colors.PRIMARY
            ))

class ReportarOficialModal(ui.Modal, title="Reportar Oficial"):
    roblox_name = ui.TextInput(
        label="Nombre de Roblox a quien reporta",
        placeholder="Ej: RobloxUser123",
        required=True,
        max_length=100
    )
    reason = ui.TextInput(
        label="Razón del reporte",
        placeholder="Describe el motivo del reporte",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )
    evidence = ui.TextInput(
        label="Link de las pruebas (opcional)",
        placeholder="Ej: https://youtube.com/...",
        required=False,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        await self.create_ticket(interaction, "reportar-oficial")

    async def create_ticket(self, interaction: discord.Interaction, option: str):
        global ticket_counter
        ticket_counter += 1
        category = bot.get_channel(Categories.TICKET)
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                embed=create_embed(
                    title="❌ Error",
                    description="No se encontró la categoría de tickets.",
                    color=Colors.DANGER
                ),
                ephemeral=True
            )
            return

        channel_name = f"reportar-oficial-{ticket_counter:03d}"
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(Roles.TICKET_VIEW_2): discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        ticket_channel = await interaction.guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites
        )

        embed = create_embed(
            title="🎫 Ticket Abierto | Reportar Oficial",
            description=f"**Abierto por**: {interaction.user.mention}\n\n**Detalles del reporte:**",
            color=Colors.PRIMARY
        )
        embed.add_field(name="Nombre de Roblox", value=self.roblox_name.value, inline=False)
        embed.add_field(name="Razón", value=self.reason.value, inline=False)
        embed.add_field(name="Pruebas", value=self.evidence.value or "No proporcionado", inline=False)
        view = TicketButtons()
        await ticket_channel.send(embed=embed, view=view)

        await interaction.response.send_message(
            embed=create_embed(
                title="✅ Ticket Abierto",
                description=f"Tu ticket ha sido abierto con éxito en {ticket_channel.mention}.",
                color=Colors.SUCCESS
            ),
            ephemeral=True
        )

        log_channel = bot.get_channel(Channels.TICKET_LOG)
        if log_channel:
            await log_channel.send(embed=create_embed(
                title="📝 Ticket Abierto",
                description=f"**Usuario**: {interaction.user.mention}\n**Opción**: Reportar Oficial\n**Canal**: {ticket_channel.mention}",
                color=Colors.PRIMARY
            ))

class DenunciaModal(ui.Modal, title="Denuncia"):
    cedula_name = ui.TextInput(
        label="Nombre de cédula a quien denuncia",
        placeholder="Ej: Juan_Perez_123",
        required=True,
        max_length=100
    )
    reason = ui.TextInput(
        label="Razón de la denuncia",
        placeholder="Describe el motivo de la denuncia",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )
    evidence = ui.TextInput(
        label="Link de las pruebas (opcional)",
        placeholder="Ej: https://youtube.com/...",
        required=False,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        await self.create_ticket(interaction, "denuncia")

    async def create_ticket(self, interaction: discord.Interaction, option: str):
        global ticket_counter
        ticket_counter += 1
        category = bot.get_channel(Categories.TICKET)
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                embed=create_embed(
                    title="❌ Error",
                    description="No se encontró la categoría de tickets.",
                    color=Colors.DANGER
                ),
                ephemeral=True
            )
            return

        channel_name = f"denuncia-{ticket_counter:03d}"
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(Roles.TICKET_VIEW_1): discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(Roles.TICKET_VIEW_2): discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        ticket_channel = await interaction.guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites
        )

        embed = create_embed(
            title="🎫 Ticket Abierto | Denuncia",
            description=f"**Abierto por**: {interaction.user.mention}\n\n**Detalles de la denuncia:**",
            color=Colors.PRIMARY
        )
        embed.add_field(name="Nombre de Cédula", value=self.cedula_name.value, inline=False)
        embed.add_field(name="Razón", value=self.reason.value, inline=False)
        embed.add_field(name="Pruebas", value=self.evidence.value or "No proporcionado", inline=False)
        view = TicketButtons()
        await ticket_channel.send(embed=embed, view=view)

        await interaction.response.send_message(
            embed=create_embed(
                title="✅ Ticket Abierto",
                description=f"Tu ticket ha sido abierto con éxito en {ticket_channel.mention}.",
                color=Colors.SUCCESS
            ),
            ephemeral=True
        )

        log_channel = bot.get_channel(Channels.TICKET_LOG)
        if log_channel:
            await log_channel.send(embed=create_embed(
                title="📝 Ticket Abierto",
                description=f"**Usuario**: {interaction.user.mention}\n**Opción**: Denuncia\n**Canal**: {ticket_channel.mention}",
                color=Colors.PRIMARY
            ))

class ApelarSancionModal(ui.Modal, title="Apelar Sanción"):
    roblox_name = ui.TextInput(
        label="Nombre de Roblox sancionado",
        placeholder="Ej: RobloxUser123",
        required=True,
        max_length=100
    )
    reason = ui.TextInput(
        label="Razón de la apelación",
        placeholder="Describe por qué apelas la sanción",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )
    evidence = ui.TextInput(
        label="Link de las pruebas (opcional)",
        placeholder="Ej: https://youtube.com/...",
        required=False,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        await self.create_ticket(interaction, "apelar-sancion")

    async def create_ticket(self, interaction: discord.Interaction, option: str):
        global ticket_counter
        ticket_counter += 1
        category = bot.get_channel(Categories.TICKET)
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                embed=create_embed(
                    title="❌ Error",
                    description="No se encontró la categoría de tickets.",
                    color=Colors.DANGER
                ),
                ephemeral=True
            )
            return

        channel_name = f"apelar-sancion-{ticket_counter:03d}"
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(Roles.TICKET_VIEW_1): discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(Roles.TICKET_VIEW_2): discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        ticket_channel = await interaction.guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites
        )

        embed = create_embed(
            title="🎫 Ticket Abierto | Apelar Sanción",
            description=f"**Abierto por**: {interaction.user.mention}\n\n**Detalles de la apelación:**",
            color=Colors.PRIMARY
        )
        embed.add_field(name="Nombre de Roblox", value=self.roblox_name.value, inline=False)
        embed.add_field(name="Razón", value=self.reason.value, inline=False)
        embed.add_field(name="Pruebas", value=self.evidence.value or "No proporcionado", inline=False)
        view = TicketButtons()
        await ticket_channel.send(embed=embed, view=view)

        await interaction.response.send_message(
            embed=create_embed(
                title="✅ Ticket Abierto",
                description=f"Tu ticket ha sido abierto con éxito en {ticket_channel.mention}.",
                color=Colors.SUCCESS
            ),
            ephemeral=True
        )

        log_channel = bot.get_channel(Channels.TICKET_LOG)
        if log_channel:
            await log_channel.send(embed=create_embed(
                title="📝 Ticket Abierto",
                description=f"**Usuario**: {interaction.user.mention}\n**Opción**: Apelar Sanción\n**Canal**: {ticket_channel.mention}",
                color=Colors.PRIMARY
            ))

class CerrarCasoModal(ui.Modal, title="Cerrar Caso"):
    reason = ui.TextInput(
        label="Razón del cierre",
        placeholder="Describe por qué se cierra el caso",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        embed = create_embed(
            title="🔒 Ticket Cerrado",
            description=f"**Cerrado por**: {interaction.user.mention}\n**Razón**: {self.reason.value}",
            color=Colors.WARNING
        )
        await interaction.response.send_message(embed=embed)

        log_channel = bot.get_channel(Channels.TICKET_LOG)
        if log_channel:
            await log_channel.send(embed=create_embed(
                title="📝 Ticket Cerrado",
                description=f"**Cerrado por**: {interaction.user.mention}\n**Canal**: {interaction.channel.mention}\n**Razón**: {self.reason.value}",
                color=Colors.WARNING
            ))

        await interaction.channel.edit(overwrites={
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=False),
            bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(Roles.TICKET_VIEW_1): discord.PermissionOverwrite(read_messages=True, send_messages=False),
            interaction.guild.get_role(Roles.TICKET_VIEW_2): discord.PermissionOverwrite(read_messages=True, send_messages=False)
        })

        await asyncio.sleep(5)
        await interaction.channel.delete()

# Vistas interactivas para PDI Panel
class PDIInfoView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Significados", style=discord.ButtonStyle.primary, emoji="📖", custom_id=f"pdi_significados_{uuid.uuid4()}")
    async def significados_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(
            title="📖 Significados PDI",
            description="Definiciones de términos y roles utilizados en Santiago RP:",
            color=Colors.PRIMARY
        )
        embed.add_field(
            name="Vehículos y Roles",
            value=(
                "**AC**: Auto de calle | Persecuciones de alta velocidad | Patrullajes cortos | Encubierto.\n"
                "**AT**: Auto todo terreno | Persecuciones patrullajes largos | Encubierto.\n"
                "**AE**: Auto especial | Patrullajes cortos | Persecuciones.\n"
                "**BRTM**: Brigada de reacción táctica Metropolitana.\n"
                "**ERTA**: Equipo de reacción táctica Antinarcóticos.\n"
                "**IMÁN**: PDI.\n"
                "**CAPA**: Carabineros.\n"
                "**H**: Helicóptero."
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Códigos y Balizas", style=discord.ButtonStyle.primary, emoji="🚨", custom_id=f"pdi_codigos_{uuid.uuid4()}")
    async def codigos_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(
            title="🚨 Uso de Códigos y Balizas",
            description="Protocolos para el uso de sirenas y balizas en operaciones policiales:",
            color=Colors.PRIMARY
        )
        embed.add_field(
            name="Etapas",
            value=(
                "**Stage 1**: Patrullaje | Marcar presencia.\n"
                "**Stage 2**: Procedimientos | Marcar presencia | Marcar peligro.\n"
                "**Stage 3**: Persecuciones | Procedimiento."
            ),
            inline=False
        )
        embed.add_field(
            name="Códigos",
            value=(
                "**Código 1**: Sin Sirenas y Sin Balizas.\n"
                "**Código 2**: Sin Sirenas, Con Balizas.\n"
                "**Código 3**: Con Sirenas, Con Balizas."
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Uso de la Fuerza", style=discord.ButtonStyle.primary, emoji="👮", custom_id=f"pdi_fuerza_{uuid.uuid4()}")
    async def fuerza_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(
            title="👮 Uso de la Fuerza",
            description="Escala de uso de la fuerza según la situación:",
            color=Colors.PRIMARY
        )
        embed.add_field(
            name="Niveles",
            value=(
                "**Presencia policial / Riesgo latente**: Mostrar presencia física y profesional para disuadir.\n"
                "**Verbalización Cooperador**: Diálogo y órdenes claras para cooperación voluntaria.\n"
                "**Control de contacto / No cooperador**: Contacto físico mínimo para asegurar cumplimiento.\n"
                "**Control físico / Resistencia física**: Técnicas avanzadas de inmovilización.\n"
                "**Tácticas no letales / Agresividad no letal**: Escopeta de balines, esposas, fuerza física.\n"
                "**Fuerza letal / Agresividad letal**: Último recurso para proteger vidas."
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Códigos de Radio", style=discord.ButtonStyle.primary, emoji="📻", custom_id=f"pdi_radio_{uuid.uuid4()}")
    async def radio_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(
            title="📻 Códigos de Radio - Claves 10",
            description="Códigos utilizados para comunicaciones por radio (divididos en partes):",
            color=Colors.PRIMARY
        )
        codes_part1 = (
            "**10-01**: Recibiendo mal.\n**10-02**: Recibiendo bien.\n**10-03**: Problemas con la transmisión.\n"
            "**10-04**: Afirmativo.\n**10-05**: Negativo.\n**10-06**: Ocupado.\n**10-07**: Fuera de servicio.\n"
            "**10-08**: En servicio.\n**10-09**: Repita transmisión.\n**10-10**: Hablando muy rápido.\n"
            "**10-11**: Civiles presentes.\n**10-12**: Informe.\n**10-13**: Novedades.\n**10-14**: Sin novedades.\n"
            "**10-15**: Recoger PDI en...\n**10-16**: Negociación en curso.\n**10-17**: Sujeto en custodia.\n"
            "**10-18**: Solicito transporte.\n**10-19**: Escoltando a Prisión/Estación.\n**10-20**: Posición actual."
        )
        codes_part2 = (
            "**10-21**: Dirigirse a estación.\n**10-22**: Se necesita supervisor.\n**10-23**: Stand by.\n"
            "**10-24**: Parada de tráfico.\n**10-25**: Ponerse en contacto con.\n**10-26**: Ignorar.\n"
            "**10-27**: Problemas en la estación.\n**10-28**: Se necesita BRTM.\n**10-29**: Se solicita SML.\n"
            "**10-30**: Información confidencial.\n**10-31**: Se necesita grúa en...\n**10-32**: Se necesita ambulancia en...\n"
            "**10-33**: Vehículo robado.\n**10-34**: Riesgo latente.\n**10-35**: En escena.\n**10-36**: Accidente de tráfico.\n"
            "**10-37**: Todas las unidades a estación.\n**10-38**: Pausa (Comer o descanso).\n**10-39**: ¿Quién llama?\n"
            "**10-40**: Carretera o calle cerrada en..."
        )
        codes_part3 = (
            "**10-41**: Peatón intoxicado.\n**10-42**: Persona entrando en escena.\n**10-43**: Persona saliendo de escena.\n"
            "**10-44**: Acaten transmisión.\n**10-45**: Incendio en...\n**10-46**: Reunirse en...\n**10-47**: Solicitar información.\n"
            "**10-48**: Abrir fuego.\n**10-49**: Detener el fuego.\n**10-50**: Persecución vehicular.\n**10-51**: Persecución a pie.\n"
            "**10-52**: Disparos.\n**10-53**: Solicitar refuerzos.\n**10-54**: Hacer perímetro."
        )
        embed.add_field(name="Códigos (Parte 1)", value=codes_part1, inline=False)
        embed.add_field(name="Códigos (Parte 2)", value=codes_part2, inline=False)
        embed.add_field(name="Códigos (Parte 3)", value=codes_part3, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Maniobra PIT", style=discord.ButtonStyle.primary, emoji="🚗", custom_id=f"pdi_pit_{uuid.uuid4()}")
    async def pit_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(
            title="🚗 Maniobra PIT",
            description="Detalles sobre la maniobra PIT y sus restricciones:",
            color=Colors.PRIMARY
        )
        embed.add_field(
            name="Definición",
            value="El **Código PIT** es una maniobra de gran destrucción que usa el parachoques trasero del vehículo sospechoso. Puede volcar el vehículo.",
            inline=False
        )
        embed.add_field(
            name="Circunstancias",
            value=(
                "Velocidad del vehículo: **20 km/h mínimo** y **100 km/h máximo**.\n"
                "**Prohibido en ciudad**. Solo en autopistas, carreteras y zonas despejadas."
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Equipamiento", style=discord.ButtonStyle.primary, emoji="🎒", custom_id=f"pdi_equipamiento_{uuid.uuid4()}")
    async def equipamiento_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(
            title="🎒 Equipamiento Básico",
            description="Equipamiento estándar para oficiales de PDI:",
            color=Colors.PRIMARY
        )
        embed.add_field(
            name="Personal",
            value="Glock 18, Linterna, Esposas, Libreta, MDT, Identificación Policial.",
            inline=False
        )
        embed.add_field(
            name="Maletero",
            value="Pinchos, Conos, Mp5, Escopeta Fabarm FP6, Chaleco de cambio (Rol), Instrumentos de investigación, Medkit (Rol).",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Derechos del Detenido | Santiago RP", style=discord.ButtonStyle.green, emoji="⚖️", custom_id=f"pdi_derechos_{uuid.uuid4()}")
    async def derechos_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(
            title="⚖️ Derechos del Detenido | Santiago RP",
            description="Derechos fundamentales de toda persona detenida según la normativa de PDI en Santiago RP:",
            color=Colors.SUCCESS
        )
        embed.add_field(
            name="Derechos",
            value=(
                "1. **Derecho a ser informado**: El detenido debe ser informado de los motivos de su detención de forma clara y comprensible.\n"
                "2. **Derecho a un abogado**: Tiene derecho a contactar y ser asistido por un abogado, ya sea privado o de oficio.\n"
                "3. **Derecho al silencio**: Puede abstenerse de declarar sin que esto se use en su contra.\n"
                "4. **Derecho a no ser maltratado**: Está protegido contra cualquier tipo de abuso físico o psicológico.\n"
                "5. **Derecho a comunicación**: Puede informar a un familiar o persona de confianza sobre su detención.\n"
                "6. **Derecho a atención médica**: Si lo necesita, debe recibir atención médica inmediata.\n"
                "7. **Derecho a un intérprete**: Si no habla el idioma, tiene derecho a un intérprete."
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Reglas PDI | Santiago RP", style=discord.ButtonStyle.green, emoji="📜", custom_id=f"pdi_reglas_{uuid.uuid4()}")
    async def reglas_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(
            title="📜 Reglas PDI | Santiago RP",
            description="Normas que deben seguir todos los oficiales de PDI en Santiago RP. Cualquier incumplimiento resultará en una sanción según la gravedad.",
            color=Colors.SUCCESS
        )
        embed.add_field(
            name="Reglas",
            value=(
                "1. **Buen comportamiento**: Mantener una actitud profesional en todo momento.\n"
                "2. **Respeto a compañeros**: Tratar a todos los miembros con respeto.\n"
                "3. **Uniforme adecuado**: Portar siempre el uniforme asignado.\n"
                "4. **Obediencia al mando**: Acatar las órdenes del alto mando inmediato.\n"
                "5. **Vehículos asignados**: Usar solo los vehículos asignados, sin operaciones encubiertas salvo autorización.\n"
                "6. **Conducción responsable**: Conducir de manera segura y profesional.\n"
                "7. **Trabajo en binomio**: Nunca operar solo, siempre en pareja.\n"
                "8. **Armamento asignado**: Usar únicamente el armamento proporcionado.\n"
                "9. **Control de ruido**: Usar 'presionar para hablar' si hay ruido externo.\n"
                "10. **Diversión responsable**: Disfrutar del rol con seriedad, siendo un ejemplo para el servidor."
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Requisitos de Ingreso | Santiago RP", style=discord.ButtonStyle.green, emoji="✅", custom_id=f"pdi_requisitos_{uuid.uuid4()}")
    async def requisitos_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(
            title="✅ Requisitos de Ingreso | Santiago RP",
            description="Requisitos para formar parte de PDI en Santiago RP:",
            color=Colors.SUCCESS
        )
        embed.add_field(
            name="Requisitos",
            value=(
                "1. **Micrófono**: Poseer un micrófono funcional.\n"
                "2. **Habilidad de rol**: Saber rolear de manera inmersiva.\n"
                "3. **Conocimiento de normativas**: Conocer las normativas de SantiagoRP y PDI.\n"
                "4. **Historial limpio**: No tener antecedentes ni multas.\n"
                "5. **Licencias**: Poseer licencia de armas y de conducir (mínimo Clase B).\n"
                "6. **Disciplina**: Ser disciplinado y responsable.\n"
                "7. **Disponibilidad**: Contar con un mínimo de 5 horas semanales para rolear."
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Normativas SantiagoRP", style=discord.ButtonStyle.green, emoji="🔗", custom_id=f"pdi_normativas_{uuid.uuid4()}")
    async def normativas_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(
            title="🔗 Normativas del Servidor SantiagoRP",
            description="Consulta las normativas oficiales del servidor SantiagoRP:",
            color=Colors.SUCCESS
        )
        embed.add_field(
            name="Enlace",
            value="[Normativas SantiagoRP](https://santiago-roleplay-or-normas.gitbook.io/untitled/)",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Vistas interactivas para Ticket
class TicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.select(
        placeholder="Selecciona una opción para abrir un ticket...",
        options=[
            discord.SelectOption(
                label="Postular a la PDI",
                value="postular_pdi",
                description="Solicita unirte a la PDI en Santiago RP",
                emoji="⭐"
            ),
            discord.SelectOption(
                label="Reportar Oficial",
                value="reportar_oficial",
                description="Reporta un mal comportamiento de un oficial",
                emoji="🚨"
            ),
            discord.SelectOption(
                label="Apelar Sanción",
                value="apelar_sancion",
                description="Solicita revisión de una sanción recibida",
                emoji="⚖️"
            ),
            discord.SelectOption(
                label="Denuncia",
                value="denuncia",
                description="Denuncia un problema grave en el servidor",
                emoji="📢"
            ),
            discord.SelectOption(
                label="Ayuda General",
                value="ayuda_general",
                description="Consulta o soporte general",
                emoji="❓"
            )
        ],
        custom_id="ticket_select"
    )
    async def ticket_select(self, interaction: discord.Interaction, select: ui.Select):
        value = select.values[0]
        if value == "postular_pdi":
            await interaction.response.send_modal(PostularPDIModal())
        elif value == "reportar_oficial":
            await interaction.response.send_modal(ReportarOficialModal())
        elif value == "denuncia":
            await interaction.response.send_modal(DenunciaModal())
        elif value == "apelar_sancion":
            await interaction.response.send_modal(ApelarSancionModal())
        else:  # ayuda_general
            global ticket_counter
            ticket_counter += 1
            category = bot.get_channel(Categories.TICKET)
            if not category or not isinstance(category, discord.CategoryChannel):
                await interaction.response.send_message(
                    embed=create_embed(
                        title="❌ Error",
                        description="No se encontró la categoría de tickets.",
                        color=Colors.DANGER
                    ),
                    ephemeral=True
                )
                return

            channel_name = f"ayuda-general-{ticket_counter:03d}"
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.guild.get_role(Roles.TICKET_VIEW_1): discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.guild.get_role(Roles.TICKET_VIEW_2): discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            ticket_channel = await interaction.guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=overwrites
            )

            embed = create_embed(
                title="🎫 Ticket Abierto | Ayuda General",
                description=f"**Abierto por**: {interaction.user.mention}\n\nPor favor, describe tu consulta o problema.",
                color=Colors.PRIMARY
            )
            view = TicketButtons()
            await ticket_channel.send(embed=embed, view=view)

            await interaction.response.send_message(
                embed=create_embed(
                    title="✅ Ticket Abierto",
                    description=f"Tu ticket ha sido abierto con éxito en {ticket_channel.mention}.",
                    color=Colors.SUCCESS
                ),
                ephemeral=True
            )

            log_channel = bot.get_channel(Channels.TICKET_LOG)
            if log_channel:
                await log_channel.send(embed=create_embed(
                    title="📝 Ticket Abierto",
                    description=f"**Usuario**: {interaction.user.mention}\n**Opción**: Ayuda General\n**Canal**: {ticket_channel.mention}",
                    color=Colors.PRIMARY
                ))

# Vistas para botones de ticket
class TicketButtons(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Reclamar el Caso", style=discord.ButtonStyle.primary, emoji="👨‍⚖️", custom_id="claim_case")
    async def claim_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(
            title="📌 Caso Reclamado",
            description=f"**Atendido por**: {interaction.user.mention}\nEste caso será manejado por el staff mencionado.",
            color=Colors.SUCCESS
        )
        await interaction.response.send_message(embed=embed)

        log_channel = bot.get_channel(Channels.TICKET_LOG)
        if log_channel:
            await log_channel.send(embed=create_embed(
                title="📝 Caso Reclamado",
                description=f"**Reclamado por**: {interaction.user.mention}\n**Canal**: {interaction.channel.mention}",
                color=Colors.SUCCESS
            ))

    @ui.button(label="Cerrar el Caso", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_case")
    async def close_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CerrarCasoModal())

# Verificación de canal para PDI panel
def is_pdi_info_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.channel_id != Channels.PDI_INFO:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Canal Incorrecto",
                description=f"Este comando solo puede usarse en <#{Channels.PDI_INFO}>.",
                color=Colors.DANGER
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# Verificación de permisos para purgar
def can_purge_messages():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Permisos Insuficientes",
                description="El bot necesita el permiso **Gestionar Mensajes** para purgar el canal.",
                color=Colors.DANGER
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# Verificación de canal para sugerir
def is_sugerir_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.channel_id != Channels.SUGERIR_INPUT:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Canal Incorrecto",
                description=f"Este comando solo puede usarse en <#{Channels.SUGERIR_INPUT}>.",
                color=Colors.DANGER
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# Verificación de rol para sugerir
def is_allowed_user():
    async def predicate(interaction: discord.Interaction) -> bool:
        has_role = any(role.id == Roles.SUGERIR_ALLOWED for role in interaction.user.roles)
        if not has_role:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Permiso Denegado",
                description="No tienes el rol necesario para usar este comando.",
                color=Colors.DANGER
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# Verificación de canal para ticket
def is_ticket_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.channel_id != Channels.TICKET:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Canal Incorrecto",
                description=f"Este comando solo puede usarse en <#{Channels.TICKET}>.",
                color=Colors.DANGER
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# Verificación de canal para busca
def is_busca_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.channel_id != Channels.BUSCA:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Canal Incorrecto",
                description=f"Este comando solo puede usarse en <#{Channels.BUSCA}>.",
                color=Colors.DANGER
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# Autocompletado para grado de peligrosidad
async def peligro_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    options = ['Bajo', 'Moderado', 'Alto', 'Extremo']
    return [
        app_commands.Choice(name=option, value=option)
        for option in options
        if current.lower() in option.lower()
    ]

# Autocompletado para grado de búsqueda
async def busqueda_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    options = ['Local', 'Regional', 'Nacional', 'Internacional']
    return [
        app_commands.Choice(name=option, value=option)
        for option in options
        if current.lower() in option.lower()
    ]

# Evento de inicio
@bot.event
async def on_ready():
    print(f'✨ {bot.user.name} está listo!')
    try:
        synced = await bot.tree.sync()
        print(f"🔁 Comandos sincronizados: {', '.join([cmd.name for cmd in synced])}")
    except Exception as e:
        print(f"❌ Error en on_ready: {e}")
    weekly_leaderboard.start()

# Comando /pdi-panel
@bot.tree.command(name="pdi-panel", description="Despliega un panel interactivo con información de PDI y purga el canal")
@app_commands.checks.has_permissions(administrator=True)
@is_pdi_info_channel()
@can_purge_messages()
async def pdi_panel(interaction: discord.Interaction):
    channel = interaction.channel
    await channel.purge(limit=100)
    
    embed = create_embed(
        title="🚔 Panel de Información PDI | Santiago RP",
        description=(
            "Bienvenido al **Panel de Información de PDI** en Santiago RP. "
            "Utiliza los botones a continuación para acceder a información sobre procedimientos, códigos, equipamiento, derechos del detenido, reglas de PDI, requisitos de ingreso y normativas del servidor."
        ),
        color=Colors.PRIMARY
    )
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else "")
    
    view = PDIInfoView()
    await interaction.response.send_message(embed=embed, view=view)

# Comando /sugerir
@bot.tree.command(name="sugerir", description="Envía una sugerencia para Santiago RP")
@app_commands.describe(
    sugerencia="La sugerencia que propones (mínimo 2 palabras)",
    utilidad="Por qué sería útil (mínimo 5 palabras)"
)
@is_sugerir_channel()
@is_allowed_user()
async def sugerir(interaction: discord.Interaction, sugerencia: str, utilidad: str):
    sugerencia_words = sugerencia.split()
    utilidad_words = utilidad.split()
    
    if len(sugerencia_words) < 2:
        await interaction.response.send_message(embed=create_embed(
            title="❌ Error en la Sugerencia",
            description="La sugerencia debe tener al menos **2 palabras**.",
            color=Colors.DANGER
        ), ephemeral=True)
        return
    
    if len(utilidad_words) < 5:
        await interaction.response.send_message(embed=create_embed(
            title="❌ Error en la Utilidad",
            description="La explicación de utilidad debe tener al menos **5 palabras**.",
            color=Colors.DANGER
        ), ephemeral=True)
        return

    await interaction.response.send_message(embed=create_embed(
        title="✅ Sugerencia Enviada",
        description="Tu sugerencia ha sido enviada con éxito.",
        color=Colors.SUCCESS
    ), ephemeral=True)

    suggestion_embed = create_embed(
        title="💡 Nueva Sugerencia | Santiago RP",
        description=f"Sugerencia propuesta por **{interaction.user.display_name}**.",
        color=Colors.PRIMARY
    )
    suggestion_embed.add_field(
        name="Sugerencia",
        value=sugerencia,
        inline=False
    )
    suggestion_embed.add_field(
        name="¿Por qué sería útil?",
        value=utilidad,
        inline=False
    )
    suggestion_embed.add_field(
        name="Estado",
        value="Esta sugerencia será llevada a cabo si recibe **10 reacciones**.",
        inline=False
    )
    suggestion_embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else "")

    suggestion_channel = bot.get_channel(Channels.SUGERIR_OUTPUT)
    if suggestion_channel:
        message = await suggestion_channel.send(embed=suggestion_embed)
        await message.add_reaction("✅")
    else:
        print(f"❌ No se encontró el canal de sugerencias con ID {Channels.SUGERIR_OUTPUT}")

# Comando /ticket
@bot.tree.command(name="ticket", description="Despliega un panel de tickets para reportes y soporte")
@app_commands.checks.has_permissions(administrator=True)
@is_ticket_channel()
@can_purge_messages()
async def ticket(interaction: discord.Interaction):
    channel = interaction.channel
    await channel.purge(limit=100)
    
    embed = create_embed(
        title="🎫 Sistema de Tickets | Santiago RP",
        description=(
            "**¡Atención!** Abrir un ticket sin justificación alguna resultará en una sanción.\n\n"
            "Selecciona una opción del menú desplegable para abrir un ticket. A continuación, se detalla para qué sirve cada opción:"
        ),
        color=Colors.PRIMARY
    )
    embed.add_field(
        name="📋 Opciones del Menú",
        value=(
            "**Postular a la PDI**: Para solicitar unirte a la PDI en Santiago RP.\n"
            "**Reportar Oficial**: Para reportar un mal comportamiento o abuso por parte de un oficial de PDI.\n"
            "**Apelar Sanción**: Para solicitar la revisión de una sanción o castigo recibido en el servidor.\n"
            "**Denuncia**: Para reportar problemas graves, como violaciones de reglas o conductas inapropiadas.\n"
            "**Ayuda General**: Para consultas generales, dudas sobre el servidor o soporte técnico."
        ),
        inline=False
    )
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else "")

    view = TicketView()
    await interaction.response.send_message(embed=embed, view=view)

# Comando /buscar-a
@bot.tree.command(name="buscar-a", description="Publica una ficha de búsqueda de una persona")
@app_commands.describe(
    nombre="Nombre de la persona buscada",
    razon="Razón por la que se busca a la persona",
    grado_peligrosidad="Grado de peligrosidad de la persona",
    grado_busqueda="Alcance de la búsqueda",
    foto="Foto de la persona buscada (imagen)"
)
@app_commands.autocomplete(grado_peligrosidad=peligro_autocomplete, grado_busqueda=busqueda_autocomplete)
@app_commands.checks.has_permissions(administrator=True)
@is_busca_channel()
async def buscar_a(
    interaction: discord.Interaction,
    nombre: str,
    razon: str,
    grado_peligrosidad: str,
    grado_busqueda: str,
    foto: discord.Attachment
):
    valid_extensions = ['.png', '.jpg', '.jpeg', '.gif']
    if not any(foto.filename.lower().endswith(ext) for ext in valid_extensions):
        await interaction.response.send_message(embed=create_embed(
            title="❌ Error en la Foto",
            description="El archivo adjunto debe ser una imagen (PNG, JPG, JPEG, GIF).",
            color=Colors.DANGER
        ), ephemeral=True)
        return

    embed = discord.Embed(
        title="🚨 FICHA DE BÚSQUEDA | PDI Santiago RP",
        description=f"**¡SE BUSCA!** {nombre.upper()}",
        color=Colors.WANTED,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Razón", value=razon, inline=False)
    embed.add_field(name="Grado de Peligrosidad", value=grado_peligrosidad, inline=True)
    embed.add_field(name="Grado de Búsqueda", value=grado_busqueda, inline=True)
    embed.add_field(name="Autorizado por", value=interaction.user.mention, inline=False)
    embed.set_image(url=foto.url)
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    embed.set_footer(text="Santiago RP | Contacte a PDI con cualquier información")

    role = interaction.guild.get_role(Roles.BUSCA_PING)
    await interaction.response.send_message(
        content=f"<@&{Roles.BUSCA_PING}>",
        embed=embed
    )

@bot.tree.command(name="horas-semanales", description="Muestra las horas semanales de todos los usuarios registrados")
@is_horas_semanales_channel()
@is_allowed_horas_semanales()
async def horas_semanales(interaction: discord.Interaction):
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE
        )
        c = conn.cursor()
        c.execute('SELECT user_id, total_hours FROM user_hours')
        users = c.fetchall()
        conn.close()

        if not users:
            await interaction.response.send_message(embed=create_embed(
                title="📊 Horas Semanales | Santiago RP",
                description="No hay usuarios registrados con horas en la base de datos.",
                color=Colors.PRIMARY
            ), ephemeral=True)
            return

        description_lines = []
        for user_id, total_hours in users:
            try:
                user = await bot.fetch_user(user_id)
                status = "✅" if total_hours >= 5 else "❌"
                description_lines.append(f"{user.mention}: **{total_hours:.2f} horas** {status}")
            except discord.NotFound:
                status = "✅" if total_hours >= 5 else "❌"
                description_lines.append(f"Usuario ID {user_id}: **{total_hours:.2f} horas** {status}")

        embed = create_embed(
            title="📊 Horas Semanales | Santiago RP",
            description="\n".join(description_lines),
            color=Colors.PRIMARY
        )
        embed.set_footer(text="✅ = 5+ horas | ❌ = Menos de 5 horas")

        await interaction.response.send_message(embed=embed, ephemeral=False)
    except mysql.connector.Error as err:
        await interaction.response.send_message(embed=create_embed(
            title="❌ Error",
            description=f"No se pudieron obtener las horas debido a un error en la base de datos: {err}",
            color=Colors.DANGER
        ), ephemeral=True)

@bot.tree.command(name="sancionar-a", description="Registra una sanción para un usuario")
@is_sancionar_channel()
@is_allowed_horas_semanales()
@app_commands.describe(
    usuario="Usuario a sancionar",
    razon="Razón de la sanción",
    tipo_sancion="Tipo de sanción",
    archivo_prueba="Archivo de prueba de la sanción (opcional, debe ser imagen)"
)
@app_commands.autocomplete(tipo_sancion=tipo_sancion_autocomplete)
async def sancionar_a(interaction: discord.Interaction, usuario: discord.Member, razon: str, tipo_sancion: str, archivo_prueba: discord.Attachment = None):
    valid_sanciones = ["1345894049818611868", "1345894049818611867", "1345894049818611866", "1345894049818611865"]
    if tipo_sancion not in valid_sanciones:
        await interaction.response.send_message(embed=create_embed(
            title="❌ Error",
            description="Tipo de sanción inválido. Selecciona una opción válida.",
            color=Colors.DANGER
        ), ephemeral=True)
        return

    foto_prueba_url = None
    if archivo_prueba:
        valid_extensions = ['.png', '.jpg', '.jpeg', '.gif']
        if not any(archivo_prueba.filename.lower().endswith(ext) for ext in valid_extensions):
            await interaction.response.send_message(embed=create_embed(
                title="❌ Error",
                description="El archivo debe ser una imagen (PNG, JPG, JPEG, GIF).",
                color=Colors.DANGER
            ), ephemeral=True)
            return
        foto_prueba_url = archivo_prueba.url

    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE
        )
        c = conn.cursor()
        timestamp = datetime.now(dt.UTC).isoformat()
        c.execute('''
            INSERT INTO sanciones (user_id, oficial_id, razon, tipo_sancion, foto_prueba, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (usuario.id, interaction.user.id, razon, tipo_sancion, foto_prueba_url, timestamp))
        conn.commit()

        c.execute('SELECT COUNT(*) FROM sanciones WHERE user_id = %s', (usuario.id,))
        sanciones_count = c.fetchone()[0]
        conn.close()

        if sanciones_count >= 4:
            try:
                await usuario.send(embed=create_embed(
                    title="⚠️ Advertencia de Sanciones",
                    description=(
                        "Has acumulado **4 o más sanciones**. Estás en peligro de ser **revocado de servicio** o **baneado del servidor**.\n"
                        "Por favor, revisa tu comportamiento y contacta a un administrador si tienes dudas."
                    ),
                    color=Colors.WARNING
                ))
            except discord.Forbidden:
                pass

        sancion_name = {
            "1345894049818611868": "Sanción 1",
            "1345894049818611867": "Sanción 2",
            "1345894049818611866": "Sanción 3",
            "1345894049818611865": "Sanción 4"
        }[tipo_sancion]
        
        embed = create_embed(
            title="🚨 Ficha de Sanción | Santiago RP",
            description=f"Se ha registrado una sanción para {usuario.mention}.",
            color=Colors.DANGER
        )
        embed.add_field(name="Usuario Sancionado", value=usuario.mention, inline=True)
        embed.add_field(name="Oficial", value=interaction.user.mention, inline=True)
        embed.add_field(name="Razón", value=razon, inline=False)
        embed.add_field(name="Tipo de Sanción", value=sancion_name, inline=True)
        embed.add_field(name="Total de Sanciones", value=str(sanciones_count), inline=True)
        if foto_prueba_url:
            embed.add_field(name="Prueba", value=f"[Ver Prueba]({foto_prueba_url})", inline=False)
            embed.set_image(url=foto_prueba_url)
        embed.set_thumbnail(url=usuario.avatar.url if usuario.avatar else None)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        sanciones_channel = bot.get_channel(1365195938674511913)
        if sanciones_channel:
            await sanciones_channel.send(embed=embed)
        else:
            await interaction.response.send_message(embed=create_embed(
                title="❌ Error",
                description="No se pudo enviar la sanción al canal de sanciones. Contacta a un administrador.",
                color=Colors.DANGER
            ), ephemeral=True)
            return

        await interaction.response.send_message(embed=create_embed(
            title="✅ Sanción Registrada",
            description=f"La sanción para {usuario.mention} ha sido enviada al canal <#{1365195938674511913}>.",
            color=Colors.SUCCESS
        ), ephemeral=True)
    except mysql.connector.Error as err:
        await interaction.response.send_message(embed=create_embed(
            title="❌ Error",
            description=f"No se pudo registrar la sanción debido a un error en la base de datos: {err}",
            color=Colors.DANGER
        ), ephemeral=True)

# Iniciar el bot
if __name__ == "__main__":
    bot.run(TOKEN)