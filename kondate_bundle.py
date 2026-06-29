from __future__ import annotations

# ===== engine\models.py =====
"""データモデル（レシピ / プロフィール / 週リクエスト）とローダ。

MEAL_PLANNER_SPEC.md §5・§9 のスキーマに対応。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

# 曜日（index 0=月 〜 6=日。週は月曜始まり）
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]

# 平日（夕食の時間/スキル上限がかかる調理日）= 月〜金
WEEKDAY_COOK_DAYS = {0, 1, 2, 3, 4}

# 可算単位（買い物時に切り上げて整数化する単位）
COUNTABLE_UNITS = {"個", "本", "束", "枚", "片", "丁", "袋", "切", "玉", "株", "パック",
                   "合", "尾", "缶", "かけ", "節"}

# 食中毒リスクの高い月（§8）
SUMMER_MONTHS = {6, 7, 8, 9}


@dataclass
class Ingredient:
    key: str
    name: str
    qty: float
    unit: str
    category: str  # protein | vegetable | seasoning | staple | other

    @staticmethod
    def from_dict(d: dict) -> "Ingredient":
        return Ingredient(
            key=d["key"], name=d["name"], qty=float(d["qty"]),
            unit=d["unit"], category=d.get("category", "other"),
        )


@dataclass
class Recipe:
    id: str
    name: str
    type: str          # main | side | soup | staple
    cuisine: str       # 和 | 洋 | 中 | エスニック
    protein: str       # chicken|pork|beef|fish|seafood|egg|tofu|soy|none|mixed
    richness: int      # 1..3
    base_servings: int
    ingredients: list[Ingredient]
    allergens: list[str]
    cook_time_min: int
    skill: int         # 1..3
    bento_ok: bool
    scalable: bool
    bento_safety: dict
    make_ahead_days: int
    steps: list[str]
    tags: list[str] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict) -> "Recipe":
        return Recipe(
            id=d["id"], name=d["name"], type=d["type"], cuisine=d["cuisine"],
            protein=d.get("protein", "none"), richness=int(d["richness"]),
            base_servings=int(d["base_servings"]),
            ingredients=[Ingredient.from_dict(i) for i in d["ingredients"]],
            allergens=list(d.get("allergens", [])),
            cook_time_min=int(d["cook_time_min"]), skill=int(d["skill"]),
            bento_ok=bool(d["bento_ok"]), scalable=bool(d["scalable"]),
            bento_safety=dict(d["bento_safety"]),
            make_ahead_days=int(d["make_ahead_days"]),
            steps=list(d.get("steps", [])), tags=list(d.get("tags", [])),
        )

    def ingredient_keys(self, *, exclude_pantry: bool = False) -> set[str]:
        """食材キー集合。exclude_pantry=True で seasoning/staple を除く。"""
        out = set()
        for ing in self.ingredients:
            if exclude_pantry and ing.category in ("seasoning", "staple"):
                continue
            out.add(ing.key)
        return out


@dataclass
class Profile:
    dinner_servings: int = 2
    bento_servings: int = 2
    weekday_time_limit: int = 30
    skill: int = 2
    staple_keys: set[str] = field(default_factory=set)
    exclude: set[str] = field(default_factory=set)

    @staticmethod
    def from_dict(d: dict) -> "Profile":
        return Profile(
            dinner_servings=int(d.get("dinner_servings", 2)),
            bento_servings=int(d.get("bento_servings", 2)),
            weekday_time_limit=int(d.get("weekday_time_limit", 30)),
            skill=int(d.get("skill", 2)),
            staple_keys=set(d.get("staple_keys", [])),
            exclude=set(d.get("exclude", [])),
        )


@dataclass
class WeekRequest:
    """今週の要件（§3 入力）。"""
    dinner_days: list[bool]      # 長さ7。夕食が要る日
    bento_days: list[bool]       # 長さ7。弁当が要る日
    inventory: dict[str, float]  # 手持ち在庫 key -> 数量（レシピ単位）
    missing_staples: list[str]   # 不足申告された常備品 key（買い物に追加）
    current_month: int           # 夏場判定用（1..12）

    @property
    def is_summer(self) -> bool:
        return self.current_month in SUMMER_MONTHS


def load_recipes(path: str | Path) -> tuple[list[Recipe], dict]:
    """recipes.json を読み込み (recipes, db_meta) を返す。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    recipes = [Recipe.from_dict(r) for r in data["recipes"]]
    meta = {k: v for k, v in data.items() if k != "recipes"}
    return recipes, meta


def load_profile(path: str | Path) -> Profile:
    return Profile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

# ===== build\ingredient_map.py =====
"""食材名→正規化キー＋カテゴリの決定的マッピング（ingredient_normalizer の中核）。

使い回し計算は key の一致で効くので、表記揺れを Python 側で吸収する。
LLM には任せず決定的に処理（再現性・信頼性のため）。
"""

import re

