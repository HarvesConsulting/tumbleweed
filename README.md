# 🌾 TumbleWeed — Job Search Bot for Displaced People

Telegram-бот для пошуку роботи для переселенців у 4 країнах: 🇺🇦 Україна, 🇵🇱 Польща, 🇷🇴 Румунія, 🇵🇹 Португалія.

## 🚀 Що вміє

- **Агрегація вакансій** з OLX.ua, Work.ua, Robota.ua, Pidbir.ua, OLX.pl, OLX.ro, OLX.pt.
- **Розумний матчинг** — стемінг, межа слова, префікс-матч (знаходить «вчитель» → «вчителя»).
- **Тільки нові вакансії** — baseline (топ-10 з джерел) + тільки нові після цього.
- **Переклад** назв вакансій українською (PL/RO/PT → UA).
- **Багато підписок** на одного користувача (різні міста/професії).
- **Інтеграція з RentAlert** — кнопка «Житло тут».

## 📋 Архітектура

- **Парсери:** `src/tumbleweed/parsers/` (OLX, Work.ua, Robota.ua, Pidbir.ua)
- **Матчер:** `src/tumbleweed/services/matcher.py` (baseline/new)
- **БД:** Turso (SQLite)
- **Бот:** Flask + webhook на Render
- **Cron:** GitHub Actions + cron-job.org (кожні 30 хв)

## 🔧 Встановлення

```bash
git clone https://github.com/HarvesConsulting/tumbleweed.git
cd tumbleweed
pip install -e .
cp .env.example .env
# Заповніть .env (TUMBLEWEED_BOT_TOKEN, TURSO_*, ...)
python scripts/run_bot.py
