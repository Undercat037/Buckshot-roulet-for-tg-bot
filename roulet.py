import random
import time
import string
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальные переменные
game_states = {}
multiplayer_games = {}
lobby_states = {}

# Предметы и их эмодзи
ITEMS = {
    "magnifier": {"emoji": "🔍", "name": "Лупа"},
    "knife": {"emoji": "🔪", "name": "Нож"},
    "cigarettes": {"emoji": "🚬", "name": "Сигареты"},
    "beer": {"emoji": "🍺", "name": "Пиво"},
    "handcuffs": {"emoji": "⛓", "name": "Наручники"},
    "adrenaline": {"emoji": "⚡️💉", "name": "Адреналин"},
    "phone": {"emoji": "📱", "name": "Телефон"},
    "reverse": {"emoji": "🖲", "name": "Реверс"}
}

def generate_game_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def create_cartridges():
    total = random.randint(4, 8)
    cartridges = []
    live = 0
    blank = 0
    live_chance = 0.66  # Шанс, что патрон будет боевым (66%)
    
    for _ in range(total):
        is_live = random.random() < live_chance
        cartridges.append(is_live)
        if is_live:
            live += 1
        else:
            blank += 1
    
    # Гарантируем хотя бы один холостой патрон
    if blank == 0:
        idx = random.randint(0, total - 1)
        cartridges[idx] = False
        live -= 1
        blank += 1
    
    random.shuffle(cartridges)
    return cartridges, live, blank

def create_initial_items():
    return random.sample(list(ITEMS.keys()), 2)

def add_item(current_items):
    current_items.append(random.choice(list(ITEMS.keys())))
    return current_items

def format_items(items):
    if not items:
        return "Нет"
    return ", ".join(f"{ITEMS[item]['emoji']} {ITEMS[item]['name']}" for item in items)

def get_user_mention(user, for_button=False):
    chat_id = user.id
    if user.username:
        name = user.username
    else:
        name = user.first_name
        if user.last_name:
            name += f" {user.last_name}"
    if for_button:
        return name  # Для кнопок возвращаем чистое имя без Markdown
    return f"[{name}](tg://user?id={chat_id})"

def build_lobby_keyboard(mode=None):
    if mode == "multiplayer":
        return ReplyKeyboardMarkup([["Создать комнату", "Присоединиться"], ["Назад"]], resize_keyboard=True, one_time_keyboard=False)
    return ReplyKeyboardMarkup([["Начать игру", "Мультиплеер"]], resize_keyboard=True, one_time_keyboard=False)

def build_game_keyboard(items, is_knife=False, mode="single", game_state=None, current_player=None):
    actions = []
    if mode == "single":
        actions.append(["В Дилера", "В Себя"] if not is_knife else ["В Дилера", "В Себя"])
    else:
        # В мультиплеере показываем живых игроков (кроме текущего) с чистыми именами
        if not is_knife:
            alive_players = [pid for pid in game_state["players"] if game_state["players"][pid]["lives"] > 0 and pid != current_player]
            for pid in alive_players:
                # Извлекаем чистое имя без Markdown
                player = game_state["players"][pid]
                user = type('obj', (object,), {'id': player['id'], 'username': player['mention'].split('[')[1].split(']')[0] if '[' in player['mention'] else None, 'first_name': player['mention'].split('[')[1].split(']')[0] if '[' in player['mention'] else player['mention'], 'last_name': None})
                actions.append([get_user_mention(user, for_button=True)])
            actions.append(["В Себя"])
        else:
            alive_players = [pid for pid in game_state["players"] if game_state["players"][pid]["lives"] > 0 and pid != current_player]
            for pid in alive_players:
                player = game_state["players"][pid]
                user = type('obj', (object,), {'id': player['id'], 'username': player['mention'].split('[')[1].split(']')[0] if '[' in player['mention'] else None, 'first_name': player['mention'].split('[')[1].split(']')[0] if '[' in player['mention'] else player['mention'], 'last_name': None})
                actions.append([get_user_mention(user, for_button=True)])
            actions.append(["В Себя"])
    for item in items:
        actions.append([f"{ITEMS[item]['emoji']} {ITEMS[item]['name']}"])
    return ReplyKeyboardMarkup(actions, resize_keyboard=True, one_time_keyboard=False)

