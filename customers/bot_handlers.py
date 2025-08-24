from django.conf import settings
from telebot.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
)
from customers.models import Customer, CustomerMessage
from tickets.models import Ticket
from agents.models import Agent
import re
import os
import logging

logger = logging.getLogger(__name__)

# -------------------------------
# Helpers
# -------------------------------
def sanitize_text(text: str) -> str:
    """Ensure UTF-8 safe text for Telegram."""
    return text.encode('utf-8', errors='ignore').decode('utf-8')

def accepted_types_message() -> str:
    """User-facing message for invalid file types based on settings."""
    readable = getattr(settings, 'ACCEPTED_TYPES_READABLE', 'PDF, JPG, PNG, DOCX')
    return (
        "❌ Invalid file type.\n\n"
        f"✅ Accepted file types: {readable}.\n"
        "• PDF (.pdf)\n"
        "• Word Document (.docx)\n"
        "• Images (.jpg, .jpeg, .png)\n\n"
        "Tip: If you’re sending a PNG photo, send it as a *file/document* so the bot can detect the .png extension."
    )

def has_allowed_extension(filename: str) -> bool:
    """Validate by extension using settings.ALLOWED_EXTENSIONS."""
    allowed_exts = getattr(settings, 'ALLOWED_EXTENSIONS', {'.pdf', '.docx', '.jpg', '.jpeg', '.png'})
    if not filename:
        return False
    _, ext = os.path.splitext(filename)
    return ext.lower() in allowed_exts

def has_allowed_mime(mime_type: str) -> bool:
    """Validate by MIME using settings.ALLOWED_MIME_PREFIXES."""
    allowed_mimes = getattr(settings, 'ALLOWED_MIME_PREFIXES', {
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'image/jpeg',
        'image/png',
    })
    if not mime_type:
        return False
    return mime_type in allowed_mimes

def is_allowed_document(document) -> bool:
    """Validate Telegram 'document' by filename extension or MIME."""
    name_ok = has_allowed_extension(getattr(document, 'file_name', '') or '')
    mime_ok = has_allowed_mime(getattr(document, 'mime_type', '') or '')
    return name_ok or mime_ok

# In-memory state store for media caption handling
_pending_media = {}