# (日本語名に含まれる部分文字列, 正規化キー, カテゴリ) ※具体的なものを先に
KEY_MAP: list[tuple[str, str, str]] = [
    # --- 肉 ---
    ("鶏もも", "chicken_thigh", "protein"), ("鶏モモ", "chicken_thigh", "protein"),
    ("鶏むね", "chicken_breast", "protein"), ("鶏ムネ", "chicken_breast", "protein"),
    ("鶏胸", "chicken_breast", "protein"), ("ムネ肉", "chicken_breast", "protein"),
    ("手羽", "chicken_wing", "protein"), ("鶏皮", "chicken_skin", "protein"),
    ("鶏ひき", "chicken_mince", "protein"), ("鶏挽", "chicken_mince", "protein"),
    ("鶏がら", "chicken_stock", "seasoning"), ("鶏ガラ", "chicken_stock", "seasoning"),
    ("鶏", "chicken_thigh", "protein"),
    ("合いびき", "beef_pork_mince", "protein"), ("合い挽", "beef_pork_mince", "protein"),
    ("合挽", "beef_pork_mince", "protein"),
    ("豚バラ", "pork_belly", "protein"), ("豚ロース", "pork_loin", "protein"),
    ("豚こま", "pork_komagire", "protein"), ("豚小間", "pork_komagire", "protein"),
    ("豚ひき", "pork_mince", "protein"), ("豚挽", "pork_mince", "protein"),
    ("豚", "pork_komagire", "protein"),
    ("牛", "beef_slice", "protein"),
    ("ベーコン", "bacon", "protein"), ("ウインナー", "sausage", "protein"),
    ("ソーセージ", "sausage", "protein"), ("ハム", "ham", "protein"),
    ("ひき肉", "mince", "protein"), ("挽肉", "mince", "protein"),
    # --- 魚介 ---
    ("鮭", "salmon", "protein"), ("サーモン", "salmon", "protein"),
    ("さば", "mackerel", "protein"), ("鯖", "mackerel", "protein"),
    ("ぶり", "yellowtail", "protein"), ("ブリ", "yellowtail", "protein"),
    ("鯛", "sea_bream", "protein"), ("あじ", "horse_mackerel", "protein"),
    ("鯵", "horse_mackerel", "protein"), ("白身魚", "white_fish", "protein"),
    ("まぐろ", "tuna", "protein"), ("マグロ", "tuna", "protein"),
    ("えび", "shrimp", "protein"), ("海老", "shrimp", "protein"), ("エビ", "shrimp", "protein"),
    ("いか", "squid", "protein"), ("イカ", "squid", "protein"),
    ("あさり", "clam", "protein"), ("かに", "crab", "protein"), ("カニ", "crab", "protein"),
    ("ツナ", "tuna_can", "protein"),
    # --- 卵・大豆 ---
    ("卵", "egg", "protein"), ("たまご", "egg", "protein"), ("玉子", "egg", "protein"),
    ("厚揚げ", "atsuage", "protein"), ("油揚げ", "abura_age", "protein"),
    ("豆腐", "tofu", "protein"), ("納豆", "natto", "protein"),
    ("おから", "okara", "protein"), ("大豆", "soybean", "protein"),
    # --- 野菜 ---
    ("玉ねぎ", "onion", "vegetable"), ("玉葱", "onion", "vegetable"),
    ("赤玉ねぎ", "red_onion", "vegetable"), ("たまねぎ", "onion", "vegetable"),
    ("長ねぎ", "green_onion", "vegetable"), ("長ネギ", "green_onion", "vegetable"),
    ("青ねぎ", "green_onion", "vegetable"), ("小ねぎ", "green_onion", "vegetable"),
    ("ねぎ", "green_onion", "vegetable"), ("ネギ", "green_onion", "vegetable"),
    ("にんじん", "carrot", "vegetable"), ("人参", "carrot", "vegetable"),
    ("じゃがいも", "potato", "vegetable"), ("じゃが芋", "potato", "vegetable"),
    ("ジャガイモ", "potato", "vegetable"),
    ("なす", "eggplant", "vegetable"), ("ナス", "eggplant", "vegetable"), ("茄子", "eggplant", "vegetable"),
    ("ピーマン", "green_pepper", "vegetable"), ("パプリカ", "paprika", "vegetable"),
    ("ブロッコリー", "broccoli", "vegetable"), ("ほうれん草", "spinach", "vegetable"),
    ("キャベツ", "cabbage", "vegetable"), ("白菜", "hakusai", "vegetable"),
    ("大根", "daikon", "vegetable"), ("ごぼう", "gobo", "vegetable"),
    ("きゅうり", "cucumber", "vegetable"), ("キュウリ", "cucumber", "vegetable"),
    ("トマト", "tomato", "vegetable"), ("ミニトマト", "cherry_tomato", "vegetable"),
    ("もやし", "moyashi", "vegetable"), ("にら", "nira", "vegetable"), ("ニラ", "nira", "vegetable"),
    ("しめじ", "shimeji", "vegetable"), ("えのき", "enoki", "vegetable"),
    ("しいたけ", "shiitake", "vegetable"), ("セロリ", "celery", "vegetable"),
    ("とうもろこし", "corn", "vegetable"), ("コーン", "corn", "vegetable"),
    ("大葉", "shiso", "vegetable"), ("紅生姜", "beni_shoga", "vegetable"),
    ("生姜", "ginger", "vegetable"), ("しょうが", "ginger", "vegetable"),
    ("にんにく", "garlic", "vegetable"), ("ニンニク", "garlic", "vegetable"),
    ("ひじき", "hijiki", "vegetable"), ("わかめ", "wakame", "vegetable"),
    # --- 調味料・粉・乳 ---
    ("醤油", "soy_sauce", "seasoning"), ("しょうゆ", "soy_sauce", "seasoning"),
    ("白だし", "shiro_dashi", "seasoning"), ("だし", "dashi", "seasoning"),
    ("出汁", "dashi", "seasoning"), ("味噌", "miso", "seasoning"), ("みそ", "miso", "seasoning"),
    ("みりん", "mirin", "seasoning"), ("砂糖", "sugar", "seasoning"),
    ("料理酒", "sake", "seasoning"), ("酒", "sake", "seasoning"),
    ("塩麹", "shio_koji", "seasoning"), ("塩", "salt", "seasoning"),
    ("こしょう", "pepper", "seasoning"), ("胡椒", "pepper", "seasoning"),
    ("酢", "vinegar", "seasoning"),
    ("ごま油", "sesame_oil", "seasoning"), ("ゴマ油", "sesame_oil", "seasoning"),
    ("サラダ油", "oil", "seasoning"), ("オリーブ", "olive_oil", "seasoning"),
    ("ごま", "sesame", "seasoning"), ("胡麻", "sesame", "seasoning"),
    ("ゴマ", "sesame", "seasoning"),
    ("片栗粉", "potato_starch", "seasoning"), ("薄力粉", "flour", "seasoning"),
    ("小麦粉", "flour", "seasoning"), ("パン粉", "breadcrumb", "seasoning"),
    ("マヨ", "mayo", "seasoning"), ("ケチャップ", "ketchup", "seasoning"),
    ("豆板醤", "doubanjiang", "seasoning"), ("甜麺醤", "tenmenjan", "seasoning"),
    ("オイスター", "oyster_sauce", "seasoning"), ("鶏がら", "chicken_stock", "seasoning"),
    ("コンソメ", "consomme", "seasoning"), ("ウスターソース", "sauce", "seasoning"),
    ("中濃ソース", "sauce", "seasoning"), ("ソース", "sauce", "seasoning"),
    ("バター", "butter", "seasoning"),
    ("牛乳", "milk", "seasoning"), ("豆乳", "soy_milk", "seasoning"),
    ("チーズ", "cheese", "seasoning"), ("生クリーム", "cream", "seasoning"),
    ("水", "water", "seasoning"),
    # --- 主食 ---
    ("ご飯", "rice", "staple"), ("ごはん", "rice", "staple"), ("米", "rice", "staple"),
    ("スパゲティ", "pasta", "staple"), ("パスタ", "pasta", "staple"),
    ("うどん", "udon", "staple"), ("そば", "soba", "staple"),
    ("食パン", "bread", "staple"), ("中華麺", "chinese_noodle", "staple"),
    # --- 追補（取りこぼし是正: カタカナ/表記揺れ/未登録） ---
    ("しょう油", "soy_sauce", "seasoning"),
    ("めんつゆ", "mentsuyu", "seasoning"), ("麺つゆ", "mentsuyu", "seasoning"),
    ("コショウ", "pepper", "seasoning"), ("コショー", "pepper", "seasoning"),
    ("七味", "chili", "seasoning"), ("一味", "chili", "seasoning"),
    ("唐辛子", "chili", "seasoning"), ("鷹の爪", "chili", "seasoning"),
    ("ラー油", "rayu", "seasoning"),
    ("白ワイン", "wine", "seasoning"), ("赤ワイン", "wine", "seasoning"), ("ワイン", "wine", "seasoning"),
    ("がらし", "karashi", "seasoning"), ("からし", "karashi", "seasoning"),
    ("辛子", "karashi", "seasoning"), ("マスタード", "mustard", "seasoning"),
    ("味の素", "umami", "seasoning"), ("ウェイパー", "weipa", "seasoning"),
    ("シャンタン", "weipa", "seasoning"), ("天ぷら粉", "flour", "seasoning"),
    ("ニンジン", "carrot", "vegetable"), ("ウィンナー", "sausage", "protein"),
    ("椎茸", "shiitake", "vegetable"), ("小松菜", "komatsuna", "vegetable"),
    ("レタス", "lettuce", "vegetable"), ("こんにゃく", "konnyaku", "vegetable"),
    ("コンニャク", "konnyaku", "vegetable"), ("パセリ", "parsley", "vegetable"),
    ("レモン", "lemon", "vegetable"), ("海苔", "nori", "vegetable"), ("のり", "nori", "vegetable"),
    ("餃子の皮", "gyoza_wrapper", "other"), ("焼売の皮", "shumai_wrapper", "other"),
    ("シュウマイの皮", "shumai_wrapper", "other"), ("バゲット", "baguette", "staple"),
    ("焼肉のタレ", "yakiniku_sauce", "seasoning"), ("焼き肉のタレ", "yakiniku_sauce", "seasoning"),
    ("塩昆布", "shio_kombu", "seasoning"), ("だしの素", "dashi", "seasoning"),
    ("アボカド", "avocado", "vegetable"), ("ズッキーニ", "zucchini", "vegetable"),
    ("みょうが", "myoga", "vegetable"), ("ミョウガ", "myoga", "vegetable"),
    ("アスパラ", "asparagus", "vegetable"), ("かぼちゃ", "pumpkin", "vegetable"),
    ("カボチャ", "pumpkin", "vegetable"), ("湯葉", "yuba", "protein"),
    ("ほうれん草", "spinach", "vegetable"), ("水菜", "mizuna", "vegetable"),
    ("お湯", "water", "seasoning"), ("湯", "water", "seasoning"),
    ("アボガド", "avocado", "vegetable"), ("ブロッコリー", "broccoli", "vegetable"),
    ("マッシュルーム", "mushroom", "vegetable"), ("ブイヨン", "consomme", "seasoning"),
    ("クミン", "spice", "seasoning"), ("コリアンダー", "spice", "seasoning"),
    ("ナツメグ", "spice", "seasoning"), ("サフラン", "spice", "seasoning"),
    ("パウダー", "spice", "seasoning"), ("バジル", "basil", "vegetable"),
    ("ライスペーパー", "rice_paper", "other"), ("オリーブオイル", "olive_oil", "seasoning"),
    # --- 追補2 (2026-06-28 増量分の取りこぼし是正) ※具体的→汎用の順を維持 ---
    ("醬油", "soy_sauce", "seasoning"),                       # 旧字「醬」
    ("中華風スープの素", "chicken_stock", "seasoning"), ("中華スープの素", "chicken_stock", "seasoning"),
    ("鶏ガラスープ", "chicken_stock", "seasoning"), ("鶏がらスープ", "chicken_stock", "seasoning"),
    ("ローリエ", "bay_leaf", "seasoning"), ("ローレル", "bay_leaf", "seasoning"),
    ("カレールー", "curry", "seasoning"), ("カレールウ", "curry", "seasoning"), ("カレー粉", "curry", "seasoning"),
    ("てんぷら粉", "flour", "seasoning"), ("クレイジーソルト", "salt", "seasoning"),
    ("はちみつ", "honey", "seasoning"), ("蜂蜜", "honey", "seasoning"), ("メープル", "syrup", "seasoning"),
    ("ラカント", "sugar", "seasoning"), ("サムジャン", "ssamjang", "seasoning"),
    ("わさび", "wasabi", "seasoning"), ("ショウガ", "ginger", "vegetable"),
    ("かつお節", "dashi", "seasoning"), ("鰹節", "dashi", "seasoning"), ("かつおぶし", "dashi", "seasoning"),
    ("かつお", "bonito", "protein"), ("カツオ", "bonito", "protein"), ("鰹", "bonito", "protein"),
    ("いわし", "sardine", "protein"), ("イワシ", "sardine", "protein"), ("鰯", "sardine", "protein"),
    ("さつま揚げ", "satsumaage", "protein"), ("ちくわ", "chikuwa", "protein"),
    ("はんぺん", "hanpen", "protein"), ("かまぼこ", "kamaboko", "protein"),
    ("卯の花", "okara", "protein"), ("薄揚げ", "abura_age", "protein"),
    ("三つ葉", "mitsuba", "vegetable"), ("みつば", "mitsuba", "vegetable"),
    ("ししとう", "shishito", "vegetable"), ("シシトウ", "shishito", "vegetable"),
    ("グリンピース", "green_pea", "vegetable"), ("グリーンピース", "green_pea", "vegetable"),
    ("長芋", "yam", "vegetable"), ("山芋", "yam", "vegetable"), ("長いも", "yam", "vegetable"),
    ("たけのこ", "bamboo", "vegetable"), ("筍", "bamboo", "vegetable"),
    ("竹の子", "bamboo", "vegetable"), ("真竹", "bamboo", "vegetable"),
    ("ふき", "fuki", "vegetable"), ("わらび", "warabi", "vegetable"), ("ぜんまい", "zenmai", "vegetable"),
    ("みず菜", "mizuna", "vegetable"), ("エノキ", "enoki", "vegetable"), ("シメジ", "shimeji", "vegetable"),
    ("マイタケ", "maitake", "vegetable"), ("まいたけ", "maitake", "vegetable"),
    ("えりんぎ", "eringi", "vegetable"), ("エリンギ", "eringi", "vegetable"),
    ("オクラ", "okra", "vegetable"), ("ゴーヤ", "goya", "vegetable"),
    ("れんこん", "renkon", "vegetable"), ("レンコン", "renkon", "vegetable"), ("蓮根", "renkon", "vegetable"),
    ("さつまいも", "satsumaimo", "vegetable"), ("さつま芋", "satsumaimo", "vegetable"),
    ("里芋", "satoimo", "vegetable"), ("さといも", "satoimo", "vegetable"),
    ("かいわれ", "kaiware", "vegetable"), ("豆苗", "toumyou", "vegetable"),
    ("春菊", "shungiku", "vegetable"), ("チンゲン菜", "chingensai", "vegetable"),
    ("ブラックペッパー", "pepper", "seasoning"), ("ペッパー", "pepper", "seasoning"),
    ("粉チーズ", "cheese", "seasoning"), ("ピザ用チーズ", "cheese", "seasoning"),
    ("コチュジャン", "gochujang", "seasoning"), ("コチジャン", "gochujang", "seasoning"),
    ("キムチの素", "kimchi", "seasoning"), ("キムチ", "kimchi", "vegetable"),
    ("ナンプラー", "fish_sauce", "seasoning"), ("ナムプラー", "fish_sauce", "seasoning"),
    ("甜面醤", "tenmenjan", "seasoning"), ("強力粉", "flour", "seasoning"),
    ("昆布茶", "kombu_cha", "seasoning"), ("昆布", "kombu", "seasoning"), ("甜菜糖", "sugar", "seasoning"),
    ("きのこ", "mushroom", "vegetable"), ("しらす", "shirasu", "protein"), ("シラス", "shirasu", "protein"),
    ("たこ", "octopus", "protein"), ("タコ", "octopus", "protein"),
    ("ホタテ", "scallop", "protein"), ("帆立", "scallop", "protein"),
    ("ハマチ", "yellowtail", "protein"), ("たら", "white_fish", "protein"), ("鱈", "white_fish", "protein"),
    ("春雨", "harusame", "staple"),
    ("油", "oil", "seasoning"),                               # 揚げ油等（醤油/ごま油/サラダ油等は上で既出）
    ("肉", "mince", "protein"),
]

