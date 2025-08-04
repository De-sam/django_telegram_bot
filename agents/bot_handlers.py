# agents/bot_handlers.py

from telebot.types import Message
from agents.views import create_pending_agent, is_registered_agent

def register_agent_handlers(bot):
    @bot.message_handler(commands=['become_agent'])
    def ask_full_name(message: Message):
        if is_registered_agent(message.from_user.id):
            bot.send_message(message.chat.id, "✅ You are already an agent.")
            return

        msg = bot.send_message(message.chat.id, "Please enter your full name to apply as an agent:")
        bot.register_next_step_handler(msg, collect_language)

    def collect_language(message: Message):
        full_name = message.text.strip()
        user_id = message.from_user.id

        msg = bot.send_message(message.chat.id, "Great. What is your preferred language? (e.g., en, fr, de)")
        bot.register_next_step_handler(msg, lambda msg2: finish_application(msg2, full_name, user_id))

    def finish_application(message: Message, full_name, user_id):
        language = message.text.strip()
        create_pending_agent(user_id, full_name, language)
        bot.send_message(message.chat.id, "🎉 Application submitted! An admin will review and approve you soon.")
