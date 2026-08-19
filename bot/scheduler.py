"""APScheduler: периодический тик рассылки напоминаний (см. BOT_DESIGN.md §2, §4)."""

from __future__ import annotations

import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Application

from bot.handlers import format_amount, format_date
from bot.storage import Payment, Storage

logger = logging.getLogger(__name__)


def _overdue_note(payment: Payment) -> str:
    days_overdue = (date.today() - date.fromisoformat(payment.date)).days
    return f" (просрочено на {days_overdue} дн.)" if days_overdue > 0 else ""


def _reminder_text(payment: Payment, payment_account: str) -> str:
    return (
        "💸 Напоминание об оплате\n"
        f"Дата: {format_date(payment.date)}{_overdue_note(payment)}\n"
        f"Кто платит: {payment.source}\n"
        f"Сумма: {format_amount(payment.amount)}\n"
        f"Счёт: {payment_account}"
    )


def _recipients_for(storage: Storage, payment: Payment) -> list[int]:
    """§2: всегда владельцу; если платёж не его — ещё и получателю recipients[source]."""
    chat_ids: list[int] = []
    owner = storage.get_owner()
    if owner is not None:
        chat_ids.append(owner.chat_id)
    if owner is None or payment.source != owner.source:
        recipient = storage.get_recipient(payment.source)
        if recipient is not None and recipient.chat_id not in chat_ids:
            chat_ids.append(recipient.chat_id)
    return chat_ids


async def send_reminders(application: Application, storage: Storage, payment_account: str) -> None:
    """Один тик: sync CSV -> DB, затем рассылка всем due&pending платежам (§4).

    Используется и как периодический cron-job, и как разовый прогон при
    старте процесса — так первое напоминание уходит сразу, не дожидаясь
    ближайшего фиксированного часа (см. §4, §9.3).
    """
    storage.sync_csv()
    due = storage.due_payments()

    for payment in due:
        chat_ids = _recipients_for(storage, payment)
        if not chat_ids:
            logger.warning(
                "Платёж #%s (%s): нет получателей, никто не зарегистрирован через /start",
                payment.id, payment.source,
            )
            continue

        text = _reminder_text(payment, payment_account)
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Выполнено", callback_data=f"done:{payment.id}")]]
        )

        sent_to_anyone = False
        for chat_id in chat_ids:
            try:
                await application.bot.send_message(chat_id, text, reply_markup=markup)
                sent_to_anyone = True
            except TelegramError:
                logger.exception("Не удалось отправить напоминание #%s в чат %s", payment.id, chat_id)

        if sent_to_anyone:
            storage.mark_reminded(payment.id)


def setup_scheduler(
    application: Application,
    storage: Storage,
    timezone: str,
    reminder_hours: list[int],
    payment_account: str,
) -> AsyncIOScheduler:
    """Один периодический job на фиксированные часы (§4) — не job-на-платёж."""
    scheduler = AsyncIOScheduler(timezone=timezone)
    hours = ",".join(str(h) for h in reminder_hours)
    scheduler.add_job(
        send_reminders,
        CronTrigger(hour=hours, timezone=timezone),
        args=[application, storage, payment_account],
        id="send_reminders",
        replace_existing=True,
    )
    return scheduler
