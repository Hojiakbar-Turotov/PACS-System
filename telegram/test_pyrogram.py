import asyncio
from pyrogram import Client

api_id = 12756254
api_hash = "c77f78c1ac09bb77b02c8b800321"
bot_token = "8901578611:AAFwH648xgPAfnw5Oh_ScBVuzVr94-JYkJI"

async def main():
    app = Client(
        "d:/PACS/telegram/session/pyrogram_bot",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token
    )
    async with app:
        me = await app.get_me()
        print("Pyrogram logged in as:", me.username)

if __name__ == "__main__":
    asyncio.run(main())