def build_multiplayer_room_keyboard(creator_id, chat_id, player_count):
    buttons = []
    if chat_id == creator_id and player_count >= 2:
        buttons.append(["Начать игру"])
    buttons.append(["Покинуть комнату"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    lobby_states[chat_id] = {"mode": "main", "action": None, "game_code": None}
    await update.message.reply_text(
        "Добро пожаловать в Buckshot Roulette!\nВыберите режим:",
        reply_markup=build_lobby_keyboard(),
        parse_mode="Markdown"
    )

async def handle_lobby_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    action = update.message.text
    
    if chat_id not in lobby_states:
        await update.message.reply_text("Начните с /start.", reply_markup=ReplyKeyboardRemove())
        return
    
    lobby_state = lobby_states[chat_id]
    
    if lobby_state["mode"] == "room":
        await handle_room_action(update, context)
        return
    
    if action == "Начать игру" and lobby_state["mode"] == "main":
        await start_singleplayer(update, context, chat_id)
        del lobby_states[chat_id]
    elif action == "Мультиплеер" and lobby_state["mode"] == "main":
        lobby_state["mode"] = "multiplayer"
        await update.message.reply_text("Выберите действие:", reply_markup=build_lobby_keyboard("multiplayer"))
    elif action == "Назад" and lobby_state["mode"] == "multiplayer":
        lobby_state["mode"] = "main"
        await update.message.reply_text("Выберите режим:", reply_markup=build_lobby_keyboard())
    elif action == "Создать комнату" and lobby_state["mode"] == "multiplayer":
        await create_multiplayer_room(update, context, chat_id)
    elif action == "Присоединиться" and lobby_state["mode"] == "multiplayer":
        await update.message.reply_text("Введите код комнаты:", reply_markup=ReplyKeyboardRemove())
        lobby_state["action"] = "join"
    elif lobby_state["action"] == "join":
        await join_multiplayer_room(update, context, chat_id, action)
    else:
        await update.message.reply_text("Неверное действие! Выберите из меню.")

async def start_singleplayer(update, context, chat_id):
    game_state = {
        "player_lives": 5,
        "dealer_lives": 5,
        "player_items": create_initial_items(),
        "dealer_items": create_initial_items(),
        "cartridges": [],
        "live": 0,
        "blank": 0,
        "current_turn": "player",
        "extra_turn": False,
        "player_handcuffed": False,
        "dealer_handcuffed": False,
        "round_number": 1,
        "game_active": True,
        "mode": "single",
        "player_mention": get_user_mention(update.effective_user)
    }
    game_state["cartridges"], game_state["live"], game_state["blank"] = create_cartridges()
    game_states[chat_id] = game_state
    
    status = (
        f"=== Раунд {game_state['round_number']} ===\n"
        f"Жизни: {game_state['player_mention']} ({game_state['player_lives'] if game_state['player_lives'] > 2 else '???'} ⚡️) | "
        f"Дилер ({game_state['dealer_lives'] if game_state['dealer_lives'] > 2 else '???'} ⚡️)\n"
        f"Патроны: Боевых: {game_state['live']}, Холостых: {game_state['blank']}\n"
        f"Предметы {game_state['player_mention']}: {format_items(game_state['player_items'])}\n"
        f"Предметы дилера: {format_items(game_state['dealer_items'])}\n"
        f"Ход: {game_state['player_mention']}\n"
    )
    await update.message.reply_text(
        status + "Выберите действие:",
        reply_markup=build_game_keyboard(game_state["player_items"], mode="single"),
        parse_mode="Markdown"
    )

async def create_multiplayer_room(update, context, chat_id):
    game_code = generate_game_code()
    while game_code in multiplayer_games:
        game_code = generate_game_code()
    
    multiplayer_games[game_code] = {
        "players": [{"id": chat_id, "mention": get_user_mention(update.effective_user), "kicked": False}],
        "creator_id": chat_id,
        "state": None
    }
    lobby_states[chat_id]["mode"] = "room"
    lobby_states[chat_id]["game_code"] = game_code
    
    await update.message.reply_text(
        f"Комната создана! Код: **{game_code}**\n"
        f"Игроки: 1/10\n"
        f"Поделитесь кодом с друзьями. Нажмите 'Начать игру' для старта (нужно ≥2 игрока).",
        reply_markup=build_multiplayer_room_keyboard(chat_id, chat_id, 1),
        parse_mode="Markdown"
    )

async def join_multiplayer_room(update, context, chat_id, code):
    code = code.upper()
    if code not in multiplayer_games:
        await update.message.reply_text(
            "Неверный код комнаты! Попробуйте снова.",
            reply_markup=build_lobby_keyboard("multiplayer")
        )
        lobby_states[chat_id]["action"] = None
        return
    
    room = multiplayer_games[code]
    if len([p for p in room["players"] if not p["kicked"]]) >= 10:
        await update.message.reply_text(
            "Комната заполнена!",
            reply_markup=build_lobby_keyboard("multiplayer")
        )
        lobby_states[chat_id]["action"] = None
        return
    
    if any(p["id"] == chat_id for p in room["players"]):
        await update.message.reply_text(
            "Вы уже в этой комнате!",
            reply_markup=build_lobby_keyboard("multiplayer")
        )
        lobby_states[chat_id]["action"] = None
        return
    
    mention = get_user_mention(update.effective_user)
    room["players"].append({"id": chat_id, "mention": mention, "kicked": False})
    player_count = len([p for p in room["players"] if not p["kicked"]])
    
    kick_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"Кикнуть {mention}", callback_data=f"kick_{chat_id}_{code}")
    ]])
    await context.bot.send_message(
        room["creator_id"],
        f"{mention} присоединился к комнате {code}!",
        reply_markup=kick_keyboard,
        parse_mode="Markdown"
    )
    
    for player in room["players"]:
        if not player["kicked"]:
            await context.bot.send_message(
                player["id"],
                f"Комната {code}\nИгроки: {player_count}/10",
                reply_markup=build_multiplayer_room_keyboard(room["creator_id"], player["id"], player_count),
                parse_mode="Markdown"
            )
    
    lobby_states[chat_id]["mode"] = "room"
    lobby_states[chat_id]["game_code"] = code
    lobby_states[chat_id]["action"] = None

