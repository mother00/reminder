import json
import re
import asyncio
import datetime
import discord
import datetime, calendar
from discord.ext import commands

def get_next_fixed_time(day_time: str):
    # 例: "Mon 12:30" / "Thu 20:00"
    day_map = {
        "Mon": 0, "Tue": 1, "Wed": 2,
        "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6
    }

    day, time_str = day_time.split()
    hour, minute = map(int, time_str.split(":"))

    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_ahead = (day_map[day] - now.weekday()) % 7
    if days_ahead == 0 and target < now:
        days_ahead = 7
    target += datetime.timedelta(days=days_ahead)

    # 🔔 通知を5分前に
    notify_time = target - datetime.timedelta(minutes=5)
    return notify_time

TOKEN = "MTQzNDc5ODc4MTM1MzY4OTEyOA.Glza6i.6yvLt_7mNDwQos9CKm1SS2nK2zSqm3VY_SPjEk"
DATA_FILE = "reminders.json"
BOSS_FILE = "boss_assets.json"

# ---- サーバー別データ管理 ----
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_guild_reminders(guild_id):
    import builtins  # ← 安全に組み込み型 list を参照できるようにする
    data = load_json(DATA_FILE, {})

    # 旧形式（リスト型）にも対応
    if isinstance(data, builtins.list):
        return data

    # 新形式（辞書型）
    return data.get(str(guild_id), [])

def save_guild_reminders(guild_id, reminders):
    data = load_data()
    data[str(guild_id)] = reminders
    save_data(data)


# ---- 設定（変えたい時はここだけ） ----
PRE_NOTIFY_MINUTES = 5   # 5分前に通知（0にすればぴったり時刻）

# ---- JSON I/O ----
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_boss_assets():
    return load_json(BOSS_FILE, [])

# ---- Discord ----
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


class MyBot(commands.Bot):
    def __init__(self, **kwargs):
        kwargs.setdefault("help_command", None) 
        super().__init__(**kwargs)
        self.reminders = load_json(DATA_FILE, [])
        self.boss_assets = load_boss_assets()  # ← ここが重要

    def save_data(self):
        save_json(DATA_FILE, self.reminders)

    async def start_reminder_loop(self):
        await self.wait_until_ready()
        while True:
            now = datetime.datetime.now().timestamp()
            fired = False

            # 通知処理
            # 🔁 サーバーごとのリマインダー全てを集約
            all_reminders = []
            if isinstance(self.reminders, dict):
                for v in self.reminders.values():
                    all_reminders.extend(v)
            else:
                all_reminders = self.reminders

            for r in all_reminders[:]:
                # 対応するボスを検索
                boss_name = r["name"].strip()
                boss = next((b for b in self.boss_assets if b["name"].strip() == boss_name), None)
                # 固定ボスはスキップ
                if boss and boss.get("type") == "fixed":
                        continue  
                if now >= r["next_time"]:
                    channel = self.get_channel(r["channel_id"])
                    if channel:
                        await channel.send(f"🔔 リマインド: {r['message']}")
                    if boss:
                        # 出現時刻を通知5分後に更新
                        boss["last_spawn"] = now + 300
                        save_json(BOSS_FILE, self.boss_assets)
                    fired = True
                    # 🔁 どのサーバーのリストから削除するか探す
                    if isinstance(self.reminders, dict):
                        for gid, lst in self.reminders.items():
                            if r in lst:
                                lst.remove(r)
                                break
                    else:
                        self.reminders.remove(r)

            if fired:
                self.save_data()
            # 🔁 通知から1時間経過したボスの自動再登録チェック
            for boss in self.boss_assets:
                if boss.get("type") == "fixed":
                    continue  # 固定ボスは除外

                last_spawn = boss.get("last_spawn")
                if not last_spawn:
                    continue

                # 1時間経過 & まだ登録されていない
                if now - last_spawn >= 3600:
                    already = next((r for r in self.reminders if r["name"] == boss["name"]), None)
                    if not already:
                        next_time = last_spawn + boss["interval"] - 300  # 通知5分前
                        new_r = {
                            "channel_id": boss["channel_id"],
                            "interval": boss["interval"],
                            "message": boss["message"],
                            "level": boss["level"],
                            "name": boss["name"],
                            "location": boss["location"],
                            "next_time": next_time
                        }
                        self.reminders.append(new_r)
                        self.save_data()
                        print(f"🕒 自動再登録: {boss['name']} をリマインダーに追加した。")

            await asyncio.sleep(1)


    async def setup_hook(self):
        asyncio.create_task(self.start_reminder_loop())
        self.register_fixed_bosses()  # ← 修正済み呼び出し
        # 再起動時の復旧処理
        now = datetime.datetime.now().timestamp()
        for boss in self.boss_assets:
            if "last_spawn" in boss and boss["last_spawn"]:
                next_time = boss["last_spawn"] + boss["interval"] - 300
                if next_time > now:
                    new_r = {
                        "channel_id": boss["channel_id"],
                        "interval": boss["interval"],
                        "message": boss["message"],
                        "level": boss["level"],
                        "name": boss["name"],
                        "location": boss["location"],
                        "next_time": next_time
                    }
                    # 🔧 全サーバー分のリマインダーを集約してチェック
                    all_reminders = []
                    if isinstance(self.reminders, dict):
                        for v in self.reminders.values():
                            all_reminders.extend(v)
                    else:
                        all_reminders = self.reminders

                    if not any(r["name"] == boss["name"] for r in all_reminders):
                        guild_id = "global"
                        if isinstance(self.reminders, dict):
                            self.reminders.setdefault(guild_id, []).append(new_r)
                        else:
                            self.reminders.append(new_r)
        self.save_data()


    def register_fixed_bosses(self):
        for b in self.boss_assets:
            if b.get("type") == "fixed":
                for fixed_time in b.get("fixed_times", []):
                    notify_time = get_next_fixed_time(fixed_time)
                    new_reminder = {
                        "channel_id": b["channel_id"],
                        "interval": 7 * 24 * 3600,
                        "message": b["message"],
                        "level": b["level"],
                        "name": b["name"],
                        "location": b["location"],
                        "next_time": notify_time.timestamp()
                    }
                     # 🔍 全リマインダーを集約
                all_reminders = []
                if isinstance(self.reminders, dict):
                    for v in self.reminders.values():
                        all_reminders.extend(v)
                else:
                    all_reminders = self.reminders

                # 🔁 重複登録を防ぐ
                if not any(
                    r["name"] == b["name"] and abs(r["next_time"] - notify_time.timestamp()) < 60
                    for r in all_reminders
                ):
                    # サーバー別に登録
                    guild_id = str(b.get("guild_id", "global"))  # サーバーIDが未設定ならglobal扱い
                    if isinstance(self.reminders, dict):
                        self.reminders.setdefault(guild_id, []).append(new_reminder)
                    else:
                        self.reminders.append(new_reminder)

        self.save_data()
        


