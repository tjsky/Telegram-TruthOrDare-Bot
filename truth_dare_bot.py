import os
import random
import time
import logging
import asyncio
from telegram import Update, ChatMemberAdministrator, ChatMemberOwner
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackContext
from dotenv import load_dotenv
from asyncio import Lock, Queue

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

# 消息队列和定时器管理
message_queue = Queue()
timer_queue = Queue()

# 定时器常量
TIMER_INTERVAL = 60  # 检查间隔(秒)
WARNING_10_MIN = 600 # 第一次提醒间隔
WARNING_20_MIN = 1200 # 第二次提醒间隔
GAME_TIMEOUT = 1800 # 第三次结束游戏间隔
MAX_MESSAGES_PER_SECOND = 28  # 限制提醒的发送速率，以防撞上TG的限制。


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
    current_time = time.time()
    
    async with games_lock:
        if chat_id in games and thread_id in games[chat_id]:
            host_name = games[chat_id][thread_id]['host'].full_name
            host_id = games[chat_id][thread_id]['host'].id
            await update.message.reply_text(f'群里已经有一个由（{host_name}：{host_id}）主持的游戏啦。')
        else:
            if chat_id not in games:
                games[chat_id] = {}
            
            # 添加游戏计时器相关字段
            games[chat_id][thread_id] = {
                'participants': set(),
                'host': user,
                'participant_info': {},
                'game_start_time': current_time,
                'host_last_active': current_time,
                'timer_state': 0
            }
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

    # 更新主持人最后活跃时间和重置计时状态
    async with games_lock:
        if chat_id in games and thread_id in games[chat_id]:
            game = games[chat_id][thread_id]
            if user.id == game['host'].id:
                game['host_last_active'] = current_time
                game['timer_state'] = 0  # 重置计时状态

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

async def game_timer_check(context: CallbackContext) -> None:
    """每分钟检查所有游戏的计时器状态"""
    current_time = time.time()
    tasks = []
    
    # 快速收集需要处理的任务而不持有锁
    async with games_lock:
        active_games = []
        for chat_id, threads in games.items():
            for thread_id, game in threads.items():
                active_games.append((
                    chat_id,
                    thread_id,
                    game['game_start_time'],
                    game['host_last_active'],
                    game.get('timer_state', 0)
                ))
    
    # 并行处理每个游戏的状态
    for chat_id, thread_id, start_time, last_active, timer_state in active_games:
        elapsed_time = current_time - start_time
        inactive_time = current_time - last_active
        timer_key = (chat_id, thread_id)
        
        # 10分钟提醒
        if WARNING_10_MIN <= elapsed_time < WARNING_20_MIN and inactive_time >= WARNING_10_MIN:
            if timer_state < 10:
                await timer_queue.put((
                    chat_id, thread_id, 
                    "⏰ 本轮游戏已经过去10分钟咯",
                    10
                ))
        
        # 20分钟提醒
        elif WARNING_20_MIN <= elapsed_time < GAME_TIMEOUT and inactive_time >= WARNING_20_MIN:
            if timer_state < 20:
                await timer_queue.put((
                    chat_id, thread_id,
                    "⏰ 本轮游戏已经过去20分钟咯，如果超过30分钟主持人无操作，本次游戏将自动结束",
                    20
                ))
        
        # 30分钟超时自动结束
        elif inactive_time >= GAME_TIMEOUT:
            await timer_queue.put((
                chat_id, thread_id,
                "⏰ 超过30分钟无操作，游戏已自动结束",
                30
            ))

async def timer_task_processor():
    """处理定时器任务队列"""
    while True:
        try:
            # 获取任务并处理
            chat_id, thread_id, text, timer_state = await timer_queue.get()
            
            # 更新游戏状态
            async with games_lock:
                if chat_id in games and thread_id in games[chat_id]:
                    game = games[chat_id][thread_id]
                    
                    if timer_state == 30:  # 结束游戏
                        del games[chat_id][thread_id]
                        if not games[chat_id]:
                            del games[chat_id]
                        
                        async with last_roll_lock:
                            if chat_id in last_roll_time and thread_id in last_roll_time[chat_id]:
                                del last_roll_time[chat_id][thread_id]
                                if not last_roll_time[chat_id]:
                                    del last_roll_time[chat_id]
                    else:  # 更新计时状态
                        game['timer_state'] = timer_state
            
            # 将消息加入发送队列
            await message_queue.put((chat_id, thread_id, text))
            
        except Exception as e:
            logging.error(f"定时任务处理错误: {e}")
            await asyncio.sleep(1)

async def message_queue_sender(context: CallbackContext):
    """以可控速率发送队列中的消息"""
    while True:
        messages_to_send = []
        start_time = time.time()
        
        # 批量获取消息（最多MAX_MESSAGES_PER_SECOND条）
        for _ in range(MAX_MESSAGES_PER_SECOND):
            if not message_queue.empty():
                messages_to_send.append(await message_queue.get())
        
        # 发送消息
        for chat_id, thread_id, text in messages_to_send:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id if thread_id != 0 else None,
                    text=text
                )
            except Exception as e:
                logging.error(f"消息发送失败: {e}")
        
        # 控制速率
        elapsed = time.time() - start_time
        if elapsed < 1.0 and messages_to_send:
            await asyncio.sleep(1.0 - elapsed)
        elif not messages_to_send:
            await asyncio.sleep(0.5)

def main():
    application = Application.builder().token(TOKEN).build()

    # 添加命令
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("createnewgame", create_game))
    application.add_handler(CommandHandler("stop", stop_game))
    application.add_handler(CommandHandler("join", join_game))
    application.add_handler(CommandHandler("leave", leave_game))
    application.add_handler(CommandHandler("roll", roll_dice))
    application.add_handler(CommandHandler("adminstop", admin_stop))
    
    # 定时任务
    application.job_queue.run_repeating(
        game_timer_check, 
        interval=TIMER_INTERVAL, 
        first=0
    )
    
    # 队列处理器
    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(timer_task_processor()), 
        when=0
    )
    
    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(message_queue_sender(ctx)), 
        when=0
    )

    application.run_polling()

if __name__ == '__main__':
    main()