async def handle_room_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    action = update.message.text
    
    if chat_id not in lobby_states or lobby_states[chat_id]["mode"] != "room":
        await update.message.reply_text("Вы не в комнате! Используйте /start.", reply_markup=ReplyKeyboardRemove())
        return
    
    game_code = lobby_states[chat_id]["game_code"]
    if game_code not in multiplayer_games:
        await update.message.reply_text(
            "Комната не найдена! Создайте новую.",
            reply_markup=build_lobby_keyboard("multiplayer")
        )
        del lobby_states[chat_id]
        return
    
    room = multiplayer_games[game_code]
    
    if action == "Начать игру":
        if chat_id != room["creator_id"]:
            await update.message.reply_text("Только создатель может начать игру!")
            return
        active_players = [p for p in room["players"] if not p["kicked"]]
        if len(active_players) < 2:
            await update.message.reply_text("Нужно минимум 2 игрока для старта!")
            return
        await start_multiplayer_game(update, context, game_code, active_players)
        for player in active_players:
            del lobby_states[player["id"]]
    elif action == "Покинуть комнату":
        for player in room["players"]:
            if player["id"] == chat_id:
                player["kicked"] = True
                break
        player_count = len([p for p in room["players"] if not p["kicked"]])
        if player_count == 0:
            del multiplayer_games[game_code]
        else:
            for player in room["players"]:
                if not player["kicked"]:
                    await context.bot.send_message(
                        player["id"],
                        f"Игрок покинул комнату {game_code}\nИгроки: {player_count}/10",
                        reply_markup=build_multiplayer_room_keyboard(room["creator_id"], player["id"], player_count),
                        parse_mode="Markdown"
                    )
        del lobby_states[chat_id]
        await update.message.reply_text(
            "Вы покинули комнату.",
            reply_markup=build_lobby_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Неверное действие! Выберите из меню.")

async def kick_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    if len(data) != 3 or data[0] != "kick":
        return
    
    player_id = int(data[1])
    game_code = data[2]
    
    if game_code not in multiplayer_games:
        await query.message.reply_text("Комната не найдена!")
        return
    
    room = multiplayer_games[game_code]
    if query.from_user.id != room["creator_id"]:
        await query.message.reply_text("Только создатель может кикать игроков!")
        return
    
    for player in room["players"]:
        if player["id"] == player_id:
            player["kicked"] = True
            break
    
    player_count = len([p for p in room["players"] if not p["kicked"]])
    if player_count == 0:
        del multiplayer_games[game_code]
        for player in room["players"]:
            if player["id"] in lobby_states:
                del lobby_states[player["id"]]
                await context.bot.send_message(
                    player["id"],
                    "Комната закрыта.",
                    reply_markup=build_lobby_keyboard(),
                    parse_mode="Markdown"
                )
        return
    
    for player in room["players"]:
        if not player["kicked"]:
            await context.bot.send_message(
                player["id"],
                f"Игрок был исключён из комнаты {game_code}\nИгроки: {player_count}/10",
                reply_markup=build_multiplayer_room_keyboard(room["creator_id"], player["id"], player_count),
                parse_mode="Markdown"
            )
    
    if player_id in lobby_states:
        del lobby_states[player_id]
        await context.bot.send_message(
            player_id,
            "Вы были исключены из комнаты.",
            reply_markup=build_lobby_keyboard(),
            parse_mode="Markdown"
        )

async def start_multiplayer_game(update, context, game_code, players):
    game_state = {
        "players": {
            f"player{i+1}": {
                "id": p["id"],
                "mention": p["mention"],
                "lives": 5,
                "items": create_initial_items(),
                "handcuffed": False
            } for i, p in enumerate(players)
        },
        "cartridges": [],
        "live": 0,
        "blank": 0,
        "current_turn": "player1",
        "extra_turn": False,
        "round_number": 1,
        "game_active": True,
        "mode": "multiplayer"
    }
    game_state["cartridges"], game_state["live"], game_state["blank"] = create_cartridges()
    
    for i, player in enumerate(players, 1):
        game_states[player["id"]] = game_state
    
    room = multiplayer_games.pop(game_code)
    
    status = (
        f"=== Раунд {game_state['round_number']} ===\n"
        f"Жизни: " + " | ".join(
            f"{game_state['players'][f'player{i}']['mention']} "
            f"({game_state['players'][f'player{i}']['lives'] if game_state['players'][f'player{i}']['lives'] > 2 else '???'} ⚡️)"
            for i in range(1, len(players) + 1)
        ) + "\n"
        f"Патроны: Боевых: {game_state['live']}, Холостых: {game_state['blank']}\n"
        f"Предметы: " + ", ".join(
            f"{game_state['players'][f'player{i}']['mention']}: "
            f"{format_items(game_state['players'][f'player{i}']['items'])}"
            for i in range(1, len(players) + 1)
        ) + "\n"
        f"Ход: {game_state['players']['player1']['mention']}\n"
    )
    
    for i, player in enumerate(players, 1):
        pid = f"player{i}"
        if pid == "player1":
            await context.bot.send_message(
                player["id"],
                status + "Ваш ход!",
                reply_markup=build_game_keyboard(game_state["players"][pid]["items"], mode="multiplayer", game_state=game_state, current_player=pid),
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                player["id"],
                status,
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="Markdown"
            )

async def handle_game_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    action = update.message.text
    
    if chat_id not in game_states:
        await update.message.reply_text("Игра не начата! Используйте /start.", reply_markup=ReplyKeyboardRemove())
        return
    
    game_state = game_states[chat_id]
    if not game_state["game_active"]:
        await update.message.reply_text(
            "Игра окончена! Начните новую с /start.",
            reply_markup=ReplyKeyboardRemove()
        )
        return
    
    if game_state["mode"] == "single":
        await process_singleplayer_action(update, context, chat_id, game_state, action)
    else:
        await process_multiplayer_action(update, context, chat_id, game_state, action)

async def process_singleplayer_action(update, context, chat_id, game_state, action):
    if game_state["current_turn"] != "player":
        await update.message.reply_text("Сейчас ход дилера! Ожидайте.", parse_mode="Markdown")
        return
    
    if game_state["player_handcuffed"]:
        await update.message.reply_text(
            f"{game_state['player_mention']} в наручниках и пропускает ход!",
            parse_mode="Markdown"
        )
        game_state["player_handcuffed"] = False
        game_state["current_turn"] = "dealer"
        time.sleep(0.3)
        await process_dealer_turn(update, context, chat_id, game_state)
        return
    
    game_state["extra_turn"] = False
    damage = context.user_data.get("pending_knife", 1)
    if action in ["В Дилера", "В Себя"] and "pending_knife" in context.user_data:
        action = "dealer" if action == "В Дилера" else "self"
    elif action == "В Дилера":
        action = "dealer"
    elif action == "В Себя":
        action = "self"
    else:
        for item_id, item in ITEMS.items():
            if action == f"{item['emoji']} {ITEMS[item_id]['name']}":
                action = item_id
                break
        else:
            await update.message.reply_text("Неверное действие! Выберите действие из меню.")
            return
    
    if action in ITEMS:
        if action not in game_state["player_items"]:
            await update.message.reply_text(
                f"У вас нет {ITEMS[action]['emoji']} {ITEMS[action]['name']}!",
                parse_mode="Markdown"
            )
            return
        game_state["player_items"].remove(action)
        
        if action == "magnifier":
            await update.message.reply_text(
                f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}: "
                f"Следующий патрон — {'боевой' if game_state['cartridges'][0] else 'холостой'}.",
                parse_mode="Markdown"
            )
            game_state["extra_turn"] = True
        elif action == "knife":
            await update.message.reply_text(
                f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}: "
                f"Следующий боевой патрон нанесёт 2 урона.",
                parse_mode="Markdown"
            )
            damage = 2
            context.user_data["pending_knife"] = damage
            await update.message.reply_text(
                "Теперь выберите:",
                reply_markup=build_game_keyboard([], is_knife=True, mode="single"),
                parse_mode="Markdown"
            )
            return
        elif action == "cigarettes":
            if game_state["player_lives"] < 5:
                game_state["player_lives"] += 1
                await update.message.reply_text(
                    f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}: +1 жизнь ⚡️!",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}, "
                    f"но жизни максимум!",
                    parse_mode="Markdown"
                )
            game_state["extra_turn"] = True
        elif action == "beer":
            if game_state["cartridges"]:
                shot = game_state["cartridges"].pop(0)
                game_state["live"] -= 1 if shot else 0
                game_state["blank"] -= 0 if shot else 1
                await update.message.reply_text(
                    f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}: "
                    f"Выброшен {'боевой' if shot else 'холостой'} патрон!",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}, "
                    f"но патронов нет!",
                    parse_mode="Markdown"
                )
            game_state["extra_turn"] = True
        elif action == "handcuffs":
            game_state["dealer_handcuffed"] = True
            await update.message.reply_text(
                f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}: "
                f"Дилер пропустит следующий ход!",
                parse_mode="Markdown"
            )
            game_state["extra_turn"] = True
        elif action == "adrenaline":
            if game_state["dealer_items"]:
                stolen_item = random.choice(game_state["dealer_items"])
                game_state["dealer_items"].remove(stolen_item)
                await update.message.reply_text(
                    f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}: "
                    f"Украден предмет {ITEMS[stolen_item]['emoji']} {ITEMS[stolen_item]['name']} у дилера!",
                    parse_mode="Markdown"
                )
                game_state["player_items"].append(stolen_item)
                await process_singleplayer_action(update, context, chat_id, game_state, stolen_item)
                return
            else:
                await update.message.reply_text(
                    f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}, "
                    f"но у дилера нет предметов!",
                    parse_mode="Markdown"
                )
            game_state["extra_turn"] = True
        elif action == "phone":
            if len(game_state["cartridges"]) > 1:
                index = random.randint(1, len(game_state["cartridges"]) - 1)
                future_shot = game_state["cartridges"][index]
                context.user_data["phone_cartridge"] = {"index": index + 1, "is_live": future_shot}
                await update.message.reply_text(
                    f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}: Патрон...",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("Посмотреть патрон", callback_data="view_cartridge")
                    ]]),
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}: "
                    f"Не повезло, патронов недостаточно!",
                    parse_mode="Markdown"
                )
            game_state["extra_turn"] = True
        elif action == "reverse":
            if game_state["cartridges"]:
                was_live = game_state["cartridges"][0]
                game_state["cartridges"][0] = not was_live
                game_state["live"] += -1 if was_live else 1
                game_state["blank"] += 1 if was_live else -1
                await update.message.reply_text(
                    f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}: "
                    f"Следующий патрон изменён на противоположный!",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"{game_state['player_mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}, "
                    f"но патронов нет!",
                    parse_mode="Markdown"
                )
            game_state["extra_turn"] = True
    
    time.sleep(0.3)
    
    if action in ["dealer", "self"]:
        if not game_state["cartridges"]:
            await start_new_round(update, context, chat_id, game_state, "single")
            return
        
        shot = game_state["cartridges"].pop(0)
        shot_type = "Боевой" if shot else "Холостой"
        game_state["live"] -= 1 if shot else 0
        game_state["blank"] -= 0 if shot else 1
        
        if action == "dealer":
            await update.message.reply_text(
                f"{game_state['player_mention']} стреляет в дилера... {shot_type} патрон!",
                parse_mode="Markdown"
            )
            time.sleep(0.8)
            if shot:
                game_state["dealer_lives"] -= damage
                await update.message.reply_text(
                    f"Дилер теряет {damage} {'жизни' if damage > 1 else 'жизнь'} ⚡️!",
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text(
                f"{game_state['player_mention']} стреляет в себя... {shot_type} патрон!",
                parse_mode="Markdown"
            )
            time.sleep(0.8)
            if shot:
                game_state["player_lives"] -= damage
                await update.message.reply_text(
                    f"{game_state['player_mention']} теряет {damage} {'жизни' if damage > 1 else 'жизнь'} ⚡️!",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"{game_state['player_mention']} получает дополнительный ход!",
                    parse_mode="Markdown"
                )
                game_state["extra_turn"] = True
        
        if "pending_knife" in context.user_data:
            del context.user_data["pending_knife"]
    
    if not game_state["cartridges"]:
        await start_new_round(update, context, chat_id, game_state, "single")
        return
    
    if game_state["player_lives"] <= 0 or game_state["dealer_lives"] <= 0:
        await end_game(update, context, chat_id, game_state, "single")
        return
    
    if game_state["extra_turn"]:
        status = (
            f"Жизни: {game_state['player_mention']} "
            f"({game_state['player_lives'] if game_state['player_lives'] > 2 else '???'} ⚡️) | "
            f"Дилер ({game_state['dealer_lives'] if game_state['dealer_lives'] > 2 else '???'} ⚡️)\n"
            f"Предметы {game_state['player_mention']}: {format_items(game_state['player_items'])}\n"
            f"Предметы дилера: {format_items(game_state['dealer_items'])}\n"
            f"Ход: {game_state['player_mention']}\n"
        )
        await update.message.reply_text(
            status + "Ваш ход!",
            reply_markup=build_game_keyboard(game_state["player_items"], mode="single"),
            parse_mode="Markdown"
        )
    else:
        game_state["current_turn"] = "dealer"
        await process_dealer_turn(update, context, chat_id, game_state)

async def process_multiplayer_action(update, context, chat_id, game_state, action):
    player_id = None
    for pid, p in game_state["players"].items():
        if p["id"] == chat_id:
            player_id = pid
            break
    
    if not player_id:
        await update.message.reply_text("Вы не в игре!", reply_markup=ReplyKeyboardRemove())
        return
    
    if game_state["current_turn"] != player_id:
        await update.message.reply_text("Сейчас не ваш ход! Ожидайте.", parse_mode="Markdown")
        return
    
    if game_state["players"][player_id]["handcuffed"]:
        await update.message.reply_text(
            f"{game_state['players'][player_id]['mention']} в наручниках и пропускает ход!",
            parse_mode="Markdown"
        )
        game_state["players"][player_id]["handcuffed"] = False
        game_state["current_turn"] = get_next_player(game_state, player_id)
        time.sleep(0.3)
        await update_multiplayer_status(update, context, game_state, game_state["current_turn"], player_id)
        return
    
    game_state["extra_turn"] = False
    damage = context.user_data.get("pending_knife", 1)
    
    # Проверяем, является ли действие выбором игрока для выстрела
    target_pid = None
    if "pending_knife" in context.user_data or action == "В Себя":
        if action == "В Себя":
            action = "self"
        else:
            # Проверяем, является ли action чистым именем игрока
            for pid, p in game_state["players"].items():
                user = type('obj', (object,), {'id': p['id'], 'username': p['mention'].split('[')[1].split(']')[0] if '[' in p['mention'] else None, 'first_name': p['mention'].split('[')[1].split(']')[0] if '[' in p['mention'] else p['mention'], 'last_name': None})
                if action == get_user_mention(user, for_button=True) and pid != player_id and p["lives"] > 0:
                    target_pid = pid
                    action = f"shoot:{pid}"
                    break
            if not target_pid and action != "self":
                await update.message.reply_text("Неверная цель! Выберите игрока из меню.", parse_mode="Markdown")
                return
    else:
        for pid, p in game_state["players"].items():
            user = type('obj', (object,), {'id': p['id'], 'username': p['mention'].split('[')[1].split(']')[0] if '[' in p['mention'] else None, 'first_name': p['mention'].split('[')[1].split(']')[0] if '[' in p['mention'] else p['mention'], 'last_name': None})
            if action == get_user_mention(user, for_button=True) and pid != player_id and p["lives"] > 0:
                target_pid = pid
                action = f"shoot:{pid}"
                break
    
    if action == "В Себя":
        action = "self"
    else:
        for item_id, item in ITEMS.items():
            if action == f"{item['emoji']} {item['name']}":
                action = item_id
                break
    
    if action in ITEMS:
        if action not in game_state["players"][player_id]["items"]:
            await update.message.reply_text(
                f"У вас нет {ITEMS[action]['emoji']} {ITEMS[action]['name']}!",
                parse_mode="Markdown"
            )
            return
        game_state["players"][player_id]["items"].remove(action)
        
        if action == "magnifier":
            msg = (
                f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}: "
                f"Следующий патрон — {'боевой' if game_state['cartridges'][0] else 'холостой'}."
            )
            for p in game_state["players"].values():
                await context.bot.send_message(p["id"], msg, parse_mode="Markdown")
            game_state["extra_turn"] = True
        elif action == "knife":
            msg = (
                f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} {ITEMS[action]['name']}: "
                f"Следующий боевой патрон нанесёт 2 урона."
            )
            for p in game_state["players"].values():
                await context.bot.send_message(p["id"], msg, parse_mode="Markdown")
            damage = 2
            context.user_data["pending_knife"] = damage
            await update.message.reply_text(
                "Теперь выберите:",
                reply_markup=build_game_keyboard([], is_knife=True, mode="multiplayer", game_state=game_state, current_player=player_id),
                parse_mode="Markdown"
            )
            return
        elif action == "cigarettes":
            if game_state["players"][player_id]["lives"] < 5:
                game_state["players"][player_id]["lives"] += 1
                msg = (
                    f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} "
                    f"{ITEMS[action]['name']}: +1 жизнь ⚡️!"
                )
            else:
                msg = (
                    f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} "
                    f"{ITEMS[action]['name']}, но жизни максимум!"
                )
            for p in game_state["players"].values():
                await context.bot.send_message(p["id"], msg, parse_mode="Markdown")
            game_state["extra_turn"] = True
        elif action == "beer":
            if game_state["cartridges"]:
                shot = game_state["cartridges"].pop(0)
                game_state["live"] -= 1 if shot else 0
                game_state["blank"] -= 0 if shot else 1
                msg = (
                    f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} "
                    f"{ITEMS[action]['name']}: Выброшен {'боевой' if shot else 'холостой'} патрон!"
                )
            else:
                msg = (
                    f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} "
                    f"{ITEMS[action]['name']}, но патронов нет!"
                )
            for p in game_state["players"].values():
                await context.bot.send_message(p["id"], msg, parse_mode="Markdown")
            game_state["extra_turn"] = True
        elif action == "handcuffs":
            next_player = get_next_player(game_state, player_id)
            game_state["players"][next_player]["handcuffed"] = True
            msg = (
                f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} "
                f"{ITEMS[action]['name']}: {game_state['players'][next_player]['mention']} пропустит следующий ход!"
            )
            for p in game_state["players"].values():
                await context.bot.send_message(p["id"], msg, parse_mode="Markdown")
            game_state["extra_turn"] = True
        elif action == "adrenaline":
            opponent_id = get_next_player(game_state, player_id)
            if game_state["players"][opponent_id]["items"]:
                stolen_item = random.choice(game_state["players"][opponent_id]["items"])
                game_state["players"][opponent_id]["items"].remove(stolen_item)
                msg = (
                    f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} "
                    f"{ITEMS[action]['name']}: Украден предмет {ITEMS[stolen_item]['emoji']} "
                    f"{ITEMS[stolen_item]['name']} у {game_state['players'][opponent_id]['mention']}!"
                )
                for p in game_state["players"].values():
                    await context.bot.send_message(p["id"], msg, parse_mode="Markdown")
                game_state["players"][player_id]["items"].append(stolen_item)
                await process_multiplayer_action(update, context, chat_id, game_state, stolen_item)
                return
            else:
                msg = (
                    f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} "
                    f"{ITEMS[action]['name']}, но у {game_state['players'][opponent_id]['mention']} нет предметов!"
                )
                for p in game_state["players"].values():
                    await context.bot.send_message(p["id"], msg, parse_mode="Markdown")
            game_state["extra_turn"] = True
        elif action == "phone":
            if len(game_state["cartridges"]) > 1:
                index = random.randint(1, len(game_state["cartridges"]) - 1)
                future_shot = game_state["cartridges"][index]
                context.user_data["phone_cartridge"] = {"index": index + 1, "is_live": future_shot}
                msg = (
                    f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} "
                    f"{ITEMS[action]['name']}: Патрон..."
                )
                for p in game_state["players"].values():
                    if p["id"] == chat_id:
                        await context.bot.send_message(
                            p["id"],
                            msg,
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("Посмотреть патрон", callback_data="view_cartridge")
                            ]]),
                            parse_mode="Markdown"
                        )
                    else:
                        await context.bot.send_message(p["id"], msg, parse_mode="Markdown")
            else:
                msg = (
                    f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} "
                    f"{ITEMS[action]['name']}: Не повезло, патронов недостаточно!"
                )
                for p in game_state["players"].values():
                    await context.bot.send_message(p["id"], msg, parse_mode="Markdown")
            game_state["extra_turn"] = True
        elif action == "reverse":
            if game_state["cartridges"]:
                was_live = game_state["cartridges"][0]
                game_state["cartridges"][0] = not was_live
                game_state["live"] += -1 if was_live else 1
                game_state["blank"] += 1 if was_live else -1
                msg = (
                    f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} "
                    f"{ITEMS[action]['name']}: Следующий патрон изменён на противоположный!"
                )
            else:
                msg = (
                    f"{game_state['players'][player_id]['mention']} использует {ITEMS[action]['emoji']} "
                    f"{ITEMS[action]['name']}, но патронов нет!"
                )
            for p in game_state["players"].values():
                await context.bot.send_message(p["id"], msg, parse_mode="Markdown")
            game_state["extra_turn"] = True
    
    time.sleep(0.3)
    
    if action.startswith("shoot:") or action == "self":
        if not game_state["cartridges"]:
            await start_new_round(update, context, chat_id, game_state, "multiplayer")
            return
        
        shot = game_state["cartridges"].pop(0)
        shot_type = "Боевой" if shot else "Холостой"
        game_state["live"] -= 1 if shot else 0
        game_state["blank"] -= 0 if shot else 1
        
        if action.startswith("shoot:"):
            opponent_id = action.split(":")[1]
            msg1 = (
                f"{game_state['players'][player_id]['mention']} стреляет в "
                f"{game_state['players'][opponent_id]['mention']}... {shot_type} патрон!"
            )
            for p in game_state["players"].values():
                await context.bot.send_message(p["id"], msg1, parse_mode="Markdown")
            time.sleep(0.8)
            if shot:
                game_state["players"][opponent_id]["lives"] -= damage
                msg2 = (
                    f"{game_state['players'][opponent_id]['mention']} теряет "
                    f"{damage} {'жизни' if damage > 1 else 'жизнь'} ⚡️!"
                )
                for p in game_state["players"].values():
                    await context.bot.send_message(p["id"], msg2, parse_mode="Markdown")
        else:
            msg1 = (
                f"{game_state['players'][player_id]['mention']} стреляет в себя... {shot_type} патрон!"
            )
            for p in game_state["players"].values():
                await context.bot.send_message(p["id"], msg1, parse_mode="Markdown")
            time.sleep(0.8)
            if shot:
                game_state["players"][player_id]["lives"] -= damage
                msg2 = (
                    f"{game_state['players'][player_id]['mention']} теряет "
                    f"{damage} {'жизни' if damage > 1 else 'жизнь'} ⚡️!"
                )
                for p in game_state["players"].values():
                    await context.bot.send_message(p["id"], msg2, parse_mode="Markdown")
            else:
                msg2 = f"{game_state['players'][player_id]['mention']} получает дополнительный ход!"
                for p in game_state["players"].values():
                    await context.bot.send_message(p["id"], msg2, parse_mode="Markdown")
                game_state["extra_turn"] = True
        
        if "pending_knife" in context.user_data:
            del context.user_data["pending_knife"]
    
    if not game_state["cartridges"]:
        await start_new_round(update, context, chat_id, game_state, "multiplayer")
        return
    
    if any(p["lives"] <= 0 for p in game_state["players"].values()):
        await end_game(update, context, chat_id, game_state, "multiplayer")
        return
    
    if not game_state["extra_turn"]:
        game_state["current_turn"] = get_next_player(game_state, player_id)
    
    await update_multiplayer_status(update, context, game_state, game_state["current_turn"], player_id)