bot = MyBot(command_prefix="!", intents=intents)
# ---- コマンド ----
@bot.command()
async def add(ctx, interval: str, level: int, name: str, location: str, *, message: str):
    unit = interval[-1]
    num = int(interval[:-1])
    if unit == "s":
        seconds = num
    elif unit == "m":
        seconds = num * 60
    elif unit == "h":
        seconds = num * 3600
    else:
        await ctx.send("s / m / h で指定してくれ。例: 10m")
        return

    next_time = datetime.datetime.now().timestamp() + seconds
    if PRE_NOTIFY_MINUTES > 0:
        next_time -= PRE_NOTIFY_MINUTES * 60

    bot.reminders.append({
        "channel_id": ctx.channel.id,
        "interval": seconds,
        "message": message,
        "level": level,
        "name": name,
        "location": location,
        "next_time": next_time,
    })
    bot.save_data()
    await ctx.send(f"✅ 登録 → {interval}ごとに『{message}』 / {level}LV {name} at {location}")

@bot.command()
async def list(ctx):
    guild_id = str(ctx.guild.id)
    reminders = get_guild_reminders(guild_id)

    if not reminders:
        await ctx.send("登録されてないな。")
        return

    sorted_list = sorted(reminders, key=lambda x: x["next_time"])
    lines = []
    now_dt = datetime.datetime.now()

    for i, r in enumerate(sorted_list, start=1):
        reminder_time = datetime.datetime.fromtimestamp(r["next_time"])
        time_str = reminder_time.strftime("%H:%M:%S")

        delta_seconds = int((reminder_time - now_dt).total_seconds())
        if delta_seconds < 0:
            delta_seconds = 0
        if delta_seconds < 60:
            after_str = f"[{delta_seconds}秒後](http://invalidlink.com)"
        elif delta_seconds < 3600:
            m = delta_seconds // 60
            s = delta_seconds % 60
            after_str = f"[{m}分{s}秒後](http://invalidlink.com)"
        elif delta_seconds < 5400:  # 1時間半以内 → リンク付き HH:MM
            h = delta_seconds // 3600
            m = (delta_seconds % 3600) // 60
            after_str = f"[{h:02}:{m:02}後](http://invalidlink.com)"
        elif delta_seconds < 5 * 3600:  # 1.5時間〜5時間未満 → HH:MM（リンクなし）
            h = delta_seconds // 3600
            m = (delta_seconds % 3600) // 60
            after_str = f"{h:02}:{m:02}後"
        elif delta_seconds < 86400:     # 5時間以上〜24時間未満 → 時間のみ
            h = delta_seconds // 3600
            after_str = f"{h}時間後"
        else:
            d = delta_seconds // 86400
            after_str = f"{d}日後"

        lines.append(
            f"    **{r['level']}LV**   ***{r['name']}***      {r['location']}        ⌚{time_str}    （{after_str}）        ⋯    {i}"
        )

    await ctx.send("🕒 *時刻順リスト*\n" + "\n".join(lines))

