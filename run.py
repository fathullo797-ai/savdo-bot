import asyncio
import os
from aiohttp import web

async def handle(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server started on port {port}")

async def main():
    # Web serverni fon rejimida ishga tushiramiz
    asyncio.create_task(start_web_server())
    
    # Bu yerda sizning asosiy botingiz ishlaydi (Long polling)
    # Masalan:
    print("Bot is starting polling...")
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
