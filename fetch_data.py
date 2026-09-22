#!/usr/bin/env python3
"""Fetch everything the Pokédex page needs into one local file: data.js

Reads the pokedex*.txt lists, resolves artwork ids from PokeAPI, pulls every
Pokémon TCG card (set, number, rarity, market price) from pokemontcg.io, and
writes data.js as `window.DEX = {...}` so index.html works offline (file:// blocks
fetch of local JSON, a <script src> does not).

Run:  python3 fetch_data.py
"""
import glob, json, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
POKEAPI = "https://pokeapi.co/api/v2/pokemon?limit=1400"
TCG = "https://api.pokemontcg.io/v2/cards"
FIELDS = "id,name,number,rarity,set,tcgplayer,cardmarket"

# pokedex*.txt -> collection key used by index.html
FILES = {"gen1": "pokedexGen1.txt", "gen2": "pokedexGen2.txt", "gen3": "pokedexGen3.txt"}
LABELS = {"gen1": "Gen 1", "gen2": "Gen 2", "gen3": "Gen 3"}

# "anniv" isn't a species list like the others -> it's the master checklist of one real-world
# release: every card from the set itself plus its Classic Collection insert (same shape as the
# 25th Anniversary's Celebrations + Celebrations: Classic Collection).
ANNIV_KEY = "anniv"
ANNIV_LABEL = "30th Celebration"
ANNIV_SETS = ["me55", "me55c"]

FORM = re.compile(r"^(Mega|Gigantamax|Alolan|Galarian|Hisuian|Paldean)\s+")
SUFFIX = [("Mega ", "-mega"), ("Gigantamax ", "-gmax"), ("Alolan ", "-alola"),
          ("Galarian ", "-galar"), ("Hisuian ", "-hisui"), ("Paldean ", "-paldea-combat-breed")]


def get(url, tries=8, fatal=True):
    """pokemontcg.io randomly 500s/502s behind Cloudflare -> retry with backoff."""
    last = None
    for i in range(tries):
        if i:
            time.sleep(1.2 * i)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pokedex-proxies/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # HTTPError, URLError, timeouts, bad JSON
            last = e
    if fatal:
        raise SystemExit(f"giving up on {url}\n  {last}")
    print(f"    ! {last} — kept previous data")
    return None


def slug(name):
    return (name.lower().replace("♀", "-f").replace("♂", "-m")
            .replace("'", "").replace(".", "").replace(" ", "-"))


def artwork_id(name, api):
    """PokeAPI id for this exact form, so Mega/Gmax/regional art is correct."""
    for prefix, suffix in SUFFIX:
        if name.startswith(prefix):
            core = slug(name[len(prefix):])
            m = re.match(r"(.+)-([xy])$", core) if suffix == "-mega" else None
            cand = f"{m.group(1)}{suffix}-{m.group(2)}" if m else core + suffix
            return api.get(cand) or api.get(slug(name))
    # a few species only exist under a form slug in PokeAPI (deoxys -> deoxys-normal)
    return api.get(slug(name)) or api.get(slug(name) + "-normal")


def tokens(text):
    """['blaine','s','charizard'] — lets us match a species as whole words, so Mew
    does not swallow Mewtwo and Mr. Mime does not swallow Mime Jr."""
    return re.findall(r"[a-z0-9]+", text.lower().replace("\u2640", " f ").replace("\u2642", " m "))


def belongs(card_name, sp_tokens):
    t = tokens(card_name)
    return any(t[i:i + len(sp_tokens)] == sp_tokens for i in range(len(t) - len(sp_tokens) + 1))


def species(name):
    return re.sub(r"\s+[XY]$", "", FORM.sub("", name)).strip()


def price(card):
    for variant, p in (card.get("tcgplayer") or {}).get("prices", {}).items():
        v = p.get("market") or p.get("mid")
        if v:
            label = re.sub(r"([a-z])([A-Z])", r"\1 \2", variant)
            return [round(v, 2), f"${v:,.2f}", label]
    cm = (card.get("cardmarket") or {}).get("prices", {})
    v = cm.get("trendPrice") or cm.get("averageSellPrice")
    return [round(v, 2), f"€{v:,.2f}", "cardmarket trend"] if v else [None, "—", "no price"]