# キー→カテゴリ（protein 推定などの逆引き用）
_PROTEIN_KEYS = {k for _, k, c in KEY_MAP if c == "protein"}

# 個数で数える食材の正規単位（在庫入力の単位＆不整合表示の是正に使用）
CANONICAL_UNITS = {
    "onion": "個", "red_onion": "個", "tomato": "個", "cherry_tomato": "個",
    "potato": "個", "cabbage": "玉", "hakusai": "玉", "lettuce": "玉",
    "carrot": "本", "cucumber": "本", "eggplant": "本", "daikon": "本",
    "gobo": "本", "green_onion": "本", "zucchini": "本", "celery": "本",
    "asparagus": "本", "corn": "本",
    "green_pepper": "個", "paprika": "個", "avocado": "個", "lemon": "個", "pumpkin": "個",
    "broccoli": "株",
    "nira": "束", "spinach": "束", "komatsuna": "束", "mizuna": "束",
    "moyashi": "袋", "shimeji": "袋", "enoki": "袋", "shiitake": "枚", "mushroom": "パック",
    "egg": "個", "tofu": "丁", "atsuage": "枚", "abura_age": "枚",
    "mackerel": "切", "yellowtail": "切", "salmon": "切", "sea_bream": "切",
    "shishito": "本", "yam": "本", "renkon": "節", "satsumaimo": "本", "satoimo": "個",
    "okra": "本", "goya": "本", "satsumaage": "枚", "eringi": "本", "maitake": "パック",
    "sardine": "尾", "bamboo": "本", "chikuwa": "本",
}
# 個数系の単位（これ以外の単位を count 食材が持っていたらデータ不整合とみなす）
COUNT_FAMILY = {"個", "玉", "本", "株", "束", "袋", "枚", "パック", "切", "丁", "尾", "片", "コ"}


# 単位の表記揺れ・中国語変種 → 標準単位
_UNIT_VARIANTS = {
    "小匙": "tsp", "小さじ": "tsp", "こさじ": "tsp", "小勺": "tsp", "小サジ": "tsp",
    "大匙": "tbsp", "大勺": "tbsp", "大さじ": "tbsp", "おおさじ": "tbsp", "大サジ": "tbsp",
    "大": "tbsp", "小": "tsp",   # 調味料の大さじ/小さじ略（実データはほぼ調味料）
    "カップ": "cup", "コ": "個", "ｺ": "個", "切れ": "切", "缶詰": "缶",
    "㏄": "cc", "ＣＣ": "cc", "Ｃ": "cc",
}
# 量が決まらない曖昧単位 → 適量
_TEKIRYO_UNITS = {
    "少々", "少量", "少し", "少许", "少", "つまみ", "ひとつまみ", "ふたつまみ", "一つまみ",
    "お好み", "お好みで", "適宜", "ちょっぴり", "ちょっと", "好きなだけ", "お好きなだけ",
    "数滴", "滴", "ひとまわし", "回し", "片手一杯分", "適量", "適度", "必要量",
}
# 認識する正規単位（これ以外の混入＝小口切り/片手等は適量扱い）
_KNOWN_UNITS = {
    "g", "ml", "cc", "cup", "個", "本", "株", "束", "袋", "パック", "切", "丁", "尾",
    "片", "缶", "玉", "tbsp", "tsp", "かけ", "cm", "合", "節", "大", "小", "適量",
}


def clean_unit(unit: str) -> str:
    """単位を標準化（コ→個 / 小匙→小さじ / 少々・お好み等→適量 / 不明な混入→適量）。"""
    u = (unit or "").strip()
    if "," in u or "、" in u:  # 「個, 大」等のゴミは先頭を採用
        u = u.replace("、", ",").split(",")[0].strip()
    u = _UNIT_VARIANTS.get(u, u)
    if u in _TEKIRYO_UNITS:
        return "適量"
    if u in _KNOWN_UNITS:
        return u
    return "適量"          # 「小口切り」「1cm」「片手一杯分」等の混入は適量に

# key→アレルゲン（§8 安全。材料キーから決定的に導出）
ALLERGEN_BY_KEY: dict[str, list[str]] = {
    "egg": ["egg"], "mayo": ["egg"],
    "tofu": ["soy"], "atsuage": ["soy"], "abura_age": ["soy"], "natto": ["soy"],
    "soybean": ["soy"], "soy_milk": ["soy"], "miso": ["soy"],
    "soy_sauce": ["soy", "wheat"], "doubanjiang": ["soy"], "tenmenjan": ["soy", "wheat"],
    "mentsuyu": ["soy", "wheat"], "weipa": ["soy"],
    "flour": ["wheat"], "breadcrumb": ["wheat"], "pasta": ["wheat"], "udon": ["wheat"],
    "chinese_noodle": ["wheat"], "bread": ["wheat"], "baguette": ["wheat"],
    "gyoza_wrapper": ["wheat"], "shumai_wrapper": ["wheat"],
    "milk": ["milk"], "butter": ["milk"], "cheese": ["milk"], "cream": ["milk"],
    "shrimp": ["shrimp"], "crab": ["crab"], "squid": ["squid"],
    "sesame": ["sesame"], "salmon": ["salmon"], "mackerel": ["mackerel"],
}


def derive_allergens(keys: list[str]) -> set[str]:
    out: set[str] = set()
    for k in keys:
        out.update(ALLERGEN_BY_KEY.get(k, []))
    return out


_GROUP_PREFIX = re.compile(r"^[（(【＜<\[]?[A-Za-zＡ-Ｚ０-９0-9]{1,2}[）)】＞>\]]?\s*[：:.、]\s*")
_LEAD_SYM = re.compile(r"^[◎●○★☆＊*・\-–—\s　]+")
_PAREN = re.compile(r"[（(][^（）()]*[）)]")
_ALT = re.compile(r"又は|または|\bor\b|/|・|＋|\+")
# 切り方・下処理の語（材料名から除去して食材本体だけにする）。長いものを先に。
_PREP = re.compile(
    "みじん切り|みじん|すりおろし|おろし|水溶き|溶き|千切り|薄切り|うす切り|ざく切り|"
    "乱切り|細切り|角切り|輪切り|短冊切り|短冊|小口切り|くし形切り|くし切り|せん切り|"
    "一口大|の薄切り|の葉|スライス|チューブ|きざみ|刻み|下ろし"
)
_TRAIL = re.compile(r"[　\s、,.の]+$")


def clean_ingredient_name(name: str) -> str:
    """材料名のゴミ・下処理語を除去して食材本体だけにする。

    例: 「おろしニンニク」→「ニンニク」/「豚ロース薄切り」→「豚ロース」/
        「水溶き片栗粉」→「片栗粉」/「バジルの葉」→「バジル」。
    """
    s = (name or "").strip()
    s = _GROUP_PREFIX.sub("", s)   # 「A：」「(B)」「1.」等の材料グループ記号
    s = _LEAD_SYM.sub("", s)       # 先頭の記号・中黒
    s = _PAREN.sub("", s)          # （小口切り）等の注記
    s = _ALT.split(s)[0]           # 「又は」「・」「＋」等の代替・並記は先頭を採用
    s = _PREP.sub("", s)           # 切り方・下処理の語を除去
    s = _TRAIL.sub("", s)          # 末尾に残る「の」「、」空白を除去
    s = s.strip("　 ,、.")
    return s or (name or "").strip()


def normalize_key(name: str) -> tuple[str, str]:
    """日本語食材名 -> (key, category)。未知は名前から一意キーを作る（衝突回避）。"""
    for sub, key, cat in KEY_MAP:
        if sub in name:
            return key, cat
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:  # 日本語のみ → 名前そのものをキー化（全部 x_item に潰さない）
        slug = re.sub(r"[\s　]+", "", name)[:16]
    return f"x_{slug or 'item'}", "other"


def infer_protein(keys: list[str]) -> str:
    """正規化キー群から主たんぱく源を推定。"""
    table = {
        "chicken_thigh": "chicken", "chicken_breast": "chicken", "chicken_wing": "chicken",
        "chicken_mince": "chicken", "chicken_skin": "chicken",
        "pork_belly": "pork", "pork_loin": "pork", "pork_komagire": "pork", "pork_mince": "pork",
        "beef_slice": "beef", "beef_pork_mince": "beef", "mince": "mixed",
        "salmon": "fish", "mackerel": "fish", "yellowtail": "fish", "sea_bream": "fish",
        "horse_mackerel": "fish", "white_fish": "fish", "tuna": "fish",
        "shrimp": "seafood", "squid": "seafood", "clam": "seafood", "crab": "seafood",
        "egg": "egg", "tofu": "tofu", "atsuage": "tofu", "abura_age": "soy",
        "natto": "soy", "soybean": "soy", "okara": "soy",
        "bacon": "pork", "sausage": "pork", "ham": "pork",
    }
    # 出現順で最初に当たった主材料
    for k in keys:
        if k in table:
            return table[k]
    return "none"

# ===== engine\shopping.py =====
"""買い物リスト生成（MEAL_PLANNER_SPEC.md §6 常備除外 / §10-5 倍率 / §10-8 店導線順）。"""

import math
from dataclasses import dataclass, field


# 魚介キー（精肉・鮮魚セクション内の鮮魚判定）
FISH_KEYS = {"mackerel", "yellowtail", "salmon", "shrimp", "tuna"}
DAIRY_EGG_KEYS = {"tofu", "egg", "abura_age"}

# 店の導線順（§10-8）
SECTION_ORDER = ["青果", "精肉・鮮魚", "豆腐・卵・乳", "乾物・調味", "冷凍", "その他"]


def _section(ing: Ingredient) -> str:
    if ing.key in DAIRY_EGG_KEYS:
        return "豆腐・卵・乳"
    if ing.category == "protein":
        return "精肉・鮮魚"
    if ing.category == "vegetable":
        return "青果"
    if ing.category in ("seasoning", "staple"):
        return "乾物・調味"
    return "その他"


# 「適量/少々」は数量を持たない（合算してもナンセンス）
TO_TASTE_UNITS = {"適量", "少々", "お好み", "適宜"}
# 標準的な単位（cc/cm/本分 等の異常単位より優先して主要単位に採用）
GOOD_UNITS = COUNTABLE_UNITS | {"g", "ml", "tbsp", "tsp"}


