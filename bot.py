import os
import random
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Cấu hình thông tin bot và admin
BOT_TOKEN = "9294891883:AAHsv-TTxyop9p_nCtqPEoPuaP3NXoo0bAk"
ADMIN_ID = 7884394252
GROUP_USERNAME_OR_ID = "@tungxxtest9" 

forced_next_result = None

# Tạo web server giả lập để Render Web Service nhận diện cổng HTTP
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Bot Tai Xiu is running smoothly!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

async def execute_roll(context: ContextTypes.DEFAULT_TYPE, dice_results=None):
    global forced_next_result
    
    try:
        await context.bot.send_message(
            chat_id=GROUP_USERNAME_OR_ID,
            text="🎲 **Bắt đầu tung xúc xắc phiên mới!**",
            parse_mode="Markdown"
        )
        
        if dice_results:
            actual_results = dice_results
        elif forced_next_result:
            actual_results = forced_next_result
            forced_next_result = None
        else:
            actual_results = [random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)]

        for _ in range(3):
            await context.bot.send_dice(chat_id=GROUP_USERNAME_OR_ID, emoji='🎲')
            await asyncio.sleep(0.5)

        total_score = sum(actual_results)
        taixiu = "TÀI" if total_score >= 11 else "XỈU"
        chanle = "CHẴN" if total_score % 2 == 0 else "LẺ"
        icon_taixiu = "🔴" if total_score >= 11 else "🔵"

        summary_text = (
            "───────────────\n"
            f"📊 **Kết quả Tổng kết Phiên chơi**\n"
            f"🎲 Mặt xúc xắc: `{actual_results[0]}`  `{actual_results[1]}`  `{actual_results[2]}`\n"
            f"💎 Tổng điểm: **{total_score}** | **{taixiu}** - **{chanle}** {icon_taixiu}"
        )
        
        await context.bot.send_message(chat_id=GROUP_USERNAME_OR_ID, text=summary_text, parse_mode="Markdown")
    
    except Exception as e:
        print(f"Lỗi khi gửi vào nhóm: {e}")

async def ep_ket_qua(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global forced_next_result
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng tính năng này!")
        return

    args = context.args
    if len(args) != 3:
        await update.message.reply_text("⚠️ Sai cú pháp! Vui lòng nhập: `/ep [mặt 1] [mặt 2] [mặt 3]`\nVí dụ: `/ep 6 3 1`", parse_mode="Markdown")
        return

    try:
        dice_results = [int(args[0]), int(args[1]), int(args[2])]
        if not all(1 <= d <= 6 for d in dice_results):
            await update.message.reply_text("⚠️ Các mặt xúc xắc phải nằm trong khoảng từ 1 đến 6!")
            return
            
        forced_next_result = dice_results
        await update.message.reply_text(f"✅ Đã ép kết quả phiên tiếp theo thành: `{dice_results[0]} {dice_results[1]} {dice_results[2]}`", parse_mode="Markdown")
        
        await execute_roll(context, dice_results)
        
    except ValueError:
        await update.message.reply_text("⚠️ Vui lòng nhập các con số nguyên hợp lệ!")

async def background_loop(app_instance):
    # Đợi bot khởi động ổn định 5 giây đầu
    await asyncio.sleep(5)
    while True:
        try:
            # Tạo một context giả lập để gọi hàm tung xúc xắc tự động
            class DummyContext:
                def __init__(self, bot):
                    self.bot = bot
            
            ctx = DummyContext(app_instance.bot)
            await execute_roll(ctx)
        except Exception as e:
            print(f"Lỗi vòng lặp tự động: {e}")
        
        # Chờ 30 giây cho phiên tiếp theo
        await asyncio.sleep(30)

async def post_init(application):
    # Chạy vòng lặp ngầm trực tiếp bằng Task độc lập, không phụ thuộc vào job_queue cũ
    asyncio.create_task(background_loop(application))

def main():
    # Chạy Web Server Flask ở một luồng riêng để đáp ứng yêu cầu của Render Web Service
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

    # Khởi động Bot Telegram
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("ep", ep_ket_qua))
    
    print("Bot đang chạy và tự động trực nhóm mỗi 30 giây...")
    app.run_polling()

if __name__ == "__main__":
    main()
