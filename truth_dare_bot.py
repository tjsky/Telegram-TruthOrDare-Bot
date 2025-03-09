import os
import random
import time
import logging
import asyncio
from telegram import Update, ChatMemberAdministrator, ChatMemberOwner
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from dotenv import load_dotenv
from asyncio import Lock

# 配置日志
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.ERROR)


# 获取BOT_TOKEN
load_dotenv(".env")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("错误: 未在 .env 文件或环境变量中找到 TELEGRAM_BOT_TOKEN！")

# 建立字典和组
games = {}
last_roll_time = {}

# 加全局锁
games_lock = Lock()
last_roll_lock = Lock()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('欢迎使用真心话大冒险 Bot！使用 /create 开始游戏。')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "/create - 开始一个新的真心话大冒险游戏\n"
        "/stop - 结束当前的游戏(仅主持人)\n"
        "/adminstop - 结束当前的游戏(仅群管理)\n"
        "/join - 加入当前游戏\n"
        "/leave - 自己离开当前游戏\n"
        "/roll - 投骰子 (仅主持人)\n"
        "/help - 显示帮助消息\n\n"
        "注意：\n"
        "- 只有主持人可以开始、结束游戏，进行 /roll 投掷骰子。\n"
        "- 主持人默认不加入游戏，如果主持人也参与投骰子，请自行用 /join 加入游戏。\n"
        "- 如果无法由主持人结束游戏时，群内管理也可以用 /adminstop 结束游戏。"
    )
    await update.message.reply_text(help_text)

async def create_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    thread_id = getattr(update.message, "message_thread_id", 0)  # Use 0 for non-topic messages
    async with games_lock:
        if chat_id in games and thread_id in games[chat_id]:
            await update.message.reply_text('游戏已经在进行中。')
        else:
            if chat_id not in games:
                games[chat_id] = {}
            games[chat_id][thread_id] = {'participants': set(), 'host': user, 'participant_info': {}}
            await update.message.reply_text('新游戏已创建！使用 /join 加入游戏。')

async def stop_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    thread_id = getattr(update.message, "message_thread_id", 0)
    user = update.effective_user

    async with games_lock:
        # 1. 先检查游戏是否存在
        if chat_id not in games or thread_id not in games[chat_id]:
            await update.message.reply_text('当前没有进行中的游戏。')
            return

        # 2. 再检查用户权限
        game = games[chat_id][thread_id]
        if user.id != game['host'].id:
            await update.message.reply_text('只有主持人可以使用/stop命令。')
            return

        # 3. 删除游戏数据
        del games[chat_id][thread_id]
        if not games[chat_id]:  # 清理空群组
            del games[chat_id]
        await update.message.reply_text('游戏已结束。')

    async with last_roll_lock:
        if chat_id in last_roll_time and thread_id in last_roll_time[chat_id]:
            del last_roll_time[chat_id][thread_id]
            if not last_roll_time[chat_id]:
                del last_roll_time[chat_id]

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    thread_id = getattr(update.message, "message_thread_id", 0)
    user = update.effective_user

    async with games_lock:
        if chat_id in games and thread_id in games[chat_id]:
            game = games[chat_id][thread_id]

            if "participants" not in game:
                game["participants"] = set()
            if "participant_info" not in game:
                game["participant_info"] = {}

            if user.id in game["participants"]:
                await update.message.reply_text(f"{user.full_name} 已经在游戏中。")
            else:
                game["participants"].add(user.id)
                game["participant_info"][user.id] = {
                    "full_name": user.full_name,
                    "username": user.username
                }
                await update.message.reply_text(f"{user.full_name} 已加入游戏。")
        else:
            await update.message.reply_text("当前没有进行中的游戏。使用 /create 开始一个新游戏。")


async def leave_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    thread_id = getattr(update.message, "message_thread_id", 0)

    async with games_lock:
        if chat_id not in games or thread_id not in games[chat_id]:
            await update.message.reply_text('当前没有进行中的游戏。')
            return
        
        game = games[chat_id][thread_id]

    # Step 1: 检查是否是主持人
        if user.id != game['host'].id:
            if user.id in game['participants']:
                game['participants'].remove(user.id)
                del game['participant_info'][user.id]
                await update.message.reply_text(f'{user.full_name} 已离开游戏。')
            else:
                await update.message.reply_text('您不在游戏中。')
            return

    # Step 2: 告知主持人无法自行离开
        await update.message.reply_text('您作为游戏主持人无法离开游戏，如果需要更换主持人请先（/stop）结束游戏，再由新主持人（/create）开始游戏')

