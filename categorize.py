from __future__ import annotations
import re
import time
import requests
import wikipedia
import pandas as pd
from fuzzywuzzy import fuzz, process
from pathlib import Path

MAP_PATH = Path("data/merchant_map.csv")

DEFAULT_CATEGORIES = [
    "Food & Drink", "Groceries", "Transport", "Shopping", "Travel",
    "Entertainment", "Bills & Utilities", "Health", "Education",
    "Income", "Other",
]

# Simple keyword → category hints used by the online guesser
KEYWORDS_TO_CATEGORY = [
    (re.compile(r"\b(supermarket|grocery|grocer|market)\b", re.I), "Groceries"),
    (re.compile(r"\b(cafe|coffee|restaurant|bar|pub|pizza|burger|kitchen|bakery)\b", re.I), "Food & Drink"),
    (re.compile(r"\b(uber|lyft|taxi|ride ?hail|cab|metro|subway|train|bus|transit|fuel|gas station)\b", re.I), "Transport"),
    (re.compile(r"\b(pharmacy|drugstore|clinic|dental|optical|health|wellness)\b", re.I), "Health"),
    (re.compile(r"\b(hotel|airlines?|flight|airways|hostel|bnb|booking|travel|tour|resort)\b", re.I), "Travel"),
    (re.compile(r"\b(cinema|theater|theatre|movie|concert|museum|park|stadium|ticket)\b", re.I), "Entertainment"),
    (re.compile(r"\b(utility|electric|water|gas bill|internet|broadband|mobile|cellular|phone)\b", re.I), "Bills & Utilities"),
    (re.compile(r"\b(college|university|tuition|course|class|learning|education|school)\b", re.I), "Education"),
    (re.compile(r"\b(amazon|target|walmart|costco|mall|boutique|store|retail|shop|outlet)\b", re.I), "Shopping"),
]

class MerchantCategorizer:
    """Local merchant→category memory with fuzzy lookup."""
    def __init__(self, map_path: Path = MAP_PATH):
        self.map_path = map_path
        self._load_map()

    def _load_map(self):
        self.map_path.parent.mkdir(parents=True, exist_ok=True)
        if self.map_path.exists():
            self.map_df = pd.read_csv(self.map_path)
        else:
            self.map_df = pd.DataFrame(columns=["merchant", "category"])
            self.map_df.to_csv(self.map_path, index=False)

        if len(self.map_df):
            self.map_df["merchant_norm"] = self.map_df["merchant"].astype(str).str.upper().str.strip()
        else:
            self.map_df["merchant_norm"] = []

    def save(self):
        out = self.map_df[["merchant", "category"]].copy()
        out.to_csv(self.map_path, index=False)

    def _best_match(self, desc: str, threshold: int = 85) -> tuple[str | None, int]:
        if not len(self.map_df):
            return None, 0
        choices = self.map_df["merchant_norm"].tolist()
        match, score = process.extractOne(desc.upper().strip(), choices, scorer=fuzz.token_set_ratio)
        return (match, score) if score >= threshold else (None, score)

    def get_category(self, description: str) -> str | None:
        match, score = self._best_match(description)
        if match is None:
            return None
        row = self.map_df.loc[self.map_df["merchant_norm"] == match].iloc[0]
        return row["category"]

    def learn(self, merchant_raw: str, category: str):
        merchant_norm = str(merchant_raw).upper().strip()
        exists = self.map_df["merchant_norm"] == merchant_norm
        if exists.any():
            self.map_df.loc[exists, "category"] = category
        else:
            self.map_df = pd.concat([
                self.map_df,
                pd.DataFrame({"merchant": [merchant_raw], "category": [category], "merchant_norm": [merchant_norm]}),
            ], ignore_index=True)
        self.save()

class OnlineGuesser:
    """Best-effort online hints: OpenStreetMap + Wikipedia keyword scan."""
    def __init__(self, timeout=6):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SpendWise/1.0 (educational; contact: user@example.com)"
        })

    def _from_osm(self, name: str) -> str | None:
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {"q": name, "format": "json", "limit": 1}
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code != 200:
                return None
            items = r.json()
            if not items:
                return None
            display = (items[0].get("display_name") or "")
            clazz = items[0].get("class") or ""
            typ = items[0].get("type") or ""
            hint = f"{display} {clazz} {typ}"
            for pat, cat in KEYWORDS_TO_CATEGORY:
                if pat.search(hint):
                    return cat
        except Exception:
            return None
        return None

    def _from_wikipedia(self, name: str) -> str | None:
        try:
            wikipedia.set_rate_limiting(True)
            results = wikipedia.search(name, results=1)
            if not results:
                return None
            page = wikipedia.page(results[0], auto_suggest=False)
            text = (page.summary or "")[:1000]
            for pat, cat in KEYWORDS_TO_CATEGORY:
                if pat.search(text):
                    return cat
        except Exception:
            return None
        return None

    def guess(self, name: str) -> str | None:
        time.sleep(0.2)  # be polite to external services
        return self._from_osm(name) or self._from_wikipedia(name)
