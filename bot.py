import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv
import random
import asyncio
import json
import re

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
VELT_ADMIN_IDS = [int(x) for x in os.getenv("VELT_ADMIN_IDS", "").split(",") if x]
VELT_LOG_CHANNEL_ID = int(os.getenv("VELT_LOG_CHANNEL_ID"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # ←これを追加
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

BALANCE_FILE = "velt_balances.json"

# メモリ上の簡易DB（本番はDB推奨）
velt_balances = {}

# 残高をファイルから読み込む
def load_balances():
    global velt_balances
    try:
        with open(BALANCE_FILE, "r", encoding="utf-8") as f:
            velt_balances.update(json.load(f))
    except FileNotFoundError:
        pass

# 残高をファイルに保存する
def save_balances():
    with open(BALANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(velt_balances, f, ensure_ascii=False)

# 残高操作関数を修正
def set_balance(user_id, amount):
    velt_balances[str(user_id)] = amount
    save_balances()

def add_balance(user_id, amount):
    uid = str(user_id)
    velt_balances[uid] = get_balance(user_id) + amount
    save_balances()

def get_balance(user_id):
    return velt_balances.get(str(user_id), 0)

def is_admin(user: discord.User):
    return user.id in VELT_ADMIN_IDS

# 1. 通貨発行
@tree.command(name="発行", description="veltを発行（管理者のみ）", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="発行先", amount="発行額")
async def 発行(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("権限がありません。", ephemeral=True)
        return
    add_balance(user.id, amount)
    await interaction.response.send_message(f"{user.mention} に {amount} velt 発行しました。", ephemeral=True)
    # ログ（コマンド実行チャンネルにのみ送信）
    await interaction.channel.send(f"【発行】{interaction.user.mention} → {user.mention} : {amount} velt")

# 2. 通貨減少
@tree.command(name="減少", description="veltを減少（管理者のみ）", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="対象ユーザー", amount="減少額")
async def 減少(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("権限がありません。", ephemeral=True)
        return
    add_balance(user.id, -amount)
    await interaction.response.send_message(f"{user.mention} から {amount} velt 減少しました。", ephemeral=True)
    # ログ（コマンド実行チャンネルにのみ送信）
    await interaction.channel.send(f"【減少】{interaction.user.mention} → {user.mention} : -{amount} velt")

# 3. 残高確認（管理者は他人の残高も確認可能）
@tree.command(name="残高確認", description="velt残高を確認", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="確認したいユーザー")
async def 残高確認(interaction: discord.Interaction, user: discord.Member = None):
    # 管理者は他人の残高も確認可能
    if user is None or user.id == interaction.user.id:
        balance = get_balance(interaction.user.id)
        await interaction.response.send_message(f"あなたの残高: {balance} velt", ephemeral=True)
    else:
        if not is_admin(interaction.user):
            await interaction.response.send_message("他人の残高は確認できません。", ephemeral=True)
            return
        balance = get_balance(user.id)
        await interaction.response.send_message(f"{user.mention} のvelt残高: {balance}", ephemeral=True)

# 4. 送金
@tree.command(name="送金", description="veltを送金", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="送金先", amount="送金額")
async def 送金(interaction: discord.Interaction, user: discord.Member, amount: int):
    if user.id == interaction.user.id:
        await interaction.response.send_message("自分自身には送金できません。", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("1以上の金額を指定してください。", ephemeral=True)
        return
    if get_balance(interaction.user.id) < amount:
        await interaction.response.send_message("残高が足りません。", ephemeral=True)
        return
    add_balance(interaction.user.id, -amount)
    add_balance(user.id, amount)
    await interaction.response.send_message(f"{user.mention} に {amount} velt 送金しました。", ephemeral=True)
    # 追加: 送金チャンネルにも通知
    await interaction.channel.send(
        f"{interaction.user.mention} から {user.mention} へ {amount} velt 送金されました。"
    )
    # ログ
    log_channel = interaction.guild.get_channel(VELT_LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"【送金】{interaction.user.mention} → {user.mention} : {amount} velt"
        )

# --- スロット ---
class SlotView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=30)
        self.user_id = user_id

    @discord.ui.button(label="1000 velt", style=discord.ButtonStyle.primary)
    async def bet_1000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet(interaction, 1000)

    @discord.ui.button(label="5000 velt", style=discord.ButtonStyle.success)
    async def bet_5000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet(interaction, 5000)

    @discord.ui.button(label="10000 velt", style=discord.ButtonStyle.danger)
    async def bet_10000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet(interaction, 10000)

    async def handle_bet(self, interaction, bet):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("自分のパネルのみ操作できます。", ephemeral=True)
            return
        if get_balance(self.user_id) < bet:
            await interaction.response.send_message("残高が足りません。", ephemeral=True)
            return

        symbols = ["🍒", "🍋", "🔔", "⭐", "7️⃣"]
        # スロット演出
        msg = await interaction.channel.send(f"{interaction.user.mention} 🎰 スロットを回しています...")
        result = []
        for i in range(3):
            slot_now = [random.choice(symbols) for _ in range(3)]
            await msg.edit(content=f"{interaction.user.mention} 🎰 {' '.join(slot_now)}")
            await asyncio.sleep(0.5)
            result.append(slot_now[i])
        await asyncio.sleep(0.5)

        # 判定
        await_msg = f"{interaction.user.mention} 🎰 {' '.join(result)}\n"
        if result[0] == result[1] == result[2]:
            payout = bet * 10
            add_balance(self.user_id, payout)
            await_msg += f"🎉 大当たり！{payout} velt獲得！"
        elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
            payout = bet * 2
            add_balance(self.user_id, payout)
            await_msg += f"当たり！{payout} velt獲得！"
        else:
            add_balance(self.user_id, -bet)
            await_msg += f"はずれ… {bet} velt失いました。"

        await msg.edit(content=await_msg)

@tree.command(name="スロット", description="veltでスロットを回す", guild=discord.Object(id=GUILD_ID))
async def スロット(interaction: discord.Interaction):
    view = SlotView(interaction.user.id)
    await interaction.response.send_message("掛け金を選んでください！", view=view, ephemeral=True)

# --- ちんちろ ---
class ChinchiroView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=30)
        self.user_id = user_id

    @discord.ui.button(label="1000 velt", style=discord.ButtonStyle.primary)
    async def bet_1000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet(interaction, 1000)

    @discord.ui.button(label="5000 velt", style=discord.ButtonStyle.success)
    async def bet_5000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet(interaction, 5000)

    @discord.ui.button(label="10000 velt", style=discord.ButtonStyle.danger)
    async def bet_10000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet(interaction, 10000)

    async def handle_bet(self, interaction, bet):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("自分のパネルのみ操作できます。", ephemeral=True)
            return
        if get_balance(self.user_id) < bet:
            await interaction.response.send_message("残高が足りません。", ephemeral=True)
            return

        async def chinchiro_judge(dice):
            dice = sorted(dice)
            # ピンゾロ
            if dice == [1, 1, 1]:
                return ("ピンゾロ", 100)
            # ゾロ目（2ゾロ～6ゾロ）
            if dice[0] == dice[1] == dice[2]:
                return (f"{dice[0]}ゾロ", 100 - dice[0])  # 数字が小さいほど強い
            # シゴロ
            if dice == [4, 5, 6]:
                return ("シゴロ", 90)
            # ヒフミ
            if dice == [1, 2, 3]:
                return ("ヒフミ", -10)
            # 通常の目
            if dice[0] == dice[1]:
                return (f"{dice[2]}の目", dice[2])
            if dice[1] == dice[2]:
                return (f"{dice[0]}の目", dice[0])
            # 役なし
            return ("役なし", 0)

        async def roll_until_yaku(name):
            for i in range(1, 4):
                roll_msg = await interaction.channel.send(f"{name} サイコロを振ります...（{i}回目）")
                await asyncio.sleep(1)
                dice = [random.randint(1, 6) for _ in range(3)]
                yaku, score = await chinchiro_judge(dice)
                await roll_msg.edit(content=f"{name} 🎲 {dice} → {yaku}")
                await asyncio.sleep(0.5)
                if yaku != "役なし":
                    return dice, yaku, score, i
            return dice, yaku, score, 3

        # ユーザー
        user_dice, user_yaku, user_score, user_try = await roll_until_yaku(interaction.user.mention)
        # BOT
        bot_dice, bot_yaku, bot_score, bot_try = await roll_until_yaku("BOT")

        # 役の強さ比較
        def yaku_rank(score):
            if score >= 90: return score  # ピンゾロ・ゾロ目・シゴロ
            if score > 0: return 10 + score  # 通常の目
            if score == 0: return 0  # 役なし
            if score == -10: return -10  # ヒフミ
            return -100

        user_rank = yaku_rank(user_score)
        bot_rank = yaku_rank(bot_score)

        msg = (
            f"🎲 {interaction.user.mention} のちんちろ！\n"
            f"あなた: {user_dice} → {user_yaku}\n"
            f"BOT: {bot_dice} → {bot_yaku}\n"
        )

        # 勝敗判定
        if user_rank > bot_rank:
            # 勝ち
            payout = bet * (user_score if user_score > 0 and user_score < 90 else 2)
            if user_score >= 90:  # ピンゾロ・ゾロ目・シゴロ
                if user_score == 100:
                    payout = bet * 5
                elif user_score >= 90:
                    payout = bet * (5 if user_score == 100 else 3 if user_score == 99 else 2)
            add_balance(interaction.user.id, payout)
            msg += f"🎉 勝ち！{payout} velt獲得！"
        elif user_rank < bot_rank:
            # 負け
            if bot_score == -10:  # ヒフミ
                loss = bet * 2
                if get_balance(interaction.user.id) < loss:
                    await interaction.response.send_message("ヒフミで2倍払う必要がありますが、残高が足りません。", ephemeral=True)
                    return
                add_balance(interaction.user.id, -loss)
                msg += f"😢 ヒフミで負け… {loss} velt失いました。"
            elif bot_score >= 90:
                if bot_score == 100:
                    loss = bet * 5
                elif bot_score == 99:
                    loss = bet * 3
                else:
                    loss = bet * 2
                add_balance(interaction.user.id, -loss)
                msg += f"😢 ゾロ目/シゴロで負け… {loss} velt失いました。"
            elif bot_score > 0:
                loss = bet * bot_score
                add_balance(interaction.user.id, -loss)
                msg += f"😢 負け… {loss} velt失いました。"
            else:
                add_balance(interaction.user.id, -bet)
                msg += f"😢 負け… {bet} velt失いました。"
        else:
            msg += "🤝 引き分け！"

        await interaction.channel.send(msg)

@tree.command(name="ちんちろ", description="veltでちんちろ勝負（BOT対戦）", guild=discord.Object(id=GUILD_ID))
async def ちんちろ(interaction: discord.Interaction):
    view = ChinchiroView(interaction.user.id)
    await interaction.response.send_message("掛け金を選んでください！", view=view, ephemeral=True)

# --- ブラックジャック ---
class BlackjackGameView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id

    @discord.ui.button(label="1000 velt", style=discord.ButtonStyle.primary)
    async def bet_1000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_game(interaction, 1000)

    @discord.ui.button(label="5000 velt", style=discord.ButtonStyle.success)
    async def bet_5000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_game(interaction, 5000)

    @discord.ui.button(label="10000 velt", style=discord.ButtonStyle.danger)
    async def bet_10000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_game(interaction, 10000)

    async def start_game(self, interaction, bet):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("自分のパネルのみ操作できます。", ephemeral=True)
            return
        if get_balance(self.user_id) < bet:
            await interaction.response.send_message("残高が足りません。", ephemeral=True)
            return
        # 新しいViewでゲーム本体を開始
        view = BlackjackPlayView(self.user_id, bet)
        await interaction.response.edit_message(content="ゲーム開始！", view=None)
        await view.show_state(interaction.channel, interaction.user)

class BlackjackPlayView(discord.ui.View):
    def __init__(self, user_id, bet):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.bet = bet
        self.player_cards = [random.randint(1, 10), random.randint(1, 10)]
        self.bot_cards = [random.randint(1, 10), random.randint(1, 10)]
        self.finished = False

    def hand_str(self, cards):
        return f"{cards}（合計: {sum(cards)}）"

    async def show_state(self, channel, user):
        await channel.send(
            f"{user.mention} の手札: {self.hand_str(self.player_cards)}\n"
            f"BOTの手札: [{self.bot_cards[0]}, ?]\n"
            "「もう一枚引く」か「スタンド」を選んでください。",
            view=self
        )

    @discord.ui.button(label="もう一枚引く", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id or self.finished:
            await interaction.response.send_message("自分のパネルのみ操作できます。", ephemeral=True)
            return
        # 演出
        draw_msg = await interaction.channel.send(f"{interaction.user.mention} カードを引きます...")
        await asyncio.sleep(1)
        self.player_cards.append(random.randint(1, 10))
        await draw_msg.edit(content=f"{interaction.user.mention} の手札: {self.hand_str(self.player_cards)}")
        if sum(self.player_cards) > 21:
            await self.finish(interaction)
        else:
            await self.show_state(interaction.channel, interaction.user)
            await interaction.response.defer()

    @discord.ui.button(label="スタンド", style=discord.ButtonStyle.success)
    async def stand_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id or self.finished:
            await interaction.response.send_message("自分のパネルのみ操作できます。", ephemeral=True)
            return
        self.finished = True
        await self.finish(interaction)

    async def finish(self, interaction):
        self.finished = True
        # BOTは17以上になるまで引く
        while sum(self.bot_cards) < 17:
            draw_msg = await interaction.channel.send("BOT カードを引きます...")
            await asyncio.sleep(1)
            self.bot_cards.append(random.randint(1, 10))
            await draw_msg.edit(content=f"BOTの手札: {self.hand_str(self.bot_cards)}")
        player_total = sum(self.player_cards)
        bot_total = sum(self.bot_cards)
        msg = (
            f"{interaction.user.mention} の手札: {self.hand_str(self.player_cards)}\n"
            f"BOTの手札: {self.hand_str(self.bot_cards)}\n"
        )
        if player_total > 21:
            add_balance(self.user_id, -self.bet)
            msg += f"バースト！{self.bet} velt失いました。"
        elif bot_total > 21 or player_total > bot_total:
            add_balance(self.user_id, self.bet)
            msg += f"🎉 勝ち！{self.bet} velt獲得！"
        elif player_total < bot_total:
            add_balance(self.user_id, -self.bet)
            msg += f"😢 負け… {self.bet} velt失いました。"
        else:
            msg += "🤝 引き分け！"
        await interaction.channel.send(msg)

@tree.command(name="ブラックジャック", description="veltでブラックジャック（BOT対戦）", guild=discord.Object(id=GUILD_ID))
async def ブラックジャック(interaction: discord.Interaction):
    view = BlackjackGameView(interaction.user.id)
    await interaction.response.send_message("掛け金を選んでください！", view=view, ephemeral=True)

@bot.event
async def on_ready():
    try:
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"Slash commands synced: {len(synced)}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    print(f"Bot is ready. Logged in as {bot.user}")

# Bot起動時に残高を読み込む
load_balances()

# /リセットコマンド（管理者のみ：全員の残高を0にする）
@tree.command(name="リセット", description="全員のvelt残高を0にリセット（管理者のみ）", guild=discord.Object(id=GUILD_ID))
async def リセット(interaction: discord.Interaction):
    if interaction.user.id not in VELT_ADMIN_IDS:
        await interaction.response.send_message("権限がありません。", ephemeral=True)
        return
    for uid in list(velt_balances.keys()):
        velt_balances[uid] = 0
    save_balances()
    await interaction.response.send_message("全員のvelt残高を0にリセットしました。", ephemeral=True)
    # ログチャンネルにも通知
    log_channel = bot.get_channel(VELT_LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"{interaction.user.mention} が全員のvelt残高をリセットしました。")

@bot.event
async def on_message(message):
    VIRTUAL_CRYPTO_CHANNEL_ID = 1397899059146264637
    TARGET_USER_ID = 1386993985691586694
    TARGET_USERNAME = "loser.sub"

    # メッセージ本文またはEmbedのdescriptionを取得
    content = message.content
    if not content and message.embeds:
        content = message.embeds[0].description or ""

    print(f"on_message: {content}")

    if message.channel.id == VIRTUAL_CRYPTO_CHANNEL_ID:
        import re
        m = re.search(
            r"<@!?([^\s>]+)>から<@!?([^\s>]+)>へ\*\*(\d+)\*\* `velt`送金されました。",
            content
        )
        if m:
            sender = m.group(1)
            receiver = m.group(2)
            amount = int(m.group(3))
            # --- ここから下は今まで通り ---
            is_target = False
            if receiver.isdigit() and int(receiver) == TARGET_USER_ID:
                is_target = True
            elif receiver == TARGET_USERNAME or receiver == f"@{TARGET_USERNAME}":
                is_target = True
            else:
                member = discord.utils.find(
                    lambda m: (
                        str(m.id) == receiver or
                        m.name == receiver or
                        (m.nick and m.nick == receiver) or
                        m.display_name == receiver
                    ),
                    message.guild.members
                )
                if member and member.id == TARGET_USER_ID:
                    is_target = True

            if is_target:
                try:
                    sender_id = int(sender)
                except ValueError:
                    member = discord.utils.find(
                        lambda m: (
                            m.name == sender or
                            (m.nick and m.nick == sender) or
                            m.display_name == sender
                        ),
                        message.guild.members
                    )
                    sender_id = member.id if member else None
                if sender_id:
                    add_balance(sender_id, amount)
                    await message.channel.send(f"<@{sender_id}> に {amount} velt を移行しました。")
                    log_channel = bot.get_channel(VELT_LOG_CHANNEL_ID)
                    if log_channel:
                        await log_channel.send(f"【発行ログ】<@{sender_id}> に {amount} velt を発行（バーチャルクリプト送金検知）")
    await bot.process_commands(message)

if __name__ == "__main__":
    bot.run(TOKEN)