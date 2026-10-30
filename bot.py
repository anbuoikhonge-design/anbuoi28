import random
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Cấu hình thông tin bot và admin của bạn
BOT_TOKEN = "9294891883:AAHsv-TTxyop9p_nCtqPEoPuaP3NXoo0bAk"
ADMIN_ID = 7884394252
GROUP_USERNAME_OR_ID = "@tungxxtest9" 

# Biến lưu trữ kết quả ép tạm thời của admin
forced_next_result = None

async def execute_roll(context: ContextTypes.DEFAULT_TYPE, dice_results=None):
    global forced_next_result
    
    try:
        # Thông báo bắt đầu phiên mới
        await context.bot.send_message(
            chat_id=GROUP_USERNAME_OR_ID,
            text="🎲 **Bắt đầu tung xúc xắc phiên mới!**",
            parse_mode="Markdown"
        )
        
        # Nếu admin có dùng lệnh /ep trước đó thì lấy kết quả ép, không thì random từ 1 đến 6
        if dice_results:
            actual_results = dice_results
        elif forced_next_result:
            actual_results = forced_next_result
            forced_next_result = None # Dùng xong reset lại
        else:
            actual_results = [random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)]

        # Gửi lần lượt 3 viên xúc xắc chuẩn nguyên bản của Telegram vào nhóm
        for _ in range(3):
            await context.bot.send_dice(chat_id=GROUP_USERNAME_OR_ID, emoji='🎲')
            await asyncio.sleep(0.5) # Độ trễ nhẹ giữa các viên cho tự nhiên

        # Tính toán tổng điểm, Tài/Xỉu, Chẵn/Lẻ dựa trên kết quả đã định đoạt
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
        
        # Gửi bảng tổng kết kết quả vào nhóm
        await context.bot.send_message(chat_id=GROUP_USERNAME_OR_ID, text=summary_text, parse_mode="Markdown")
    
    except Exception as e:
        print(f"Lỗi khi gửi vào nhóm: {e}")

# Lệnh dành riêng cho Admin để ép kết quả
async def ep_ket_qua(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global forced_next_result
    user_id = update.effective_user.id
    
    # Kiểm tra bảo mật: Chỉ đúng ID Admin mới được phép thực thi
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
        
        # Tiến hành tung ngay kết quả vừa ép vào nhóm
        await execute_roll(context, dice_results)
        
    except ValueError:
        await update.message.reply_text("⚠️ Vui lòng nhập các con số nguyên hợp lệ!")

# Vòng lặp tự động chạy ngầm cứ mỗi 30 giây tung xúc xắc một lần
async def auto_roll_job(context: ContextTypes.DEFAULT_TYPE):
    while True:
        await asyncio.sleep(30) # Chờ đúng 30 giây
        await execute_roll(context)

async def post_init(application):
    application.job_queue.run_once(lambda ctx: asyncio.create_task(auto_roll_job(ctx)), 3)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("ep", ep_ket_qua))
    
    print("Bot đang chạy và tự động trực nhóm mỗi 30 giây...")
    app.run_polling()

if __name__ == "__main__":
    main()
