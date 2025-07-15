import os
import random
import time
import logging
import asyncio
from telegram import Update, ChatMemberAdministrator, ChatMemberOwner
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv
from asyncio import Lock

# 配置日志
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.ERROR)


# 配置BOT_TOKEN
load_dotenv(".env")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("错误: 未在 .env 文件或环境变量中找到 TELEGRAM_BOT_TOKEN！")

# 记录
games = {}
last_roll_time = {}

# 全局锁
games_lock = Lock()
last_roll_lock = Lock()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('欢迎使用真心话大冒险 Bot！使用 /createnewgame 开始游戏。')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "/createnewgame - 开始一个新的真心话大冒险游戏\n"
        "/stop - 结束当前的游戏(仅主持人)\n"
        "/adminstop - 结束当前的游戏(仅群管理)\n"
        "/join - 加入当前游戏\n"
        "/leave - 离开当前游戏\n"
        "/roll - 投骰子 (仅主持人)\n"
        "/help - 显示帮助消息\n\n"
        "注意：\n"
        "- 只有主持人可以开始、结束游戏，进行 /roll 投掷骰子。\n"
        "- 主持人默认不加入游戏，如果主持人也参与投骰子，请自行用 /join 加入游戏。\n"
        "- 主持人可以通过对玩家消息回复 /leave 将其移出游戏\n"
        "- 如果无法由主持人结束游戏时，群内管理可以用 /adminstop 结束游戏。\n"
        "- Bot需要管理员权限中的「删除消息」权限，以正确识别群内成员并管理游戏。"
    )
    await update.message.reply_text(help_text)

async def create_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    thread_id = getattr(update.message, "message_thread_id", 0)  # 兼容话题群组
    async with games_lock:
        if chat_id in games and thread_id in games[chat_id]:
            host_name = games[chat_id][thread_id]['host'].full_name
            host_id = games[chat_id][thread_id]['host'].id
            await update.message.reply_text(f'群里已经有一个由（{host_name}：{host_id}）主持的游戏啦。')
        else:
            if chat_id not in games:
                games[chat_id] = {}
            games[chat_id][thread_id] = {'participants': set(), 'host': user, 'participant_info': {}}
            await update.message.reply_text('新游戏已创建！使用 /join 加入游戏。\n开始游戏的人会充当主持人，负责本局游戏的管理。\n当不能负责时，请及时 /stop 结束游戏。')

async def stop_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    thread_id = getattr(update.message, "message_thread_id", 0)
    user = update.effective_user

    async with games_lock:
        # 1. 检查游戏是否存在
        if chat_id not in games or thread_id not in games[chat_id]:
            await update.message.reply_text('当前没有进行中的游戏。')
            return

        # 2. 检查用户权限
        game = games[chat_id][thread_id]
        if user.id != game['host'].id:
            host_name = game['host'].full_name
            host_id = game['host'].id
            await update.message.reply_text(f'只有本次游戏的主持人（{host_name}：{host_id}）可以结束游戏。\n 如果TA这会儿不在，可呼叫群管理结束游戏')
            return

        # 3. 删除游戏数据
        del games[chat_id][thread_id]
        if not games[chat_id]:  
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
    message_id = update.message.message_id

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
                chat_id_for_link = chat_id
                if isinstance(chat_id_for_link, int) and chat_id_for_link < 0:
                    chat_id_str = str(chat_id_for_link)[4:]  # 处理超级群ID
                else:
                    chat_id_str = str(chat_id_for_link)
                message_link = f"https://t.me/c/{chat_id_str}/{message_id}"

                host_name = games[chat_id][thread_id]['host'].full_name
                game["participants"].add(user.id)
                game["participant_info"][user.id] = {
                    "full_name": user.full_name,
                    "username": user.username,
                    "join_message_link": message_link
                }
                await update.message.reply_text(f"{user.full_name} 已加入由（{host_name}）主持的游戏。")
                if not user.username:
                    await update.message.reply_text("您的账号没有设置用户名，根据TG的规则 bot 将无法在游戏中对您做出@提醒，请自行注意游戏结果。")

        else:
            await update.message.reply_text("当前没有进行中的游戏。使用 /createnewgame 开始一个新游戏。\n开始游戏的人会充当主持人，负责本局游戏的管理。\n当不能负责时，请及时 /stop 结束游戏。")


