import csv
import json
import os
 
 
# ---------------------------------------------------------------------------
# File locations
# ---------------------------------------------------------------------------
 
CLIENTS_FILE = "clients.json"        # Saved clients (persists between runs)
REPORT_FILE = "coaching_report.txt"  # Exported human-readable report
SUMMARY_FILE = "summary.csv"         # Exported machine-readable summary
 

# ---------------------------------------------------------------------------
# Configuration tables
# ---------------------------------------------------------------------------
 
# Valid goals and the calorie adjustment each one applies.
GOAL_CALORIE_ADJUSTMENT = {
    "fat_loss": -500,      # ~1 lb/week loss
    "maintenance": 0,
    "muscle_gain": 300,    # modest surplus to limit fat gain
}
 
# Valid activity levels and the multiplier each applies to BMR.
ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
}
 
 

# SECTION 1 — BUILT-IN FOOD DATABASE
# A small fixed list of common foods. Each food records the macros for one
# standard serving. The meal suggester picks and stacks servings from here.
 
# Each entry records the macros for one standard serving. The
# 'breakfast_friendly' flag lets the meal builder favour breakfast-style
# foods at breakfast (it does not forbid other foods, only nudges).
# Fields: name, serving, calories, protein_g, carbs_g, fat_g, breakfast_friendly
FOOD_DATABASE = [
    {"name": "Chicken breast", "serving": "6 oz cooked",
     "calories": 280, "protein_g": 52, "carbs_g": 0, "fat_g": 6,
     "breakfast_friendly": False},
    {"name": "Lean ground beef", "serving": "5 oz cooked",
     "calories": 290, "protein_g": 38, "carbs_g": 0, "fat_g": 15,
     "breakfast_friendly": False},
    {"name": "Salmon fillet", "serving": "5 oz cooked",
     "calories": 300, "protein_g": 34, "carbs_g": 0, "fat_g": 18,
     "breakfast_friendly": False},
    {"name": "Whole eggs", "serving": "2 large",
     "calories": 140, "protein_g": 12, "carbs_g": 1, "fat_g": 10,
     "breakfast_friendly": True},
    {"name": "Egg whites", "serving": "1 cup",
     "calories": 125, "protein_g": 26, "carbs_g": 2, "fat_g": 0,
     "breakfast_friendly": True},
    {"name": "Greek yogurt", "serving": "1 cup non-fat",
     "calories": 130, "protein_g": 22, "carbs_g": 9, "fat_g": 0,
     "breakfast_friendly": True},
    {"name": "Cottage cheese", "serving": "1 cup low-fat",
     "calories": 160, "protein_g": 28, "carbs_g": 8, "fat_g": 2,
     "breakfast_friendly": True},
    {"name": "Whey protein", "serving": "1 scoop",
     "calories": 120, "protein_g": 24, "carbs_g": 3, "fat_g": 1,
     "breakfast_friendly": True},
    {"name": "White rice", "serving": "1 cup cooked",
     "calories": 205, "protein_g": 4, "carbs_g": 45, "fat_g": 0,
     "breakfast_friendly": False},
    {"name": "Brown rice", "serving": "1 cup cooked",
     "calories": 215, "protein_g": 5, "carbs_g": 45, "fat_g": 2,
     "breakfast_friendly": False},
    {"name": "Oats", "serving": "1 cup dry",
     "calories": 300, "protein_g": 10, "carbs_g": 54, "fat_g": 5,
     "breakfast_friendly": True},
    {"name": "Sweet potato", "serving": "1 medium",
     "calories": 115, "protein_g": 2, "carbs_g": 27, "fat_g": 0,
     "breakfast_friendly": False},
    {"name": "Whole wheat bread", "serving": "2 slices",
     "calories": 160, "protein_g": 8, "carbs_g": 28, "fat_g": 2,
     "breakfast_friendly": True},
    {"name": "Pasta", "serving": "1 cup cooked",
     "calories": 220, "protein_g": 8, "carbs_g": 43, "fat_g": 1,
     "breakfast_friendly": False},
    {"name": "Banana", "serving": "1 medium",
     "calories": 105, "protein_g": 1, "carbs_g": 27, "fat_g": 0,
     "breakfast_friendly": True},
    {"name": "Apple", "serving": "1 medium",
     "calories": 95, "protein_g": 0, "carbs_g": 25, "fat_g": 0,
     "breakfast_friendly": True},
    {"name": "Mixed berries", "serving": "1 cup",
     "calories": 70, "protein_g": 1, "carbs_g": 17, "fat_g": 0,
     "breakfast_friendly": True},
    {"name": "Broccoli", "serving": "1 cup cooked",
     "calories": 55, "protein_g": 4, "carbs_g": 11, "fat_g": 0,
     "breakfast_friendly": False},
    {"name": "Spinach", "serving": "2 cups raw",
     "calories": 15, "protein_g": 2, "carbs_g": 2, "fat_g": 0,
     "breakfast_friendly": False},
    {"name": "Mixed salad greens", "serving": "2 cups",
     "calories": 20, "protein_g": 2, "carbs_g": 4, "fat_g": 0,
     "breakfast_friendly": False},
    {"name": "Almonds", "serving": "1 oz (23 nuts)",
     "calories": 165, "protein_g": 6, "carbs_g": 6, "fat_g": 14,
     "breakfast_friendly": True},
    {"name": "Peanut butter", "serving": "2 tbsp",
     "calories": 190, "protein_g": 8, "carbs_g": 7, "fat_g": 16,
     "breakfast_friendly": True},
    {"name": "Olive oil", "serving": "1 tbsp",
     "calories": 120, "protein_g": 0, "carbs_g": 0, "fat_g": 14,
     "breakfast_friendly": False},
    {"name": "Avocado", "serving": "1/2 medium",
     "calories": 120, "protein_g": 1, "carbs_g": 6, "fat_g": 11,
     "breakfast_friendly": True},
    {"name": "Cheddar cheese", "serving": "1 oz",
     "calories": 115, "protein_g": 7, "carbs_g": 1, "fat_g": 9,
     "breakfast_friendly": True},
]
 
 

