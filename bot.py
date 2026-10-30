import os
import random
import asyncio
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Cấu hình thông tin bot và admin
BOT_TOKEN = "9294891883:AAHsv-TTxyop9p_nCtqPEoPuaP3NXoo0bAk"
ADMIN_ID = 7884394252
GROUP_USERNAME_OR_ID = "@tungxxtest9" 

forced_next_result = None

async def execute_roll(context: ContextTypes.DEFAULT_TYPE, dice_results=None):
    global forced_next_result
    
    if not dice_results:
        if forced_next_result:
            dice_results = forced_next_result
            forced_next_result = None
        else:
            dice_results = [random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)]

    try:
        await context.bot.send_message(
            chat_id=GROUP_USERNAME_OR_ID,
            text="🎲 **Bắt đầu tung xúc xắc phiên mới!**",
            parse_mode="Markdown"
        )
        
        for number in dice_results:
            video_path = f"dice_output/video/dice_{number}.mp4"
            if os.path.exists(video_path):
                with open(video_path, 'rb') as video_file:
                    await context.bot.send_animation(
                        chat_id=GROUP_USERNAME_OR_ID,
                        animation=InputFile(video_file)
                    )
            else:
                await context.bot.send_message(chat_id=GROUP_USERNAME_OR_ID, text=f"🎲 Mặt: **{number}**", parse_mode="Markdown")
            await asyncio.sleep(0.4)

        total_score = sum(dice_results)
        taixiu = "TÀI" if total_score >= 11 else "XỈU"
        chanle = "CHẴN" if total_score % 2 == 0 else "LẺ"
        icon_taixiu = "🔴" if total_score >= 11 else "🔵"

        summary_text = (
            "───────────────\n"
            f"📊 **Kết quả Tổng kết**\n"
            f"🎲 Mặt xúc xắc: `{dice_results[0]}`  `{dice_results[1]}`  `{dice_results[2]}`\n"
            f"💎 Tổng điểm: **{total_score}** | **{taixiu}** - **{chanle}** {icon_taixiu}"
        )
        
        await context.bot.send_message(chat_id=GROUP_USERNAME_OR_ID, text=summary_text, parse_mode="Markdown")
    
    except Exception as e:
        print(f"Lỗi khi gửi vào nhóm: {e}")

async def ep_ket_qua(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global forced_next_result
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này!")
        return

    args = context.args
    if len(args) != 3:
        await update.message.reply_text("⚠️ Sai cú pháp! Nhập: `/ep [mặt 1] [mặt 2] [mặt 3]` (Ví dụ: `/ep 6 3 1`)", parse_mode="Markdown")
        return

    try:
        dice_results = [int(args[0]), int(args[1]), int(args[2])]
        if not all(1 <= d <= 6 for d in dice_results):
            await update.message.reply_text("⚠️ Các mặt xúc xắc phải từ 1 đến 6!")
            return
            
        forced_next_result = dice_results
        await update.message.reply_text(f"✅ Đã ép kết quả phiên tiếp theo thành: `{dice_results[0]} {dice_results[1]} {dice_results[2]}`", parse_mode="Markdown")
        
        await execute_roll(context, dice_results)
        
    except ValueError:
        await update.message.reply_text("⚠️ Vui lòng nhập số nguyên hợp lệ!")

async def auto_roll_job(context: ContextTypes.DEFAULT_TYPE):
    while True:
        await asyncio.sleep(30)
        await execute_roll(context)

async def post_init(application):
    application.job_queue.run_once(lambda ctx: asyncio.create_task(auto_roll_job(ctx)), 5)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("ep", ep_ket_qua))
    print("Bot đang chạy trên Railway...")
    app.run_polling()

if __name__ == "__main__":
    main()