# -------------------------------
# Handlers
# -------------------------------
def register_customer_handlers(bot):
    @bot.message_handler(commands=['start'])
    def handle_start(message: Message):
        customer, _ = Customer.objects.get_or_create(telegram_id=message.from_user.id)
        customer.full_name = message.from_user.full_name
        customer.language_code = message.from_user.language_code
        customer.save()

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📋 FAQ", callback_data="show_faq"))
        bot.send_message(
            message.chat.id,
            settings.TEXT_MESSAGES['start'].format(customer.full_name),
            reply_markup=markup
        )

    @bot.message_handler(content_types=['text'])
    def handle_text(message: Message):
        user_id = message.from_user.id
        text = (message.text or "").strip()

        # Check if user is in caption input state
        if user_id in _pending_media:
            media_data = _pending_media[user_id]
            caption = text or "[No caption provided]"
            content_type = media_data['content_type']
            customer = media_data['customer']
            customer_message = media_data['customer_message']
            ticket = media_data.get('ticket')

            # Update the existing media message with the caption
            try:
                customer_message.message_text = caption
                customer_message.save()
                logger.info(f"Updated media message caption for customer {user_id}, message_id: {customer_message.id}")
            except Exception as e:
                logger.error(f"Failed to update media message with caption for customer {user_id}: {e}")
                bot.send_message(message.chat.id, "⚠️ Failed to process your caption. Please try again.")
                customer_message.delete()
                del _pending_media[user_id]
                return

            # If claimed, forward directly to agent
            if ticket and ticket.agent:
                label = f"📨 Media from {customer.full_name or customer.telegram_id}"
                final_caption = sanitize_text(f"{label}\n\n{caption}")
                try:
                    if content_type == 'photo':
                        bot.send_photo(
                            ticket.agent.telegram_id,
                            media_data['file_id'],
                            caption=final_caption
                        )
                        logger.info(f"Forwarded photo to agent {ticket.agent.telegram_id} for ticket {ticket.id}")
                    elif content_type == 'document':
                        bot.send_document(
                            ticket.agent.telegram_id,
                            media_data['file_id'],
                            caption=final_caption
                        )
                        logger.info(f"Forwarded document to agent {ticket.agent.telegram_id} for ticket {ticket.id}")
                    customer_message.is_forwarded = True
                    customer_message.save()
                    logger.info(f"Marked message {customer_message.id} as forwarded for customer {user_id}")
                except Exception as e:
                    logger.error(f"Failed to forward media to agent for customer {user_id}, ticket {ticket.id if ticket else 'None'}: {e}")
                    bot.send_message(message.chat.id, "⚠️ Failed to forward your message. Please try again.")
                    customer_message.delete()
                    del _pending_media[user_id]
                    return
                bot.send_message(
                    message.chat.id,
                    "✅ Your file and caption have been sent to our support team.",
                    parse_mode="Markdown"
                )
                del _pending_media[user_id]
                return

            # Unclaimed: follow 3-message queue logic
            message_count = CustomerMessage.objects.filter(customer=customer).count()
            label = f"📩 ID:customer {customer.id:03d}"
            full_caption = sanitize_text(f"{label}\n\n{caption}")

            if message_count == 1:
                try:
                    ticket = Ticket.objects.create(customer=customer)
                    logger.info(f"Created new ticket {ticket.id} for customer {user_id}")
                except Exception as e:
                    logger.error(f"Failed to create ticket for customer {user_id}: {e}")
                    bot.send_message(message.chat.id, "⚠️ Failed to create a ticket. Please try again.")
                    customer_message.delete()
                    del _pending_media[user_id]
                    return

                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton("🎫 Claim Ticket", callback_data=f"claim_{ticket.id}"),
                    InlineKeyboardButton("👀 Preview Messages", callback_data=f"preview_{ticket.id}")
                )

                try:
                    if content_type == 'photo':
                        bot.send_photo(
                            settings.SUPPORT_CHAT,
                            media_data['file_id'],
                            caption=full_caption,
                            reply_markup=markup
                        )
                        logger.info(f"Forwarded photo to support group for ticket {ticket.id}")
                    elif content_type == 'document':
                        bot.send_document(
                            settings.SUPPORT_CHAT,
                            media_data['file_id'],
                            caption=full_caption,
                            reply_markup=markup
                        )
                        logger.info(f"Forwarded document to support group for ticket {ticket.id}")
                    customer_message.is_forwarded = True
                    customer_message.save()
                    logger.info(f"Marked message {customer_message.id} as forwarded to support group for customer {user_id}")
                except Exception as e:
                    logger.error(f"Failed to forward media to support group for customer {user_id}, ticket {ticket.id}: {e}")
                    bot.send_message(message.chat.id, "⚠️ Failed to forward your message. Please try again.")
                    customer_message.delete()
                    del _pending_media[user_id]
                    return

                bot.send_message(
                    message.chat.id,
                    "✅ Your file and caption have been received. You may send *two more messages* if needed.",
                    parse_mode="Markdown"
                )
            elif message_count in [2, 3]:
                bot.send_message(message.chat.id, f"📄 File and caption queued ({message_count}/3). Thank you.")
            else:
                bot.send_message(message.chat.id, "⚠️ You've reached the message limit. An agent will get back to you shortly.")
                logger.warning(f"Customer {user_id} reached message limit with {message_count} messages")
            del _pending_media[user_id]
            return

        # Block agents/admins from opening tickets as customers
        is_agent = Agent.objects.filter(telegram_id=user_id).exists()
        is_admin = user_id in settings.ADMIN_IDS
        if is_agent or is_admin:
            role = "Admin" if is_admin else "Agent"
            if is_agent and is_admin:
                role = "Admin & Agent"
            bot.send_message(
                message.chat.id,
                f"ℹ️ Hello {role}, you’re currently registered with elevated access.\n"
                f"You cannot open support tickets as a customer.\n\n"
                "If you’re testing the bot, please use a separate non-agent account."
            )
            return

        # Language filter
        if getattr(settings, 'BAD_WORDS_TOGGLE', False):
            if re.match(settings.REGEX_FILTER['bad_words'], text or "", re.IGNORECASE):
                bot.reply_to(message, "⚠️ Please mind your language.")
                return

        # Get/Create customer
        customer, _ = Customer.objects.get_or_create(telegram_id=user_id)

        # Save message
        try:
            customer_message = CustomerMessage.objects.create(
                customer=customer,
                message_text=text,
                message_type=message.content_type,
                telegram_message_id=message.message_id
            )
            logger.info(f"Saved text message {customer_message.id} for customer {user_id}")
        except Exception as e:
            logger.error(f"Failed to save message for customer {user_id}: {e}")
            bot.reply_to(message, "⚠️ Failed to process your message. Please try again.")
            return

        # If there's a claimed ticket, forward directly to assigned agent
        ticket = Ticket.objects.filter(customer=customer, is_claimed=True, is_closed=False).first()
        if ticket and ticket.agent:
            label = f"📨 Customer {customer.full_name or customer.telegram_id}"
            msg = f"{label}:\n\n{text}"
            try:
                bot.send_message(ticket.agent.telegram_id, sanitize_text(msg))
                customer_message.is_forwarded = True
                customer_message.save()
                logger.info(f"Forwarded message from customer {user_id} to agent {ticket.agent.telegram_id} for ticket {ticket.id}")
            except Exception as e:
                logger.error(f"Failed to forward message to agent for customer {user_id}: {e}")
                bot.reply_to(message, "⚠️ Failed to forward your message. Please try again.")
                customer_message.delete()
                return
            return

        # 3-message queue logic for unclaimed tickets
        message_count = CustomerMessage.objects.filter(customer=customer).count()
        if message_count == 1:
            try:
                ticket = Ticket.objects.create(customer=customer)
                logger.info(f"Created new ticket {ticket.id} for customer {user_id}")
            except Exception as e:
                logger.error(f"Failed to create ticket for customer {user_id}: {e}")
                bot.reply_to(message, "⚠️ Failed to create a ticket. Please try again.")
                customer_message.delete()
                return

            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("🎫 Claim Ticket", callback_data=f"claim_{ticket.id}"),
                InlineKeyboardButton("👀 Preview Messages", callback_data=f"preview_{ticket.id}")
            )

            forwarded_text = f"📩 ID:customer {customer.id:03d}\n\n{text}"
            try:
                bot.send_message(settings.SUPPORT_CHAT, sanitize_text(forwarded_text), reply_markup=markup)
                customer_message.is_forwarded = True
                customer_message.save()
                logger.info(f"Forwarded message from customer {user_id} to support group for ticket {ticket.id}")
            except Exception as e:
                logger.error(f"Failed to forward message to support group for customer {user_id}: {e}")
                bot.reply_to(message, "⚠️ Failed to forward your message. Please try again.")
                customer_message.delete()
                return

            bot.send_message(
                message.chat.id,
                "✅ Your message has been successfully sent to our support team.\n\n"
                "An agent will get back to you shortly.\n"
                "You may send *up to two more messages* with additional details if needed.",
                parse_mode="Markdown"
            )
        elif message_count in [2, 3]:
            bot.send_message(
                message.chat.id,
                f"💬 Got it! We've queued your message ({message_count}/3). An agent will review it once available."
            )
        else:
            bot.send_message(
                message.chat.id,
                "⚠️ You've reached the message limit. Please wait while an agent reviews your inquiry."
            )
            logger.warning(f"Customer {user_id} reached message limit with {message_count} messages")

    @bot.message_handler(content_types=['photo', 'document', 'video'])
    def handle_media(message: Message):
        user_id = message.from_user.id

        # Block agents/admins
        is_agent = Agent.objects.filter(telegram_id=user_id).exists()
        is_admin = user_id in settings.ADMIN_IDS
        if is_agent or is_admin:
            role = "Admin" if is_admin else "Agent"
            if is_agent and is_admin:
                role = "Admin & Agent"
            bot.send_message(
                message.chat.id,
                f"ℹ️ Hello {role}, you’re currently registered with elevated access.\n"
                f"You cannot open support tickets as a customer.\n\n"
                "If you’re testing the bot, please use a separate non-agent account."
            )
            return

        # Reject videos outright per policy
        if message.content_type == 'video':
            bot.send_message(message.chat.id, accepted_types_message(), parse_mode="Markdown")
            return

        # Validate document types using settings
        if message.content_type == 'document':
            if not is_allowed_document(message.document):
                bot.send_message(message.chat.id, accepted_types_message(), parse_mode="Markdown")
                return

        # Get/Create customer
        customer, _ = Customer.objects.get_or_create(telegram_id=user_id)

        # Store media info and create a preliminary message
        file_id = message.photo[-1].file_id if message.content_type == 'photo' else message.document.file_id
        message_count = CustomerMessage.objects.filter(customer=customer).count()
        ticket = Ticket.objects.filter(customer=customer, is_claimed=True, is_closed=False).first()

        # Save media message with a temporary caption
        try:
            customer_message = CustomerMessage.objects.create(
                customer=customer,
                message_text="[Pending caption]",
                message_type=message.content_type,
                telegram_message_id=message.message_id
            )
            logger.info(f"Saved preliminary media message {customer_message.id} for customer {user_id}")
        except Exception as e:
            logger.error(f"Failed to save media message for customer {user_id}: {e}")
            bot.send_message(message.chat.id, "⚠️ Failed to process your message. Please try again.")
            return

        _pending_media[user_id] = {
            'content_type': message.content_type,
            'file_id': file_id,
            'customer': customer,
            'message_count': message_count + 1,  # Include the media message in count
            'ticket': ticket,
            'customer_message': customer_message
        }

        bot.send_message(
            message.chat.id,
            "📷 Please provide a caption for your media file.",
            parse_mode="Markdown"
        )