# SECTION 2 — INPUT HELPERS
# Small reusable functions that ask the coach a question and keep asking
# until the answer is valid. This keeps the menu code clean and safe.
 
def ask_text(prompt: str) -> str:
#Ask for a non-empty line of text and return it (trimmed)
    while True:
        answer = input(prompt).strip()
        if answer:
            return answer
        print("  Please enter a value.")
 
 
def ask_number(prompt: str, minimum: float = 0.1) -> float:
#Ask for a positive number and return it as a float.
#Repeats the question until the coach types a valid number that is at
#least `minimum`. This prevents crashes from bad input later on.
    while True:
        raw = input(prompt).strip()
        try:
            value = float(raw)
        except ValueError:
            print("  Please enter a number (digits only).")
            continue
        if value < minimum:
            print(f"  Please enter a number of at least {minimum}.")
            continue
        return value
 
 
def ask_choice(prompt: str, choices: list) -> str:
    """Ask the coach to pick one option from a numbered list.
 
    `choices` is a list of strings. The coach types the number next to the
    option they want. Returns the chosen string.
    """
    print(prompt)
    for index, choice in enumerate(choices, start=1):
        # Show goals/activity nicely, e.g. "fat_loss" -> "Fat Loss".
        label = choice.replace("_", " ").title()
        print(f"  {index}. {label}")
 
    while True:
        raw = input("  Enter the number of your choice: ").strip()
        if raw.isdigit():
            number = int(raw)
            if 1 <= number <= len(choices):
                return choices[number - 1]
        print(f"  Please enter a number between 1 and {len(choices)}.")
 
 
def ask_yes_no(prompt: str) -> bool:
    """Ask a yes/no question and return True for yes, False for no.
 
    Repeats the question until the coach types 'y' or 'n' (any case).
    Used to confirm destructive actions like deleting a client.
    """
    while True:
        answer = input(prompt).strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please answer 'y' or 'n'.")
 
 
