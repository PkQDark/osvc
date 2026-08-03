"""Telegram-интерфейс: команды и обработка кнопки «Выполнено» (см. BOT_DESIGN.md §5)."""

from __future__ import annotations

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.storage import Payment, Storage

# Источник в payments.csv/recipients, чьё подтверждение делает пользователя
# владельцем (см. §2, §9) — единственное место, где это имя хардкодится.
OWNER_SOURCE = "Влад"
DEFAULT_LIST_DAYS = 30

HELP_TEXT = (
    "💸 Бот напоминает об оплатах из payments.csv.\n\n"
    "/start — регистрация и подтверждение роли\n"
    "/pending — список неподтверждённых платежей\n"
    "/list [дней] — ближайшие платежи (по умолчанию 30 дней)\n"
    "/help — эта справка"
)


def format_date(iso_date: str) -> str:
    return datetime.fromisoformat(iso_date).strftime("%d.%m.%Y")


def format_amount(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def format_payment_line(payment: Payment) -> str:
    mark = "✅" if payment.status == "done" else "•"
    return f"{mark} {format_date(payment.date)} — {format_amount(payment.amount)} ({payment.source}) [#{payment.id}]"


def _storage(context: ContextTypes.DEFAULT_TYPE) -> Storage:
    return context.bot_data["storage"]


# ---------- /start (§3.2, §5, §9.1) ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage = _storage(context)
    chat_id = update.effective_chat.id

    recipient = storage.get_recipient_by_chat_id(chat_id)
    if recipient is not None:
        role = "владелец" if recipient.is_owner else "пользователь"
        await update.message.reply_text(
            f"Привет! Ты уже зарегистрирован как {recipient.source} ({role})."
        )
        return

    taken_sources = {r.source for r in storage.list_recipients()}
    available = [s for s in storage.list_sources() if s not in taken_sources]

    if not available:
        await update.message.reply_text(
            "Все роли уже заняты. Если это ошибка — обратись к владельцу бота."
        )
        return

    buttons = [
        [
            InlineKeyboardButton(
                f"Я — {source}" + (" (владелец)" if source == OWNER_SOURCE else ""),
                callback_data=f"start:{source}",
            )
        ]
        for source in available
    ]
    await update.message.reply_text("Привет! Кто ты?", reply_markup=InlineKeyboardMarkup(buttons))


async def start_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage = _storage(context)
    query = update.callback_query
    chat_id = query.message.chat_id
    source = query.data.split(":", 1)[1]

    taken = storage.get_recipient(source)
    if taken is not None and taken.chat_id != chat_id:
        await query.answer("Эту роль уже кто-то занял, обнови /start.", show_alert=True)
        return

    is_owner = source == OWNER_SOURCE
    storage.upsert_recipient(source, chat_id, is_owner=is_owner)

    role = "владелец" if is_owner else "пользователь"
    await query.answer()
    await query.edit_message_text(f"Готово! Ты зарегистрирован как {source} ({role}).", reply_markup=None)


# ---------- /pending ----------

async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage = _storage(context)
    recipient = storage.get_recipient_by_chat_id(update.effective_chat.id)
    if recipient is None:
        await update.message.reply_text("Сначала зарегистрируйся: /start")
        return

    source = None if recipient.is_owner else recipient.source
    payments = storage.pending_payments(source=source)
    if not payments:
        await update.message.reply_text("Неподтверждённых платежей нет 🎉")
        return

    text = "Неподтверждённые платежи:\n" + "\n".join(format_payment_line(p) for p in payments)
    await update.message.reply_text(text)


# ---------- /list ----------

async def list_payments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage = _storage(context)
    recipient = storage.get_recipient_by_chat_id(update.effective_chat.id)
    if recipient is None:
        await update.message.reply_text("Сначала зарегистрируйся: /start")
        return

    days = DEFAULT_LIST_DAYS
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Использование: /list [дней]")
            return

    source = None if recipient.is_owner else recipient.source
    payments = storage.upcoming_payments(days=days, source=source)
    if not payments:
        await update.message.reply_text(f"Платежей за ближайшие {days} дн. нет.")
        return

    text = f"Платежи за ближайшие {days} дн.:\n" + "\n".join(format_payment_line(p) for p in payments)
    await update.message.reply_text(text)


# ---------- /help ----------

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


# ---------- done:<id> (§5 «Обработка нажатия кнопки») ----------

async def done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage = _storage(context)
    query = update.callback_query
    chat_id = query.message.chat_id
    payment_id = int(query.data.split(":", 1)[1])

    payment = storage.get_payment(payment_id)
    if payment is None:
        await query.answer("Платёж не найден.", show_alert=True)
        return
    if payment.status == "done":
        await query.answer("Уже подтверждено.")
        return

    recipient = storage.get_recipient_by_chat_id(chat_id)
    if recipient is None:
        await query.answer("Сначала зарегистрируйся: /start", show_alert=True)
        return
    if not recipient.is_owner and recipient.source != payment.source:
        await query.answer("Ты не можешь подтвердить чужой платёж.", show_alert=True)
        return

    now = datetime.now()
    storage.mark_done(payment_id, done_by=recipient.source, when=now)

    await query.answer()
    await query.edit_message_text(
        f"✅ Оплачено {now.strftime('%d.%m.%Y в %H:%M')} ({recipient.source})",
        reply_markup=None,
    )

    if not recipient.is_owner:
        owner = storage.get_owner()
        if owner is not None and owner.chat_id != chat_id:
            await context.bot.send_message(
                owner.chat_id,
                f"{recipient.source} подтвердил(а) оплату {format_amount(payment.amount)} "
                f"за {format_date(payment.date)}.",
            )


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("pending", pending))
    application.add_handler(CommandHandler("list", list_payments))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(start_confirm, pattern=r"^start:"))
    application.add_handler(CallbackQueryHandler(done_callback, pattern=r"^done:\d+$"))