@bot.command()
async def remove(ctx, index: int):
    guild_id = str(ctx.guild.id)
    reminders = get_guild_reminders(guild_id)
    index -= 1

    sorted_list = sorted(reminders, key=lambda x: x["next_time"])

    if 0 <= index < len(sorted_list):
        removed = sorted_list[index]
        reminders.remove(removed)
        save_guild_reminders(guild_id, reminders)
        await ctx.send(f"❌ 削除 → {removed['level']}LV {removed['name']} ({removed['location']})")
    else:
        await ctx.send("指定された番号が無効です。リストにある番号を入力してください。")

# ---- エイリアス登録（!a → アラネオ など） ----
boss_alias = {
    "a": "アラネオ",
    "be": "ベナトゥス",
    "bi": "ビオレント",
    "e": "エゴ",
    "ku": "クレメンティス",
    "ri": "リベラ",
}

@bot.command()
async def help(ctx):
    
    help_text = (
        "📘 **コマンド一覧**\n\n"
    
        "   !a             → アラネオ討伐登録\n"
        "   !be 0900       → ベナトゥス 09:00登録\n"
        "   !list          → 登録済みリマインダー一覧を表示\n"
        "   !remove 2      → リスト番号2を削除\n"
        "   !help          → このヘルプを表示\n"
       
    )
    await ctx.send(help_text)



async def add_reminder_from_asset(ctx, boss_name: str, time_str: str = None):
    boss = next((b for b in bot.boss_assets if b["name"].strip() == boss_name.strip()), None)
    if not boss:
        await ctx.send(f"❌ ボス「{boss_name}」はアセットにないよ。")
        return

    interval = int(boss.get("interval", 0))
    if interval <= 0:
        await ctx.send("⚠️ interval が不正（または未設定）だな。boss_assets.json を見直して。")
        return

    now = datetime.datetime.now()
    base_time = now  # デフォは“今”

    if time_str is not None:
        ts = str(time_str).strip().replace("：", ":")
        # 4桁数字（例：2000）を20:00形式に変換
        if re.fullmatch(r"^\d{4}$", ts):
            ts = f"{ts[:2]}:{ts[2:]}"
        # コロン付き or 変換済みフォーマットを処理
        if re.fullmatch(r"^([01]?\d|2[0-3]):[0-5]\d$", ts):
            input_time = datetime.datetime.strptime(ts, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            if input_time > now:
                input_time -= datetime.timedelta(days=1)  # 翌日補正
            base_time = input_time


    spawn_time = base_time + datetime.timedelta(seconds=interval)
    notify_time = spawn_time - datetime.timedelta(minutes=PRE_NOTIFY_MINUTES)

    new_rem = {
        "channel_id": boss["channel_id"],
        "interval": interval,
        "message": boss["message"],
        "level": boss["level"],
        "name": boss["name"],
        "location": boss["location"],
        "next_time": notify_time.timestamp(),
    }

    # 同名ボスは上書き
    if isinstance(bot.reminders, dict):
    # 各サーバーごとのリストをまとめて処理
        for gid, lst in bot.reminders.items():
            bot.reminders[gid] = [r for r in lst if r.get("name") != boss["name"]]
    else:
        bot.reminders = [r for r in bot.reminders if r.get("name") != boss["name"]]
        guild_id = str(ctx.guild.id) if ctx.guild else "dm"
    # ---- 安全にギルドIDを決定 ----
    if ctx.guild is not None:
        guild_id = str(ctx.guild.id)
    else:
        guild_id = "dm"  # DMチャット時のフォールバック

    # ---- 追加処理 ----
    if isinstance(bot.reminders, dict):
        bot.reminders.setdefault(guild_id, []).append(new_rem)
    else:
        bot.reminders.append(new_rem)
    bot.save_data()

    await ctx.send(
        f"✅ {boss_name} を登録しました！（{PRE_NOTIFY_MINUTES}分前通知）\n"
    )


def register_alias_command(alias: str, boss_name: str):
    @bot.command(name=alias)
    async def _cmd(ctx, time_str: str = None):
        await add_reminder_from_asset(ctx, boss_name, time_str)

for alias, name in boss_alias.items():
    register_alias_command(alias, name)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

bot.run(TOKEN)