def pick_client(clients: list, action_label: str) -> int:
#Show a numbered list of clients and return the chosen client's index.
#`action_label` is the verb to display ('edit', 'delete') so the
#prompt reads naturally. Returns None if the list is empty or the
#coach types 0 to cancel.
    if not clients:
        print(f"\n  No clients to {action_label}. Add a client first.")
        return None
 
    # Show every client on a numbered line so the coach can pick by number.
    print(f"\n  Which client would you like to {action_label}?")
    for index, client in enumerate(clients, start=1):
        goal_label = client["goal"].replace("_", " ").title()
        print(f"    {index}. {client['name']} ({goal_label})")
    print("    0. Cancel")
 
    # Keep asking until we get a valid number in range (0 cancels).
    while True:
        raw = input("  Enter the number of your choice: ").strip()
        if raw.isdigit():
            number = int(raw)
            if number == 0:
                return None
            if 1 <= number <= len(clients):
                return number - 1  # convert to a zero-based list index
        print(f"  Please enter a number between 0 and {len(clients)}.")
 
 

# SECTION 3 — MACRO ENGINE
# Calculates a client's daily macro targets using the Mifflin-St Jeor BMR
# equation, an activity multiplier, and a goal-based calorie adjustment.
 
def calculate_bmr(weight_lbs: float, height_inches: float,
                   age: int, sex: str) -> float:
    """Return Basal Metabolic Rate using the Mifflin-St Jeor equation.
 
    The formula is metric, so pounds and inches are converted first.
    """
    weight_kg = weight_lbs * 0.453592
    height_cm = height_inches * 2.54
 
    if sex.lower() == "male":
        return (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + 5
    else:
        return (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161
 
 
def calculate_macro_targets(client: dict) -> dict:
#Return a client's daily targets: calories, protein, carbs, fat
    bmr = calculate_bmr(
        client["weight_lbs"], client["height_inches"],
        client["age"], client["sex"],
    )
 
    # Total daily energy use = BMR x activity multiplier.
    multiplier = ACTIVITY_MULTIPLIERS.get(client["activity"], 1.2)
    maintenance_calories = bmr * multiplier
 
    # Apply the goal-based calorie adjustment.
    adjustment = GOAL_CALORIE_ADJUSTMENT.get(client["goal"], 0)
    target_calories = maintenance_calories + adjustment
 
    # Protein: 1.0 g per lb of body weight (4 calories per gram).
    protein_g = client["weight_lbs"] * 1.0
    protein_calories = protein_g * 4
 
    # Fat: 25% of total calories (9 calories per gram).
    fat_calories = target_calories * 0.25
    fat_g = fat_calories / 9
 
    # Carbs: whatever calories are left (4 calories per gram).
    carb_calories = target_calories - protein_calories - fat_calories
    carb_g = max(carb_calories / 4, 0)
 
    return {
        "calories": round(target_calories),
        "protein_g": round(protein_g),
        "carbs_g": round(carb_g),
        "fat_g": round(fat_g),
    }
 
 

# SECTION 4 — MEAL SUGGESTER
# Builds a structured day of three meals (breakfast, lunch, dinner). Each
# meal gets roughly a third of the day's macro targets as its own budget,
# and is filled by adding foods one serving at a time. Variety is enforced
# two ways: a food can repeat only twice within a single meal, and a food
# already used earlier in the day is penalised so later meals look different.
 
# The three meals of the day and how the daily macros are split between them.
# Lunch and dinner get slightly more than breakfast, which is realistic.
MEAL_PLAN = [
    {"name": "Breakfast", "share": 0.30},
    {"name": "Lunch", "share": 0.35},
    {"name": "Dinner", "share": 0.35},
]
 
 
def _build_one_meal(meal_targets: dict, breakfast: bool,
                    used_today: dict) -> dict:
#Build a single meal that fits within `meal_targets`.
#`breakfast` nudges the scoring toward breakfast-style foods.
#`used_today` counts how many times each food was used in earlier meals,
#so this meal can avoid repeating them and stay varied.
#Returns a dict with a 'foods' list and a 'totals' dict for the meal.
    totals = {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}
    chosen_counts = {}                 # servings of each food in THIS meal
    max_servings_per_food = 2          # limit repeats within one meal
    calorie_floor = meal_targets["calories"] * 0.90
 
    def remaining(macro: str) -> float:
        """Return how far below this meal's target a macro still is."""
        return max(meal_targets[macro] - totals[macro], 0)
 
    def score_food(food: dict) -> float:
    #Score how useful adding one serving of this food would be.
    #Higher is better. The score rewards filling macros the meal still
    #needs, nudges breakfast foods at breakfast, and penalises foods
    #already eaten earlier in the day so the day stays varied.
        protein_value = min(food["protein_g"], remaining("protein_g")) * 3.0
        carb_value = min(food["carbs_g"], remaining("carbs_g")) * 1.0
        fat_value = min(food["fat_g"], remaining("fat_g")) * 1.0
        score = protein_value + carb_value + fat_value
 
        # Nudge: at breakfast, strongly favour breakfast-style foods and
        # discourage dinner-style foods (raw chicken, beef, salad greens
        # rarely belong at breakfast). This is a preference, not a ban.
        if breakfast:
            if food["breakfast_friendly"]:
                score *= 1.6     # boost eggs, oats, yogurt, fruit, etc.
            else:
                score *= 0.45    # hold back chicken, beef, rice, etc.
 
        # Variety penalty: the more this food was used earlier today,
        # the less attractive it becomes now (each prior use cuts 35%).
        prior_uses = used_today.get(food["name"], 0)
        score *= (0.65 ** prior_uses)
 
        return score
 
    # Add foods one serving at a time until the meal is full enough.
    safety_limit = 25  # cap on servings per meal, prevents endless loops
    while safety_limit > 0:
        safety_limit -= 1
 
        best_food = None
        best_score = 0.0
 
        for food in FOOD_DATABASE:
            # Skip foods that would push this meal over its calorie budget.
            if totals["calories"] + food["calories"] > meal_targets["calories"]:
                continue
            # Skip foods already used the max number of times in this meal.
            if chosen_counts.get(food["name"], 0) >= max_servings_per_food:
                continue
 
            score = score_food(food)
            if score > best_score:
                best_score = score
                best_food = food
 
        # Stop if nothing helps this meal anymore.
        if best_food is None or best_score <= 0:
            break
 
        # Add the chosen food to this meal's totals.
        for macro in ("calories", "protein_g", "carbs_g", "fat_g"):
            totals[macro] += best_food[macro]
        chosen_counts[best_food["name"]] = (
            chosen_counts.get(best_food["name"], 0) + 1)
 
        # Stop once the meal is close enough to its calorie budget.
        if totals["calories"] >= calorie_floor:
            break
 
    # Build a readable food list for this meal.
    foods = []
    for food in FOOD_DATABASE:
        count = chosen_counts.get(food["name"], 0)
        if count > 0:
            foods.append({
                "name": food["name"],
                "serving": food["serving"],
                "servings": count,
            })
 
    return {"foods": foods, "totals": totals}
 
 
def suggest_meal(targets: dict) -> dict:
#Return a full day of meals (breakfast, lunch, dinner) for the targets.
#The result has:
#- 'meals': a list of {name, foods, totals} for each of the 3 meals
#- 'totals': the macros summed across the whole day

    # Tracks how many times each food has been used across the day so far,
    # so later meals can avoid repeating earlier ones.
    used_today = {}
 
    meals = []
    day_totals = {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}
 
    for meal_def in MEAL_PLAN:
        # Each meal's budget is its share of the daily targets.
        share = meal_def["share"]
        meal_targets = {
            "calories": targets["calories"] * share,
            "protein_g": targets["protein_g"] * share,
            "carbs_g": targets["carbs_g"] * share,
            "fat_g": targets["fat_g"] * share,
        }
 
        is_breakfast = (meal_def["name"] == "Breakfast")
        meal = _build_one_meal(meal_targets, is_breakfast, used_today)
 
        # Record this meal's foods into the day-wide usage counter.
        for item in meal["foods"]:
            used_today[item["name"]] = (
                used_today.get(item["name"], 0) + item["servings"])
 
        # Add this meal's macros to the running day total.
        for macro in ("calories", "protein_g", "carbs_g", "fat_g"):
            day_totals[macro] += meal["totals"][macro]
 
        meals.append({
            "name": meal_def["name"],
            "foods": meal["foods"],
            "totals": meal["totals"],
        })
 
    return {"meals": meals, "totals": day_totals}
 
 

# SECTION 5 — CONTENT GENERATOR
# Builds content ideas tailored to a client's actual profile, instead of
# random items. Ideas are chosen based on the client's goal and activity.
 
def generate_content_ideas(client: dict) -> list:
#Return a list of content ideas tailored to one client's profile
    goal = client["goal"]
    activity = client["activity"]
    name = client["name"]
 
    ideas = []
 
    # --- Goal-driven ideas -------------------------------------------------
    if goal == "fat_loss":
        ideas.append(("Instagram Reel",
                       "A full day of eating in a calorie deficit"))
        ideas.append(("Email Newsletter",
                       "How to feel full while eating fewer calories"))
        ideas.append(("Carousel",
                       "5 high-volume, low-calorie food swaps"))
    elif goal == "muscle_gain":
        ideas.append(("Instagram Reel",
                       "Hitting a calorie surplus without junk food"))
        ideas.append(("Email Newsletter",
                       "Easy ways to add 300 quality calories a day"))
        ideas.append(("Carousel",
                       "Best high-protein foods for building muscle"))
    else:  # maintenance
        ideas.append(("Instagram Reel",
                       "What eating at maintenance actually looks like"))
        ideas.append(("Email Newsletter",
                       "Staying consistent once you've hit your goal"))
        ideas.append(("Carousel",
                       "How to keep results without strict tracking"))
 
    # --- Activity-driven idea ---------------------------------------------
    if activity in ("sedentary", "light"):
        ideas.append(("LinkedIn Post",
                       "Nutrition tips for clients with a desk-bound routine"))
    else:
        ideas.append(("LinkedIn Post",
                       "Fueling an active training schedule the right way"))
 
    # --- A personalised client-story idea ---------------------------------
    goal_label = goal.replace("_", " ")
    ideas.append(("Client Story",
                  f"Behind {name}'s {goal_label} plan: a coach's breakdown"))
 
    return ideas
 
 
# SECTION 6 — CLIENT STORAGE
# Loads and saves the client list so data survives between sessions.
 
def load_clients() -> list:
#Return the saved client list, or an empty list if none exists yet
    if not os.path.exists(CLIENTS_FILE):
        return []
    try:
        with open(CLIENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # If the file is missing or corrupt, start fresh rather than crash.
        print("  Warning: could not read saved clients; starting empty.")
        return []
 
 
def save_clients(clients: list) -> None:
    """Write the client list to disk as JSON."""
    with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(clients, f, indent=2)
 
 

# SECTION 7 — MENU ACTIONS
# Each function below handles one menu option the coach can choose.
 
def add_client(clients: list) -> None:
#Prompt the coach for one new client and append it to the list
    print("\n--- Add a new client ---")
 
    name = ask_text("  Client name: ")
    goal = ask_choice("  Goal:", list(GOAL_CALORIE_ADJUSTMENT.keys()))
    sex = ask_choice("  Sex:", ["male", "female"])
    weight_lbs = ask_number("  Body weight (lbs): ", minimum=50)
    height_inches = ask_number("  Height (inches): ", minimum=36)
    age = ask_number("  Age (years): ", minimum=13)
    activity = ask_choice("  Activity level:",
                          list(ACTIVITY_MULTIPLIERS.keys()))
 
    client = {
        "name": name,
        "goal": goal,
        "sex": sex,
        "weight_lbs": weight_lbs,
        "height_inches": height_inches,
        "age": int(age),
        "activity": activity,
    }
    clients.append(client)
    save_clients(clients)
    print(f"\n  Client '{name}' added and saved.")
 
 
def edit_client(clients: list) -> None:
#Let the coach pick a client and update any of its fields.
#For each field, the current value is shown and the coach can press Enter
#to keep it or type a new value to change it. New values are validated
#the same way 'Add a client' validates them.
    index = pick_client(clients, action_label="edit")
    if index is None:
        return  # the coach cancelled or no clients exist
 
    client = clients[index]
    print(f"\n--- Editing '{client['name']}' "
          "(press Enter to keep a value) ---")
 
    # --- Name --------------------------------------------------------------
    # We only validate the new name if the coach actually typed one.
    new_name = input(f"  Name [{client['name']}]: ").strip()
    if new_name:
        client["name"] = new_name
 
    # --- Goal --------------------------------------------------------------
    # ask_choice always requires a pick, so we wrap it in a yes/no first.
    if ask_yes_no(f"  Change goal "
                  f"(currently {client['goal'].replace('_', ' ').title()})? "
                  "[y/n]: "):
        client["goal"] = ask_choice(
            "  New goal:", list(GOAL_CALORIE_ADJUSTMENT.keys()))
 
    # --- Sex ---------------------------------------------------------------
    if ask_yes_no(f"  Change sex (currently {client['sex'].title()})? "
                  "[y/n]: "):
        client["sex"] = ask_choice("  New sex:", ["male", "female"])
 
    # --- Weight ------------------------------------------------------------
    # For numbers, we accept an empty Enter to mean "keep current value".
    raw = input(f"  Weight in lbs [{client['weight_lbs']}]: ").strip()
    if raw:
        try:
            new_weight = float(raw)
            if new_weight >= 50:
                client["weight_lbs"] = new_weight
            else:
                print("  Weight not changed (must be at least 50).")
        except ValueError:
            print("  Weight not changed (not a number).")
 
    # --- Height ------------------------------------------------------------
    raw = input(f"  Height in inches [{client['height_inches']}]: ").strip()
    if raw:
        try:
            new_height = float(raw)
            if new_height >= 36:
                client["height_inches"] = new_height
            else:
                print("  Height not changed (must be at least 36).")
        except ValueError:
            print("  Height not changed (not a number).")
 
    # --- Age ---------------------------------------------------------------
    raw = input(f"  Age [{client['age']}]: ").strip()
    if raw:
        try:
            new_age = int(float(raw))  # accept '30' or '30.0'
            if new_age >= 13:
                client["age"] = new_age
            else:
                print("  Age not changed (must be at least 13).")
        except ValueError:
            print("  Age not changed (not a number).")
 
    # --- Activity ----------------------------------------------------------
    if ask_yes_no(f"  Change activity level (currently "
                  f"{client['activity'].title()})? [y/n]: "):
        client["activity"] = ask_choice(
            "  New activity level:", list(ACTIVITY_MULTIPLIERS.keys()))
 
    # Save the updated client list to disk so the change persists.
    save_clients(clients)
    print(f"\n  Client '{client['name']}' updated and saved.")
 
 
def delete_client(clients: list) -> None: #coach/user pick a client and delete it after a confirmation
    index = pick_client(clients, action_label="delete")
    if index is None:
        return  # the coach cancelled or no clients exist
 
    client = clients[index]
 
    # Always confirm before a destructive action, naming the client clearly.
    if not ask_yes_no(f"\n  Delete '{client['name']}'? "
                      "This cannot be undone. [y/n]: "):
        print("  Deletion cancelled.")
        return
 
    # Remove the client from the list, then save the new list.
    removed = clients.pop(index)
    save_clients(clients)
    print(f"\n  Client '{removed['name']}' deleted.")
 
 
def show_client_report(client: dict) -> None: #Print a full on-screen report for one client
    targets = calculate_macro_targets(client)
    day = suggest_meal(targets)
    ideas = generate_content_ideas(client)
 
    print("\n" + "=" * 60)
    print(f"  {client['name']}  "
          f"({client['goal'].replace('_', ' ').title()})")
    print("=" * 60)
 
    # Macro targets.
    print("  Daily macro targets:")
    print(f"    Calories: {targets['calories']}")
    print(f"    Protein:  {targets['protein_g']} g")
    print(f"    Carbs:    {targets['carbs_g']} g")
    print(f"    Fat:      {targets['fat_g']} g")
 
    # Suggested meals, grouped breakfast / lunch / dinner.
    print("\n  Suggested meals for the day:")
    for meal in day["meals"]:
        print(f"\n    {meal['name']}:")
        if not meal["foods"]:
            print("      (No suitable foods found for this meal.)")
        for item in meal["foods"]:
            print(f"      - {item['servings']} x {item['name']} "
                  f"({item['serving']})")
        m = meal["totals"]
        print(f"      Subtotal: {m['calories']} cal | "
              f"{m['protein_g']}g P | {m['carbs_g']}g C | {m['fat_g']}g F")
 
    # Whole-day total.
    t = day["totals"]
    print(f"\n    DAY TOTAL: {t['calories']} cal | {t['protein_g']}g protein "
          f"| {t['carbs_g']}g carbs | {t['fat_g']}g fat")
 
    # Tailored content ideas.
    print("\n  Tailored content ideas:")
    for platform, title in ideas:
        print(f"    [{platform}] {title}")
 
 
def view_all_clients(clients: list) -> None:
    """Print on-screen reports for every saved client."""
    if not clients:
        print("\n  No clients yet. Choose 'Add a client' first.")
        return
    for client in clients:
        show_client_report(client)
 
 
def export_report(clients: list) -> None: #Write a full coaching report file and a summary CSV for all clients
    if not clients:
        print("\n  No clients yet. Add a client before exporting.")
        return
 
    # --- Build the text report --------------------------------------------
    lines = []
    lines.append("=" * 64)
    lines.append("  COACHING REPORT".center(64))
    lines.append("=" * 64)
 
    for client in clients:
        targets = calculate_macro_targets(client)
        day = suggest_meal(targets)
        ideas = generate_content_ideas(client)
 
        lines.append("")
        lines.append(f"  {client['name']}  "
                     f"({client['goal'].replace('_', ' ').title()})")
        lines.append("  " + "-" * 60)
        lines.append(f"  Daily targets: {targets['calories']} cal | "
                     f"{targets['protein_g']}g protein | "
                     f"{targets['carbs_g']}g carbs | "
                     f"{targets['fat_g']}g fat")
 
        lines.append("")
        lines.append("  Suggested meals for the day:")
        for meal in day["meals"]:
            lines.append(f"    {meal['name']}:")
            for item in meal["foods"]:
                lines.append(f"      - {item['servings']} x {item['name']} "
                             f"({item['serving']})")
            m = meal["totals"]
            lines.append(f"      Subtotal: {m['calories']} cal | "
                         f"{m['protein_g']}g P | {m['carbs_g']}g C | "
                         f"{m['fat_g']}g F")
        t = day["totals"]
        lines.append(f"    DAY TOTAL: {t['calories']} cal | "
                     f"{t['protein_g']}g protein | "
                     f"{t['carbs_g']}g carbs | {t['fat_g']}g fat")
 
        lines.append("")
        lines.append("  Tailored content ideas:")
        for platform, title in ideas:
            lines.append(f"    [{platform}] {title}")
        lines.append("")
 
    lines.append("=" * 64)
 
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
 
    # --- Build the summary CSV --------------------------------------------
    with open(SUMMARY_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "client", "goal", "target_calories",
            "target_protein_g", "target_carbs_g", "target_fat_g",
        ])
        for client in clients:
            targets = calculate_macro_targets(client)
            writer.writerow([
                client["name"], client["goal"], targets["calories"],
                targets["protein_g"], targets["carbs_g"], targets["fat_g"],
            ])
 
    print(f"\n  Report exported to:  {REPORT_FILE}")
    print(f"  Summary exported to: {SUMMARY_FILE}")
 
 

# MAIN — the interactive menu loop
def main() -> None: #Run the interactive menu until the coach chooses to exit.
    print("=" * 60)
    print("  MACRO PLANNER + NUTRITION TRACKER".center(60))
    print("=" * 60)
 
    # Load any clients saved from a previous session.
    clients = load_clients()
    if clients:
        print(f"  Loaded {len(clients)} saved client(s).")
 
    # The menu repeats until the coach picks 'Exit'.
    while True:
        print("\nMenu:")
        print("  1. Add a client")
        print("  2. View all clients and reports")
        print("  3. Edit a client")
        print("  4. Delete a client")
        print("  5. Export report to file")
        print("  6. Exit")
 
        choice = input("Enter your choice (1-6): ").strip()
 
        if choice == "1":
            add_client(clients)
        elif choice == "2":
            view_all_clients(clients)
        elif choice == "3":
            edit_client(clients)
        elif choice == "4":
            delete_client(clients)
        elif choice == "5":
            export_report(clients)
        elif choice == "6":
            print("\nGoodbye.")
            break
        else:
            print("  Please enter a number between 1 and 6.")
 
 
if __name__ == "__main__":
    main()