async def view_cartridge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.from_user.id
    if "phone_cartridge" not in context.user_data:
        await query.message.reply_text("Данные о патроне отсутствуют!", parse_mode="Markdown")
        return
    
    cartridge_data = context.user_data["phone_cartridge"]
    index = cartridge_data["index"]
    is_live = cartridge_data["is_live"]
    
    await query.message.reply_text(
        f"{index}-й патрон — {'боевой' if is_live else 'холостой'}.",
        parse_mode="Markdown"
    )
    
    # Удаляем данные после просмотра
    del context.user_data["phone_cartridge"]

def get_next_player(game_state, current_player):
    player_ids = sorted([pid for pid in game_state["players"] if game_state["players"][pid]["lives"] > 0])
    current_idx = player_ids.index(current_player)
    next_idx = (current_idx + 1) % len(player_ids)
    return player_ids[next_idx]

async def update_multiplayer_status(update, context, game_state, current_turn, current_player_id):
    status = (
        f"Жизни: " + " | ".join(
            f"{game_state['players'][f'player{i}']['mention']} "
            f"({game_state['players'][f'player{i}']['lives'] if game_state['players'][f'player{i}']['lives'] > 2 else '???'} ⚡️)"
            for i in range(1, len(game_state["players"]) + 1)
        ) + "\n"
        f"Предметы: " + ", ".join(
            f"{game_state['players'][f'player{i}']['mention']}: "
            f"{format_items(game_state['players'][f'player{i}']['items'])}"
            for i in range(1, len(game_state["players"]) + 1)
        ) + "\n"
        f"Ход: {game_state['players'][current_turn]['mention']}\n"
    )
    
    for pid, p in game_state["players"].items():
        if pid == current_turn:
            await context.bot.send_message(
                p["id"],
                status + "Ваш ход!",
                reply_markup=build_game_keyboard(p["items"], mode="multiplayer", game_state=game_state, current_player=pid),
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                p["id"],
                status,
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="Markdown"
            )

