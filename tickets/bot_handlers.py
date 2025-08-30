from telebot.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from django.conf import settings
from agents.models import Agent, AgentMessage
from tickets.models import Ticket
from customers.models import CustomerMessage
from tickets.views import (
    claim_ticket,
    resolve_ticket,
    close_ticket,
    approve_ticket_resolution,
    approve_ticket_closure,
    decline_ticket_resolution,
    decline_ticket_closure,
    raise_ticket,
    handle_ticket,
    close_ticket_finally,
)
from django.utils import timezone
from utils import sanitize_text, get_agent_active_ticket
import logging
import datetime

logger = logging.getLogger(__name__)

def register_ticket_handlers(bot):
    @bot.message_handler(commands=['resolve_ticket'])
    def handle_resolve_ticket_cmd(message: Message):
        agent_tid = message.from_user.id
        if not Agent.objects.filter(telegram_id=agent_tid).exists():
            bot.reply_to(message, "🚫 This command is for registered agents only.")
            return
        ticket = get_agent_active_ticket(agent_tid)
        if not ticket:
            bot.reply_to(message, "⚠️ You have no active ticket to resolve.")
            return
        prompt = bot.send_message(message.chat.id, "📝 Please enter the resolution summary for this ticket:")
        bot.register_next_step_handler(prompt, _resolve_collect_summary, ticket_id=ticket.id, agent_tid=agent_tid)

    def _resolve_collect_summary(msg: Message, ticket_id: int, agent_tid: int):
        summary = (msg.text or "").strip()
        if not summary:
            bot.reply_to(msg, "⚠️ Summary cannot be empty. Try the command again: /resolve_ticket")
            return
        result = resolve_ticket(ticket_id, agent_tid, summary)
        if result["status"] != "success":
            bot.reply_to(msg, f"❌ {result['message']}")
            logger.error(f"Failed to resolve ticket {ticket_id}: {result['message']}")
            return
        ticket = Ticket.objects.get(id=ticket_id)
        bot.send_message(agent_tid, f"✅ Ticket #{ticket.id} marked as *resolved* (pending admin approval).", parse_mode="Markdown")
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_resolved_{ticket.id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"decline_resolved_{ticket.id}")
        )
        for admin_id in getattr(settings, "ADMIN_IDS", []):
            try:
                bot.send_message(
                    admin_id,
                    f"📩 Ticket #{ticket.id} resolved by Agent {ticket.agent.full_name or ticket.agent.telegram_id}.\n\n"
                    f"📝 Summary:\n{sanitize_text(ticket.resolution_summary or '')}\n\n"
                    "Approve or decline:",
                    reply_markup=markup
                )
                logger.info(f"Sent resolution approval request for ticket {ticket.id} to admin {admin_id}")
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id} for ticket {ticket.id}: {e}")

    @bot.message_handler(commands=['close_ticket'])
    def handle_close_ticket_cmd(message: Message):
        agent_tid = message.from_user.id
        if not Agent.objects.filter(telegram_id=agent_tid).exists():
            bot.reply_to(message, "🚫 This command is for registered agents only.")
            return
        ticket = get_agent_active_ticket(agent_tid)
        if not ticket:
            bot.reply_to(message, "⚠️ You have no active ticket to close.")
            return
        prompt = bot.send_message(message.chat.id, "📝 Please enter the closure summary for this ticket:")
        bot.register_next_step_handler(prompt, _close_collect_summary, ticket_id=ticket.id, agent_tid=agent_tid)

    def _close_collect_summary(msg: Message, ticket_id: int, agent_tid: int):
        summary = (msg.text or "").strip()
        if not summary:
            bot.reply_to(msg, "⚠️ Summary cannot be empty. Try the command again: /close_ticket")
            return
        result = close_ticket(ticket_id, agent_tid, summary)
        if result["status"] != "success":
            bot.reply_to(msg, f"❌ {result['message']}")
            logger.error(f"Failed to close ticket {ticket_id}: {result['message']}")
            return
        ticket = Ticket.objects.get(id=ticket_id)
        bot.send_message(agent_tid, f"✅ Ticket #{ticket.id} marked as *closed* (pending admin approval).", parse_mode="Markdown")
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_closed_{ticket.id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"decline_closed_{ticket.id}")
        )
        for admin_id in getattr(settings, "ADMIN_IDS", []):
            try:
                bot.send_message(
                    admin_id,
                    f"📩 Ticket #{ticket.id} closed by Agent {ticket.agent.full_name or ticket.agent.telegram_id}.\n\n"
                    f"📝 Summary:\n{sanitize_text(ticket.closure_summary or '')}\n\n"
                    "Approve or decline:",
                    reply_markup=markup
                )
                logger.info(f"Sent closure approval request for ticket {ticket.id} to admin {admin_id}")
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id} for ticket {ticket.id}: {e}")

    @bot.message_handler(func=lambda message: Agent.objects.filter(telegram_id=message.from_user.id).exists())
    def handle_agent_message(message: Message):
        """Handle messages sent by agents and save them to AgentMessage."""
        agent_tid = message.from_user.id
        ticket = get_agent_active_ticket(agent_tid)
        if not ticket:
            bot.reply_to(message, "⚠️ You have no active ticket to respond to.")
            return
        try:
            agent = Agent.objects.get(telegram_id=agent_tid)
            message_text = message.text or "[No text provided]"
            sent_at = datetime.datetime.fromtimestamp(message.date, tz=datetime.timezone.utc)
            AgentMessage.objects.create(
                ticket=ticket,
                agent=agent,
                customer=ticket.customer,
                message_text=message_text,
                message_type=message.content_type,
                telegram_message_id=message.message_id,
                sent_at=sent_at
            )
            logger.info(f"Agent message saved for ticket {ticket.id} from agent {agent_tid}: {message_text}")
            label = f"👨‍💼 Agent {agent.full_name or agent.id:03d}"
            if message.content_type == 'text':
                bot.send_message(
                    ticket.customer.telegram_id,
                    f"{label}:\n\n{sanitize_text(message_text)}"
                )
            elif message.content_type == 'photo':
                bot.send_photo(
                    ticket.customer.telegram_id,
                    message.photo[-1].file_id,
                    caption=f"{label}:\n\n{sanitize_text(message.caption or '')}"
                )
            elif message.content_type == 'document':
                bot.send_document(
                    ticket.customer.telegram_id,
                    message.document.file_id,
                    caption=f"{label}:\n\n{sanitize_text(message.caption or '')}"
                )
            elif message.content_type == 'video':
                bot.send_video(
                    ticket.customer.telegram_id,
                    message.video.file_id,
                    caption=f"{label}:\n\n{sanitize_text(message.caption or '')}"
                )
            bot.reply_to(message, "✅ Message sent to customer.")
        except Exception as e:
            logger.error(f"Failed to save or forward agent message for ticket {ticket.id}: {e}")
            bot.reply_to(message, f"❌ Failed to send message: {str(e)}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("claim_"))
    def handle_claim_ticket(call: CallbackQuery):
        ticket_id = int(call.data.split("_")[1])
        user_id = call.from_user.id

        result = claim_ticket(ticket_id, user_id)
        if result["status"] != "success":
            bot.answer_callback_query(call.id, f"❌ {result['message']}", show_alert=True)
            logger.error(f"Failed to claim ticket {ticket_id}: {result['message']}")
            return

        ticket = result["ticket"]
        agent = result["agent"]

        # 1) Remove inline buttons first (works for both text and media)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            logger.warning(f"Failed to remove reply markup for ticket {ticket_id}")

        # 2) Edit banner depending on message type (caption vs text)
        try:
            claimed_line = f"📩 Ticket #{ticket.id} claimed by Agent {agent.id:03d}"
            content_type = getattr(call.message, "content_type", "")

            if content_type in ("photo", "document", "video", "animation", "audio", "voice"):
                # Media messages must use caption editing
                original_caption = getattr(call.message, "caption", "") or ""
                new_caption = sanitize_text(f"{claimed_line}\n\n{original_caption}".strip())
                bot.edit_message_caption(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    caption=new_caption
                )
            else:
                # Plain text message
                original_text = call.message.text or ""
                new_text = sanitize_text(f"{claimed_line}\n\n{original_text}".strip())
                bot.edit_message_text(
                    new_text,
                    call.message.chat.id,
                    call.message.message_id
                )
        except Exception as e:
            logger.warning(f"Failed to edit message/caption for ticket {ticket_id}: {e}")

        # 3) Notify agent that they claimed the ticket
        bot.send_message(
            agent.telegram_id,
            f"✅ You’ve claimed Ticket #{ticket.id}.\n\nForwarding conversation history now..."
        )

        # 4) Send conversation history to the claiming agent
        customer_messages = CustomerMessage.objects.filter(
            customer=ticket.customer
        ).order_by("sent_at")

        agent_messages = AgentMessage.objects.filter(
            ticket__customer=ticket.customer
        ).order_by("sent_at")

        # Combine and sort by timestamp
        all_messages = [
            (msg.sent_at, f"Customer {ticket.customer.full_name or ticket.customer.telegram_id}", msg.message_text)
            for msg in customer_messages
        ] + [
            (msg.sent_at, f"Agent {msg.agent.full_name or msg.agent.telegram_id} (Ticket #{msg.ticket_id})", msg.message_text)
            for msg in agent_messages
        ]
        all_messages.sort(key=lambda x: x[0])

        if all_messages:
            bot.send_message(agent.telegram_id, f"📜 Conversation history for Ticket #{ticket.id}:")
            for sent_at, sender, content in all_messages:
                label = f"📨 {sender}:"
                content = sanitize_text(content or "[Media Message]")
                bot.send_message(agent.telegram_id, f"{label}\n{content}\n\nSent at: {sent_at}")
            logger.info(f"Forwarded {len(all_messages)} messages for ticket {ticket_id} to agent {agent.telegram_id}")

            # Mark customer messages as forwarded now that the agent has the history
            customer_messages.update(is_forwarded=True)
        else:
            bot.send_message(agent.telegram_id, "ℹ️ No previous messages were found.")
            logger.info(f"No previous messages found for ticket {ticket_id} for agent {agent.telegram_id}")


    @bot.callback_query_handler(func=lambda call: call.data.startswith("preview_"))
    def handle_preview_messages(call: CallbackQuery):
        ticket_id = int(call.data.split("_")[1])
        user_id = call.from_user.id
        try:
            ticket = Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            bot.answer_callback_query(call.id, "❌ Ticket not found.", show_alert=True)
            logger.error(f"Ticket {ticket_id} not found for preview by user {user_id}")
            return
        if not Agent.objects.filter(telegram_id=user_id).exists():
            bot.answer_callback_query(call.id, "🚫 This action is for registered agents only.", show_alert=True)
            logger.warning(f"Non-agent {user_id} attempted to preview ticket {ticket_id}")
            return
        queued_messages = CustomerMessage.objects.filter(
            customer=ticket.customer,
            ticket=ticket,              # ✅ scope to this ticket only
            is_forwarded=False
        ).order_by("sent_at")

        if not queued_messages.exists():
            bot.send_message(user_id, f"ℹ️ No queued messages for Ticket #{ticket.id}.")
            logger.info(f"No queued messages found for ticket {ticket_id} preview by agent {user_id}")
            return
        preview_text = f"📬 Queued Messages for Ticket #{ticket.id}:\n\n"
        for i, msg in enumerate(queued_messages, 1):
            label = f"📨 Message {i} from {ticket.customer.full_name or ticket.customer.telegram_id}:"
            content = sanitize_text(msg.message_text or "[Media Message]")
            preview_text += f"{label}\n{content}\n\n"
        try:
            bot.send_message(user_id, preview_text, parse_mode="Markdown")
            logger.info(f"Sent preview of {queued_messages.count()} messages for ticket {ticket_id} to agent {user_id}")
            bot.answer_callback_query(call.id, "✅ Messages previewed. Check your private chat.")
        except Exception as e:
            logger.error(f"Failed to send preview for ticket {ticket_id} to agent {user_id}: {e}")
            bot.answer_callback_query(call.id, f"❌ Failed to preview messages: {str(e)}", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("approve_resolved_"))
    def cb_approve_resolved(call: CallbackQuery):
        ticket_id = int(call.data.split("_")[2])
        result = approve_ticket_resolution(ticket_id, call.from_user.id)
        if result["status"] != "success":
            bot.answer_callback_query(call.id, f"❌ {result['message']}", show_alert=True)
            logger.error(f"Failed to approve resolution for ticket {ticket_id}: {result['message']}")
            return
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            agent_telegram_id = result.get("agent_telegram_id")
            # Notify customer
            bot.send_message(
                ticket.customer.telegram_id,
                f"🎉 Your Ticket #{ticket.id} has been resolved.\nSummary: {sanitize_text(ticket.resolution_summary or 'No summary provided')}\n\n"
                f"This ticket is now closed, but can be reopened if you send further messages.",
                parse_mode="Markdown"
            )
            logger.info(f"Notified customer {ticket.customer.telegram_id} of resolution approval for ticket {ticket_id}")
            # Notify agent if available
            if agent_telegram_id:
                bot.send_message(
                    agent_telegram_id,
                    f"✅ Your resolution for Ticket #{ticket.id} has been approved by an admin.\nSummary: {sanitize_text(ticket.resolution_summary or 'No summary provided')}\n\n"
                    f"You are no longer assigned to this ticket.",
                    parse_mode="Markdown"
                )
                logger.info(f"Notified agent {agent_telegram_id} of resolution approval and unlinking for ticket {ticket_id}")
            else:
                logger.warning(f"No agent Telegram ID available for resolution approval notification of ticket {ticket_id}")
            # Update admin message with action buttons
            # new_markup = InlineKeyboardMarkup()
            # new_markup.add(
            #     InlineKeyboardButton("📬 Raise Ticket", callback_data=f"raise_ticket_{ticket.id}"),
            #     InlineKeyboardButton("🤝 Handle Ticket", callback_data=f"handle_ticket_{ticket.id}"),
            #     InlineKeyboardButton("🔒 Close Ticket Finally", callback_data=f"close_finally_{ticket.id}")
            # )
            # bot.edit_message_text(
            #     f"✅ Ticket #{ticket.id} resolution approved by admin. Agent unlinked.\n\nChoose next action:",
            #     call.message.chat.id,
            #     call.message.message_id,
            #     reply_markup=new_markup
            # )
            # bot.answer_callback_query(call.id, "✅ Resolution approved. Choose next action.")
            # Update admin message — only offer Final Close (no Raise / Handle after resolution)
            new_markup = InlineKeyboardMarkup()
            new_markup.add(
                InlineKeyboardButton("🔒 Close Ticket Finally", callback_data=f"close_finally_{ticket.id}")
            )
            bot.edit_message_text(
                f"✅ Ticket #{ticket.id} resolution approved by admin. Agent unlinked.\n\n"
                f"You can permanently close this ticket if desired:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=new_markup
            )
            bot.answer_callback_query(call.id, "✅ Resolution approved.")
        except Exception as e:
            logger.error(f"Failed to notify or update for resolution approval of ticket {ticket_id}: {e}")
            bot.answer_callback_query(call.id, f"✅ Resolution approved, but notification failed: {str(e)}", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("decline_resolved_"))
    def cb_decline_resolved(call: CallbackQuery):
        ticket_id = int(call.data.split("_")[2])
        result = decline_ticket_resolution(ticket_id, call.from_user.id)
        if result["status"] != "success":
            bot.answer_callback_query(call.id, f"❌ {result['message']}", show_alert=True)
            logger.error(f"Failed to decline resolution for ticket {ticket_id}: {result['message']}")
            return
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            agent_telegram_id = result.get("agent_telegram_id")
            # Notify customer
            bot.send_message(
                ticket.customer.telegram_id,
                f"📩 Your Ticket #{ticket.id} resolution was declined by an admin. The assigned agent will continue assisting you.",
                parse_mode="Markdown"
            )
            logger.info(f"Notified customer {ticket.customer.telegram_id} of resolution decline for ticket {ticket_id}")
            # Notify agent if available
            if agent_telegram_id:
                bot.send_message(
                    agent_telegram_id,
                    f"❌ Your resolution for Ticket #{ticket.id} was declined by an admin. Please review and resubmit or continue assisting.",
                    parse_mode="Markdown"
                )
                logger.info(f"Notified agent {agent_telegram_id} of resolution decline for ticket {ticket_id}")
            # Update admin message
            bot.edit_message_text(
                f"❌ Ticket #{ticket.id} resolution declined by admin.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None
            )
            bot.answer_callback_query(call.id, "✅ Resolution declined.")
        except Exception as e:
            logger.error(f"Failed to notify for resolution decline of ticket {ticket_id}: {e}")
            bot.answer_callback_query(call.id, f"✅ Resolution declined, but notification failed: {str(e)}", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("approve_closed_"))
    def cb_approve_closed(call: CallbackQuery):
        ticket_id = int(call.data.split("_")[2])
        result = approve_ticket_closure(ticket_id, call.from_user.id)
        if result["status"] != "success":
            bot.answer_callback_query(call.id, f"❌ {result['message']}", show_alert=True)
            logger.error(f"Failed to approve closure for ticket {ticket_id}: {result['message']}")
            return
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            agent_telegram_id = result.get("agent_telegram_id")
            # Notify customer
            bot.send_message(
                ticket.customer.telegram_id,
                f"✅ Your Ticket #{ticket.id} has been closed.\nSummary: {sanitize_text(ticket.closure_summary or 'No summary provided')}\n\n"
                f"This ticket is now closed, but can be reopened if you send further messages.",
                parse_mode="Markdown"
            )
            logger.info(f"Notified customer {ticket.customer.telegram_id} of closure approval for ticket {ticket_id}")
            # Notify agent if available
            if agent_telegram_id:
                bot.send_message(
                    agent_telegram_id,
                    f"✅ Your closure for Ticket #{ticket.id} has been approved by an admin.\nSummary: {sanitize_text(ticket.closure_summary or 'No summary provided')}\n\n"
                    f"You are no longer assigned to this ticket.",
                    parse_mode="Markdown"
                )
                logger.info(f"Notified agent {agent_telegram_id} of closure approval and unlinking for ticket {ticket_id}")
            else:
                logger.warning(f"No agent Telegram ID available for closure approval notification of ticket {ticket_id}")
            # Update admin message with new options
            new_markup = InlineKeyboardMarkup()
            new_markup.add(
                InlineKeyboardButton("📬 Raise Ticket", callback_data=f"raise_ticket_{ticket.id}"),
                InlineKeyboardButton("🤝 Handle Ticket", callback_data=f"handle_ticket_{ticket.id}"),
                InlineKeyboardButton("🔒 Close Ticket Finally", callback_data=f"close_finally_{ticket.id}")
            )
            bot.edit_message_text(
                f"✅ Ticket #{ticket.id} closure approved by admin. Agent unlinked.\n\nChoose next action:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=new_markup
            )
            bot.answer_callback_query(call.id, "✅ Closure approved. Choose next action.")
        except Exception as e:
            logger.error(f"Failed to notify or update for closure approval of ticket {ticket_id}: {e}")
            bot.answer_callback_query(call.id, f"✅ Closure approved, but notification failed: {str(e)}", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("decline_closed_"))
    def cb_decline_closed(call: CallbackQuery):
        ticket_id = int(call.data.split("_")[2])
        result = decline_ticket_closure(ticket_id, call.from_user.id)
        if result["status"] != "success":
            bot.answer_callback_query(call.id, f"❌ {result['message']}", show_alert=True)
            logger.error(f"Failed to decline closure for ticket {ticket_id}: {result['message']}")
            return
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            agent_telegram_id = result.get("agent_telegram_id")
            # Notify customer
            bot.send_message(
                ticket.customer.telegram_id,
                f"📩 Your Ticket #{ticket.id} closure was declined by an admin. The assigned agent will continue assisting you.",
                parse_mode="Markdown"
            )
            logger.info(f"Notified customer {ticket.customer.telegram_id} of closure decline for ticket {ticket_id}")
            # Notify agent if available
            if agent_telegram_id:
                bot.send_message(
                    agent_telegram_id,
                    f"❌ Your closure for Ticket #{ticket.id} was declined by an admin. Please review and resubmit or continue assisting.",
                    parse_mode="Markdown"
                )
                logger.info(f"Notified agent {agent_telegram_id} of closure decline for ticket {ticket_id}")
            # Update admin message
            bot.edit_message_text(
                f"❌ Ticket #{ticket.id} closure declined by admin.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None
            )
            bot.answer_callback_query(call.id, "✅ Closure declined.")
        except Exception as e:
            logger.error(f"Failed to notify for closure decline of ticket {ticket_id}: {e}")
            bot.answer_callback_query(call.id, f"✅ Closure declined, but notification failed: {str(e)}", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("raise_ticket_"))
    def cb_raise_ticket(call: CallbackQuery):
        ticket_id = int(call.data.split("_")[2])
        result = raise_ticket(ticket_id)
        if result["status"] != "success":
            bot.answer_callback_query(call.id, f"❌ {result['message']}", show_alert=True)
            logger.error(f"Failed to raise ticket {ticket_id}: {result['message']}")
            return
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            # Notify customer
            bot.send_message(
                ticket.customer.telegram_id,
                f"📩 Your Ticket #{ticket.id} has been reopened and will be reassigned to a new agent.",
                parse_mode="Markdown"
            )
            logger.info(f"Notified customer {ticket.customer.telegram_id} of ticket raise for {ticket_id}")
            # Post to support group
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("🎫 Claim Ticket", callback_data=f"claim_{ticket.id}"),
                InlineKeyboardButton("👀 Preview Messages", callback_data=f"preview_{ticket.id}")
            )
            bot.send_message(
                settings.SUPPORT_CHAT,
                f"📩 Ticket #{ticket.id} reopened for re-claim.\n\nSummary: {sanitize_text(ticket.resolution_summary or ticket.closure_summary or 'No summary provided')}",
                reply_markup=markup
            )
            logger.info(f"Posted reopened ticket {ticket_id} to support group {settings.SUPPORT_CHAT}")
            # Update admin message
            bot.edit_message_text(
                f"✅ Ticket #{ticket.id} raised back to support group.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None
            )
            bot.answer_callback_query(call.id, "✅ Ticket raised.")
        except Exception as e:
            logger.error(f"Failed to notify or post for raise of ticket {ticket_id}: {e}")
            bot.answer_callback_query(call.id, f"✅ Ticket raised, but notification failed: {str(e)}", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("handle_ticket_"))
    def cb_handle_ticket(call: CallbackQuery):
        ticket_id = int(call.data.split("_")[2])
        admin_id = call.from_user.id
        result = handle_ticket(ticket_id, admin_id)
        if result["status"] != "success":
            bot.answer_callback_query(call.id, f"❌ {result['message']}", show_alert=True)
            logger.error(f"Failed to handle ticket {ticket_id}: {result['message']}")
            return
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            # Notify customer
            bot.send_message(
                ticket.customer.telegram_id,
                f"📩 An admin is now handling your Ticket #{ticket.id}.",
                parse_mode="Markdown"
            )
            logger.info(f"Notified customer {ticket.customer.telegram_id} of admin handling for ticket {ticket_id}")
            # Notify admin
            bot.send_message(
                admin_id,
                f"✅ You are now assigned to Ticket #{ticket.id}.\n\nForwarding conversation history now..."
            )
            logger.info(f"Notified admin {admin_id} of assignment for ticket {ticket_id}")
            # Fetch and combine CustomerMessage and AgentMessage for the ticket's customer
            customer_messages = CustomerMessage.objects.filter(
                customer=ticket.customer
            ).order_by("sent_at")
            agent_messages = AgentMessage.objects.filter(
                ticket__customer=ticket.customer
            ).order_by("sent_at")
            # Combine messages and sort by sent_at
            all_messages = [
                (msg.sent_at, f"Customer {ticket.customer.full_name or ticket.customer.telegram_id}", msg.message_text)
                for msg in customer_messages
            ] + [
                (msg.sent_at, f"Agent {msg.agent.full_name or msg.agent.telegram_id} (Ticket #{msg.ticket_id})", msg.message_text)
                for msg in agent_messages
            ]
            all_messages.sort(key=lambda x: x[0]) # Sort by sent_at
            if all_messages:
                bot.send_message(admin_id, f"📜 Conversation history for Ticket #{ticket.id}:")
                for sent_at, sender, content in all_messages:
                    label = f"📨 {sender}:"
                    content = sanitize_text(content or "[Media Message]")
                    bot.send_message(admin_id, f"{label}\n{content}\n\nSent at: {sent_at}")
                logger.info(f"Forwarded {len(all_messages)} messages for ticket {ticket_id} to admin {admin_id}")
                # Mark customer messages as forwarded
                customer_messages.update(is_forwarded=True)
            else:
                bot.send_message(admin_id, "ℹ️ No previous messages were found.")
                logger.info(f"No previous messages found for ticket {ticket_id} for admin {admin_id}")
            # Update admin message
            bot.edit_message_text(
                f"✅ Ticket #{ticket.id} assigned to you for handling.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None
            )
            bot.answer_callback_query(call.id, "✅ Ticket handled by you.")
        except Exception as e:
            logger.error(f"Failed to notify or forward history for handle of ticket {ticket_id}: {e}")
            bot.answer_callback_query(call.id, f"✅ Ticket handled, but notification or history forwarding failed: {str(e)}", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("close_finally_"))
    def cb_close_ticket_finally(call: CallbackQuery):
        ticket_id = int(call.data.split("_")[2])
        admin_id = call.from_user.id
        result = close_ticket_finally(ticket_id, admin_id)
        if result["status"] != "success":
            bot.answer_callback_query(call.id, f"❌ {result['message']}", show_alert=True)
            logger.error(f"Failed to permanently close ticket {ticket_id}: {result['message']}")
            return
        try:
            ticket = Ticket.objects.get(id=ticket_id)
            agent_telegram_id = result.get("agent_telegram_id")
            # Notify customer
            bot.send_message(
                ticket.customer.telegram_id,
                f"🔒 Your Ticket #{ticket.id} has been permanently closed by an admin.\nSummary: {sanitize_text(ticket.resolution_summary or ticket.closure_summary or 'No summary provided')}",
                parse_mode="Markdown"
            )
            logger.info(f"Notified customer {ticket.customer.telegram_id} of final closure for ticket {ticket_id}")
            # Notify original agent if available
            if agent_telegram_id:
                bot.send_message(
                    agent_telegram_id,
                    f"🔒 Ticket #{ticket.id} has been permanently closed by an admin.\nSummary: {sanitize_text(ticket.resolution_summary or ticket.closure_summary or 'No summary provided')}",
                    parse_mode="Markdown"
                )
                logger.info(f"Notified agent {agent_telegram_id} of final closure for ticket {ticket_id}")
            # Update admin message
            bot.edit_message_text(
                f"🔒 Ticket #{ticket.id} permanently closed by admin.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None
            )
            bot.answer_callback_query(call.id, "✅ Ticket permanently closed.")
        except Exception as e:
            logger.error(f"Failed to notify for final closure of ticket {ticket_id}: {e}")
            bot.answer_callback_query(call.id, f"✅ Ticket closed, but notification failed: {str(e)}", show_alert=True)