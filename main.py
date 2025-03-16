import asyncio
import yaml
import requests
import argparse
import time
import aiohttp
import base64
from rich.console import Console
from rich.logging import RichHandler
from rich.traceback import install
from nio import AsyncClient, MatrixRoom, RoomMessageText, RoomMessageImage, RoomMessageAudio, RoomMessageFile

# Configuration des logs avec Rich
install()
console = Console()
logging_config = {
    "level": "INFO",
    "format": "%(message)s",
    "handlers": [RichHandler(console=console, show_time=True, show_path=False)]
}

import logging
logging.basicConfig(**logging_config)
logger = logging.getLogger("matrix-bridge")


class MatrixBot(AsyncClient):
    """
    MatrixBot
    """

    def __init__(self, bot_config):
        """
        Initialisation du bot avec un fichier de configuration YAML.
        """
        self.bot_config = bot_config
        super().__init__(self.bot_config["matrix"]["homeserver"], self.bot_config["matrix"]["user_id"])
        self.access_token = self.bot_config["matrix"]["access_token"]
        self.last_event_timestamp = int(time.time() * 1000)
    # end __init__

    def transform_mxc_url(self, mxc_url):
        """
        Convert a link to a media file to a direct download link.
        """
        if not mxc_url.startswith("mxc://"):
            return None
        # end if
        server_name, media_id = mxc_url.replace("mxc://", "").split("/")
        return f"{self.bot_config['matrix']['homeserver']}/_matrix/v3/download/{server_name}/{media_id}"
    # end transform_mxc_url

    def check_timestamp(self, event):
        """
        Check if the event timestamp is greater than the last event timestamp.

        Args:
            event (nio.events.room_events.RoomEvent): The event to check

        Returns:
            bool: True if the event timestamp is greater than the last event timestamp
        """
        if event.server_timestamp > self.last_event_timestamp:
            self.last_event_timestamp = event.server_timestamp
            return True
        # end if
        return False
    # end check_timestamp

    async def download_media(self, url):
        """
        Télécharge le contenu du fichier et le convertit en base64.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return base64.b64encode(await resp.read()).decode(), resp.status
                # end if
                return None, resp.status
            # end if
        # end with
    # end download_media

    async def message_callback(self, room: MatrixRoom, event: RoomMessageText):
        """
        Gérer les messages texte reçus.
        """
        if not self.check_timestamp(event):
            return
        # end if

        # Log
        logger.info(f"[TEXT] {event.sender} at {event.server_timestamp} vs {self.last_event_timestamp}")

        payload = {
            "type": "text",
            "sender": event.sender,
            "message": event.body,
            "event_id": event.event_id,
            "room_id": room.room_id
        }
        requests.post(self.bot_config["n8n"]["webhook_url"], json=payload, verify=False)
    # end message_callback

    async def image_callback(self, room: MatrixRoom, event: RoomMessageImage):
        """
        Gérer les images envoyées.
        """
        if not self.check_timestamp(event):
            return
        # end if

        image_url = self.transform_mxc_url(event.url)
        media_data, response_status = await self.download_media(image_url) if image_url else None

        logger.info(f"[IMAGE] {event.sender}")
        if not media_data: logger.warning(f"Cannot download media from URL {image_url}, status code {response_status}")
        payload = {
            "type": "image",
            "sender": event.sender,
            "url": image_url,
            "event_id": event.event_id,
            "room_id": room.room_id,
            "data": media_data
        }
        requests.post(self.bot_config["n8n"]["webhook_url"], json=payload, verify=False)
    # end image_callback

    async def audio_callback(self, room: MatrixRoom, event: RoomMessageAudio):
        """
        Gérer les fichiers audio.
        """
        if not self.check_timestamp(event):
            return
        # end if

        audio_url = self.transform_mxc_url(event.url)
        logger.info(f"[AUDIO] {event.sender}")
        payload = {
            "type": "audio",
            "sender": event.sender,
            "url": audio_url,
            "event_id": event.event_id,
            "room_id": room.room_id
        }
        requests.post(self.bot_config["n8n"]["webhook_url"], json=payload, verify=False)
    # end audio_callback

    async def file_callback(self, room: MatrixRoom, event: RoomMessageFile):
        """
        Gérer les fichiers envoyés.
        """
        if not self.check_timestamp(event):
            return
        # end if

        file_url = self.transform_mxc_url(event.url)
        logger.info(f"[FILE] {event.sender}")
        payload = {
            "type": "file",
            "sender": event.sender,
            "url": file_url,
            "event_id": event.event_id,
            "room_id": room.room_id
        }
        requests.post(self.bot_config["n8n"]["webhook_url"], json=payload, verify=False)
    # end file_callback
# end MatrixBot


async def main(config_path):
    """
    Charger la configuration et démarrer le bot.
    """
    # Charger la configuration YAML
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    bot = MatrixBot(config)

    logger.info("Connexion à Matrix...")
    await bot.login(config["matrix"]["user_password"])

    # Rejoindre la salle
    await bot.join(config["matrix"]["room_id"])

    # Ajouter les callbacks pour différents types de messages
    bot.add_event_callback(bot.message_callback, RoomMessageText)
    bot.add_event_callback(bot.image_callback, RoomMessageImage)
    bot.add_event_callback(bot.audio_callback, RoomMessageAudio)
    bot.add_event_callback(bot.file_callback, RoomMessageFile)

    logger.info("Bot en écoute...")

    # Boucle d'écoute
    await bot.sync_forever(timeout=30000)
# end main


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Matrix Bot Bridge")
    parser.add_argument("--config", required=True, help="Chemin vers le fichier de configuration YAML")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.config))
    except Exception as e:
        logger.exception("Erreur fatale lors de l'exécution du bot :")
# end if