def _round_qty(qty: float, unit: str) -> float:
    if unit in TO_TASTE_UNITS:
        return 0.0
    if unit in COUNTABLE_UNITS:
        return float(math.ceil(qty - 1e-9))
    # 重量/容量は安全側に5刻みで切り上げ
    return float(math.ceil((qty - 1e-9) / 5.0) * 5)


@dataclass
class ShoppingItem:
    key: str
    name: str
    qty: float
    unit: str
    section: str
    dishes: list[str]

    @property
    def reused(self) -> bool:
        return len(set(self.dishes)) >= 2


@dataclass
class ShoppingList:
    sections: dict[str, list[ShoppingItem]] = field(default_factory=dict)
    covered_by_inventory: list[str] = field(default_factory=list)
    excluded_pantry: int = 0

    def ordered(self) -> list[tuple[str, list[ShoppingItem]]]:
        return [(s, self.sections[s]) for s in SECTION_ORDER if self.sections.get(s)]

    def total_items(self) -> int:
        return sum(len(v) for v in self.sections.values())


def build_shopping_list(plan: Plan, profile: Profile, request: WeekRequest) -> ShoppingList:
    agg: dict[str, dict] = {}
    excluded = 0

    for unit in plan.production_units(profile):
        recipe = unit["recipe"]
        mult = unit["multiplier"]
        for ing in recipe.ingredients:
            is_pantry = (ing.category in ("seasoning", "staple")
                         or ing.key in profile.staple_keys)
            if is_pantry and ing.key not in request.missing_staples:
                excluded += 1
                continue
            slot = agg.setdefault(ing.key, {
                "name": ing.name, "category": ing.category, "key": ing.key,
                # 単位ごとに分けて集計（本/g/cm の混在合算を防ぐ）
                "units": {}, "dishes": [],
            })
            u = slot["units"].setdefault(ing.unit, {"count": 0, "qty": 0.0})
            u["count"] += 1
            u["qty"] += ing.qty * mult
            if recipe.name not in slot["dishes"]:
                slot["dishes"].append(recipe.name)

    sl = ShoppingList()
    sl.excluded_pantry = excluded
    for key, slot in agg.items():
        # 主要単位＝最も多くの料理で使われた「実単位」（適量類は除く）。混在の異常合算を回避
        real = {u: v for u, v in slot["units"].items() if u not in TO_TASTE_UNITS}
        if real:
            primary = max(real, key=lambda u: (u in GOOD_UNITS, real[u]["count"], real[u]["qty"]))
            needed, unit = real[primary]["qty"], primary
        else:
            needed, unit = 0.0, "適量"
        on_hand = request.inventory.get(key, 0)
        remaining = needed - on_hand
        ing_like = Ingredient(key=key, name=slot["name"], qty=0,
                              unit=unit, category=slot["category"])
        if unit not in TO_TASTE_UNITS and remaining <= 1e-9:
            sl.covered_by_inventory.append(slot["name"])
            continue
        item = ShoppingItem(
            key=key, name=slot["name"], qty=_round_qty(remaining, unit),
            unit=unit, section=_section(ing_like), dishes=slot["dishes"],
        )
        sl.sections.setdefault(item.section, []).append(item)

    # セクション内は使い回し品（複数料理で使う）を上に、次に名前順
    for items in sl.sections.values():
        items.sort(key=lambda it: (not it.reused, it.name))
    sl.covered_by_inventory.sort()
    return sl

# ===== engine\planner.py =====
"""スケジューラ＋スコアラ（MEAL_PLANNER_SPEC.md §6）。

ハード制約は決定的ルール、味/飽きはビルド時タグを実行時に読むだけ。
貪欲法＋軽いバックトラックで7枠を確定する。重いソルバーは使わない。
"""

import math
import random
from dataclasses import dataclass, field


# スコア重み（§6 初期値）
WEIGHTS = {
    "inventory": 10,  # 在庫消費（手持ちを使い切る）
    "reuse": 6,       # 食材使い回し（買い切り）
    "cuisine": 4,     # cuisine ローテ
    "richness": 3,    # richness 配置
    "protein": 2,     # protein 多様性
    "effort": 1,      # 平日の手間超過
}
# 残り物（在庫）消費はユーザー最優先事項。bias非依存の強い加点（在庫キー1つ当たり）。
INV_PRIORITY = 30.0


# ---------------------------------------------------------------- 適格判定

def allergy_ok(r: Recipe, profile: Profile) -> bool:
    if set(r.allergens) & profile.exclude:
        return False
    if r.ingredient_keys() & profile.exclude:
        return False
    return True


def bento_eligible(r: Recipe, is_summer: bool) -> bool:
    """弁当メイン適格（§8 ハード判定式）。"""
    s = r.bento_safety
    if not (r.bento_ok and r.scalable):
        return False
    if not s.get("needs_full_heat"):
        return False
    if s.get("raw_or_undercooked"):
        return False
    return True


def side_bento_ok(r: Recipe, profile: Profile, is_summer: bool) -> bool:
    if not r.bento_ok or not allergy_ok(r, profile):
        return False
    if r.bento_safety.get("raw_or_undercooked"):
        return False
    return True


def is_one_plate_main(r: Recipe) -> bool:
    """たんぱく質を含む一皿物 staple（丼/チャーハン/オムライス/パエリア等）は夕食メイン扱い。"""
    return r.type == "staple" and any(i.category == "protein" for i in r.ingredients)


# ---------------------------------------------------------------- 出力構造

@dataclass
class MakeAheadBatch:
    side: Recipe
    cook_day: int          # 調理する曜日 index
    covers_days: list[int]  # この作り置きでまかなう弁当日


@dataclass
class Plan:
    dinner_mains: list[Recipe | None]   # len 7
    dinner_sides: list[Recipe | None]   # len 7
    bento_days: list[bool]
    dinner_days: list[bool]
    makeahead: list[MakeAheadBatch] = field(default_factory=list)
    # 各夕食日の副菜がどの作り置きバッチ由来か（index）。None=その日に作る
    dinner_side_source: list[int | None] = field(default_factory=lambda: [None] * 7)
    dinner_soups: list[Recipe | None] = field(default_factory=lambda: [None] * 7)
    is_summer: bool = False
    metrics: dict = field(default_factory=dict)

    def carried_main(self, day: int) -> Recipe | None:
        """source基準: day の夕食を翌朝の弁当に取り分ける場合の主菜（弁当適格なら）。

        bento_days は「その夕食を翌朝の弁当に回す日」を表す（source基準）。
        日曜(6)の夕食は翌週月曜の弁当になる。今週月曜を弁当源にはしない。
        丼・刺身等で弁当に向かない場合は None（=要手当て）。最終判断はユーザー。
        """
        if not self.bento_days[day] or not self.dinner_days[day]:
            return None
        m = self.dinner_mains[day]
        if m and bento_eligible(m, self.is_summer):
            return m
        return None

    def bento_side(self, day: int) -> Recipe | None:
        for b in self.makeahead:
            if day in b.covers_days:
                return b.side
        return None

    def production_units(self, profile: Profile) -> list[dict]:
        """買い物・分量計算用の生産単位リスト。

        弁当メインは前夜夕食の「取り分け」なので独立ユニットにしない
        （夕食メインの portions に弁当人数を上乗せして表現）。
        """
        units: list[dict] = []
        for d in range(7):
            main = self.dinner_mains[d]
            if main:
                portions = profile.dinner_servings
                # この日の夕食を翌朝の弁当に回す（弁当適格な）場合は弁当人数分を上乗せ
                if self.carried_main(d) is main:
                    portions += profile.bento_servings
                units.append(_unit(main, portions, f"{WEEKDAYS[d]}夕食"))
        # 作り置きバッチ＝弁当分＋（同じ作り置きを夕食にも回す分）を1回でまとめて調理
        for bi, b in enumerate(self.makeahead):
            reuse_dn = sum(1 for d in range(7) if self.dinner_side_source[d] == bi)
            portions = (profile.bento_servings * len(b.covers_days)
                        + profile.dinner_servings * reuse_dn)
            label = (f"作り置き（弁当{len(b.covers_days)}日"
                     + (f"＋夕食{reuse_dn}回" if reuse_dn else "") + "分）")
            units.append(_unit(b.side, portions, label))
        # その日に作る夕食副菜（作り置き流用でないもの）
        for d in range(7):
            if not self.dinner_days[d] or self.dinner_side_source[d] is not None:
                continue
            side = self.dinner_sides[d]
            if side:
                units.append(_unit(side, profile.dinner_servings, f"{WEEKDAYS[d]}副菜"))
        # 汁物（その日に作る）
        for d in range(7):
            soup = self.dinner_soups[d]
            if soup:
                units.append(_unit(soup, profile.dinner_servings, f"{WEEKDAYS[d]}汁物"))
        return units


def _unit(recipe: Recipe, portions: int, role: str) -> dict:
    multiplier = max(1.0, portions / recipe.base_servings)
    return {
        "recipe": recipe, "portions": portions,
        "multiplier": multiplier, "role": role,
    }


# ---------------------------------------------------------------- スコアリング

