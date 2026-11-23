import asyncio
import os
import sqlite3
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "10000"))

SECTIONS = {
    "sec_adabiyot": "📚 Badiiy adabiyot",
    "sec_tarix": "🏛 Tarix va tafakkur",
    "sec_maqola": "✍️ Maqola va qaydlar",
    "sec_fayl": "📂 Maxsus fayllar",
}

conn = sqlite3.connect("library.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    full_name TEXT,
    username TEXT,
    status TEXT DEFAULT 'pending'
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section_key TEXT,
    title TEXT,
    file_id TEXT,
    file_type TEXT
)
""")
conn.commit()


def get_user_status(user_id: int) -> str | None:
    if user_id == ADMIN_ID:
        return "approved"
    cur.execute("SELECT status FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else None


def upsert_user(user_id: int, full_name: str, username: str | None, status: str):
    cur.execute("""
    INSERT INTO users (user_id, full_name, username, status)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
        full_name = excluded.full_name,
        username = excluded.username,
        status = excluded.status
    """, (user_id, full_name, username or "", status))
    conn.commit()


def request_access_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 Ruxsat so‘rash", callback_data="req_access")]
    ])


def admin_decision_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ruxsat berish", callback_data=f"allow:{user_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"deny:{user_id}"),
        ]
    ])


def sections_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=title, callback_data=f"open_sec:{key}")]
        for key, title in SECTIONS.items()
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="➕ Material qo‘shish", callback_data="admin_add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def add_section_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=title, callback_data=f"pick_add_sec:{key}")]
        for key, title in SECTIONS.items()
    ])


pending_admin_upload: dict[int, str] = {}

dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    status = get_user_status(user_id)

    if status == "approved":
        await message.answer(
            "🏛 <b>Shaxsiy kutubxonaga xush kelibsiz!</b>\nKerakli bo‘limni tanlang:",
            reply_markup=sections_kb(is_admin=(user_id == ADMIN_ID)),
            parse_mode="HTML",
            protect_content=True,
        )
        return

    if status == "pending":
        await message.answer(
            "⏳ Ruxsat so‘rovingiz yuborilgan. Admin tasdiqlashini kuting.",
            protect_content=True,
        )
        return

    if status == "denied":
        await message.answer(
            "🚫 Ushbu kutubxonaga kirish ruxsati berilmagan.",
            protect_content=True,
        )
        return

    await message.answer(
        "🔒 Bu yopiq kutubxona. Kirish uchun admin ruxsati kerak.",
        reply_markup=request_access_kb(),
        protect_content=True,
    )


@dp.callback_query(F.data == "req_access")
async def on_request_access(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    current = get_user_status(user.id)
    if current == "approved":
        await callback.message.edit_text(
            "🏛 Kutubxona bo‘limlari:",
            reply_markup=sections_kb(is_admin=(user.id == ADMIN_ID)),
        )
        return

    upsert_user(user.id, user.full_name, user.username, "pending")
    await callback.message.edit_text(
        "✅ So‘rovingiz adminga yuborildi. Tasdiqni kuting."
    )

    uname = f"@{user.username}" if user.username else "yo‘q"
    text = (
        "📩 <b>Yangi kirish so‘rovi</b>\n"
        f"👤 Ism: {user.full_name}\n"
        f"🔗 Username: {uname}\n"
        f"🆔 ID: <code>{user.id}</code>"
    )
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=text,
        reply_markup=admin_decision_kb(user.id),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("allow:"))
async def on_allow(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Faqat admin uchun!", show_alert=True)
        return

    target_id = int(callback.data.split(":")[1])
    cur.execute("SELECT full_name, username FROM users WHERE user_id = ?", (target_id,))
    row = cur.fetchone()
    full_name = row[0] if row else str(target_id)
    username = row[1] if row else ""
    upsert_user(target_id, full_name, username, "approved")

    await callback.message.edit_text(
        f"{callback.message.html_text}\n\n✅ <b>Ruxsat berildi</b>",
        parse_mode="HTML",
    )
    try:
        await bot.send_message(
            chat_id=target_id,
            text="🎉 Tabriklaymiz! Kutubxonaga kirishga ruxsat berildi. /start bosing.",
            protect_content=True,
        )
    except Exception:
        pass
    await callback.answer("Tasdiqlandi")


@dp.callback_query(F.data.startswith("deny:"))
async def on_deny(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Faqat admin uchun!", show_alert=True)
        return

    target_id = int(callback.data.split(":")[1])
    cur.execute("SELECT full_name, username FROM users WHERE user_id = ?", (target_id,))
    row = cur.fetchone()
    full_name = row[0] if row else str(target_id)
    username = row[1] if row else ""
    upsert_user(target_id, full_name, username, "denied")

    await callback.message.edit_text(
        f"{callback.message.html_text}\n\n❌ <b>Rad etildi</b>",
        parse_mode="HTML",
    )
    try:
        await bot.send_message(
            chat_id=target_id,
            text="❌ Kirish so‘rovingiz rad etildi.",
            protect_content=True,
        )
    except Exception:
        pass
    await callback.answer("Rad etildi")


@dp.callback_query(F.data.startswith("open_sec:"))
async def on_open_section(callback: CallbackQuery):
    user_id = callback.from_user.id
    if get_user_status(user_id) != "approved":
        await callback.answer("Ruxsat yo‘q!", show_alert=True)
        return

    sec_key = callback.data.split(":", 1)[1]
    sec_title = SECTIONS.get(sec_key, "Bo‘lim")

    cur.execute(
        "SELECT title, file_id, file_type FROM items WHERE section_key = ? ORDER BY id DESC",
        (sec_key,),
    )
    items = cur.fetchall()

    await callback.message.answer(
        f"<b>{sec_title}</b>",
        parse_mode="HTML",
        protect_content=True,
    )

    if not items:
        await callback.message.answer(
            "Bu bo‘limda hozircha fayllar yo‘q.",
            protect_content=True,
        )
    else:
        for title, file_id, file_type in items:
            if file_type == "document":
                await callback.message.answer_document(
                    document=file_id,
                    caption=title,
                    protect_content=True,
                )
            elif file_type == "photo":
                await callback.message.answer_photo(
                    photo=file_id,
                    caption=title,
                    protect_content=True,
                )

    await callback.message.answer(
        "Boshqa bo‘limni tanlang:",
        reply_markup=sections_kb(is_admin=(user_id == ADMIN_ID)),
        protect_content=True,
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_add")
async def on_admin_add(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Faqat admin uchun!", show_alert=True)
        return
    await callback.message.answer(
        "Qaysi bo‘limga material qo‘shmoqchisiz?",
        reply_markup=add_section_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("pick_add_sec:"))
async def on_pick_add_sec(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Faqat admin uchun!", show_alert=True)
        return
    sec_key = callback.data.split(":", 1)[1]
    pending_admin_upload[ADMIN_ID] = sec_key
    await callback.message.answer(
        f"<b>{SECTIONS[sec_key]}</b> bo‘limiga yuboriladigan fayl yoki rasmni jo‘nating.\n"
        "Xohlasangiz, izoh (caption) qismiga kitob/material nomini yozing.",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(F.from_user.id == ADMIN_ID, F.document | F.photo)
async def on_admin_file(message: Message):
    sec_key = pending_admin_upload.get(ADMIN_ID)
    if not sec_key:
        return

    if message.document:
        file_id = message.document.file_id
        file_type = "document"
        title = message.caption or message.document.file_name or "Material"
    else:
        file_id = message.photo[-1].file_id
        file_type = "photo"
        title = message.caption or "Rasm / Qayd"

    cur.execute(
        "INSERT INTO items (section_key, title, file_id, file_type) VALUES (?, ?, ?, ?)",
        (sec_key, title, file_id, file_type),
    )
    conn.commit()
    del pending_admin_upload[ADMIN_ID]

    await message.answer(
        f"✅ <b>{title}</b> — <b>{SECTIONS[sec_key]}</b> bo‘limiga saqlandi!",
        parse_mode="HTML",
        reply_markup=sections_kb(is_admin=True),
    )


async def health_handler(request: web.Request):
    return web.Response(text="OK")


async def main():
    if not BOT_TOKEN or not ADMIN_ID:
        raise RuntimeError("BOT_TOKEN va ADMIN_ID Environment Variables da ko‘rsatilishi shart!")

    bot = Bot(token=BOT_TOKEN)

    app = web.Application()
    app.router.add_get("/", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
