from django.conf import settings
from telebot.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, InputMediaDocument, InputMediaVideo
)
from customers.models import Customer, CustomerMessage
import re
import telebot

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

    # Handle text messages
    @bot.message_handler(content_types=['text'])
    def handle_text(message: Message):
        user_id = message.from_user.id
        text = message.text

        if settings.BAD_WORDS_TOGGLE:
            if re.match(settings.REGEX_FILTER['bad_words'], text or "", re.IGNORECASE):
                bot.reply_to(message, "⚠️ Please mind your language.")
                return

        customer, _ = Customer.objects.get_or_create(telegram_id=user_id)
        CustomerMessage.objects.create(customer=customer, message_text=text)

        forwarded_text = f"📩 ID:customer {customer.id:03d}\n\n{text}"
        bot.send_message(settings.SUPPORT_CHAT, forwarded_text)

        confirmation = (
            "✅ Your message has been successfully sent to our support team.\n\n"
            "An agent will get back to you shortly.\n"
            "You may send *up to two more messages* with additional details if needed."
        )
        bot.send_message(message.chat.id, confirmation, parse_mode="Markdown")

    # Handle images, documents, and videos
    @bot.message_handler(content_types=['photo', 'document', 'video'])
    def handle_media(message: Message):
        user_id = message.from_user.id
        customer, _ = Customer.objects.get_or_create(telegram_id=user_id)

        caption = message.caption or ""
        label = f"📩 ID:customer {customer.id:03d}"

        # Save text + media info to DB
        CustomerMessage.objects.create(
            customer=customer,
            message_text=caption or "[Media Message]"
        )

        # Forward media to support group
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id  # Highest resolution
            bot.send_photo(settings.SUPPORT_CHAT, file_id, caption=f"{label}\n\n{caption}")
        elif message.content_type == 'document':
            bot.send_document(settings.SUPPORT_CHAT, message.document.file_id, caption=f"{label}\n\n{caption}")
        elif message.content_type == 'video':
            bot.send_video(settings.SUPPORT_CHAT, message.video.file_id, caption=f"{label}\n\n{caption}")

        # Optional feedback for media messages
        bot.send_message(
            message.chat.id,
            "✅ Your file has been received by our support team. Feel free to add any extra info.",
            parse_mode="Markdown"
        )