ANNIV_FIELDS = FIELDS + ",images"


def set_cards(set_id):
    """Every card printed in one TCG set, paging past the 250-per-request cap."""
    cards, page, total = [], 1, None
    while total is None or len(cards) < total:
        q = urllib.parse.urlencode({"q": f"set.id:{set_id}", "pageSize": 250,
                                    "page": page, "select": ANNIV_FIELDS})
        res = get(f"{TCG}?{q}")
        total = res.get("totalCount", 0)
        cards += res.get("data", [])
        page += 1
    return cards


def num(card):
    """Numeric read of a card's number ('129' -> 129); non-numeric ones (promos, the R/G/B
    Mew trio) sort last within their section instead of collapsing to 0."""
    n = re.sub(r"\D", "", card.get("number", ""))
    return int(n) if n else 999


def anniv_master_set():
    """Mirrors the ETB book's own checklist layout: All cards, then Secret Illustrations
    (both from the main me55 set, split at its printed total), then the Classic Collection
    insert, then Promo cards, then the bonus Mew R/G/B trio -- each its own section, each
    kept in the book's own order rather than one flat alphanumeric sort."""
    main = set_cards("me55")
    classic = set_cards("me55c")
    printed = next((c.get("set", {}).get("printedTotal") for c in main), 128) or 128

    mews = sorted([c for c in main if c.get("number") in ("R", "G", "B")],
                  key=lambda c: "RGB".index(c["number"]))
    regular = sorted([c for c in main if c not in mews and num(c) <= printed], key=num)
    secret = sorted([c for c in main if c not in mews and num(c) > printed], key=num)
    # Classic Collection cards keep their original vintage numbers (a deliberate reprint
    # quirk -> e.g. "4" is Base Set Charizard's #4/102), which repeat across different source
    # sets and can't be sorted numerically. The API's own return order isn't numeric or
    # alphabetical either -- it walks the TCG's history oldest to newest (Base Set Pikachu ->
    # Gym -> Neo -> EX -> DP -> HGSS -> BW -> XY -> SM -> SWSH -> SV), matching the ETB book's
    # "trip through history" layout, so it's kept as-is rather than re-sorted.
    promos = []  # not in the TCG API yet for this release -- ask for the checklist to fill this in

    sections = [("All", regular), ("Secret Illustrations", secret),
                ("Classic Collection", classic), ("Promo Cards", promos),
                ("Mew R/G/B", mews)]

    items, i = [], 0
    for section, cards in sections:
        for c in cards:
            items.append({
                "i": i, "section": section, "id": c["id"], "name": c["name"],
                "number": c.get("number", "?"),
                "total": (c.get("set") or {}).get("printedTotal") or (c.get("set") or {}).get("total"),
                "set": (c.get("set") or {}).get("name", "?"),
                "series": (c.get("set") or {}).get("series", ""),
                "date": (c.get("set") or {}).get("releaseDate", ""),
                "rarity": c.get("rarity") or "",
                "img": (c.get("images") or {}).get("large") or (c.get("images") or {}).get("small"),
                "price": price(c),
            })
            i += 1
    return {"name": ANNIV_LABEL, "kind": "cards", "items": items}


def previous():
    """Reuse the last data.js so a re-run only fetches what is missing."""
    path = os.path.join(HERE, "data.js")
    if "--refresh" in sys.argv or not os.path.exists(path):
        return {}
    raw = open(path, encoding="utf-8").read().strip()
    try:
        return json.loads(raw[raw.index("=") + 1:].rstrip(";\n")).get("tcg", {})
    except Exception:
        return {}


