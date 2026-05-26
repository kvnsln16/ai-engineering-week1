import hashlib
import hmac
import html
import http.cookies
import http.server
import json
import os
import random
import secrets
import socketserver
import sqlite3
import urllib.parse
from datetime import date, datetime, timezone
PORT = 8000
DB_FILE = 'macro_coach.db'
SECRET_FILE = '.session_secret'
SESSION_COOKIE = 'macro_session'

def get_or_create_secret() -> bytes:
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, 'rb') as f:
            return f.read()
    secret = secrets.token_bytes(32)
    with open(SECRET_FILE, 'wb') as f:
        f.write(secret)
    return secret
SESSION_SECRET = get_or_create_secret()

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def db_init() -> None:
    conn = db_connect()
    try:
        conn.executescript('\n            CREATE TABLE IF NOT EXISTS users (\n                id           INTEGER PRIMARY KEY AUTOINCREMENT,\n                email        TEXT UNIQUE NOT NULL,\n                password_hash TEXT NOT NULL,   -- scrypt hash, hex-encoded\n                salt         TEXT NOT NULL,    -- per-user random salt (hex)\n                created_at   TEXT NOT NULL\n            );\n\n            CREATE TABLE IF NOT EXISTS clients (\n                id            INTEGER PRIMARY KEY AUTOINCREMENT,\n                user_id       INTEGER NOT NULL,    -- which coach owns this\n                name          TEXT NOT NULL,\n                goal          TEXT NOT NULL,       -- fat_loss/maintenance/muscle_gain\n                sex           TEXT NOT NULL,       -- male/female\n                weight_lbs    REAL NOT NULL,\n                height_inches REAL NOT NULL,\n                age           INTEGER NOT NULL,\n                activity      TEXT NOT NULL,       -- sedentary/light/moderate/active\n                created_at    TEXT NOT NULL,\n                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE\n            );\n\n            CREATE TABLE IF NOT EXISTS content_entries (\n                id             INTEGER PRIMARY KEY AUTOINCREMENT,\n                user_id        INTEGER NOT NULL,\n                client_id      INTEGER,           -- optional link to a client\n                platform       TEXT NOT NULL,     -- e.g. Instagram, Email\n                title          TEXT NOT NULL,\n                status         TEXT NOT NULL,     -- idea/draft/scheduled/posted\n                scheduled_date TEXT,              -- YYYY-MM-DD or NULL\n                created_at     TEXT NOT NULL,\n                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,\n                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL\n            );\n\n            CREATE TABLE IF NOT EXISTS progress_logs (\n                id          INTEGER PRIMARY KEY AUTOINCREMENT,\n                client_id   INTEGER NOT NULL,\n                log_date    TEXT NOT NULL,        -- YYYY-MM-DD\n                weight_lbs  REAL,                 -- optional check-in weight\n                calories    REAL NOT NULL,\n                protein_g   REAL NOT NULL,\n                carbs_g     REAL NOT NULL,\n                fat_g       REAL NOT NULL,\n                notes       TEXT,\n                created_at  TEXT NOT NULL,\n                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE\n            );\n        ')
        conn.commit()
    finally:
        conn.close()

def hash_password(password: str, salt: bytes=None) -> tuple:
    if salt is None:
        salt = secrets.token_bytes(16)
    hash_bytes = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2 ** 14, r=8, p=1, dklen=64)
    return (hash_bytes.hex(), salt.hex())

