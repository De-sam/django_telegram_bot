from django.core.management.base import BaseCommand
import os, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'botcore.settings')
django.setup()

import telebot
from django.conf import settings

from customers.bot_handlers import register_customer_handlers
from tickets.bot_handlers import register_ticket_handlers
from agents.bot_handlers import register_agent_handlers

bot = telebot.TeleBot(settings.TELEGRAM_BOT_TOKEN)

class Command(BaseCommand):
    help = 'Run the Telegram bot'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting bot polling...")

        register_agent_handlers(bot)
        register_customer_handlers(bot)
        register_ticket_handlers()
        

        bot.polling(none_stop=True)