async def roll_dice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    thread_id = getattr(update.message, "message_thread_id", 0)
    current_time = time.time()
    retry_count = 0
    max_retries = 5
    
    async with last_roll_lock:
        if chat_id in last_roll_time and thread_id in last_roll_time[chat_id]:
            last_roll = last_roll_time[chat_id][thread_id]
            if current_time - last_roll < 10:
                remaining = 10 - int(current_time - last_roll)
                await update.message.reply_text(f"⏳ 你扔的太快了吧，请等待 {remaining} 秒")
                return      

    async with games_lock:
        if chat_id not in games or thread_id not in games[chat_id]:
            await update.message.reply_text('当前没有进行中的游戏。')
            return
        
        game = games[chat_id][thread_id]

        # 检查主持人权限
        if user.id != game['host'].id:
            await update.message.reply_text('只有主持人可以掷骰子。')
            return

        # 检查参与者数量
        if len(game['participants']) < 2:
            await update.message.reply_text('至少需要两名参与者才能掷骰子。')
            return
        
        while retry_count < max_retries:

            # 🎲 掷骰子 🎲
            rolls = {
                user_id: random.randint(1, 100)
                for user_id in games[chat_id][thread_id]['participants']
            }

            participant_count = len(rolls)

            results = (
                f"🎲 本局玩家共（{participant_count}人） 🎲\n\n"
                + "\n".join([
                    f"{games[chat_id][thread_id]['participant_info'][user_id]['full_name']}: {score}"
                    for user_id, score in rolls.items()
                ])
            )

            # 计算胜负
            max_score = max(rolls.values())
            min_score = min(rolls.values())
            max_users = [user_id for user_id, score in rolls.items() if score == max_score]
            min_users = [user_id for user_id, score in rolls.items() if score == min_score]

            # 处理平局（自动重掷）
            if len(max_users) == 1 and len(min_users) == 1:
                winner_info = games[chat_id][thread_id]['participant_info'][max_users[0]]
                loser_info = games[chat_id][thread_id]['participant_info'][min_users[0]]
                winner_name = f"[{escape_markdown(winner_info.user.full_name, version=2)}](tg://user?id={max_users[0]})"
                loser_name = f"[{escape_markdown(loser_info.user.full_name, version=2)}](tg://user?id={min_users[0]})"
                await update.message.reply_text(
                    f"🎲 结果 🎲\n{results}\n\n🏆 胜利者: {winner_name}\n😵 失败者: {loser_name}",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                break
            else:
                retry_count += 1
                await update.message.reply_text(
                    f"🎲 结果 🎲\n{results}\n\n⚠️ 出现平局！重新掷骰子...",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await asyncio.sleep(1)
        else:
            # 最多重复5次，以免出现游戏人数大于100后，永远无法得出结果
            await update.message.reply_text("多次平局，游戏终止，请手动处理。")
            return
        
    async with last_roll_lock:
            if chat_id not in last_roll_time:
                last_roll_time[chat_id] = {}
            last_roll_time[chat_id][thread_id] = time.time()  # 记录成功执行时间
    

async def admin_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    thread_id = getattr(update.message, "message_thread_id", 0)
    user = update.effective_user

    # 获取用户的权限
    member = await context.bot.get_chat_member(chat_id, user.id)
    if not isinstance(member, (ChatMemberAdministrator, ChatMemberOwner)):
        await update.message.reply_text("只有管理员可以使用 /adminstop 结束游戏。")
        return

    async with games_lock:
        if chat_id in games and thread_id in games[chat_id]:
            del games[chat_id][thread_id]
            await update.message.reply_text("管理员已结束游戏。")
        else:
            await update.message.reply_text("当前没有进行中的游戏。")
            return
        
    async with last_roll_lock:
        if chat_id in last_roll_time and thread_id in last_roll_time[chat_id]:
            del last_roll_time[chat_id][thread_id]

def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("create", create_game))
    application.add_handler(CommandHandler("stop", stop_game))
    application.add_handler(CommandHandler("join", join_game))
    application.add_handler(CommandHandler("leave", leave_game))
    application.add_handler(CommandHandler("roll", roll_dice))
    application.add_handler(CommandHandler("adminstop", admin_stop))

    application.run_polling()

if __name__ == '__main__':
    main()