def verify_password(password: str, stored_hash_hex: str, salt_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    candidate_hex, _ = hash_password(password, salt=salt)
    return hmac.compare_digest(candidate_hex, stored_hash_hex)

def make_session_cookie(user_id: int) -> str:
    user_id_str = str(user_id)
    signature = hmac.new(SESSION_SECRET, user_id_str.encode('utf-8'), hashlib.sha256).hexdigest()
    return f'{user_id_str}.{signature}'

def read_session_cookie(cookie_value: str) -> int:
    if not cookie_value or '.' not in cookie_value:
        return None
    user_id_str, signature = cookie_value.rsplit('.', 1)
    expected = hmac.new(SESSION_SECRET, user_id_str.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        return int(user_id_str)
    except ValueError:
        return None
GOAL_CALORIE_ADJUSTMENT = {'fat_loss': -500, 'maintenance': 0, 'muscle_gain': 300}
ACTIVITY_MULTIPLIERS = {'sedentary': 1.2, 'light': 1.375, 'moderate': 1.55, 'active': 1.725}

def calculate_bmr(weight_lbs: float, height_inches: float, age: int, sex: str) -> float:
    weight_kg = weight_lbs * 0.453592
    height_cm = height_inches * 2.54
    if sex.lower() == 'male':
        return 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    return 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

def calculate_macro_targets(client: dict) -> dict:
    bmr = calculate_bmr(client['weight_lbs'], client['height_inches'], client['age'], client['sex'])
    maintenance = bmr * ACTIVITY_MULTIPLIERS.get(client['activity'], 1.2)
    target_calories = maintenance + GOAL_CALORIE_ADJUSTMENT.get(client['goal'], 0)
    protein_g = client['weight_lbs'] * 1.0
    fat_g = target_calories * 0.25 / 9
    carb_calories = target_calories - protein_g * 4 - fat_g * 9
    carb_g = max(carb_calories / 4, 0)
    return {'calories': round(target_calories), 'protein_g': round(protein_g), 'carbs_g': round(carb_g), 'fat_g': round(fat_g)}
FOOD_DATABASE = [{'name': 'Chicken breast', 'serving': '6 oz cooked', 'calories': 280, 'protein_g': 52, 'carbs_g': 0, 'fat_g': 6, 'breakfast_friendly': False}, {'name': 'Lean ground beef', 'serving': '5 oz cooked', 'calories': 290, 'protein_g': 38, 'carbs_g': 0, 'fat_g': 15, 'breakfast_friendly': False}, {'name': 'Salmon fillet', 'serving': '5 oz cooked', 'calories': 300, 'protein_g': 34, 'carbs_g': 0, 'fat_g': 18, 'breakfast_friendly': False}, {'name': 'Whole eggs', 'serving': '2 large', 'calories': 140, 'protein_g': 12, 'carbs_g': 1, 'fat_g': 10, 'breakfast_friendly': True}, {'name': 'Egg whites', 'serving': '1 cup', 'calories': 125, 'protein_g': 26, 'carbs_g': 2, 'fat_g': 0, 'breakfast_friendly': True}, {'name': 'Greek yogurt', 'serving': '1 cup non-fat', 'calories': 130, 'protein_g': 22, 'carbs_g': 9, 'fat_g': 0, 'breakfast_friendly': True}, {'name': 'Cottage cheese', 'serving': '1 cup low-fat', 'calories': 160, 'protein_g': 28, 'carbs_g': 8, 'fat_g': 2, 'breakfast_friendly': True}, {'name': 'Whey protein', 'serving': '1 scoop', 'calories': 120, 'protein_g': 24, 'carbs_g': 3, 'fat_g': 1, 'breakfast_friendly': True}, {'name': 'White rice', 'serving': '1 cup cooked', 'calories': 205, 'protein_g': 4, 'carbs_g': 45, 'fat_g': 0, 'breakfast_friendly': False}, {'name': 'Brown rice', 'serving': '1 cup cooked', 'calories': 215, 'protein_g': 5, 'carbs_g': 45, 'fat_g': 2, 'breakfast_friendly': False}, {'name': 'Oats', 'serving': '1 cup dry', 'calories': 300, 'protein_g': 10, 'carbs_g': 54, 'fat_g': 5, 'breakfast_friendly': True}, {'name': 'Sweet potato', 'serving': '1 medium', 'calories': 115, 'protein_g': 2, 'carbs_g': 27, 'fat_g': 0, 'breakfast_friendly': False}, {'name': 'Whole wheat bread', 'serving': '2 slices', 'calories': 160, 'protein_g': 8, 'carbs_g': 28, 'fat_g': 2, 'breakfast_friendly': True}, {'name': 'Pasta', 'serving': '1 cup cooked', 'calories': 220, 'protein_g': 8, 'carbs_g': 43, 'fat_g': 1, 'breakfast_friendly': False}, {'name': 'Banana', 'serving': '1 medium', 'calories': 105, 'protein_g': 1, 'carbs_g': 27, 'fat_g': 0, 'breakfast_friendly': True}, {'name': 'Apple', 'serving': '1 medium', 'calories': 95, 'protein_g': 0, 'carbs_g': 25, 'fat_g': 0, 'breakfast_friendly': True}, {'name': 'Mixed berries', 'serving': '1 cup', 'calories': 70, 'protein_g': 1, 'carbs_g': 17, 'fat_g': 0, 'breakfast_friendly': True}, {'name': 'Broccoli', 'serving': '1 cup cooked', 'calories': 55, 'protein_g': 4, 'carbs_g': 11, 'fat_g': 0, 'breakfast_friendly': False}, {'name': 'Spinach', 'serving': '2 cups raw', 'calories': 15, 'protein_g': 2, 'carbs_g': 2, 'fat_g': 0, 'breakfast_friendly': False}, {'name': 'Mixed salad greens', 'serving': '2 cups', 'calories': 20, 'protein_g': 2, 'carbs_g': 4, 'fat_g': 0, 'breakfast_friendly': False}, {'name': 'Almonds', 'serving': '1 oz (23 nuts)', 'calories': 165, 'protein_g': 6, 'carbs_g': 6, 'fat_g': 14, 'breakfast_friendly': True}, {'name': 'Peanut butter', 'serving': '2 tbsp', 'calories': 190, 'protein_g': 8, 'carbs_g': 7, 'fat_g': 16, 'breakfast_friendly': True}, {'name': 'Olive oil', 'serving': '1 tbsp', 'calories': 120, 'protein_g': 0, 'carbs_g': 0, 'fat_g': 14, 'breakfast_friendly': False}, {'name': 'Avocado', 'serving': '1/2 medium', 'calories': 120, 'protein_g': 1, 'carbs_g': 6, 'fat_g': 11, 'breakfast_friendly': True}, {'name': 'Cheddar cheese', 'serving': '1 oz', 'calories': 115, 'protein_g': 7, 'carbs_g': 1, 'fat_g': 9, 'breakfast_friendly': True}]
MEAL_PLAN = [{'name': 'Breakfast', 'share': 0.3}, {'name': 'Lunch', 'share': 0.35}, {'name': 'Dinner', 'share': 0.35}]

def _build_one_meal(meal_targets: dict, breakfast: bool, used_today: dict) -> dict:
    totals = {'calories': 0, 'protein_g': 0, 'carbs_g': 0, 'fat_g': 0}
    chosen_counts = {}
    max_servings_per_food = 2
    calorie_floor = meal_targets['calories'] * 0.9

    def remaining(macro):
        return max(meal_targets[macro] - totals[macro], 0)

    def score_food(food):
        score = min(food['protein_g'], remaining('protein_g')) * 3.0 + min(food['carbs_g'], remaining('carbs_g')) * 1.0 + min(food['fat_g'], remaining('fat_g')) * 1.0
        if breakfast:
            score *= 1.6 if food['breakfast_friendly'] else 0.45
        score *= 0.65 ** used_today.get(food['name'], 0)
        return score
    safety = 25
    while safety > 0:
        safety -= 1
        best, best_score = (None, 0.0)
        for food in FOOD_DATABASE:
            if totals['calories'] + food['calories'] > meal_targets['calories']:
                continue
            if chosen_counts.get(food['name'], 0) >= max_servings_per_food:
                continue
            s = score_food(food)
            if s > best_score:
                best_score, best = (s, food)
        if best is None or best_score <= 0:
            break
        for m in ('calories', 'protein_g', 'carbs_g', 'fat_g'):
            totals[m] += best[m]
        chosen_counts[best['name']] = chosen_counts.get(best['name'], 0) + 1
        if totals['calories'] >= calorie_floor:
            break
    foods = [{'name': f['name'], 'serving': f['serving'], 'servings': chosen_counts[f['name']]} for f in FOOD_DATABASE if chosen_counts.get(f['name'], 0)]
    return {'foods': foods, 'totals': totals}

def suggest_meal(targets: dict) -> dict:
    used_today = {}
    meals = []
    day_totals = {'calories': 0, 'protein_g': 0, 'carbs_g': 0, 'fat_g': 0}
    for meal_def in MEAL_PLAN:
        meal_targets = {k: targets[k] * meal_def['share'] for k in ('calories', 'protein_g', 'carbs_g', 'fat_g')}
        meal = _build_one_meal(meal_targets, meal_def['name'] == 'Breakfast', used_today)
        for item in meal['foods']:
            used_today[item['name']] = used_today.get(item['name'], 0) + item['servings']
        for m in ('calories', 'protein_g', 'carbs_g', 'fat_g'):
            day_totals[m] += meal['totals'][m]
        meals.append({'name': meal_def['name'], **meal})
    return {'meals': meals, 'totals': day_totals}

def score_log(log: dict, targets: dict) -> float:
    scores = []
    for macro in ('calories', 'protein_g', 'carbs_g', 'fat_g'):
        target = targets[macro]
        if target <= 0:
            continue
        difference = abs(log[macro] - target) / target
        scores.append(max(0.0, 100.0 - difference * 100.0))
    return sum(scores) / len(scores) if scores else 0.0
GOAL_POOLS = {'fat_loss': {'topic': ['calorie deficits', 'hunger management', 'low-cal swaps', 'portion control', 'appetite hacks'], 'topic_adj': ['sneaky', 'surprising', 'common', 'underrated', 'silent'], 'food_style': ['high-volume', 'protein-forward', 'low-density', 'satiating', 'veggie-loaded'], 'angle_word': ['The real reason behind', 'What nobody tells you about', 'Why most people fail at', 'The honest truth about', 'Quick wins for']}, 'muscle_gain': {'topic': ['bulking', 'protein timing', 'high-calorie meals', 'training fuel', 'recovery nutrition'], 'topic_adj': ['common', 'underrated', 'overlooked', 'high-impact', 'easy-to-miss'], 'food_style': ['calorie-dense', 'high-protein', 'training-day', 'nutrient-dense', 'macro-balanced'], 'angle_word': ['What it really takes for', 'The smart way to approach', 'The overlooked side of', 'The honest playbook for', 'Faster results in']}, 'maintenance': {'topic': ['staying consistent', 'intuitive tracking', 'balanced eating', 'flexible nutrition', 'habit anchors'], 'topic_adj': ['sustainable', 'boring-but-effective', 'low-stress', 'underrated', 'long-term'], 'food_style': ['balanced', 'flexible', 'intuitive', 'low-effort', 'everyday'], 'angle_word': ['The quiet truth about', 'What lasting results look like in', 'Habits that protect', 'Long-game tips for', 'Smart routines for']}}
UNIVERSAL_POOLS = {'n': ['3', '5', '7'], 'weekday': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'], 'hook_word': ['Rethinking', 'Decoding', 'Demystifying', 'Unpacking', 'Rewiring', 'Mastering'], 'timeframe': ['4-week', '8-week', '12-week', 'first-month', 'off-season', 'in-season']}
PLATFORMS = ['Instagram', 'Email', 'LinkedIn', 'TikTok', 'YouTube', 'Facebook Group']
FORMAT_TEMPLATES = ['{n} {topic_adj} mistakes coaches see in {topic}', "Behind the scenes: {name}'s macros on a typical {weekday}", 'What {calories} calories of {food_style} food actually looks like', '{angle_word} {topic}', 'A day of eating for {goal_label} ({calories} cal target)', '{hook_word} {topic} — the {goal_label} edition', "Client win: {name}'s {timeframe} {goal_label} update"]

def _pick(pool: list) -> str:
    return random.choice(pool)

def generate_content_ideas(client: dict) -> list:
    goal = client['goal']
    name = client['name']
    goal_label = goal.replace('_', ' ')
    targets = calculate_macro_targets(client)
    calories = f'{targets['calories']:,}'
    selected_formats = random.sample(FORMAT_TEMPLATES, k=min(5, len(FORMAT_TEMPLATES)))
    goal_pool = GOAL_POOLS.get(goal, GOAL_POOLS['maintenance'])
    ideas = []
    for fmt in selected_formats:
        slots = {'name': name, 'calories': calories, 'goal_label': goal_label, 'n': _pick(UNIVERSAL_POOLS['n']), 'weekday': _pick(UNIVERSAL_POOLS['weekday']), 'hook_word': _pick(UNIVERSAL_POOLS['hook_word']), 'timeframe': _pick(UNIVERSAL_POOLS['timeframe']), 'topic': _pick(goal_pool['topic']), 'topic_adj': _pick(goal_pool['topic_adj']), 'food_style': _pick(goal_pool['food_style']), 'angle_word': _pick(goal_pool['angle_word'])}
        title = fmt.format(**slots)
        platform = _pick(PLATFORMS)
        ideas.append((platform, title))
    return ideas

def _insert_ideas_for_client(user_id: int, client: dict) -> int:
    ideas = generate_content_ideas(client)
    now = datetime.now(timezone.utc).isoformat()
    conn = db_connect()
    try:
        conn.executemany("INSERT INTO content_entries (user_id, client_id, platform, title, status, scheduled_date, created_at) VALUES (?, ?, ?, ?, 'idea', NULL, ?)", [(user_id, client['id'], platform, title, now) for platform, title in ideas])
        conn.commit()
    finally:
        conn.close()
    return len(ideas)

def e(value) -> str:
    if value is None:
        return ''
    return html.escape(str(value))
PAGE_CSS = '\n  body { font-family: -apple-system, system-ui, sans-serif; max-width: 880px;\n         margin: 2rem auto; padding: 0 1rem; color: #222; line-height: 1.5; }\n  h1, h2, h3 { color: #1a1a1a; }\n  nav { background: #f4f4f4; padding: 0.75rem 1rem; border-radius: 6px;\n        margin-bottom: 1.5rem; display: flex; gap: 1rem; align-items: center; }\n  nav a { text-decoration: none; color: #2563eb; font-weight: 500; }\n  nav .spacer { flex: 1; }\n  form { display: grid; gap: 0.5rem; max-width: 420px; }\n  form.inline { display: inline; }\n  input, select, textarea, button { font: inherit; padding: 0.45rem 0.6rem;\n        border: 1px solid #ccc; border-radius: 4px; }\n  button { background: #2563eb; color: white; border: none; cursor: pointer;\n        padding: 0.5rem 1rem; }\n  button.danger { background: #dc2626; }\n  button.small { padding: 0.25rem 0.6rem; font-size: 0.9rem; }\n  .card { border: 1px solid #e5e5e5; border-radius: 6px; padding: 1rem;\n        margin-bottom: 1rem; background: white; }\n  .meal { background: #f9fafb; padding: 0.75rem; border-radius: 4px;\n        margin: 0.5rem 0; }\n  .score { font-weight: 600; }\n  .score.good { color: #16a34a; }\n  .score.ok { color: #ca8a04; }\n  .score.bad { color: #dc2626; }\n  .error { color: #dc2626; background: #fef2f2; padding: 0.75rem;\n        border-radius: 4px; margin-bottom: 1rem; }\n  .flash { color: #166534; background: #f0fdf4; padding: 0.75rem;\n        border-radius: 4px; margin-bottom: 1rem; }\n  table { border-collapse: collapse; width: 100%; }\n  th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; }\n'

def layout(title: str, body: str, user_email: str=None, error: str=None, flash: str=None) -> str:
    if user_email:
        nav = f'<a href="/">Dashboard</a><a href="/clients">Clients</a><a href="/content">Content</a><span class="spacer"></span><span>{e(user_email)}</span><form method="POST" action="/logout" class="inline"><button class="small">Log out</button></form>'
    else:
        nav = '<a href="/">Home</a><span class="spacer"></span><a href="/login">Log in</a><a href="/signup">Sign up</a>'
    error_html = f'<div class="error">{e(error)}</div>' if error else ''
    flash_html = f'<div class="flash">{e(flash)}</div>' if flash else ''
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{e(title)} — Macro Coach</title><style>{PAGE_CSS}</style></head><body><nav>{nav}</nav>{error_html}{flash_html}{body}</body></html>"
ROUTES = []

def route(method: str, pattern: str):

    def decorator(func):
        parts = pattern.strip('/').split('/') if pattern != '/' else ['']
        ROUTES.append((method, parts, func))
        return func
    return decorator

def match_route(method: str, path: str):
    path_parts = path.strip('/').split('/') if path != '/' else ['']
    for route_method, pattern_parts, handler in ROUTES:
        if route_method != method:
            continue
        if len(pattern_parts) != len(path_parts):
            continue
        captured = []
        matched = True
        for pat, actual in zip(pattern_parts, path_parts):
            if pat == '<int>':
                if not actual.isdigit():
                    matched = False
                    break
                captured.append(int(actual))
            elif pat != actual:
                matched = False
                break
        if matched:
            return (handler, captured)
    return (None, None)

def parse_form_body(handler) -> dict:
    length = int(handler.headers.get('Content-Length', '0'))
    raw = handler.rfile.read(length).decode('utf-8') if length else ''
    parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items()}

def get_current_user(handler):
    raw_cookie = handler.headers.get('Cookie', '')
    if not raw_cookie:
        return None
    jar = http.cookies.SimpleCookie()
    jar.load(raw_cookie)
    morsel = jar.get(SESSION_COOKIE)
    if morsel is None:
        return None
    user_id = read_session_cookie(morsel.value)
    if user_id is None:
        return None
    conn = db_connect()
    try:
        row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        return row
    finally:
        conn.close()

def send_html(handler, html_body: str, status: int=200, extra_headers: list=None) -> None:
    body_bytes = html_body.encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Content-Length', str(len(body_bytes)))
    for name, value in extra_headers or []:
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(body_bytes)

def send_redirect(handler, location: str, extra_headers: list=None) -> None:
    handler.send_response(303)
    handler.send_header('Location', location)
    for name, value in extra_headers or []:
        handler.send_header(name, value)
    handler.send_header('Content-Length', '0')
    handler.end_headers()

def require_login(handler):
    user = get_current_user(handler)
    if user is None:
        send_redirect(handler, '/login')
        return None
    return user
FLASH_COOKIE = 'macro_flash'

def flash_header(message: str) -> tuple:
    encoded = urllib.parse.quote(message)
    return ('Set-Cookie', f'{FLASH_COOKIE}={encoded}; Path=/; HttpOnly; SameSite=Lax')

def consume_flash(handler) -> tuple:
    raw_cookie = handler.headers.get('Cookie', '')
    if not raw_cookie:
        return (None, None)
    jar = http.cookies.SimpleCookie()
    jar.load(raw_cookie)
    morsel = jar.get(FLASH_COOKIE)
    if morsel is None:
        return (None, None)
    clear = ('Set-Cookie', f'{FLASH_COOKIE}=; Path=/; Max-Age=0')
    try:
        return (urllib.parse.unquote(morsel.value), clear)
    except Exception:
        return (None, clear)

@route('GET', '/')
def view_home(handler):
    user = get_current_user(handler)
    if user is None:
        body = "<h1>Macro Coach</h1><p>A simple backend for online fitness coaches: manage clients, plan content, log daily nutrition, and see macro targets and adherence scores.</p><p><a href='/signup'>Sign up</a> or <a href='/login'>log in</a> to get started.</p>"
        return send_html(handler, layout('Welcome', body))
    conn = db_connect()
    try:
        client_count = conn.execute('SELECT COUNT(*) FROM clients WHERE user_id = ?', (user['id'],)).fetchone()[0]
        content_count = conn.execute('SELECT COUNT(*) FROM content_entries WHERE user_id = ?', (user['id'],)).fetchone()[0]
    finally:
        conn.close()
    body = f"<h1>Dashboard</h1><div class='card'><h3>Clients</h3><p>{client_count} client(s). <a href='/clients'>Manage</a></p></div><div class='card'><h3>Content</h3><p>{content_count} content item(s). <a href='/content'>Manage</a></p></div>"
    send_html(handler, layout('Dashboard', body, user['email']))

@route('GET', '/signup')
def view_signup(handler):
    body = "<h1>Sign up</h1><form method='POST' action='/signup'><label>Email <input type='email' name='email' required></label><label>Password (min 8 chars) <input type='password' name='password' required minlength='8'></label><button>Create account</button></form>"
    send_html(handler, layout('Sign up', body))

@route('POST', '/signup')
def do_signup(handler):
    form = parse_form_body(handler)
    email = form.get('email', '').strip().lower()
    password = form.get('password', '')
    if not email or len(password) < 8:
        body = '<h1>Sign up</h1><p>Provide an email and an 8+ char password.</p>'
        return send_html(handler, layout('Sign up', body, error='Invalid input'), status=400)
    hash_hex, salt_hex = hash_password(password)
    conn = db_connect()
    try:
        try:
            cursor = conn.execute('INSERT INTO users (email, password_hash, salt, created_at) VALUES (?, ?, ?, ?)', (email, hash_hex, salt_hex, datetime.now(timezone.utc).isoformat()))
            conn.commit()
            user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            body = '<h1>Sign up</h1><p>That email is already registered.</p>'
            return send_html(handler, layout('Sign up', body, error='Email already in use'), status=400)
    finally:
        conn.close()
    cookie = f'{SESSION_COOKIE}={make_session_cookie(user_id)}; Path=/; HttpOnly; SameSite=Lax'
    send_redirect(handler, '/', extra_headers=[('Set-Cookie', cookie)])

@route('GET', '/login')
def view_login(handler):
    body = "<h1>Log in</h1><form method='POST' action='/login'><label>Email <input type='email' name='email' required></label><label>Password <input type='password' name='password' required></label><button>Log in</button></form><p>No account? <a href='/signup'>Sign up</a>.</p>"
    send_html(handler, layout('Log in', body))

@route('POST', '/login')
def do_login(handler):
    form = parse_form_body(handler)
    email = form.get('email', '').strip().lower()
    password = form.get('password', '')
    conn = db_connect()
    try:
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    finally:
        conn.close()
    if user is None or not verify_password(password, user['password_hash'], user['salt']):
        body = "<h1>Log in</h1><p>Wrong email or password.</p><p><a href='/login'>Try again</a></p>"
        return send_html(handler, layout('Log in', body, error='Invalid credentials'), status=401)
    cookie = f'{SESSION_COOKIE}={make_session_cookie(user['id'])}; Path=/; HttpOnly; SameSite=Lax'
    send_redirect(handler, '/', extra_headers=[('Set-Cookie', cookie)])

@route('POST', '/logout')
def do_logout(handler):
    cookie = f'{SESSION_COOKIE}=; Path=/; Max-Age=0'
    send_redirect(handler, '/', extra_headers=[('Set-Cookie', cookie)])

@route('GET', '/clients')
def view_clients(handler):
    user = require_login(handler)
    if user is None:
        return
    conn = db_connect()
    try:
        rows = conn.execute('SELECT * FROM clients WHERE user_id = ? ORDER BY name', (user['id'],)).fetchall()
    finally:
        conn.close()
    items = ''.join((f"<li><a href='/clients/{r['id']}'>{e(r['name'])}</a> — {e(r['goal'].replace('_', ' ').title())}</li>" for r in rows)) or '<li>No clients yet.</li>'
    body = f"<h1>Clients</h1><ul>{items}</ul><p><a href='/clients/new'>+ Add a client</a></p>"
    send_html(handler, layout('Clients', body, user['email']))

def _client_form_html(action: str, client: dict=None, button_label: str='Save') -> str:
    c = client or {'name': '', 'goal': 'fat_loss', 'sex': 'female', 'weight_lbs': '', 'height_inches': '', 'age': '', 'activity': 'moderate'}

    def options(name, values, selected):
        return ''.join((f'<option value="{v}"{(' selected' if v == selected else '')}>{v.replace('_', ' ').title()}</option>' for v in values))
    return f"<form method='POST' action='{action}'><label>Name <input name='name' value='{e(c['name'])}' required></label><label>Goal <select name='goal'>{options('goal', list(GOAL_CALORIE_ADJUSTMENT.keys()), c['goal'])}</select></label><label>Sex <select name='sex'>{options('sex', ['female', 'male'], c['sex'])}</select></label><label>Weight (lbs) <input name='weight_lbs' type='number' step='0.1' min='50' value='{e(c['weight_lbs'])}' required></label><label>Height (inches) <input name='height_inches' type='number' step='0.1' min='36' value='{e(c['height_inches'])}' required></label><label>Age <input name='age' type='number' min='13' value='{e(c['age'])}' required></label><label>Activity <select name='activity'>{options('activity', list(ACTIVITY_MULTIPLIERS.keys()), c['activity'])}</select></label><button>{e(button_label)}</button></form>"

@route('GET', '/clients/new')
def view_new_client(handler):
    user = require_login(handler)
    if user is None:
        return
    body = '<h1>Add a client</h1>' + _client_form_html('/clients', button_label='Add')
    send_html(handler, layout('New client', body, user['email']))

def _validate_client_form(form: dict) -> tuple:
    try:
        name = form.get('name', '').strip()
        if not name:
            return (None, 'Name is required.')
        goal = form['goal']
        sex = form['sex']
        activity = form['activity']
        if goal not in GOAL_CALORIE_ADJUSTMENT:
            return (None, 'Invalid goal.')
        if sex not in ('male', 'female'):
            return (None, 'Invalid sex.')
        if activity not in ACTIVITY_MULTIPLIERS:
            return (None, 'Invalid activity.')
        weight = float(form['weight_lbs'])
        height = float(form['height_inches'])
        age = int(form['age'])
        if weight < 50 or height < 36 or age < 13:
            return (None, 'Weight, height, or age out of range.')
    except (KeyError, ValueError):
        return (None, 'Please fill all fields with valid values.')
    return ({'name': name, 'goal': goal, 'sex': sex, 'weight_lbs': weight, 'height_inches': height, 'age': age, 'activity': activity}, None)

@route('POST', '/clients')
def do_create_client(handler):
    user = require_login(handler)
    if user is None:
        return
    form = parse_form_body(handler)
    data, error = _validate_client_form(form)
    if error:
        body = f'<h1>Add a client</h1>' + _client_form_html('/clients', button_label='Add')
        return send_html(handler, layout('New client', body, user['email'], error=error), status=400)
    conn = db_connect()
    try:
        conn.execute('INSERT INTO clients (user_id, name, goal, sex, weight_lbs, height_inches, age, activity, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (user['id'], data['name'], data['goal'], data['sex'], data['weight_lbs'], data['height_inches'], data['age'], data['activity'], datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()
    send_redirect(handler, '/clients')

def _get_owned_client(user_id: int, client_id: int):
    conn = db_connect()
    try:
        return conn.execute('SELECT * FROM clients WHERE id = ? AND user_id = ?', (client_id, user_id)).fetchone()
    finally:
        conn.close()

@route('GET', '/clients/<int>')
def view_client(handler, client_id: int):
    user = require_login(handler)
    if user is None:
        return
    client = _get_owned_client(user['id'], client_id)
    if client is None:
        return send_html(handler, layout('Not found', '<h1>404 — Not found</h1>', user['email']), status=404)
    targets = calculate_macro_targets(dict(client))
    day = suggest_meal(targets)
    conn = db_connect()
    try:
        log_rows = conn.execute('SELECT * FROM progress_logs WHERE client_id = ? ORDER BY log_date DESC LIMIT 14', (client_id,)).fetchall()
    finally:
        conn.close()
    scored_logs = []
    for r in log_rows:
        score = score_log(dict(r), targets)
        css_class = 'good' if score >= 85 else 'ok' if score >= 65 else 'bad'
        scored_logs.append((r, score, css_class))
    meals_html = ''
    for meal in day['meals']:
        food_lis = ''.join((f'<li>{f['servings']} x {e(f['name'])} ({e(f['serving'])})</li>' for f in meal['foods']))
        t = meal['totals']
        meals_html += f"<div class='meal'><strong>{e(meal['name'])}</strong><ul>{food_lis}</ul><small>Subtotal: {t['calories']:.0f} cal | {t['protein_g']:.0f}g P | {t['carbs_g']:.0f}g C | {t['fat_g']:.0f}g F</small></div>"
    if scored_logs:
        log_rows_html = ''.join((f"<tr><td>{e(r['log_date'])}</td><td>{r['calories']:.0f}</td><td>{r['protein_g']:.0f}</td><td>{r['carbs_g']:.0f}</td><td>{r['fat_g']:.0f}</td><td class='score {cls}'>{score:.0f}</td></tr>" for r, score, cls in scored_logs))
        logs_html = f'<table><tr><th>Date</th><th>Cal</th><th>P</th><th>C</th><th>F</th><th>Score</th></tr>{log_rows_html}</table>'
    else:
        logs_html = '<p>No logs yet.</p>'
    today = date.today().isoformat()
    body = f"""<h1>{e(client['name'])}</h1><p>{e(client['goal'].replace('_', ' ').title())} · {e(client['sex']).title()} · {client['weight_lbs']:.0f} lbs · {client['height_inches']:.0f} in · {client['age']} yrs · {e(client['activity']).title()}</p><div class='card'><h3>Daily macro targets</h3><p>{targets['calories']} cal · {targets['protein_g']}g protein · {targets['carbs_g']}g carbs · {targets['fat_g']}g fat</p></div><div class='card'><h3>Suggested meals</h3>{meals_html}</div><div class='card'><h3>Recent logs</h3>{logs_html}</div><div class='card'><h3>Log a day</h3><form method='POST' action='/clients/{client_id}/log'><label>Date <input type='date' name='log_date' value='{today}' required></label><label>Weight (lbs, optional) <input type='number' step='0.1' name='weight_lbs'></label><label>Calories <input type='number' step='1' name='calories' required></label><label>Protein (g) <input type='number' step='1' name='protein_g' required></label><label>Carbs (g) <input type='number' step='1' name='carbs_g' required></label><label>Fat (g) <input type='number' step='1' name='fat_g' required></label><label>Notes <textarea name='notes' rows='2'></textarea></label><button>Log it</button></form></div><div class='card'><h3>Content ideas</h3><p>Generate a set of content ideas tailored to {e(client['name'])}'s profile. They land in your <a href='/content'>Content</a> list as 'idea' status, ready to edit or schedule.</p><form method='POST' action='/clients/{client_id}/generate-content'><button>Generate content ideas</button></form></div><div class='card'><h3>Manage</h3><p><a href='/clients/{client_id}/edit'>Edit</a></p><form method='POST' action='/clients/{client_id}/delete' onsubmit="return confirm('Delete {e(client['name'])}? This removes all their logs too.')"><button class='danger'>Delete client</button></form></div>"""
    flash, clear_header = consume_flash(handler)
    extra = [clear_header] if clear_header else []
    send_html(handler, layout(client['name'], body, user['email'], flash=flash), extra_headers=extra)

@route('GET', '/clients/<int>/edit')
def view_edit_client(handler, client_id: int):
    user = require_login(handler)
    if user is None:
        return
    client = _get_owned_client(user['id'], client_id)
    if client is None:
        return send_html(handler, layout('Not found', '<h1>404</h1>', user['email']), status=404)
    body = f'<h1>Edit {e(client['name'])}</h1>' + _client_form_html(f'/clients/{client_id}/edit', dict(client), button_label='Save changes')
    send_html(handler, layout('Edit client', body, user['email']))

@route('POST', '/clients/<int>/edit')
def do_edit_client(handler, client_id: int):
    user = require_login(handler)
    if user is None:
        return
    client = _get_owned_client(user['id'], client_id)
    if client is None:
        return send_html(handler, layout('Not found', '<h1>404</h1>', user['email']), status=404)
    form = parse_form_body(handler)
    data, error = _validate_client_form(form)
    if error:
        body = f'<h1>Edit {e(client['name'])}</h1>' + _client_form_html(f'/clients/{client_id}/edit', dict(client), button_label='Save changes')
        return send_html(handler, layout('Edit client', body, user['email'], error=error), status=400)
    conn = db_connect()
    try:
        conn.execute('UPDATE clients SET name=?, goal=?, sex=?, weight_lbs=?, height_inches=?, age=?, activity=? WHERE id=? AND user_id=?', (data['name'], data['goal'], data['sex'], data['weight_lbs'], data['height_inches'], data['age'], data['activity'], client_id, user['id']))
        conn.commit()
    finally:
        conn.close()
    send_redirect(handler, f'/clients/{client_id}')

@route('POST', '/clients/<int>/delete')
def do_delete_client(handler, client_id: int):
    user = require_login(handler)
    if user is None:
        return
    conn = db_connect()
    try:
        conn.execute('DELETE FROM clients WHERE id=? AND user_id=?', (client_id, user['id']))
        conn.commit()
    finally:
        conn.close()
    send_redirect(handler, '/clients')

@route('POST', '/clients/<int>/log')
def do_create_log(handler, client_id: int):
    user = require_login(handler)
    if user is None:
        return
    client = _get_owned_client(user['id'], client_id)
    if client is None:
        return send_html(handler, layout('Not found', '<h1>404</h1>', user['email']), status=404)
    form = parse_form_body(handler)
    try:
        log_date = form.get('log_date', '').strip()
        datetime.strptime(log_date, '%Y-%m-%d')
        weight_raw = form.get('weight_lbs', '').strip()
        weight = float(weight_raw) if weight_raw else None
        calories = float(form['calories'])
        protein = float(form['protein_g'])
        carbs = float(form['carbs_g'])
        fat = float(form['fat_g'])
    except (KeyError, ValueError):
        return send_redirect(handler, f'/clients/{client_id}')
    notes = form.get('notes', '').strip() or None
    conn = db_connect()
    try:
        conn.execute('INSERT INTO progress_logs (client_id, log_date, weight_lbs, calories, protein_g, carbs_g, fat_g, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (client_id, log_date, weight, calories, protein, carbs, fat, notes, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()
    send_redirect(handler, f'/clients/{client_id}')

@route('POST', '/clients/<int>/generate-content')
def do_generate_content_for_client(handler, client_id: int):
    user = require_login(handler)
    if user is None:
        return
    client = _get_owned_client(user['id'], client_id)
    if client is None:
        return send_html(handler, layout('Not found', '<h1>404</h1>', user['email']), status=404)
    count = _insert_ideas_for_client(user['id'], dict(client))
    msg = f'Added {count} content ideas for {client['name']}. See them in Content.'
    send_redirect(handler, f'/clients/{client_id}', extra_headers=[flash_header(msg)])

@route('GET', '/content')
def view_content(handler):
    user = require_login(handler)
    if user is None:
        return
    conn = db_connect()
    try:
        rows = conn.execute('SELECT ce.*, c.name AS client_name FROM content_entries ce LEFT JOIN clients c ON c.id = ce.client_id WHERE ce.user_id = ? ORDER BY COALESCE(ce.scheduled_date, ce.created_at) DESC', (user['id'],)).fetchall()
        clients = conn.execute('SELECT id, name FROM clients WHERE user_id = ? ORDER BY name', (user['id'],)).fetchall()
    finally:
        conn.close()
    client_options = "<option value=''>(none)</option>" + ''.join((f"<option value='{c['id']}'>{e(c['name'])}</option>" for c in clients))
    status_options = ''.join((f"<option value='{s}'>{s.title()}</option>" for s in ('idea', 'draft', 'scheduled', 'posted')))
    platform_options = ''.join((f"<option value='{p}'>{p}</option>" for p in ('Instagram', 'Email', 'LinkedIn', 'Facebook Group', 'TikTok', 'YouTube')))
    rows_html = ''.join((f"""<tr><td>{e(r['scheduled_date'] or '-')}</td><td>{e(r['platform'])}</td><td>{e(r['title'])}</td><td>{e(r['status'])}</td><td>{(e(r['client_name']) if r['client_name'] else '-')}</td><td><form method='POST' action='/content/{r['id']}/delete' class='inline' onsubmit="return confirm('Delete this content item?')"><button class='small danger'>Delete</button></form></td></tr>""" for r in rows)) or "<tr><td colspan='6'><em>No content yet.</em></td></tr>"
    if not clients:
        generate_card = "<div class='card'><h3>Generate ideas from your clients</h3><p><em>Add a client first to generate tailored content ideas.</em></p></div>"
    else:
        per_client_buttons = ''.join((f"<form method='POST' action='/content/generate' class='inline' style='display:inline-block;margin:0 0.4rem 0.4rem 0;'><input type='hidden' name='client_id' value='{c['id']}'><button class='small'>Generate for {e(c['name'])}</button></form>" for c in clients))
        all_button = "<form method='POST' action='/content/generate' class='inline' style='display:inline-block;'><button class='small'>Generate for all clients</button></form>"
        generate_card = f"<div class='card'><h3>Generate ideas from your clients</h3><p>Tailored ideas land in the list below as 'idea' status — edit, schedule, or delete them just like manual entries.</p>{per_client_buttons}{all_button}</div>"
    body = f"<h1>Content planner</h1>{generate_card}<div class='card'><h3>Add a content item</h3><form method='POST' action='/content'><label>Title <input name='title' required></label><label>Platform <select name='platform'>{platform_options}</select></label><label>Status <select name='status'>{status_options}</select></label><label>Scheduled date <input type='date' name='scheduled_date'></label><label>Related client <select name='client_id'>{client_options}</select></label><button>Add</button></form></div><div class='card'><h3>All content</h3><table><tr><th>Date</th><th>Platform</th><th>Title</th><th>Status</th><th>Client</th><th></th></tr>{rows_html}</table></div>"
    flash, clear_header = consume_flash(handler)
    extra = [clear_header] if clear_header else []
    send_html(handler, layout('Content', body, user['email'], flash=flash), extra_headers=extra)

@route('POST', '/content')
def do_create_content(handler):
    user = require_login(handler)
    if user is None:
        return
    form = parse_form_body(handler)
    title = form.get('title', '').strip()
    platform = form.get('platform', '').strip()
    status = form.get('status', 'idea').strip()
    scheduled_date = form.get('scheduled_date', '').strip() or None
    client_id_raw = form.get('client_id', '').strip()
    client_id = int(client_id_raw) if client_id_raw.isdigit() else None
    if not title or not platform:
        return send_redirect(handler, '/content')
    if client_id is not None:
        if _get_owned_client(user['id'], client_id) is None:
            client_id = None
    if scheduled_date:
        try:
            datetime.strptime(scheduled_date, '%Y-%m-%d')
        except ValueError:
            scheduled_date = None
    conn = db_connect()
    try:
        conn.execute('INSERT INTO content_entries (user_id, client_id, platform, title, status, scheduled_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)', (user['id'], client_id, platform, title, status, scheduled_date, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()
    send_redirect(handler, '/content')

@route('POST', '/content/generate')
def do_generate_content(handler):
    user = require_login(handler)
    if user is None:
        return
    form = parse_form_body(handler)
    client_id_raw = form.get('client_id', '').strip()
    if client_id_raw.isdigit():
        client = _get_owned_client(user['id'], int(client_id_raw))
        if client is None:
            return send_redirect(handler, '/content')
        targets = [dict(client)]
    else:
        conn = db_connect()
        try:
            rows = conn.execute('SELECT * FROM clients WHERE user_id = ?', (user['id'],)).fetchall()
        finally:
            conn.close()
        targets = [dict(r) for r in rows]
    if not targets:
        return send_redirect(handler, '/content', extra_headers=[flash_header('Add a client first to generate ideas.')])
    total = 0
    for c in targets:
        total += _insert_ideas_for_client(user['id'], c)
    label = targets[0]['name'] if len(targets) == 1 else f'{len(targets)} clients'
    send_redirect(handler, '/content', extra_headers=[flash_header(f'Generated {total} ideas for {label}. Edit, schedule, or delete below.')])

@route('POST', '/content/<int>/delete')
def do_delete_content(handler, content_id: int):
    user = require_login(handler)
    if user is None:
        return
    conn = db_connect()
    try:
        conn.execute('DELETE FROM content_entries WHERE id=? AND user_id=?', (content_id, user['id']))
        conn.commit()
    finally:
        conn.close()
    send_redirect(handler, '/content')

class ReusableThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

class MacroCoachHandler(http.server.BaseHTTPRequestHandler):

    def _dispatch(self, method: str) -> None:
        path = urllib.parse.urlparse(self.path).path
        handler_func, args = match_route(method, path)
        if handler_func is None:
            return send_html(self, layout('Not found', '<h1>404 — Not found</h1>'), status=404)
        try:
            handler_func(self, *args)
        except Exception as exc:
            self.log_error('Unhandled error: %s', exc)
            try:
                send_html(self, layout('Error', '<h1>500 — Something went wrong</h1>'), status=500)
            except Exception:
                pass

    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def log_message(self, format, *args):
        print(f'[{self.command}] {self.path} -> {(args[1] if len(args) > 1 else '')}')

def run() -> None:
    db_init()
    print(f'Macro Coach running at http://localhost:{PORT}')
    print(f'Database: {os.path.abspath(DB_FILE)}')
    with ReusableThreadingServer(('', PORT), MacroCoachHandler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print('\nShutting down.')
if __name__ == '__main__':
    run()
