# Reminder Bot — шпаргалка по командам

Подробный дизайн и обоснования — в [BOT_DESIGN.md](BOT_DESIGN.md). Здесь —
только команды, чтобы не искать их по всему документу.

## Команды в Telegram

| Команда | Кто может | Что делает |
|---|---|---|
| `/start` | все | регистрирует chat_id, просит подтвердить роль (владелец / источник из CSV) |
| `/pending` | все | список неподтверждённых платежей — у владельца все, у остальных только свои |
| `/list [дней]` | все | ближайшие платежи на N дней вперёд (по умолчанию 30) — фильтр по роли как в `/pending` |
| `/help` | все | краткая справка по командам |
| кнопка **✅ Выполнено** | владелец, либо тот, чей это платёж | подтверждает оплату, убирает кнопку, шлёт уведомление владельцу (если подтвердил не он) |

## Локальный запуск (для теста)

```bash
.venv/bin/python -m bot.main
```

Останавливается `Ctrl+C` — планировщик и БД корректно закрываются.

## Обновление данных (новый платёж)

```bash
# локально: вписать строку в payments.csv (не трогать существующие id)
git add payments.csv
git commit -m "Add payment ..."
git push

# на сервере
ssh -i osvc.pem ubuntu@ec2-... "cd reminder_bot && git pull && sudo systemctl restart reminder-bot"
```

Бот сам подхватит новые строки при старте/на следующем тике — можно не
рестартовать сервис руками, если не спешишь.

## Обновление кода бота

```bash
# локально
git add . && git commit -m "..." && git push

# на сервере
ssh -i osvc.pem ubuntu@ec2-... "cd reminder_bot && git pull && sudo systemctl restart reminder-bot"
```

## Обслуживание на сервере

```bash
# подключиться
ssh -i osvc.pem ubuntu@ec2-...   # или просто содержимое ssh.command

# логи в реальном времени
sudo journalctl -u reminder-bot -f

# статус / рестарт / стоп
sudo systemctl status reminder-bot
sudo systemctl restart reminder-bot
sudo systemctl stop reminder-bot
```

## Секреты (никогда не в git)

- `telegram.key` — токен бота, на сервер копируется отдельно через `scp` (см. §7 в BOT_DESIGN.md).
- `osvc.pem` — SSH-ключ, нужен только локально, на сервер не копируется.
