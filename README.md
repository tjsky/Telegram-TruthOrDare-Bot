##  Telegram Truth Or Dare Bot （Telegram 真心话大冒险机器人）

### 一、简介

Demo：[真心话大冒险辅助Bot](https://t.me/zh_sexting_TOD_bot)

![20250308113225_副本](https://github.com/user-attachments/assets/ba7d462b-ce2e-46d0-9dd1-74651a2e19a6)



真心话大冒险为派对游戏，又称诚实与大胆、Truth or Dare，可以由二人或多人参与
通过抽签、转瓶、骰子、击鼓传花等形式决定胜利者和失败者
- 真心话：失败者必须要如实的回答胜利者提出的任何问题（一般是隐私且令人尴尬的）
- 大冒险：失败者必须原则上要做胜利者所提出的任何事情（通常也是令人尴尬的）
- 原则上如果胜利者提出的问题或条件过于苛刻或过火，失败者有拒绝的权利。实则受气氛环境等影响，失败者或会在半推半就下作出有违意愿的言行。（当然太过分的要求该拒绝还是要决绝的）😚

#### 特色
- 使用主持人制度，由最先发起游戏者担任主持人控制游戏开始、结束、每局的roll点
- 群友可自行加入和离开游戏。
- 平局结果自动重试。
- 自动总结当前游戏情况。
- 群管理员可强制结束游戏，以免出现主持人失踪导致群内游戏无法结束。

#### 优势
- 解决破解客户端的 🎲 作弊问题
- 解决PC客户端发送 🎲 需要输入的问题（安卓端可以点其他人发送的 🎲 来快速发送 🎲 ）
- 解决使用客户端 🎲 只有6个面，导致的高几率胜负不唯一的问题，将Roll点范围扩大到1~100。
- 明确列出每局游戏参与者，以免手动区分的出现遗漏的问题。

### 二、准备工作

1. 找 @BotFather 申请一个机器人。
2. 获取机器人的token
3. 将机器人加入群组（Bot设计上不需要管理权限，但给个管理更好）

### 三、部署运行
1. 修改env
打开.env_example，将自己机器人的Token、账号的API_ID/HASH、管理群组ID和管理员ID补全。 另存.env_example为.env

2. 获取代码/构建python venv
   
```bash
git clone https://github.com/tjsky/Telegram-TruthOrDare-Bot.git
cd Telegram-TruthOrDare-Bot
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```

3. 执行
`python truth_dare_bot.py`

PS: 正式运营，还是需要类似PM2、supervisor之类的进程管理工具，来实现不间断运行、自动重启、失效重启等功能。

### 关于
- 本产品基于Apache协议开源。
- 原始作者不是我本人 ( @tjsky )，项目为代友发布，我只写了这个介绍，补全了项目部署需要的文件，我们都不是职业程序员，纯粹是业余写点东西，有问题别太理直气壮的跑来下命令。
- 随意Fork，记得保留关于的内容。
- 服务器推荐RackNerd或CloudCone的就行。Demo就在CloudCone上运行，这款就够：3核2G--年25刀
- 其实实在不会部署的话，用Demo 就行，理论上应该能支撑挺高的并发的。