def score_main(r: Recipe, d: int, assigned: list[Recipe | None],
               request: WeekRequest, profile: Profile, bias: float,
               protein_delta: dict[str, float] | None = None,
               force_consume: set[str] | None = None, jitter: float = 0.0) -> float:
    inv_keys = set(request.inventory)
    chosen_keys: set[str] = set()
    used_cuisines: set[str] = set()
    used_proteins: set[str] = set()
    for a in assigned:
        if a is None:
            continue
        chosen_keys |= a.ingredient_keys(exclude_pantry=True)
        used_cuisines.add(a.cuisine)
        if a.protein != "none":
            used_proteins.add(a.protein)

    r_keys = r.ingredient_keys(exclude_pantry=True)
    inv = len(r_keys & inv_keys)
    reuse = len(r_keys & chosen_keys)

    # 隣接日（実曜日）との衝突を見る
    left = assigned[d - 1] if d - 1 >= 0 else None
    right = assigned[d + 1] if d + 1 <= 6 else None

    cuisine_term = 0
    if left and left.cuisine == r.cuisine:
        cuisine_term -= 1
    if right and right.cuisine == r.cuisine:
        cuisine_term -= 1
    if r.cuisine not in used_cuisines:
        cuisine_term += 1

    richness_term = 0
    if r.richness == 3:
        if (left and left.richness == 3) or (right and right.richness == 3):
            richness_term -= 1

    protein_term = 1 if (r.protein != "none" and r.protein not in used_proteins) else 0

    effort_term = 0.0
    if d in WEEKDAY_COOK_DAYS:
        effort_term = r.cook_time_min / 10.0 + (r.skill - 1)

    save = WEIGHTS["inventory"] * inv + WEIGHTS["reuse"] * reuse
    variety = (WEIGHTS["cuisine"] * cuisine_term
               + WEIGHTS["richness"] * richness_term
               + WEIGHTS["protein"] * protein_term)

    # bias に依らないガードレール（試作で出た粗さの是正）
    guard = 0.0
    # こってり(richness3)を隣接させない：使い回し報酬に負けない重い減点
    if r.richness == 3 and ((left and left.richness == 3) or (right and right.richness == 3)):
        guard -= 50
    # 残り物（在庫）の消費を最優先：まだ使っていない残り物を新たに使う料理を最優先（bias非依存）。
    # 既に使った残り物の重複より、未使用の残り物のカバーを優先＝各残り物が最低1回使われやすい。
    new_inv = len((r_keys & inv_keys) - chosen_keys)
    if new_inv:
        guard += INV_PRIORITY * new_inv
    already_inv = inv - new_inv
    if already_inv:
        guard += 6.0 * already_inv
    # 一皿物（丼/チャーハン等）が週に偏らないよう、3品目以降は減点（残り物消費が勝てば例外）
    if is_one_plate_main(r) and sum(1 for a in assigned if a and is_one_plate_main(a)) >= 2:
        guard -= 20
    # たんぱく源の多様性を強める：その週でまだ出ていないproteinを優先（鯖×2・豚×2の単調を避ける）
    if r.protein != "none" and r.protein not in used_proteins:
        guard += 10
    # 週に最低1回は魚介を入れる：まだ魚介ゼロなら強めの加点
    if r.protein in ("fish", "seafood") and not any(
        a and a.protein in ("fish", "seafood") for a in assigned
    ):
        guard += 15
    # この日の夕食を翌朝の弁当に回す（source day）なら、弁当に向く主菜を強く優先。
    # 弁当不可（丼・汁麺・生・半熟卵等）は重く減点し、適格な主菜が他にある限り選ばれないようにする。
    is_source = (request.bento_days[d] and request.dinner_days[d])
    if is_source:
        if bento_eligible(r, request.is_summer):
            guard += 12
        else:
            guard -= 120

    # §7 コマンド由来の調整
    if force_consume and (r_keys & force_consume):       # この余り食材を使い切る
        guard += 40
    if protein_delta:                                    # カテゴリ増減（魚増やす/肉減らす）
        guard += protein_delta.get(r.protein, 0.0)
    guard += jitter                                      # 全体シャッフル用のゆらぎ

    # 単一つまみ variety_bias で「使い回し ↔ 飽き」を調整（§6）
    save_scale = (1 - bias) * 2
    variety_scale = bias * 2
    return (save_scale * save + variety_scale * variety
            - WEIGHTS["effort"] * effort_term + guard)


# ---------------------------------------------------------------- スケジューラ

def _main_candidates(d: int, mains: list[Recipe], request: WeekRequest,
                     profile: Profile, excluded_ids: set[str] | None = None,
                     time_limit: int | None = None) -> list[Recipe]:
    # 弁当縛りはハード制約から外した（丼・刺身等も夕食に出せる）。
    # 取り分け可能性は score_main のソフト加点で優先しつつ、最終判断はユーザー。
    limit = time_limit if time_limit is not None else profile.weekday_time_limit
    out = []
    weekday = d in WEEKDAY_COOK_DAYS
    for r in mains:
        if excluded_ids and r.id in excluded_ids:        # 差し替えで除外
            continue
        if not allergy_ok(r, profile):
            continue
        if weekday and (r.cook_time_min > limit or r.skill > profile.skill):
            continue
        out.append(r)
    return out


def schedule_week(recipes: list[Recipe], profile: Profile,
                  request: WeekRequest, variety_bias: float = 0.4,
                  include_side: bool = True, include_soup: bool = True,
                  washoku_target: float | None = None,
                  pins: dict[int, str] | None = None,
                  excluded_ids: set[str] | None = None,
                  force_consume: set[str] | None = None,
                  protein_delta: dict[str, float] | None = None,
                  weekday_time_override: int | None = None,
                  rng_seed: int | None = None) -> Plan:
    # 夕食メイン候補 = 主菜 ＋ たんぱく質入り一皿物（丼/チャーハン/オムライス等）
    mains = [r for r in recipes if r.type == "main" or is_one_plate_main(r)]
    sides = [r for r in recipes if r.type == "side"]
    soups = [r for r in recipes if r.type == "soup"]
    by_id = {r.id: r for r in recipes}
    pins = pins or {}

    # 全体シャッフル用のゆらぎ（レシピごとに固定値）
    jitter_map: dict[str, float] = {}
    if rng_seed is not None:
        rnd = random.Random(rng_seed)
        jitter_map = {r.id: rnd.uniform(-6, 6) for r in mains}

    needed = [d for d in range(7) if request.dinner_days[d]]
    cand_by_day = {d: _main_candidates(d, mains, request, profile,
                                       excluded_ids, weekday_time_override)
                   for d in needed}
    # 固定日は埋め込み済みとして外す。残りを候補の少ない日から（most-constrained-first）
    free = [d for d in needed if d not in pins]
    order = sorted(free, key=lambda d: len(cand_by_day[d]))

    # 和食比率の目標 → 非和食の上限本数（例: 7日×0.8 なら非和は1本まで）
    nonwa_cap = (len(needed) - round(len(needed) * washoku_target)
                 if washoku_target is not None else len(needed))

    assigned: list[Recipe | None] = [None] * 7
    used_ids: set[str] = set()
    protein_count: dict[str, int] = {}
    nonwa_count = [0]

    # 固定（pin）された日を先に確定（制約より優先：ユーザーが明示指定）
    for d, rid in pins.items():
        r = by_id.get(rid)
        if r is None or not request.dinner_days[d]:
            continue
        assigned[d] = r
        used_ids.add(r.id)
        protein_count[r.protein] = protein_count.get(r.protein, 0) + 1
        if r.cuisine != "和":
            nonwa_count[0] += 1

    def feasible(r: Recipe, d: int) -> bool:
        if r.id in used_ids:                       # 週内ユニーク
            return False
        if r.cuisine != "和" and nonwa_count[0] >= nonwa_cap:  # 和食比率の確保
            return False
        if r.protein != "none":
            if protein_count.get(r.protein, 0) >= 2:  # 週内 最大2回
                return False
            for d2 in range(7):                    # 同一proteinは中1日空け
                a = assigned[d2]
                if a and a.protein == r.protein and abs(d - d2) == 1:
                    return False
        return True

    def backtrack(i: int) -> bool:
        if i == len(order):
            return True
        d = order[i]
        ranked = sorted(
            cand_by_day[d],
            key=lambda r: score_main(r, d, assigned, request, profile, variety_bias,
                                     protein_delta, force_consume,
                                     jitter_map.get(r.id, 0.0)),
            reverse=True,
        )
        for r in ranked:
            if not feasible(r, d):
                continue
            assigned[d] = r
            used_ids.add(r.id)
            protein_count[r.protein] = protein_count.get(r.protein, 0) + 1
            if r.cuisine != "和":
                nonwa_count[0] += 1
            if backtrack(i + 1):
                return True
            assigned[d] = None
            used_ids.discard(r.id)
            protein_count[r.protein] -= 1
            if r.cuisine != "和":
                nonwa_count[0] -= 1
        return False

    ok = backtrack(0)

    plan = Plan(
        dinner_mains=assigned,
        dinner_sides=[None] * 7,
        bento_days=list(request.bento_days),
        dinner_days=list(request.dinner_days),
        is_summer=request.is_summer,
    )
    if not ok:
        plan.metrics["error"] = "ハード制約を満たす割当が見つかりませんでした（DB/制約を要見直し）"
        return plan

    if include_side:
        _assign_makeahead_sides(plan, sides, profile, request)
        _assign_dinner_sides(plan, sides, profile, request)
    if include_soup:
        _assign_soups(plan, soups, profile, request)
    plan.metrics = _compute_metrics(plan, profile, request)
    if force_consume:  # 使い切れたか（強制消費の達成確認）
        used = set()
        for m in assigned:
            if m:
                used |= m.ingredient_keys(exclude_pantry=True)
        plan.metrics["force_consume_missed"] = sorted(force_consume - used)
    return plan


# ---------------------------------------------------------------- 副菜割当

def _assign_makeahead_sides(plan: Plan, sides: list[Recipe], profile: Profile,
                            request: WeekRequest) -> None:
    keep_window = 3   # 作り置き保存日数の上限（夏ルールは廃止）
    bento_day_list = [d for d in range(7) if request.bento_days[d] and request.dinner_days[d]]
    if not bento_day_list:
        return
    batches = math.ceil(len(bento_day_list) / keep_window)

    mains_keys: set[str] = set()
    for m in plan.dinner_mains:
        if m:
            mains_keys |= m.ingredient_keys(exclude_pantry=True)
    inv_keys = set(request.inventory)

    cands = [s for s in sides
             if s.make_ahead_days >= keep_window
             and side_bento_ok(s, profile, request.is_summer)]
    cands.sort(
        key=lambda s: (len(s.ingredient_keys(exclude_pantry=True) & (mains_keys | inv_keys)),
                       s.make_ahead_days),
        reverse=True,
    )
    if not cands:
        return
    chosen = cands[:batches] if len(cands) >= batches else cands

    # 弁当日を曜日順で連続グループに分割
    groups = _contiguous_split(bento_day_list, len(chosen))

    for side, grp in zip(chosen, groups):
        if not grp:
            continue
        cook_day = max(0, grp[0] - 1)
        plan.makeahead.append(MakeAheadBatch(side=side, cook_day=cook_day, covers_days=grp))


def _contiguous_split(days: list[int], n: int) -> list[list[int]]:
    if n <= 0:
        return []
    size = math.ceil(len(days) / n)
    return [days[i:i + size] for i in range(0, len(days), size)] or [[]]