async def start_new_round(update, context, chat_id, game_state, mode):
    game_state["round_number"] += 1
    game_state["cartridges"], game_state["live"], game_state["blank"] = create_cartridges()
    
    if mode == "single":
        game_state["player_items"] = add_item(game_state["player_items"])
        game_state["dealer_items"] = add_item(game_state["dealer_items"])
        game_state["current_turn"] = "player"
        status = (
            f"=== Раунд {game_state['round_number']} ===\n"
            f"Жизни: {game_state['player_mention']} "
            f"({game_state['player_lives'] if game_state['player_lives'] > 2 else '???'} ⚡️) | "
            f"Дилер ({game_state['dealer_lives'] if game_state['dealer_lives'] > 2 else '???'} ⚡️)\n"
            f"Патроны: Боевых: {game_state['live']}, Холостых: {game_state['blank']}\n"
            f"Предметы {game_state['player_mention']}: {format_items(game_state['player_items'])}\n"
            f"Предметы дилера: {format_items(game_state['dealer_items'])}\n"
            f"Ход: {game_state['player_mention']}\n"
        )
        await update.message.reply_text(
            status + "Выберите действие:",
            reply_markup=build_game_keyboard(game_state["player_items"], mode="single"),
            parse_mode="Markdown"
        )
    else:
        for pid in game_state["players"]:
            game_state["players"][pid]["items"] = add_item(game_state["players"][pid]["items"])
        game_state["current_turn"] = "player1"
        status = (
            f"=== Раунд {game_state['round_number']} ===\n"
            f"Жизни: " + " | ".join(
                f"{game_state['players'][f'player{i}']['mention']} "
                f"({game_state['players'][f'player{i}']['lives'] if game_state['players'][f'player{i}']['lives'] > 2 else '???'} ⚡️)"
                for i in range(1, len(game_state["players"]) + 1)
            ) + "\n"
            f"Патроны: Боевых: {game_state['live']}, Холостых: {game_state['blank']}\n"
            f"Предметы: " + ", ".join(
                f"{game_state['players'][f'player{i}']['mention']}: "
                f"{format_items(game_state['players'][f'player{i}']['items'])}"
                for i in range(1, len(game_state["players"]) + 1)
            ) + "\n"
            f"Ход: {game_state['players']['player1']['mention']}\n"
        )
        for pid, p in game_state["players"].items():
            if pid == "player1":
                await context.bot.send_message(
                    p["id"],
                    status + "Ваш ход!",
                    reply_markup=build_game_keyboard(p["items"], mode="multiplayer", game_state=game_state, current_player=pid),
                    parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(
                    p["id"],
                    status,
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="Markdown"
                )

async def process_dealer_turn(update, context, chat_id, game_state):
    if not game_state["cartridges"]:
        await start_new_round(update, context, chat_id, game_state, "single")
        return
    
    if game_state["dealer_handcuffed"]:
        await update.message.reply_text(
            "Дилер в наручниках и пропускает ход!",
            parse_mode="Markdown"
        )
        game_state["dealer_handcuffed"] = False
        game_state["current_turn"] = "player"
        time.sleep(0.3)
        status = (
            f"Жизни: {game_state['player_mention']} "
            f"({game_state['player_lives'] if game_state['player_lives'] > 2 else '???'} ⚡️) | "
            f"Дилер ({game_state['dealer_lives'] if game_state['dealer_lives'] > 2 else '???'} ⚡️)\n"
            f"Предметы {game_state['player_mention']}: {format_items(game_state['player_items'])}\n"
            f"Предметы дилера: {format_items(game_state['dealer_items'])}\n"
            f"Ход: {game_state['player_mention']}\n"
        )
        await update.message.reply_text(
            status + "Выберите действие:",
            reply_markup=build_game_keyboard(game_state["player_items"], mode="single"),
            parse_mode="Markdown"
        )
        return
    
    game_state["extra_turn"] = False
    action, used_item = dealer_decision(
        game_state["live"], game_state["blank"], game_state["dealer_items"],
        game_state["cartridges"][0] if game_state["cartridges"] else None,
        game_state["player_handcuffed"], game_state["dealer_lives"]
    )
    time.sleep(0.3)
    
    if used_item:
        game_state["dealer_items"].remove(used_item)
        if used_item == "magnifier":
            await update.message.reply_text(
                f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}: "
                f"Следующий патрон — {'боевой' if game_state['cartridges'][0] else 'холостой'}.",
                parse_mode="Markdown"
            )
            await update.message.reply_text(
                f"Дилер выбирает: {'стрелять в игрока' if action == 'player' else 'стрелять в себя'}",
                parse_mode="Markdown"
            )
            game_state["extra_turn"] = True
        elif used_item == "knife":
            await update.message.reply_text(
                f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}: "
                f"Следующий боевой патрон нанесёт 2 урона.",
                parse_mode="Markdown"
            )
            await update.message.reply_text(
                "Дилер выбирает: стрелять в игрока",
                parse_mode="Markdown"
            )
            action = "player"
        elif used_item == "cigarettes":
            if game_state["dealer_lives"] < 5:
                game_state["dealer_lives"] += 1
                await update.message.reply_text(
                    f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}: +1 жизнь ⚡️!",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}, "
                    f"но жизни максимум!",
                    parse_mode="Markdown"
                )
            game_state["extra_turn"] = True
        elif used_item == "beer":
            if game_state["cartridges"]:
                shot = game_state["cartridges"].pop(0)
                game_state["live"] -= 1 if shot else 0
                game_state["blank"] -= 0 if shot else 1
                await update.message.reply_text(
                    f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}: "
                    f"Выброшен {'боевой' if shot else 'холостой'} патрон!",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}, "
                    f"но патронов нет!",
                    parse_mode="Markdown"
                )
            game_state["extra_turn"] = True
        elif used_item == "handcuffs":
            game_state["player_handcuffed"] = True
            await update.message.reply_text(
                f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}: "
                f"Игрок пропустит следующий ход!",
                parse_mode="Markdown"
            )
            game_state["extra_turn"] = True
        elif used_item == "adrenaline":
            if game_state["player_items"]:
                stolen_item = random.choice(game_state["player_items"])
                game_state["player_items"].remove(stolen_item)
                await update.message.reply_text(
                    f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}: "
                    f"Украден предмет {ITEMS[stolen_item]['emoji']} {ITEMS[stolen_item]['name']} "
                    f"у {game_state['player_mention']}!",
                    parse_mode="Markdown"
                )
                game_state["dealer_items"].append(stolen_item)
            else:
                await update.message.reply_text(
                    f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}, "
                    f"но у {game_state['player_mention']} нет предметов!",
                    parse_mode="Markdown"
                )
            game_state["extra_turn"] = True
        elif used_item == "phone":
            if len(game_state["cartridges"]) > 1:
                index = random.randint(1, len(game_state["cartridges"]) - 1)
                future_shot = game_state["cartridges"][index]
                context.user_data["phone_cartridge"] = {"index": index + 1, "is_live": future_shot}
                await update.message.reply_text(
                    f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}: Патрон...",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}: "
                    f"Не повезло, патронов недостаточно!",
                    parse_mode="Markdown"
                )
            game_state["extra_turn"] = True
        elif used_item == "reverse":
            if game_state["cartridges"]:
                was_live = game_state["cartridges"][0]
                game_state["cartridges"][0] = not was_live
                game_state["live"] += -1 if was_live else 1
                game_state["blank"] += 1 if was_live else -1
                await update.message.reply_text(
                    f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}: "
                    f"Следующий патрон изменён на противоположный!",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"Дилер использует {ITEMS[used_item]['emoji']} {ITEMS[used_item]['name']}, "
                    f"но патронов нет!",
                    parse_mode="Markdown"
                )
            game_state["extra_turn"] = True
    
    if not game_state["cartridges"]:
        await start_new_round(update, context, chat_id, game_state, "single")
        return
    
    damage = 2 if used_item == "knife" else 1
    
    if action in ["player", "self"]:
        if not game_state["cartridges"]:
            await start_new_round(update, context, chat_id, game_state, "single")
            return
        
        shot = game_state["cartridges"].pop(0)
        shot_type = "Боевой" if shot else "Холостой"
        game_state["live"] -= 1 if shot else 0
        game_state["blank"] -= 0 if shot else 1
        
        if action == "player":
            await update.message.reply_text(
                f"Дилер стреляет в {game_state['player_mention']}... {shot_type} патрон!",
                parse_mode="Markdown"
            )
            time.sleep(0.8)
            if shot:
                game_state["player_lives"] -= damage
                await update.message.reply_text(
                    f"{game_state['player_mention']} теряет {damage} {'жизни' if damage > 1 else 'жизнь'} ⚡️!",
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text(
                f"Дилер стреляет в себя... {shot_type} патрон!",
                parse_mode="Markdown"
            )
            time.sleep(0.8)
            if shot:
                game_state["dealer_lives"] -= damage
                await update.message.reply_text(
                    f"Дилер теряет {damage} {'жизни' if damage > 1 else 'жизнь'} ⚡️!",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    "Дилер получает дополнительный ход!",
                    parse_mode="Markdown"
                )
                game_state["extra_turn"] = True
    
    if not game_state["cartridges"]:
        await start_new_round(update, context, chat_id, game_state, "single")
        return
    
    if game_state["player_lives"] <= 0 or game_state["dealer_lives"] <= 0:
        await end_game(update, context, chat_id, game_state, "single")
        return
    
    if game_state["extra_turn"]:
        await process_dealer_turn(update, context, chat_id, game_state)
    else:
        game_state["current_turn"] = "player"
        status = (
            f"Жизни: {game_state['player_mention']} "
            f"({game_state['player_lives'] if game_state['player_lives'] > 2 else '???'} ⚡️) | "
            f"Дилер ({game_state['dealer_lives'] if game_state['dealer_lives'] > 2 else '???'} ⚡️)\n"
            f"Предметы {game_state['player_mention']}: {format_items(game_state['player_items'])}\n"
            f"Предметы дилера: {format_items(game_state['dealer_items'])}\n"
            f"Ход: {game_state['player_mention']}\n"
        )
        await update.message.reply_text(
            status + "Выберите действие:",
            reply_markup=build_game_keyboard(game_state["player_items"], mode="single"),
            parse_mode="Markdown"
        )

async def end_game(update, context, chat_id, game_state, mode):
    game_state["game_active"] = False
    if mode == "single":
        if game_state["player_lives"] > 0:
            await update.message.reply_text(
                f"=== Игра окончена ===\nПоздравляю! {game_state['player_mention']} победил!",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "=== Игра окончена ===\nДилер победил!",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="Markdown"
            )
        del game_states[chat_id]
    else:
        alive = [pid for pid, p in game_state["players"].items() if p["lives"] > 0]
        if len(alive) == 1:
            winner = alive[0]
            msg = (
                f"=== Игра окончена ===\n"
                f"Поздравляю! {game_state['players'][winner]['mention']} победил!"
            )
            for p in game_state["players"].values():
                await context.bot.send_message(
                    p["id"],
                    msg,
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="Markdown"
                )
            for p in game_state["players"].values():
                if p["id"] in game_states:
                    del game_states[p["id"]]
        elif len(alive) == 0:
            msg = "=== Игра окончена ===\nВсе игроки проиграли!"
            for p in game_state["players"].values():
                await context.bot.send_message(
                    p["id"],
                    msg,
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="Markdown"
                )
            for p in game_state["players"].values():
                if p["id"] in game_states:
                    del game_states[p["id"]]
        else:
            # Продолжаем игру, если больше одного игрока живы
            game_state["game_active"] = True
            await start_new_round(update, context, chat_id, game_state, "multiplayer")

def dealer_decision(live, blank, dealer_items, next_cartridge, player_handcuffed, dealer_lives):
    total = live + blank
    if total == 0:
        return "player", None
    live_prob = live / total if total > 0 else 0
    
    used_item = None
    if player_handcuffed:
        return None, None
    if "handcuffs" in dealer_items and live_prob > 0.5 and total > 2:
        used_item = "handcuffs"
        return None, used_item
    if "beer" in dealer_items and total > 1 and live_prob > 0.5:
        used_item = "beer"
        return None, used_item
    if "magnifier" in dealer_items and 0.3 < live_prob < 0.7 and total > 1:
        used_item = "magnifier"
        if next_cartridge:
            return "player", used_item
        return "self", used_item
    if "knife" in dealer_items and live_prob > 0.3:
        used_item = "knife"
        return "player", used_item
    if "cigarettes" in dealer_items and dealer_lives <= 2 and dealer_lives < 5:
        used_item = "cigarettes"
        return None, used_item
    if "adrenaline" in dealer_items and live_prob > 0.5:
        used_item = "adrenaline"
        return None, used_item
    if "phone" in dealer_items and total > 2:
        used_item = "phone"
        return None, used_item
    if "reverse" in dealer_items and total > 1 and live_prob > 0.5:
        used_item = "reverse"
        return None, used_item
    
    if live == 0:
        return "self", None
    if blank == 0:
        return "player", None
    return "player" if random.random() < live_prob else "self", None

def main():
    try:
        application = Application.builder().token("TokenTgBota").build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            lambda u, c: handle_lobby_action(u, c) if u.effective_chat.id in lobby_states else handle_game_action(u, c)
        ))
        application.add_handler(CallbackQueryHandler(kick_player, pattern="kick_.*"))
        application.add_handler(CallbackQueryHandler(view_cartridge, pattern="view_cartridge"))
        
        logger.info("Starting bot polling...")
        application.run_polling()
    except Exception as e:
        logger.error(f"Bot crashed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()