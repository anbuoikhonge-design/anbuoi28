import os
import random
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# Cấu hình thông tin bot và admin
BOT_TOKEN = "9294891883:AAHsv-TTxyop9p_nCtqPEoPuaP3NXoo0bAk"
ADMIN_ID = 7884394252
GROUP_CHAT_ID = -1004331746455 

forced_next_result = None

# Web Server Flask giả lập để duy trì Render Web Service
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Bot Tai Xiu is running smoothly!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

# Hàm xử lý tung xúc xắc và tính kết quả
async def execute_roll(context: ContextTypes.DEFAULT_TYPE, target_chat_id, dice_results=None):
    global forced_next_result
    
    try:
        await context.bot.send_message(
            chat_id=target_chat_id,
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
            await context.bot.send_dice(chat_id=target_chat_id, emoji='🎲')
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
        
        await context.bot.send_message(chat_id=target_chat_id, text=summary_text, parse_mode="Markdown")
    
    except Exception as e:
        print(f"Lỗi khi gửi vào chat ID {target_chat_id}: {e}")

# Lệnh /start khi người dùng hoặc admin chat riêng với bot
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    reply_msg = (
        f"👋 Chào **{user_name}**!\n\n"
        f"🤖 Bot Tài Xỉu đang hoạt động hoàn toàn bình thường 24/7.\n"
        f"📌 **Nhóm mục tiêu:** `{GROUP_CHAT_ID}`\n"
        f"⏱ Bot tự động tung xúc xắc mỗi 30 giây vào nhóm."
    )
    
    if update.effective_user.id == ADMIN_ID:
        reply_msg += "\n\n👑 **Quyền Admin:** Bạn có thể dùng lệnh `/ep [mặt 1] [mặt 2] [mặt 3]` tại đây để ép kết quả phiên tiếp theo trong nhóm!"

    await update.message.reply_text(reply_msg, parse_mode="Markdown")

# Lệnh ép kết quả dành riêng cho Admin /ep
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
        await update.message.reply_text(f"✅ Đã ép kết quả phiên tiếp theo trong nhóm thành: `{dice_results[0]} {dice_results[1]} {dice_results[2]}`", parse_mode="Markdown")
        
        # Thực hiện tung ngay lập tức vào nhóm
        await execute_roll(context, GROUP_CHAT_ID, dice_results)
        
    except ValueError:
        await update.message.reply_text("⚠️ Vui lòng nhập các con số nguyên hợp lệ!")

# Lắng nghe tin nhắn chat riêng từ người dùng
async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await start_command(update, context)

# Vòng lặp tự động tung xúc xắc mỗi 30 giây vào nhóm
async def background_loop(app_instance):
    await asyncio.sleep(5)
    while True:
        try:
            class DummyContext:
                def __init__(self, bot):
                    self.bot = bot
            
            ctx = DummyContext(app_instance.bot)
            await execute_roll(ctx, GROUP_CHAT_ID)
        except Exception as e:
            print(f"Lỗi vòng lặp tự động: {e}")
        
        await asyncio.sleep(30)

async def post_init(application):
    asyncio.create_task(background_loop(application))

def main():
    # Khởi chạy máy chủ Flask phụ cho Render
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

    # Khởi tạo Bot Telegram
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("ep", ep_ket_qua))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, handle_private_message))
    
    print("Bot đang chạy và đã sẵn sàng phục vụ...")
    app.run_polling()

if __name__ == "__main__":
    main()