def _assign_dinner_sides(plan: Plan, sides: list[Recipe], profile: Profile,
                         request: WeekRequest) -> None:
    inv_keys = set(request.inventory)
    keep_window = 3   # 作り置き保存日数の上限（夏ルールは廃止）
    avail = [s for s in sides if allergy_ok(s, profile)]

    # 副菜の延べ出現回数（作り置きの弁当カバー分を初期値に）。多用するほど減点して単調を防ぐ
    appearances: dict[str, int] = {}
    for b in plan.makeahead:
        appearances[b.side.id] = appearances.get(b.side.id, 0) + len(b.covers_days)

    plan.dinner_side_source = [None] * 7
    for d in range(7):
        if not request.dinner_days[d]:
            continue
        main = plan.dinner_mains[d]
        ref_keys = (main.ingredient_keys(exclude_pantry=True) if main else set()) | inv_keys
        recent = {plan.dinner_sides[d - 1].id if d - 1 >= 0 and plan.dinner_sides[d - 1] else None,
                  plan.dinner_sides[d - 2].id if d - 2 >= 0 and plan.dinner_sides[d - 2] else None}
        # この日に「まだ新鮮な」作り置きバッチ（流用すれば追加調理ゼロ）
        fresh_batch: dict[str, int] = {}
        for bi, b in enumerate(plan.makeahead):
            if b.cook_day <= d <= b.cook_day + keep_window:
                fresh_batch.setdefault(b.side.id, bi)

        def score_side(s: Recipe) -> float:
            reuse = len(s.ingredient_keys(exclude_pantry=True) & ref_keys)
            batch_bonus = 1.5 if s.id in fresh_batch else 0.0  # 作り置き流用を優先
            repeat_pen = 1.2 * appearances.get(s.id, 0)        # 出すぎを抑える
            recent_pen = 4.0 if s.id in recent else 0.0        # 直近2日と同じは強く回避
            same_cuisine_pen = 0.3 if (main and s.cuisine == main.cuisine) else 0.0
            return reuse + batch_bonus - repeat_pen - recent_pen - same_cuisine_pen

        pick = max(avail, key=score_side) if avail else None
        plan.dinner_sides[d] = pick
        if pick:
            plan.dinner_side_source[d] = fresh_batch.get(pick.id)
            appearances[pick.id] = appearances.get(pick.id, 0) + 1


def _assign_soups(plan: Plan, soups: list[Recipe], profile: Profile,
                  request: WeekRequest) -> None:
    """各夕食に汁物を1品割当（一汁の構成）。味噌汁の連続は許容気味。"""
    if not soups:
        return
    inv_keys = set(request.inventory)
    avail = [s for s in soups if allergy_ok(s, profile)]
    if not avail:
        return
    appearances: dict[str, int] = {}
    for d in range(7):
        if not request.dinner_days[d]:
            continue
        main = plan.dinner_mains[d]
        ref = (main.ingredient_keys(exclude_pantry=True) if main else set()) | inv_keys
        prev = plan.dinner_soups[d - 1].id if d - 1 >= 0 and plan.dinner_soups[d - 1] else None

        def score_soup(s: Recipe) -> float:
            reuse = len(s.ingredient_keys(exclude_pantry=True) & ref)
            repeat_pen = 0.6 * appearances.get(s.id, 0)  # 汁物は繰り返し許容気味
            recent_pen = 2.0 if s.id == prev else 0.0
            return reuse - repeat_pen - recent_pen

        pick = max(avail, key=score_soup)
        plan.dinner_soups[d] = pick
        appearances[pick.id] = appearances.get(pick.id, 0) + 1


# ---------------------------------------------------------------- メトリクス

def _compute_metrics(plan: Plan, profile: Profile, request: WeekRequest) -> dict:
    mains = [m for m in plan.dinner_mains if m]
    protein_dist: dict[str, int] = {}
    cuisine_dist: dict[str, int] = {}
    for m in mains:
        protein_dist[m.protein] = protein_dist.get(m.protein, 0) + 1
        cuisine_dist[m.cuisine] = cuisine_dist.get(m.cuisine, 0) + 1

    # 使い回し：メイン間で共有された食材キーの延べ数
    key_count: dict[str, int] = {}
    for m in mains:
        for k in m.ingredient_keys(exclude_pantry=True):
            key_count[k] = key_count.get(k, 0) + 1
    shared = {k: c for k, c in key_count.items() if c >= 2}

    # 在庫消費：在庫キーのうちメイン/副菜で使われた数
    used_keys: set[str] = set()
    for m in mains:
        used_keys |= m.ingredient_keys(exclude_pantry=True)
    for s in plan.dinner_sides:
        if s:
            used_keys |= s.ingredient_keys(exclude_pantry=True)
    inv_used = sorted(set(request.inventory) & used_keys)
    inv_unused = sorted(set(request.inventory) - used_keys)

    # 副菜の延べ出現回数（弁当カバー＋夕食）
    side_appear: dict[str, int] = {}
    for b in plan.makeahead:
        side_appear[b.side.name] = side_appear.get(b.side.name, 0) + len(b.covers_days)
    for s in plan.dinner_sides:
        if s:
            side_appear[s.name] = side_appear.get(s.name, 0) + 1

    fish_count = sum(1 for m in mains if m.protein in ("fish", "seafood"))
    rich3_adj = sum(1 for i in range(6)
                    if plan.dinner_mains[i] and plan.dinner_mains[i + 1]
                    and plan.dinner_mains[i].richness == 3
                    and plan.dinner_mains[i + 1].richness == 3)

    # 弁当の取り分け状況（その夕食が弁当向きでない日＝要手当て。source基準）
    bento_total = sum(1 for d in range(7) if request.bento_days[d] and request.dinner_days[d])
    bento_manual = [WEEKDAYS[d] for d in range(7)
                    if request.bento_days[d] and request.dinner_days[d] and plan.carried_main(d) is None]
    one_plate = [m.name for m in mains if is_one_plate_main(m)]

    violations = _check_constraints(plan, profile, request)
    wa_ratio = round(cuisine_dist.get("和", 0) / len(mains), 2) if mains else 0
    return {
        "protein_dist": protein_dist,
        "cuisine_dist": cuisine_dist,
        "washoku_ratio": wa_ratio,
        "richness_seq": [m.richness for m in plan.dinner_mains if m],
        "richness3_adjacent": rich3_adj,
        "fish_seafood_count": fish_count,
        "shared_ingredients": shared,
        "side_appearances": side_appear,
        "inventory_used": inv_used,
        "inventory_unused": inv_unused,
        "bento_auto": bento_total - len(bento_manual),
        "bento_manual_days": bento_manual,
        "one_plate_mains": one_plate,
        "violations": violations,
    }


def _check_constraints(plan: Plan, profile: Profile, request: WeekRequest) -> list[str]:
    v: list[str] = []
    ids = [m.id for m in plan.dinner_mains if m]
    if len(ids) != len(set(ids)):
        v.append("同一レシピが週内で重複")
    # protein 隣接
    for d in range(6):
        a, b = plan.dinner_mains[d], plan.dinner_mains[d + 1]
        if a and b and a.protein == b.protein and a.protein != "none":
            v.append(f"protein連続: {WEEKDAYS[d]}-{WEEKDAYS[d + 1]} ({a.protein})")
    # protein 週内2回まで
    pc: dict[str, int] = {}
    for m in plan.dinner_mains:
        if m and m.protein != "none":
            pc[m.protein] = pc.get(m.protein, 0) + 1
    for p, c in pc.items():
        if c > 2:
            v.append(f"protein過多: {p} {c}回")
    # 弁当縛りはソフト化（取り分け不可は違反でなく「要手当て」扱い、§metrics で集計）
    return v

# ===== engine\session.py =====
"""PlanSession：週プランの状態＋§7 構造化コマンド（手直し再計算）。

実行時LLMなし。各コマンドは modifiers を更新して schedule_week を再実行するだけ。
コマンドは制約を壊さない範囲でのみ動く（§7）。
"""

import random
from dataclasses import dataclass, field


# カテゴリ操作（魚増やす/肉減らす 等）の protein グループ
PROTEIN_GROUPS = {
    "fish": ["fish", "seafood"],
    "meat": ["chicken", "pork", "beef", "mixed"],
    "chicken": ["chicken"], "pork": ["pork"], "beef": ["beef"],
    "tofu": ["tofu", "soy"], "egg": ["egg"],
}
CATEGORY_STEP = 15.0


@dataclass
class Mods:
    variety_bias: float = 0.4
    include_side: bool = False
    include_soup: bool = False
    washoku_target: float | None = 0.8
    pins: dict[int, str] = field(default_factory=dict)         # day -> recipe_id（固定）
    excluded_ids: set[str] = field(default_factory=set)        # 差し替えで除外
    force_consume: set[str] = field(default_factory=set)       # 強制消費する在庫key
    protein_delta: dict[str, float] = field(default_factory=dict)
    weekday_time_override: int | None = None
    rng_seed: int | None = None

    def to_dict(self) -> dict:
        return {
            "variety_bias": self.variety_bias, "include_side": self.include_side,
            "include_soup": self.include_soup, "washoku_target": self.washoku_target,
            "pins": {str(k): v for k, v in self.pins.items()},
            "excluded_ids": sorted(self.excluded_ids),
            "force_consume": sorted(self.force_consume),
            "protein_delta": self.protein_delta,
            "weekday_time_override": self.weekday_time_override, "rng_seed": self.rng_seed,
        }

    @staticmethod
    def from_dict(d: dict) -> "Mods":
        return Mods(
            variety_bias=d.get("variety_bias", 0.4),
            include_side=d.get("include_side", False),
            include_soup=d.get("include_soup", False),
            washoku_target=d.get("washoku_target", 0.8),
            pins={int(k): v for k, v in d.get("pins", {}).items()},
            excluded_ids=set(d.get("excluded_ids", [])),
            force_consume=set(d.get("force_consume", [])),
            protein_delta=dict(d.get("protein_delta", {})),
            weekday_time_override=d.get("weekday_time_override"),
            rng_seed=d.get("rng_seed"),
        )


