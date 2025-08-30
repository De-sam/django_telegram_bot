from django.conf import settings
from telebot.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
)
from utils import sanitize_text, get_active_ticket_for_customer
from tickets.models import Ticket
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
        "Tip: If you’re sending a PNG photo, send it as a file/document so the bot can detect the .png extension."
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

        # -----------------------------------------
        # 0) If user is providing a caption for a media message
        # -----------------------------------------
        if user_id in _pending_media:
            media_data = _pending_media[user_id]
            caption = text or "[No caption provided]"
            content_type = media_data['content_type']
            customer = media_data['customer']
            customer_message = media_data['customer_message']
            ticket = media_data.get('ticket')  # may be None if this media started a new conversation

            # Update media message's caption in DB
            try:
                customer_message.message_text = caption
                customer_message.save()
                logger.info(f"Updated media caption for customer {user_id}, msg_id: {customer_message.id}")
            except Exception as e:
                logger.error(f"Caption save failed for customer {user_id}: {e}")
                bot.send_message(message.chat.id, "⚠️ Failed to process your caption. Please try again.")
                customer_message.delete()
                del _pending_media[user_id]
                return

            # If there's an active, claimed ticket with an agent → forward directly to agent
            if ticket and ticket.agent:
                label = f"📨 Media from {customer.full_name or customer.telegram_id}"
                final_caption = sanitize_text(f"{label}\n\n{caption}")
                try:
                    if content_type == 'photo':
                        bot.send_photo(ticket.agent.telegram_id, media_data['file_id'], caption=final_caption)
                    elif content_type == 'document':
                        bot.send_document(ticket.agent.telegram_id, media_data['file_id'], caption=final_caption)
                    customer_message.is_forwarded = True
                    customer_message.save()
                    logger.info(f"Forwarded media to agent {ticket.agent.telegram_id} (ticket {ticket.id})")
                except Exception as e:
                    logger.error(f"Media forward to agent failed (cust {user_id}, ticket {ticket.id if ticket else 'None'}): {e}")
                    bot.send_message(message.chat.id, "⚠️ Failed to forward your message. Please try again.")
                    customer_message.delete()
                    del _pending_media[user_id]
                    return

                bot.send_message(message.chat.id, "✅ Your file and caption have been sent to our support team.", parse_mode="Markdown")
                del _pending_media[user_id]
                return

            # Per-ticket queue logic for UNCLAIMED flow
            # If no active ticket (approved/closed previously), create a fresh ticket
            if not ticket:
                try:
                    ticket = Ticket.objects.create(customer=customer)
                    # Attach this media message to the new ticket
                    CustomerMessage.objects.filter(id=customer_message.id).update(ticket=ticket)
                    logger.info(f"Created new ticket {ticket.id} for customer {user_id} (media caption)")
                except Exception as e:
                    logger.error(f"Ticket create failed for customer {user_id} (media): {e}")
                    bot.send_message(message.chat.id, "⚠️ Failed to create a ticket. Please try again.")
                    customer_message.delete()
                    del _pending_media[user_id]
                    return

                # Count unforwarded messages for THIS ticket
                count = CustomerMessage.objects.filter(customer=customer, ticket=ticket, is_forwarded=False).count()  # should be 1
                label = f"📩 Customer ID:{customer.id:03d}"
                full_caption = sanitize_text(f"{label}\n\n{caption}")

                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton("🎫 Claim Ticket", callback_data=f"claim_{ticket.id}"),
                    InlineKeyboardButton("👀 Preview Messages", callback_data=f"preview_{ticket.id}")
                )
                try:
                    if content_type == 'photo':
                        bot.send_photo(settings.SUPPORT_CHAT, media_data['file_id'], caption=full_caption, reply_markup=markup)
                    elif content_type == 'document':
                        bot.send_document(settings.SUPPORT_CHAT, media_data['file_id'], caption=full_caption, reply_markup=markup)
                    customer_message.is_forwarded = True
                    customer_message.save()
                    logger.info(f"Forwarded media to group for ticket {ticket.id}")
                except Exception as e:
                    logger.error(f"Forward media to group failed (cust {user_id}, ticket {ticket.id}): {e}")
                    bot.send_message(message.chat.id, "⚠️ Failed to forward your message. Please try again.")
                    customer_message.delete()
                    del _pending_media[user_id]
                    return

                bot.send_message(message.chat.id, "✅ Your file and caption have been received. You may send two more messages if needed.", parse_mode="Markdown")
                del _pending_media[user_id]
                return

            # Ticket exists but is UNCLAIMED → per-ticket counting
            count = CustomerMessage.objects.filter(customer=customer, ticket=ticket, is_forwarded=False).count()
            label = f"📩 Customer ID:{customer.id:03d}"
            full_caption = sanitize_text(f"{label}\n\n{caption}")

            if count == 1:
                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton("🎫 Claim Ticket", callback_data=f"claim_{ticket.id}"),
                    InlineKeyboardButton("👀 Preview Messages", callback_data=f"preview_{ticket.id}")
                )
                try:
                    if content_type == 'photo':
                        bot.send_photo(settings.SUPPORT_CHAT, media_data['file_id'], caption=full_caption, reply_markup=markup)
                    elif content_type == 'document':
                        bot.send_document(settings.SUPPORT_CHAT, media_data['file_id'], caption=full_caption, reply_markup=markup)
                    customer_message.is_forwarded = True
                    customer_message.save()
                    logger.info(f"Forwarded media to group (ticket {ticket.id})")
                except Exception as e:
                    logger.error(f"Forward media to group failed (cust {user_id}, ticket {ticket.id}): {e}")
                    bot.send_message(message.chat.id, "⚠️ Failed to forward your message. Please try again.")
                    customer_message.delete()
                    del _pending_media[user_id]
                    return

                bot.send_message(message.chat.id, "✅ File received. You may send two more messages if needed.", parse_mode="Markdown")
            elif count in (2, 3):
                bot.send_message(message.chat.id, f"📄 File and caption queued ({count}/3). Thank you.")
            else:
                bot.send_message(message.chat.id, "⚠️ You've reached the message limit. An agent will get back to you shortly.")
                logger.warning(f"Customer {user_id} reached per-ticket message limit (ticket {ticket.id})")

            del _pending_media[user_id]
            return

        # -----------------------------------------
        # 1) Block agents/admins from opening tickets as customers
        # -----------------------------------------
        is_agent = Agent.objects.filter(telegram_id=user_id).exists()
        is_admin = user_id in getattr(settings, 'ADMIN_IDS', [])
        if is_agent or is_admin:
            role = "Admin" if is_admin else "Agent"
            if is_agent and is_admin:
                role = "Admin & Agent"
            bot.send_message(
                message.chat.id,
                f"ℹ️ Hello {role}, you’re registered with elevated access.\n"
                f"You cannot open support tickets as a customer.\n\n"
                "If you’re testing the bot, please use a separate non-agent account."
            )
            return

        # -----------------------------------------
        # 2) Language / bad-words filter (safe guard)
        # -----------------------------------------
        if getattr(settings, 'BAD_WORDS_TOGGLE', False):
            pattern = getattr(settings, 'REGEX_FILTER', {}).get('bad_words')
            if pattern and re.match(pattern, text or "", re.IGNORECASE):
                bot.reply_to(message, "⚠️ Please mind your language.")
                return

        # -----------------------------------------
        # 3) Get/Create customer + find active ticket (not finally approved)
        # -----------------------------------------
        customer, _ = Customer.objects.get_or_create(telegram_id=user_id)
        ticket = get_active_ticket_for_customer(customer)  # may be None

        # Save the incoming text, attach to ticket if present
        try:
            customer_message = CustomerMessage.objects.create(
                customer=customer,
                ticket=ticket,  # None if first message of a brand new ticket
                message_text=text,
                message_type=message.content_type,
                telegram_message_id=message.message_id
            )
            logger.info(f"Saved text message {customer_message.id} for customer {user_id}")
        except Exception as e:
            logger.error(f"Failed to save message for customer {user_id}: {e}")
            bot.reply_to(message, "⚠️ Failed to process your message. Please try again.")
            return

        # -----------------------------------------
        # 4) If claimed ticket with agent → forward straight to agent
        # -----------------------------------------
        if ticket and ticket.is_claimed and ticket.agent:
            label = f"📨 Customer {customer.full_name or customer.telegram_id}"
            msg = f"{label}:\n\n{text}"
            try:
                bot.send_message(ticket.agent.telegram_id, sanitize_text(msg))
                customer_message.is_forwarded = True
                customer_message.save()
                logger.info(f"Forwarded message from customer {user_id} to agent {ticket.agent.telegram_id} (ticket {ticket.id})")
            except Exception as e:
                logger.error(f"Forward to agent failed (cust {user_id}): {e}")
                bot.reply_to(message, "⚠️ Failed to forward your message. Please try again.")
                customer_message.delete()
            return

        # -----------------------------------------
        # 5) Unclaimed flow (queue) — create a new ticket if none exists yet
        # -----------------------------------------
        if ticket is None:
            try:
                ticket = Ticket.objects.create(customer=customer)
                # attach this just-saved message to the new ticket
                CustomerMessage.objects.filter(id=customer_message.id).update(ticket=ticket)
                logger.info(f"Created new ticket {ticket.id} for customer {user_id}")
            except Exception as e:
                logger.error(f"Failed to create ticket for customer {user_id}: {e}")
                bot.reply_to(message, "⚠️ Failed to create a ticket. Please try again.")
                customer_message.delete()
                return

            # Count unforwarded for THIS ticket (should be 1 here)
            count = CustomerMessage.objects.filter(customer=customer, ticket=ticket, is_forwarded=False).count()

            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("🎫 Claim Ticket", callback_data=f"claim_{ticket.id}"),
                InlineKeyboardButton("👀 Preview Messages", callback_data=f"preview_{ticket.id}")
            )
            forwarded_text = f"📩 Customer ID:{customer.id:03d}\n\n{text}"
            try:
                bot.send_message(settings.SUPPORT_CHAT, sanitize_text(forwarded_text), reply_markup=markup)
                customer_message.is_forwarded = True
                customer_message.save()
                logger.info(f"Forwarded first message to group for ticket {ticket.id}")
            except Exception as e:
                logger.error(f"Forward to group failed (cust {user_id}, ticket {ticket.id}): {e}")
                bot.reply_to(message, "⚠️ Failed to forward your message. Please try again.")
                customer_message.delete()
                return

            bot.send_message(
                message.chat.id,
                "✅ Your message has been sent to our support team.\nYou may send up to two more messages if needed.",
                parse_mode="Markdown"
            )
            return

        # -----------------------------------------
        # 6) Ticket exists but unclaimed → per-ticket count & queue
        # -----------------------------------------
        count_unf = CustomerMessage.objects.filter(
            customer=customer,
            ticket=ticket,
            is_forwarded=False
        ).count()

        if count_unf <= 3:
            # Keep it queued. Don't send to support group again.
            bot.send_message(
                message.chat.id,
                f"💬 Got it! We’ve queued your message ({count_unf}/3)."
            )
        else:
            bot.send_message(
                message.chat.id,
                "⚠️ You’ve reached the message limit. An agent will get back to you soon."
            )
            logger.warning(f"Customer {user_id} reached per-ticket message limit (ticket {ticket.id})")

    
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
        # Get/Create customer
        customer, _ = Customer.objects.get_or_create(telegram_id=user_id)
        # Use the same active-ticket logic as text handler (claimed OR unclaimed but not approved/closed)
        ticket = get_active_ticket_for_customer(customer)

        # Store media info and create a preliminary message
        file_id = message.photo[-1].file_id if message.content_type == 'photo' else message.document.file_id

        # Save media message with a temporary caption
        try:
            customer_message = CustomerMessage.objects.create(
                    customer=customer,
                    ticket=ticket,  # attach if there’s already an active ticket
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
            'ticket': ticket,
            'customer_message': customer_message
        }
        bot.send_message(
            message.chat.id,
            "📷 Please provide a caption for your media file.",
            parse_mode="Markdown"
        )