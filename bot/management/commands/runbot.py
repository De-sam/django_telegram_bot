# runbot.py
import os
import django
import logging
import signal
import sys
import time

from django.core.management.base import BaseCommand
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botcore.settings')
django.setup()

import telebot
import requests

from customers.bot_handlers import register_customer_handlers
from tickets.bot_handlers import register_ticket_handlers
from agents.bot_handlers import register_agent_handlers


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

bot = telebot.TeleBot(settings.TELEGRAM_BOT_TOKEN, threaded=True, num_threads=20)


class Command(BaseCommand):
    help = 'Run the Telegram bot'

    def handle(self, *args, **kwargs):
        logger.info("Starting Telegram bot with 20 threads...")

        # Register handlers
        register_ticket_handlers(bot)
        register_agent_handlers(bot)
        register_customer_handlers(bot)

        # Setup graceful shutdown
        def shutdown_handler(signum, frame):
            logger.info("Received shutdown signal. Stopping bot gracefully...")
            bot.stop_polling()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

        # Retry loop to keep bot alive
        while True:
            try:
                bot.polling(none_stop=True, timeout=60)
            except requests.exceptions.RequestException as e:
                # Network/Telegram API errors
                logger.error(f"Network error: {e}. Retrying in 10s...")
                time.sleep(10)
            except Exception as e:
                # Catch-all for unexpected crashes
                logger.exception(f"Bot crashed unexpectedly: {e}. Restarting in 15s...")
                time.sleep(15)