class PlanSession:
    def __init__(self, recipes: list[Recipe], profile: Profile,
                 request: WeekRequest, mods: Mods | None = None):
        self.recipes = recipes
        self.profile = profile
        self.request = request
        self.mods = mods or Mods()
        self.plan: Plan | None = None
        self.liked: set[str] = set()    # いいねした料理id（好み・週をまたいで永続）
        self.banned: set[str] = set()   # バッドした料理id（提案・候補から恒久除外）

    # ----------------------------------------------------------- 再計算
    def regenerate(self, extra_pins: dict[int, str] | None = None) -> Plan:
        m = self.mods
        pins = dict(m.pins)
        if extra_pins:
            pins.update(extra_pins)
        self.plan = schedule_week(
            self.recipes, self.profile, self.request,
            variety_bias=m.variety_bias, include_side=m.include_side,
            include_soup=m.include_soup, washoku_target=m.washoku_target,
            pins=pins, excluded_ids=m.excluded_ids | self.banned,
            force_consume=m.force_consume,
            protein_delta=m.protein_delta, weekday_time_override=m.weekday_time_override,
            rng_seed=m.rng_seed,
        )
        return self.plan

    def _cur_ids(self, except_day: int | None = None) -> dict[int, str]:
        out = {}
        if not self.plan:
            return out
        for d in range(7):
            m = self.plan.dinner_mains[d]
            if m and d != except_day:
                out[d] = m.id
        return out

    # ----------------------------------------------------------- §7 コマンド
    def _pick_for_day(self, day: int, ok) -> Plan:
        """day だけを条件 ok を満たす最良の料理にし、他曜日は現状維持で再計算（連動しない）。

        選んだ料理は mods.pins に記憶する（＝ユーザーの選択。シャッフル等でも保持される）。
        """
        if not self.plan:
            return self.plan
        cur = self.plan.dinner_mains[day]
        assigned = list(self.plan.dinner_mains)
        used_other = {m.id for d, m in enumerate(assigned) if m and d != day}
        assigned[day] = None
        mains = [r for r in self.recipes if r.type == "main" or is_one_plate_main(r)]
        cands = _main_candidates(day, mains, self.request, self.profile,
                                 self.mods.excluded_ids, self.mods.weekday_time_override)
        cands = [r for r in cands if ok(r) and r.id not in used_other]
        if cur and ok(cur) and len(cands) > 1:        # 同条件を再度選んだら別の料理に巡回
            cands = [r for r in cands if r.id != cur.id]
        if not cands:
            return self.plan                          # 該当レシピなし＝何も変えない
        best = max(cands, key=lambda r: score_main(
            r, day, assigned, self.request, self.profile, self.mods.variety_bias,
            self.mods.protein_delta, self.mods.force_consume))
        self.mods.pins[day] = best.id                 # ユーザー選択として記憶
        # 他曜日は現状のまま固定 → この日だけが変わる（連動しない）
        return self.regenerate(extra_pins=self._cur_ids(except_day=day))

    def set_protein(self, day: int, group: str) -> Plan:
        """この日だけを指定のたんぱく源（鶏/豚/牛/魚 等）の料理にする。"""
        proteins = set(PROTEIN_GROUPS.get(group, [group]))
        return self._pick_for_day(day, lambda r: r.protein in proteins)

    def set_cuisine(self, day: int, cuisine: str) -> Plan:
        """この日だけを指定ジャンル（和/洋/中/エスニック）の料理にする。"""
        return self._pick_for_day(day, lambda r: r.cuisine == cuisine)

    def swap(self, day: int) -> Plan:
        """この日だけ別の料理に差し替える（他曜日は維持）。"""
        if not self.plan:
            return self.plan
        cur = self.plan.dinner_mains[day]
        added = False
        if cur and cur.id not in self.mods.excluded_ids:
            self.mods.excluded_ids.add(cur.id)        # この回だけ現在の料理を外して別案に
            added = True
        self.mods.pins.pop(day, None)                 # 一旦自由にして別案を選ぶ
        plan = self.regenerate(extra_pins=self._cur_ids(except_day=day))
        if added:
            self.mods.excluded_ids.discard(cur.id)    # 恒久除外しない（解空間を痩せさせない）
        nm = self.plan.dinner_mains[day]              # 選ばれた別案を記憶（以後も保持）
        if nm:
            self.mods.pins[day] = nm.id
        return plan

    def unpin(self, day: int) -> Plan:
        """この日をおまかせ（自動選択）に戻す（他曜日は維持）。"""
        self.mods.pins.pop(day, None)
        return self.regenerate(extra_pins=self._cur_ids(except_day=day))

    def candidates(self, day: int, cuisine=None, protein_group=None) -> list[dict]:
        """その日に選べる料理一覧（ジャンル/種類で絞り込み）。他曜日と重複する料理は除く。"""
        if not self.plan:
            return []
        used_other = {m.id for d, m in enumerate(self.plan.dinner_mains) if m and d != day}
        proteins = set(PROTEIN_GROUPS.get(protein_group, [protein_group])) if protein_group else None
        out = []
        for r in self.recipes:
            if not (r.type == "main" or is_one_plate_main(r)):
                continue
            if r.id in used_other or r.id in self.banned or not allergy_ok(r, self.profile):
                continue
            if cuisine and r.cuisine != cuisine:
                continue
            if proteins and r.protein not in proteins:
                continue
            out.append({"id": r.id, "name": r.name, "cuisine": r.cuisine,
                        "protein": r.protein, "cook": r.cook_time_min})
        out.sort(key=lambda x: (x["cook"], x["name"]))
        return out

    def pick(self, day: int, recipe_id: str) -> Plan:
        """一覧から選んだ料理をその日に確定（他曜日は維持・ユーザー選択として記憶）。"""
        r = next((x for x in self.recipes if x.id == recipe_id), None)
        if r is None or not (r.type == "main" or is_one_plate_main(r)):
            return self.plan
        self.mods.pins[day] = r.id
        return self.regenerate(extra_pins=self._cur_ids(except_day=day))

    # ----------------------------------------------------------- 好み（いいね/バッド）
    def like(self, recipe_id: str) -> Plan:
        """いいね（一覧に表示。提案には影響しない）。"""
        self.liked.add(recipe_id)
        self.banned.discard(recipe_id)
        return self.plan

    def unlike(self, recipe_id: str) -> Plan:
        self.liked.discard(recipe_id)
        return self.plan

    def ban(self, recipe_id: str) -> Plan:
        """バッド（今後の提案・候補から除外）。今出ている日だけ差し替える。"""
        self.banned.add(recipe_id)
        self.liked.discard(recipe_id)
        self.mods.pins = {d: i for d, i in self.mods.pins.items() if i != recipe_id}
        if not self.plan:
            return self.plan
        day = next((d for d in range(7)
                    if self.plan.dinner_mains[d] and self.plan.dinner_mains[d].id == recipe_id), None)
        return self.regenerate(extra_pins=self._cur_ids(except_day=day))

    def unban(self, recipe_id: str) -> Plan:
        """バッドを解除して通常プールに戻す（現在の献立は変えない）。"""
        self.banned.discard(recipe_id)
        return self.plan

    def pref_list(self, ids: set[str]) -> list[dict]:
        """好み一覧の表示用（id, 名前, ジャンル, 時間）。"""
        by = {r.id: r for r in self.recipes}
        out = [{"id": i, "name": by[i].name, "cuisine": by[i].cuisine, "cook": by[i].cook_time_min}
               for i in ids if i in by]
        out.sort(key=lambda x: x["name"])
        return out

    def fix(self, day: int) -> Plan:
        """この日を固定して残りを再生成。"""
        cur = self.plan.dinner_mains[day] if self.plan else None
        if cur:
            self.mods.pins[day] = cur.id
        self.mods.rng_seed = random.randint(1, 10 ** 6)  # 残りを振り直す
        return self.regenerate()

    def category(self, group: str, sign: int) -> Plan:
        """カテゴリ増減（魚を増やす/肉を減らす 等）。sign=+1/-1。"""
        for p in PROTEIN_GROUPS.get(group, [group]):
            self.mods.protein_delta[p] = self.mods.protein_delta.get(p, 0.0) + sign * CATEGORY_STEP
        return self.regenerate()

    def useup(self, key: str) -> Plan:
        """この余り食材を使い切る（強制消費）。"""
        self.mods.force_consume.add(key)
        return self.regenerate()

    def set_time(self, limit: int) -> Plan:
        """平日の調理時間上限を引き下げる。"""
        self.mods.weekday_time_override = limit
        return self.regenerate()

    def shuffle(self) -> Plan:
        """全体シャッフル（固定日は維持）。"""
        self.mods.rng_seed = random.randint(1, 10 ** 6)
        return self.regenerate()

    def set_days(self, dinner: list[bool] | None = None,
                 bento: list[bool] | None = None) -> Plan:
        """必要な曜日（夕食／弁当）の変更。"""
        if dinner is not None:
            self.request.dinner_days = dinner
        if bento is not None:
            self.request.bento_days = bento
        self.mods.pins = {d: v for d, v in self.mods.pins.items()
                          if self.request.dinner_days[d]}
        return self.regenerate()

    def reset(self) -> Plan:
        """手直しを全部捨てて素の提案に戻す。"""
        self.mods = Mods(variety_bias=self.mods.variety_bias,
                         include_side=self.mods.include_side,
                         include_soup=self.mods.include_soup,
                         washoku_target=self.mods.washoku_target)
        return self.regenerate()

    # ----------------------------------------------------------- 永続化
    def to_dict(self) -> dict:
        return {
            "request": {
                "dinner_days": self.request.dinner_days,
                "bento_days": self.request.bento_days,
                "inventory": self.request.inventory,
                "missing_staples": self.request.missing_staples,
                "current_month": self.request.current_month,
            },
            "mods": self.mods.to_dict(),
            "liked": sorted(self.liked),
            "banned": sorted(self.banned),
            "plan_ids": [m.id if m else None for m in self.plan.dinner_mains]
            if self.plan else [None] * 7,
        }

    @staticmethod
    def from_dict(d: dict, recipes: list[Recipe], profile: Profile) -> "PlanSession":
        rq = d["request"]
        request = WeekRequest(
            dinner_days=rq["dinner_days"], bento_days=rq["bento_days"],
            inventory=rq["inventory"], missing_staples=rq["missing_staples"],
            current_month=rq["current_month"],
        )
        s = PlanSession(recipes, profile, request, Mods.from_dict(d.get("mods", {})))
        s.liked = set(d.get("liked", []))
        s.banned = set(d.get("banned", []))
        return s



# ================= ブラウザ用グルー（server.py 相当・Flask無し） =================
from datetime import date, timedelta

_UNIT_DISP = {"tbsp": "大さじ", "tsp": "小さじ"}
_BAD_COUNT_UNITS = {"tbsp", "tsp", "ml", "cc"}


def _fmt_qty(qty, unit):
    if unit in ("適量", "少々", "少量", "少し", "つまみ", "ひとつまみ", "お好み", "お好みで", "適宜"):
        return "適量"
    if unit in ("tbsp", "tsp"):
        r = round(qty * 2) / 2
        s = str(int(r)) if abs(r - int(r)) < 1e-9 else f"{r:g}"
        return f"{_UNIT_DISP[unit]}{s}"
    if unit in COUNTABLE_UNITS:
        r = round(qty * 2) / 2
        if r == 0 and qty > 0:
            r = 0.5
        s = str(int(r)) if abs(r - int(r)) < 1e-9 else f"{r:g}"
        return f"{s}{unit}"
    return f"{int(__import__('math').ceil(qty / 5.0) * 5)}{unit}"