async def leave_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    thread_id = getattr(update.message, "message_thread_id", 0)
    replied_message = update.message.reply_to_message  # 获取被回复的消息

    async with games_lock:
        if chat_id not in games or thread_id not in games[chat_id]:
            await update.message.reply_text('当前没有进行中的游戏。')
            return
        
        game = games[chat_id][thread_id]
        host_id = game['host'].id

        # 主持人通过回复他人消息踢人
        if user.id == host_id and replied_message:
            target_user = replied_message.from_user
            if target_user.id == host_id:
                await update.message.reply_text("主持人不能自己移除自己。")
                return

            if target_user.id in game['participants']:
                host_name = games[chat_id][thread_id]['host'].full_name
                game['participants'].remove(target_user.id)
                del game['participant_info'][target_user.id]
                await update.message.reply_text(
                    f"主持人（{host_name}）已将 {target_user.full_name} 移出游戏。"
                )
                return
            else:
                await update.message.reply_text("该用户不在游戏中。")
                return

        # 普通用户自己离开
        if user.id != host_id:
            if user.id in game['participants']:
                game['participants'].remove(user.id)
                del game['participant_info'][user.id]
                await update.message.reply_text(f'{user.full_name} 已离开游戏。')
            else:
                await update.message.reply_text('您不在游戏中。')
            return

        # 主持人单独发送/leave
        await update.message.reply_text(
            '您作为游戏主持人无法离开游戏，'
            '如果需要更换主持人请先（/stop）结束游戏，'
            '再由新主持人（/createnewgame）开始游戏'
        )
async def roll_dice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    thread_id = getattr(update.message, "message_thread_id", 0)
    current_time = time.time()
    retry_count = 0
    max_retries = 5   

    # 平局最多重试5次

    async with last_roll_lock:
        if chat_id in last_roll_time and thread_id in last_roll_time[chat_id]:
            last_roll = last_roll_time[chat_id][thread_id]
            if current_time - last_roll < 10:
                async with games_lock:
                    game = games.get(chat_id, {}).get(thread_id)
                    if not game:
                        return
                remaining = 10 - int(current_time - last_roll) # 最小间隔10秒
                remaining = max(0, remaining)
                if user.id != game['host'].id:
                    host_name = game['host'].full_name
                    await update.message.reply_text(f'只有本次游戏的主持人（{host_name}）可以掷骰子。')
                    return
                else:
                    await update.message.reply_text(f"⏳ 你扔的太快了吧，请等待 {remaining} 秒")
                    return 

    async with games_lock:
        if chat_id not in games or thread_id not in games[chat_id]:
            await update.message.reply_text('当前没有进行中的游戏。')
            return
        
        game = games[chat_id][thread_id]

        # 检查主持人权限
        if user.id != game['host'].id:
            host_name = game['host'].full_name
            await update.message.reply_text(f'只有本次游戏的主持人（{host_name}）可以掷骰子。')
            return

        # 检查参与者数量
        if len(game['participants']) < 2:
            await update.message.reply_text('至少需要两名参与者才能掷骰子。')
            return
        
        while retry_count < max_retries:

            #  掷骰子 
            rolls = {
                user_id: random.randint(1, 100)
                for user_id in games[chat_id][thread_id]['participants']
            }

            def get_user_display(user_id):
                user_info = game['participant_info'][user_id]
                if user_info['username']:
                    return f'<a href="{user_info["join_message_link"]}">🔗 </a>{user_info["full_name"]}'
                else:
                    return f'<a href="{user_info["join_message_link"]}">🔗 </a>{user_info["full_name"]}'


            participant_count = len(rolls)

            results = (
                f"🎲 本局玩家共（{participant_count}人） 🎲\n\n"
                + "\n".join([
                    f"{get_user_display(user_id)}: {score}"
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
                winner_info = game['participant_info'][max_users[0]]
                loser_info = game['participant_info'][min_users[0]]
                winner_name = f"@{winner_info['username']}" if winner_info['username'] else winner_info['full_name']
                loser_name = f"@{loser_info['username']}" if loser_info['username'] else loser_info['full_name']
                await update.message.reply_text(
                    f"{results}\n\n🏆 胜利者: {winner_name}\n😵 失败者: {loser_name}",
                    parse_mode='HTML'
                )
                break
            else:
                retry_count += 1
                await update.message.reply_text(
                    f"{results}\n\n⚠️ 出现平局！重新掷骰子...", 
                    parse_mode='HTML'
                )
                await asyncio.sleep(1)
        else:
            # 多次平局后结束自动重roll
            await update.message.reply_text("多次平局，游戏终止，请手动处理。")
            return
        
    async with last_roll_lock:
            if chat_id not in last_roll_time:
                last_roll_time[chat_id] = {}
            last_roll_time[chat_id][thread_id] = time.time()  
    

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
    application.add_handler(CommandHandler("createnewgame", create_game))
    application.add_handler(CommandHandler("stop", stop_game))
    application.add_handler(CommandHandler("join", join_game))
    application.add_handler(CommandHandler("leave", leave_game))
    application.add_handler(CommandHandler("roll", roll_dice))
    application.add_handler(CommandHandler("adminstop", admin_stop))

    application.run_polling()

if __name__ == '__main__':
    main()