def main():
    print("· PokeAPI form ids …")
    api = {r["name"]: int(r["url"].rstrip("/").split("/")[-1])
           for r in get(POKEAPI)["results"]}

    collections, wanted = {}, []
    for key, fname in FILES.items():
        path = os.path.join(HERE, fname)
        items = []
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                m = re.match(r"Index (\d+) : (\d+) - (.+?)\s*$", line)
                if not m:
                    continue
                name = m.group(3)
                items.append({"i": int(m.group(1)), "dex": m.group(2), "name": name,
                              "id": artwork_id(name, api), "sp": species(name)})
                if species(name) not in wanted:
                    wanted.append(species(name))
        collections[key] = {"name": LABELS[key], "items": items}
        print(f"  {LABELS[key]:22} {len(items):4} entries" + ("" if items else "  (no list file)"))

    missing = [i["name"] for c in collections.values() for i in c["items"] if not i["id"]]
    if missing:
        print(f"  ! no artwork id for: {', '.join(missing)}")

    print(f"· {ANNIV_LABEL} master set ({' + '.join(ANNIV_SETS)}) …")
    collections[ANNIV_KEY] = anniv_master_set()
    print(f"  {ANNIV_LABEL:22} {len(collections[ANNIV_KEY]['items']):4} cards")

    tcg = previous()
    todo = [s for s in wanted if s not in tcg]
    print(f"· TCG cards: {len(wanted)} species, {len(todo)} to fetch"
          f"{' (--refresh to redo all + prices)' if len(todo) < len(wanted) else ''} …")
    failed = []
    for n, sp in enumerate(todo, 1):
        token = sorted(re.split(r"[^A-Za-z0-9]+", sp), key=len, reverse=True)[0]
        sp_tokens, cards, page, total = tokens(sp), [], 1, None
        while total is None or len(cards) < total:      # the API caps a page at 250
            q = urllib.parse.urlencode({"q": f"name:*{token}*", "pageSize": 250,
                                        "page": page, "select": FIELDS})
            res = get(f"{TCG}?{q}", fatal=False)
            if res is None:
                break
            total = res.get("totalCount", 0)
            cards += res.get("data", [])
            page += 1
        if res is None and not cards:
            failed.append(sp)
            continue
        cards = [c for c in cards if belongs(c["name"], sp_tokens)]  # drop Mewtwo from Mew, etc.
        tcg[sp] = [{
            "id": c["id"], "name": c["name"], "number": c.get("number", "?"),
            "total": (c.get("set") or {}).get("printedTotal"),
            "set": (c.get("set") or {}).get("name", "?"),
            "series": (c.get("set") or {}).get("series", ""),
            "date": (c.get("set") or {}).get("releaseDate", ""),
            "rarity": c.get("rarity") or "",
            "price": price(c),
        } for c in cards]
        print(f"  [{n:3}/{len(todo)}] {sp:22} {len(cards):3} cards" +
              (f"  (of {total} name matches)" if total and total != len(cards) else ""))

    out = {"fetched": time.strftime("%Y-%m-%d %H:%M"), "collections": collections, "tcg": tcg}
    path = os.path.join(HERE, "data.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write("window.DEX = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n")
    # Browsers cache data.js hard, so a refresh would keep showing the old collections until a
    # manual hard-reload. Stamp the tag with this run's timestamp instead.
    page = os.path.join(HERE, "index.html")
    if os.path.exists(page):
        html = open(page, encoding="utf-8").read()
        stamped = re.sub(r'<script src="data\.js(?:\?v=[^"]*)?">',
                         f'<script src="data.js?v={time.strftime("%Y%m%d%H%M")}">', html, count=1)
        if stamped != html:
            open(page, "w", encoding="utf-8").write(stamped)
            print("  cache-buster stamped into index.html")

    total = sum(len(v) for v in tcg.values())
    print(f"\n✓ {total} cards for {len(tcg)} species -> data.js ({os.path.getsize(path)/1e6:.1f} MB)")
    if failed:
        print(f"  ! {len(failed)} species failed ({', '.join(failed)}) — just run the script again")
    print("  open index.html — it now runs fully offline. Re-run to add species or refresh prices.")


if __name__ == "__main__":
    sys.exit(main())