def _next_monday():
    today = date.today()
    return today - timedelta(days=today.weekday()) + timedelta(days=7)


def _week_dates():
    mon = _next_monday()
    return [(mon + timedelta(days=i)).strftime("%m/%d") for i in range(7)]


def _parse_days(spec):
    if isinstance(spec, list) and len(spec) == 7 and all(isinstance(x, bool) for x in spec):
        return spec
    if isinstance(spec, list):
        return [WEEKDAYS[i] in spec for i in range(7)]
    s = str(spec).strip()
    if s in ("all", "毎日"):
        return [True] * 7
    if s in ("weekday", "平日"):
        return [i in (0, 1, 2, 3, 4) for i in range(7)]
    if s in ("none", "なし", ""):
        return [False] * 7
    out = [False] * 7
    wd = {w: i for i, w in enumerate(WEEKDAYS)}
    if "-" in s and all(p in wd for p in s.split("-")):
        a, b = s.split("-")
        for i in range(wd[a], wd[b] + 1):
            out[i] = True
        return out
    for ch in s.replace("、", ",").replace(" ", ",").split(","):
        if ch in wd:
            out[wd[ch]] = True
    return out


class Core:
    """サーバの App + ルート群に相当。状態を保持し dict を返す（JSON化はJS側）。"""

    def __init__(self, recipes_data, profile_data):
        self.recipes = [Recipe.from_dict(r) for r in recipes_data["recipes"]]
        self.profile = Profile.from_dict(profile_data or {})
        self.by_id = {r.id: r for r in self.recipes}
        self.catalog = self._build_catalog()
        self.catalog_unit = {c["key"]: c["unit"] for c in self.catalog}
        self.catalog_name = {c["key"]: c["name"] for c in self.catalog}
        self.session = None
        self.inv_names = {}

    def _build_catalog(self):
        by_key = {}
        for r in self.recipes:
            for ing in r.ingredients:
                if ing.category in ("protein", "vegetable"):
                    slot = by_key.setdefault(ing.key, {"name": ing.name, "units": {}})
                    u = clean_unit(ing.unit)
                    slot["units"][u] = slot["units"].get(u, 0) + 1
        out = []
        for key, slot in by_key.items():
            unit = CANONICAL_UNITS.get(key) or max(slot["units"], key=slot["units"].get)
            out.append({"key": key, "name": slot["name"], "unit": unit})
        out.sort(key=lambda x: x["name"])
        return out

    def _ing_amount(self, ing, mult):
        u = clean_unit(ing.unit)
        if ing.key in CANONICAL_UNITS and u in _BAD_COUNT_UNITS:
            return "適量"
        return _fmt_qty(ing.qty * mult, u)

    def _brief(self, r, mult=1.0):
        if not r:
            return None
        return {
            "id": r.id, "name": r.name, "cuisine": r.cuisine, "protein": r.protein,
            "cook": r.cook_time_min, "servings": r.base_servings, "mult": round(mult, 2),
            "bento": bool(r.bento_ok), "steps": r.steps,
            "ings": [{"name": i.name, "amount": self._ing_amount(i, mult),
                      "seasoning": i.category in ("seasoning", "staple")}
                     for i in r.ingredients],
        }

    # ---- 初期化／復元／永続化 ----
    def init_default(self, week_data):
        wk = week_data or {}
        inv = [{"name": n, "qty": q} for n, q in (wk.get("inventory") or {}).items()]
        self.set_week(dinner=wk.get("dinner", "all"), bento=wk.get("bento", "weekday"),
                      month=int(wk.get("month", 6)), inventory=inv,
                      missing=wk.get("missing_staples", []), regen=True)

    def restore(self, d):
        self.session = PlanSession.from_dict(d, self.recipes, self.profile)
        self.inv_names = dict(d.get("inventory_names", {}))
        self.session.regenerate()

    def dump(self):
        d = self.session.to_dict()
        d["inventory_names"] = self.inv_names
        return d

    # ---- 週条件 ----
    def set_week(self, dinner=None, bento=None, month=None, inventory=None,
                 missing=None, regen=True):
        if self.session is None:
            req = WeekRequest([True] * 7, [False] * 7, {}, [], month or 6)
            self.session = PlanSession(self.recipes, self.profile, req, Mods())
        req = self.session.request
        if dinner is not None:
            req.dinner_days = _parse_days(dinner)
        if bento is not None:
            req.bento_days = _parse_days(bento)
        if month is not None:
            req.current_month = int(month)
        if inventory is not None:
            inv = {}
            self.inv_names = {}
            for it in inventory:
                name = str(it.get("name", "")).strip()
                key = it.get("key") or (normalize_key(name)[0] if name else None)
                if not key:
                    continue
                try:
                    q = float(it.get("qty", 0) or 0)
                except (TypeError, ValueError):
                    q = 0.0
                inv[key] = inv.get(key, 0) + q
                self.inv_names[key] = name or key
            req.inventory = inv
        if missing is not None:
            req.missing_staples = [normalize_key(n)[0] for n in missing]
        if regen:
            self.session.regenerate()

    # ---- 状態（state_dict 相当） ----
    def state(self):
        s = self.session
        plan = s.plan
        dates = _week_dates()
        days = []
        if not plan.metrics.get("error"):
            for d in range(7):
                if not plan.dinner_days[d]:
                    continue
                main = plan.dinner_mains[d]
                side = plan.dinner_sides[d]
                soup = plan.dinner_soups[d]
                main_mult = 1.0
                if main:
                    portions = s.profile.dinner_servings
                    if plan.carried_main(d) is main:
                        portions += s.profile.bento_servings
                    main_mult = max(1.0, portions / main.base_servings)
                days.append({
                    "idx": d, "weekday": WEEKDAYS[d], "date": dates[d],
                    "main": self._brief(main, main_mult), "side": self._brief(side),
                    "soup": self._brief(soup), "pinned": d in s.mods.pins,
                })
        sl = build_shopping_list(plan, s.profile, s.request)
        shopping = [{
            "section": sec,
            "items": [{"name": it.name, "qty": _fmt_qty(it.qty, it.unit),
                       "reused": it.reused, "dishes": list(dict.fromkeys(it.dishes))}
                      for it in items],
        } for sec, items in sl.ordered()]
        m = plan.metrics
        return {
            "profile": {"dinner": s.profile.dinner_servings, "bento": s.profile.bento_servings},
            "week": {
                "dinner_days": s.request.dinner_days, "bento_days": s.request.bento_days,
                "month": s.request.current_month,
                "inventory": [{"key": k, "name": self.catalog_name.get(k) or self.inv_names.get(k, k),
                               "qty": q, "unit": self.catalog_unit.get(k, "")}
                              for k, q in s.request.inventory.items()],
            },
            "catalog": self.catalog,
            "days": days,
            "shopping": shopping,
            "shopping_excluded": sl.excluded_pantry,
            "prefs": {"liked": s.pref_list(s.liked), "banned": s.pref_list(s.banned)},
            "metrics": {
                "washoku": int(m.get("washoku_ratio", 0) * 100),
                "violations": m.get("violations", []),
                "inventory_unused": [self.catalog_name.get(k, k) for k in m.get("inventory_unused", [])],
                "error": m.get("error"),
            },
            "mods": {
                "include_side": s.mods.include_side, "include_soup": s.mods.include_soup,
                "washoku_target": s.mods.washoku_target,
                "time_override": s.mods.weekday_time_override,
                "protein_delta": s.mods.protein_delta,
            },
        }

    # ---- §7 コマンド ----
    def command(self, body):
        s = self.session
        if s is None or s.plan is None:
            return {"error": "not ready"}
        cmd = body.get("cmd")
        if cmd == "swap":
            s.swap(int(body["day"]))
        elif cmd == "protein":
            s.set_protein(int(body["day"]), str(body["group"]))
        elif cmd == "cuisine":
            s.set_cuisine(int(body["day"]), str(body["cuisine"]))
        elif cmd == "unpin":
            s.unpin(int(body["day"]))
        elif cmd == "pick":
            s.pick(int(body["day"]), str(body["id"]))
        elif cmd == "like":
            s.like(str(body["id"]))
        elif cmd == "unlike":
            s.unlike(str(body["id"]))
        elif cmd == "ban":
            s.ban(str(body["id"]))
        elif cmd == "unban":
            s.unban(str(body["id"]))
        elif cmd == "more":
            s.category(str(body["group"]), +1)
        elif cmd == "less":
            s.category(str(body["group"]), -1)
        elif cmd == "useup":
            key, _ = normalize_key(str(body["food"]))
            s.useup(key)
        elif cmd == "time":
            s.set_time(int(body["minutes"]))
        elif cmd == "shuffle":
            s.shuffle()
        elif cmd == "reset":
            s.reset()
        elif cmd == "config":
            if "include_side" in body:
                s.mods.include_side = bool(body["include_side"])
            if "include_soup" in body:
                s.mods.include_soup = bool(body["include_soup"])
            if "washoku_target" in body:
                wt = body["washoku_target"]
                s.mods.washoku_target = None if wt is None else float(wt)
            s.regenerate()
        else:
            return {"error": f"unknown command: {cmd}"}
        return self.state()

    def week(self, body):
        self.set_week(dinner=body.get("dinner"), bento=body.get("bento"),
                      month=body.get("month"), inventory=body.get("inventory"),
                      missing=body.get("missing"))
        return self.state()

    def candidates(self, body):
        s = self.session
        if s is None or s.plan is None:
            return {"candidates": []}
        try:
            cands = s.candidates(int(body["day"]), body.get("cuisine") or None,
                                 body.get("protein") or None)
        except (KeyError, ValueError, TypeError):
            return {"candidates": []}
        return {"candidates": cands}

    def recipe(self, rid):
        r = self.by_id.get(rid)
        if not r:
            return {"error": "not found"}
        return self._brief(r, 1.0)

    def record(self):
        plan = self.session.plan
        if plan.metrics.get("error"):
            return {"error": "記録できる献立がありません"}
        mon = _next_monday()
        cal = {}
        n = 0
        for d in range(7):
            if not plan.dinner_days[d] or not plan.dinner_mains[d]:
                continue
            iso = (mon + timedelta(days=d)).isoformat()
            cal[iso] = {
                "main": plan.dinner_mains[d].name, "main_id": plan.dinner_mains[d].id,
                "side": plan.dinner_sides[d].name if plan.dinner_sides[d] else None,
                "soup": plan.dinner_soups[d].name if plan.dinner_soups[d] else None,
            }
            n += 1
        return {"recorded": n, "entries": cal}
