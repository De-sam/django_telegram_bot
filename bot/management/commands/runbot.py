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

# --- Optional: simple single-instance lock (POSIX) ---
LOCK_PATH = "/tmp/telegram_bot_runbot.lock"
_lock_fd = None
def acquire_lock():
    # On Windows you'd use portalocker instead; this is POSIX-only.
    global _lock_fd
    try:
        import fcntl
        _lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
        fcntl.lockf(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info("Acquired bot lock: %s", LOCK_PATH)
        return True
    except Exception:
        logger.error("Another bot instance seems to be running (lock: %s). Exiting.", LOCK_PATH)
        return False

def release_lock():
    global _lock_fd
    try:
        if _lock_fd is not None:
            os.close(_lock_fd)
            _lock_fd = None
            logger.info("Released bot lock.")
    except Exception:
        pass
# --- End lock helpers ---


class Command(BaseCommand):
    help = 'Run the Telegram bot'

    def handle(self, *args, **kwargs):
        # Ensure only one process runs
        if not acquire_lock():
            return

        logger.info("Starting Telegram bot with 20 threads...")

        # Remove webhook so polling doesn't conflict with it
        try:
            # pyTelegramBotAPI >=4.x
            bot.delete_webhook(drop_pending_updates=True)
            logger.info("Deleted webhook (drop_pending_updates=True).")
        except AttributeError:
            # Older versions use remove_webhook()
            try:
                bot.remove_webhook()
                logger.info("Removed webhook.")
            except Exception as e:
                logger.warning(f"Failed to remove webhook: {e}")
        except Exception as e:
            logger.warning(f"delete_webhook failed: {e}")

        # Register handlers
        register_ticket_handlers(bot)
        register_agent_handlers(bot)
        register_customer_handlers(bot)

        # Setup graceful shutdown
        def shutdown_handler(signum, frame):
            logger.info("Received shutdown signal. Stopping bot gracefully...")
            try:
                bot.stop_polling()
            except Exception:
                pass
            release_lock()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

        # Retry loop to keep bot alive
        while True:
            try:
                bot.polling(none_stop=True, timeout=60)
            except requests.exceptions.RequestException as e:
                logger.error(f"Network error: {e}. Retrying in 10s...")
                try:
                    bot.stop_polling()  # make sure old polling stops before retry
                except Exception:
                    pass
                time.sleep(10)
            except Exception as e:
                logger.exception(f"Bot crashed unexpectedly: {e}. Restarting in 15s...")
                try:
                    bot.stop_polling()  # prevent overlapping pollers that cause 409
                except Exception:
                    pass
                time.sleep(15)
