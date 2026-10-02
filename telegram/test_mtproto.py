import asyncio
from telethon import TelegramClient

api_id = 12756254
api_hash = "c77f78c1ac09bb77b02c8b800321"
bot_token = "8901578611:AAFwH648xgPAfnw5Oh_ScBVuzVr94-JYkJI"

async def main():
    client = TelegramClient(
        "d:/PACS/telegram/session/bot_session",
        api_id,
        api_hash,
        device_model="Desktop",
        system_version="Windows 11",
        app_version="1.0"
    )
    await client.start(bot_token=bot_token)
    me = await client.get_me()
    print("Logged in successfully:", me.username)
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
