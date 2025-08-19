from telebot.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from agents.views import create_pending_agent, is_registered_agent
from agents.models import Agent, PendingAgent
from tickets.models import Ticket
from customers.models import Customer
from django.conf import settings
from datetime import datetime, timedelta  # ⏱️ For expiring invite link

def sanitize_text(text):
    return text.encode('utf-8', errors='ignore').decode('utf-8')

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

        # Notify user
        bot.send_message(message.chat.id, "🎉 Application submitted! An admin will review and approve you soon.")

        # Notify admins with inline buttons
        for admin_id in settings.ADMIN_IDS:
            markup = InlineKeyboardMarkup()
            markup.row(
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
            )
            bot.send_message(
                admin_id,
                f"👤 New Agent Application:\n\nFull Name: {full_name}\nTelegram ID: {user_id}\nLanguage: {language}",
                reply_markup=markup
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
    def handle_admin_decision(call: CallbackQuery):
        action, telegram_id = call.data.split("_")
        telegram_id = int(telegram_id)

        try:
            pending = PendingAgent.objects.get(telegram_id=telegram_id)
        except PendingAgent.DoesNotExist:
            bot.answer_callback_query(call.id, "❌ Application not found.")
            return

        if action == "approve":
            # Create Agent
            Agent.objects.create(
                telegram_id=pending.telegram_id,
                full_name=pending.full_name,
                language=pending.language
            )
            pending.delete()

            # ✅ One-time, expiring link for this agent
            try:
                invite = bot.create_chat_invite_link(
                    chat_id=settings.SUPPORT_CHAT,
                    member_limit=1,
                    expire_date=int((datetime.utcnow() + timedelta(minutes=5)).timestamp()),
                    creates_join_request=False,
                    name=f"AgentInvite-{telegram_id}"
                )
                invite_link = invite.invite_link
                bot.send_message(
                    telegram_id,
                    f"🎉 Congratulations! You’ve been approved as a support agent.\n\n"
                    f"👉 Join the support group with this one-time link (valid 5 minutes):\n{invite_link}"
                )
            except Exception as e:
                bot.send_message(call.message.chat.id, f"⚠️ Agent approved, but invite link could not be created: {e}")

            bot.edit_message_text("✅ Agent approved and invite sent.", call.message.chat.id, call.message.message_id)

        elif action == "reject":
            pending.delete()
            bot.edit_message_text("❌ Application rejected and removed.", call.message.chat.id, call.message.message_id)
            bot.send_message(telegram_id, "😞 Sorry, your application to become an agent was rejected.")

    # ✅ Text reply from agent to customer
    @bot.message_handler(func=lambda msg: is_registered_agent(msg.from_user.id), content_types=['text'])
    def handle_agent_reply(message: Message):
        agent_id = message.from_user.id
        text = message.text.strip()

        ticket = Ticket.objects.filter(agent__telegram_id=agent_id, is_claimed=True, is_closed=False).first()
        if not ticket:
            bot.send_message(message.chat.id, "⚠️ You don’t have an active ticket. Claim one before replying.")
            return

        customer = ticket.customer
        label = f"👨‍💼 Agent {message.from_user.full_name or agent_id}"
        full_message = f"{label}:\n\n{text}"
        bot.send_message(customer.telegram_id, sanitize_text(full_message))

    # ✅ Media files from agent to customer
    @bot.message_handler(func=lambda msg: is_registered_agent(msg.from_user.id), content_types=['photo', 'document', 'video'])
    def handle_agent_media(message: Message):
        agent_id = message.from_user.id
        ticket = Ticket.objects.filter(agent__telegram_id=agent_id, is_claimed=True, is_closed=False).first()

        if not ticket:
            bot.send_message(message.chat.id, "⚠️ You don’t have an active ticket. Claim one before sending files.")
            return

        customer = ticket.customer
        caption = message.caption or ""
        caption = sanitize_text(caption)

        if message.content_type == 'photo':
            bot.send_photo(customer.telegram_id, message.photo[-1].file_id, caption=caption)
        elif message.content_type == 'document':
            bot.send_document(customer.telegram_id, message.document.file_id, caption=caption)
        elif message.content_type == 'video':
            bot.send_video(customer.telegram_id, message.video.file_id, caption=caption)

        bot.send_message(message.chat.id, "✅ Sent to customer.")
