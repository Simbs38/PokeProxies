#!/usr/bin/env python3
"""Fetch everything the Pokédex page needs into one local file: data.js

Reads the pokedex*.txt lists, resolves artwork ids from PokeAPI, pulls every
Pokémon TCG card (set, number, rarity, market price) from pokemontcg.io, and
writes data.js as `window.DEX = {...}` so index.html works offline (file:// blocks
fetch of local JSON, a <script src> does not).

Run:  python3 fetch_data.py
"""
import glob, json, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
POKEAPI = "https://pokeapi.co/api/v2/pokemon?limit=1400"
TCG = "https://api.pokemontcg.io/v2/cards"
FIELDS = "id,name,number,rarity,set,tcgplayer,cardmarket"
# pokemontcg.io lags weeks behind on prices for the newest sets; TCGdex carries Cardmarket's already
TCGDEX = "https://api.tcgdex.net/v2/en"
TCGDEX_SETS = {"30th Celebration: Classic Collection": "30th Classic Collection",   # where the names differ
               "Scarlet & Violet Black Star Promos": "SVP Black Star Promos",
               "Scarlet & Violet Energies": "Scarlet & Violet Energy",
               "Mega Evolution Black Star Promos": "MEP Black Star Promos"}

# pokedex*.txt -> collection key used by index.html
FILES = {"gen1": "pokedexGen1.txt"}
LABELS = {"gen1": "Gen 1"}

# "anniv" isn't a species list like the others -> it's the master checklist of one real-world
# release: every card from the set itself plus its Classic Collection insert (same shape as the
# 25th Anniversary's Celebrations + Celebrations: Classic Collection).
ANNIV_KEY = "anniv"
ANNIV_LABEL = "30th Celebration"
ANNIV_SETS = ["me55", "me55c"]
ANNIV_PROMOS = ("mep", 94, 110)    # the 30th Celebration's own promos: MEP 094-110, one or two per product

# Deckbuilder -> cards.js: every card legal in Standard (these regulation marks) plus the basic
# Energies, which carry no mark and are always legal. Rotation = edit LEGAL and re-run.
LEGAL = ["H", "I", "J"]
CARD_FIELDS = ("id,name,supertype,subtypes,types,hp,number,set,images,nationalPokedexNumbers,attacks,abilities,"
               "rules,weaknesses,resistances,retreatCost,evolvesFrom,cardmarket,tcgplayer,regulationMark")
ECODE = {"Grass": "G", "Fire": "R", "Water": "W", "Lightning": "L", "Psychic": "P", "Fighting": "F",
         "Darkness": "D", "Metal": "M", "Dragon": "N", "Fairy": "Y", "Colorless": "C"}

# Deckbuilder -> meta.js: the archetypes winning right now, from Limitless online Standard events.
LIMITLESS = "https://play.limitlesstcg.com/api"
META_DAYS, META_EVENTS, META_TOP = 28, 150, 100  # window, biggest events read, archetypes kept
META_MIN, META_GAMES = 5, 6                       # lists to count as an archetype, games for a real matchup

FORM = re.compile(r"^(Mega|Gigantamax|Alolan|Galarian|Hisuian|Paldean)\s+")
SUFFIX = [("Mega ", "-mega"), ("Gigantamax ", "-gmax"), ("Alolan ", "-alola"),
          ("Galarian ", "-galar"), ("Hisuian ", "-hisui"), ("Paldean ", "-paldea-combat-breed")]


def get(url, tries=8, fatal=True):
    """pokemontcg.io randomly 500s/502s behind Cloudflare -> retry with backoff. A 429 (too many
    requests, Limitless) waits as long as the server asks, or a growing pause."""
    last, wait = None, 0
    for i in range(tries):
        if i:
            time.sleep(wait or 1.2 * i)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pokedex-proxies/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # HTTPError, URLError, timeouts, bad JSON
            last = e
            retry = getattr(e, "headers", None) and e.headers.get("Retry-After")
            wait = (int(retry) if retry and retry.isdigit() else 15 * (i + 1)) if getattr(e, "code", 0) == 429 else 0
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


_tcgdex = {}


def tcgdex(path):
    """One TCGdex call, remembered: the 30th set is asked for by both the collection and the legal cards.
    A failure is not remembered, so the next ask tries again (one cached 500 once cost every 30th price)."""
    if _tcgdex.get(path) is None:
        _tcgdex[path] = get(f"{TCGDEX}{path}", tries=5, fatal=False)
    return _tcgdex[path]


# What the last run's data.js / cards.js held, by card id: what a card keeps when this run finds no
# price, so a flaky API never blanks prices that were there. Filled at the start of main().
OLD = {}                                                  # data.js: card id -> [value, label, source]
OLD_PRINT = {}                                            # cards.js: print id -> [€, $]


def old_prices():
    d, c = previous_js("data.js") or {}, previous_js("cards.js") or {}
    OLD.update({x["id"]: x["price"] for cs in (d.get("tcg") or {}).values() for x in cs})
    OLD.update({x["id"]: x["price"] for col in (d.get("collections") or {}).values()
                for x in col.get("items", []) if x.get("price")})
    OLD_PRINT.update({p[0]: p[4:6] for g in c.get("cards", []) for p in g["p"]})


def keep_old(item):
    """An item still without a price takes the last run's."""
    if item["price"][0] is None and (OLD.get(item["id"]) or [None])[0] is not None:
        item["price"] = OLD[item["id"]]


def tcgdex_eur(want):
    """Cardmarket trend € from TCGdex for cards pokemontcg.io has no € for.
    want: {key: (set name, number, card name)} -> {key: €}, only the ones TCGdex prices."""
    sid = {s["name"]: s["id"] for s in tcgdex("/sets") or []
           if not re.match(r"^(?:[A-Z]\d|P-[A-Z])", s["id"])}   # skip TCG Pocket's sets
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    nnum = lambda n: n.lstrip("0") or "0"
    by_set, ids = {}, {}                                  # ids: our key -> TCGdex card id
    for k, (st, number, name) in want.items():
        by_set.setdefault(TCGDEX_SETS.get(st, st), []).append((k, number, name))
    for st, mine in by_set.items():
        theirs = list((sid.get(st) and tcgdex(f"/sets/{sid[st]}") or {}).get("cards") or [])
        if not theirs:                                    # say why, or a silent 0 hides it (as on GitHub's runners)
            print(f"    ! TCGdex: no cards for {st!r} ({'no such set among ' + str(len(sid)) if st not in sid else 'empty answer'})")
        same = lambda m, c: nnum(c["localId"]) == nnum(m[1])
        rules = [lambda m, c: same(m, c) and norm(c["name"]) == norm(m[2])]
        if sum(any(rules[0](m, c) for c in theirs) for m in mine) * 2 < len(mine):
            # renumbered reprints (the Classic Collection keeps its vintage numbers): go by name,
            # twins in order, and "Palkia LV.X" is plain "Palkia" there
            rules += [lambda m, c: norm(c["name"]) == norm(m[2]), lambda m, c: norm(m[2]).startswith(norm(c["name"]))]
        else:
            rules += [same]                               # same set, same number: only the name is spelt differently
        mine.sort(key=lambda m: (len(m[1]), m[1]))
        theirs.sort(key=lambda c: (len(c["localId"]), c["localId"]))
        for rule in rules:
            for m in [m for m in mine if m[0] not in ids]:
                hit = next((c for c in theirs if rule(m, c)), None)
                if hit:
                    ids[m[0]] = hit["id"]
                    theirs.remove(hit)

    def one(item):
        cm = ((tcgdex(f"/cards/{item[1]}") or {}).get("pricing") or {}).get("cardmarket") or {}
        v = cm.get("trend") or cm.get("avg30") or cm.get("avg")
        return item[0], round(v, 2) if v else None
    with ThreadPoolExecutor(6) as pool:
        found = {k: v for k, v in pool.map(one, ids.items()) if v}
    print(f"  TCGdex: € for {len(found)} of {len(want)} cards pokemontcg.io had no € for"
          f" ({len(ids)} found there, {len(ids) - len(found)} of those unpriced)")
    return found


ANNIV_FIELDS = FIELDS + ",images,supertype"

# Black Star Promo sets pokemontcg.io lacks or has only part of: the Mega Evolution ones (MEP) not at
# all, Scarlet & Violet's (SVP) a couple dozen short. TCGdex has them all, so they come from there in
# pokemontcg.io's own shape and then group, price and show like any other print. Ids follow
# pokemontcg.io ("mep-101": set + number, no leading zeros): scrydex serves their images under it.
PROMO_SETS = {"mep": {"id": "mep", "name": "Mega Evolution Black Star Promos", "series": "Mega Evolution",
                      "ptcgoCode": "MEP", "releaseDate": "2025/09/26"},
              "svp": {"id": "svp", "name": "Scarlet & Violet Black Star Promos", "series": "Scarlet & Violet",
                      "ptcgoCode": "PR-SV", "releaseDate": "2023/01/01"}}
SCRYDEX = "https://images.scrydex.com/pokemon"
TDX_STAGE = {"Stage1": "Stage 1", "Stage2": "Stage 2"}
RULE = {"MEGA": "Mega Evolution ex Rule: When your Mega Evolution Pokémon ex is Knocked Out, your opponent takes 3 Prize cards.",
        "ex": "Pokémon ex rule: When your Pokémon ex is Knocked Out, your opponent takes 2 Prize cards."}
_promos = None


def from_tcgdex(d, st):
    """A TCGdex card as pokemontcg.io would send it (the fields legal_cards and the 30th read)."""
    cat = {"Pokemon": "Pokémon", "Trainer": "Trainer", "Energy": "Energy"}.get(d.get("category"), "Pokémon")
    if cat == "Pokémon":
        sub = [TDX_STAGE.get(d.get("stage"), d.get("stage") or "Basic")]
        sub += ["MEGA"] if d["name"].startswith("Mega ") else []
        sub += ["ex"] if d["name"].endswith(" ex") else []
    elif cat == "Trainer":
        sub = [{"Tool": "Pokémon Tool"}.get(d.get("trainerType"), d.get("trainerType") or "Item")]
    else:
        sub = ["Special" if d.get("energyType") == "Special" else "Basic"]
    pr = d.get("pricing") or {}
    cm, tp = pr.get("cardmarket") or {}, pr.get("tcgplayer") or {}
    number = d["localId"].lstrip("0") or "0"
    pid = f"{st['id']}-{number}"
    rules = [d["effect"]] if d.get("effect") else []
    rules += [RULE["MEGA"]] if "MEGA" in sub else [RULE["ex"]] if "ex" in sub else []
    return {"id": pid, "name": d["name"], "supertype": cat, "subtypes": sub, "types": d.get("types") or [],
            "hp": str(d["hp"]) if d.get("hp") else None, "number": number, "rarity": d.get("rarity") or "Promo",
            "regulationMark": (d.get("regulationMark") or "").upper() or None, "set": st,
            "images": {"small": f"{SCRYDEX}/{pid}/small", "large": f"{SCRYDEX}/{pid}/large"},
            "nationalPokedexNumbers": d.get("dexId") or [], "evolvesFrom": d.get("evolveFrom"),
            "attacks": [{"name": a["name"], "cost": a.get("cost") or [], "damage": str(a.get("damage") or ""),
                         "text": a.get("effect") or ""} for a in d.get("attacks") or []],
            "abilities": [{"name": a["name"], "text": a.get("effect") or ""} for a in d.get("abilities") or []],
            "rules": rules,
            "weaknesses": [{"type": w["type"]} for w in d.get("weaknesses") or []],
            "resistances": [{"type": w["type"]} for w in d.get("resistances") or []],
            "retreatCost": ["Colorless"] * (d.get("retreat") or 0),
            "cardmarket": {"prices": {"trendPrice": cm.get("trend") or cm.get("avg30") or cm.get("avg")}},
            "tcgplayer": {"prices": {k: {"market": v.get("marketPrice"), "mid": v.get("midPrice")}
                                     for k, v in tp.items() if isinstance(v, dict)}}}


def tcgdex_promos(skip=()):
    """Every card of PROMO_SETS that TCGdex has, as from_tcgdex makes it, minus the ids in skip
    (what pokemontcg.io already sent). Remembered: the legal cards and the 30th both ask."""
    global _promos
    if _promos is None:
        briefs = []
        for sid, st in PROMO_SETS.items():
            cs = (tcgdex(f"/sets/{sid}") or {}).get("cards") or []
            if not cs:
                print(f"    ! TCGdex: no cards for {sid}")
            briefs += [(c, st) for c in cs if re.fullmatch(r"\d+", c.get("localId") or "")]
        with ThreadPoolExecutor(6) as pool:
            full = list(pool.map(lambda b: (tcgdex(f"/cards/{b[0]['id']}"), b[1]), briefs))
        _promos = [from_tcgdex(d, st) for d, st in full if d]
        print(f"  TCGdex promos: {len(_promos)} of {len(briefs)} cards read ({', '.join(PROMO_SETS)})")
    skip = set(skip)
    return [c for c in _promos if c["id"] not in skip]


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
    insert, then Promo cards -- each its own section, each kept in the book's own order rather
    than one flat alphanumeric sort. The bonus Mew R/G/B trio is left out on purpose: not
    something to collect (thousands of euros each)."""
    main = set_cards("me55")
    classic = set_cards("me55c")
    printed = next((c.get("set", {}).get("printedTotal") for c in main), 128) or 128

    # set apart first, or their non-numeric numbers would sort them into Secret Illustrations
    mews = [c for c in main if c.get("number") in ("R", "G", "B")]
    regular = sorted([c for c in main if c not in mews and num(c) <= printed], key=num)
    secret = sorted([c for c in main if c not in mews and num(c) > printed], key=num)
    # Classic Collection cards keep their original vintage numbers (a deliberate reprint
    # quirk -> e.g. "4" is Base Set Charizard's #4/102), which repeat across different source
    # sets and can't be sorted numerically. The API's own return order isn't numeric or
    # alphabetical either -- it walks the TCG's history oldest to newest (Base Set Pikachu ->
    # Gym -> Neo -> EX -> DP -> HGSS -> BW -> XY -> SM -> SWSH -> SV), matching the ETB book's
    # "trip through history" layout, so it's kept as-is rather than re-sorted.
    # the 30th's own promos are Black Star Promos pokemontcg.io doesn't carry: MEP 094-110 from TCGdex
    sid, lo, hi = ANNIV_PROMOS
    promos = sorted([c for c in tcgdex_promos() if c["set"]["id"] == sid and lo <= int(c["number"]) <= hi], key=num)

    sections = [("All", regular), ("Secret Illustrations", secret),
                ("Classic Collection", classic), ("Promo Cards", promos)]

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
                "c": (c.get("supertype") or "P")[0],    # P / T / E: the Trade binder files a non-legal one by it
                "img": (c.get("images") or {}).get("large") or (c.get("images") or {}).get("small"),
                "price": price(c),
            })
            i += 1
    eur = tcgdex_eur({it["id"]: (it["set"], it["number"], it["name"]) for it in items if it["price"][0] is None})
    for it in items:
        if it["id"] in eur:
            it["price"] = [eur[it["id"]], f"€{eur[it['id']]:,.2f}", "cardmarket trend"]
        keep_old(it)
    return {"name": ANNIV_LABEL, "kind": "cards", "items": items}


def tcg_item(c):
    """A card in a Pokémon's list (data.js). The image is kept only where it can't be worked out from
    the id: the newest sets and the TCGdex promos live on scrydex, not images.pokemontcg.io."""
    s = c.get("set") or {}
    img = (c.get("images") or {}).get("small", "")
    it = {"id": c["id"], "name": c["name"], "number": c.get("number", "?"), "total": s.get("printedTotal"),
          "set": s.get("name", "?"), "series": s.get("series", ""), "date": s.get("releaseDate", ""),
          "rarity": c.get("rarity") or "", "price": price(c)}
    if img and img != f"https://images.pokemontcg.io/{s.get('id')}/{c.get('number')}.png":
        it["img"] = img
    return it


def eur_usd(card):
    """[Cardmarket trend €, TCGplayer market $] — either may be None."""
    cm = (card.get("cardmarket") or {}).get("prices", {})
    eur = cm.get("trendPrice") or cm.get("averageSellPrice") or cm.get("avg30")
    usd = next((p.get("market") or p.get("mid") for p in (card.get("tcgplayer") or {}).get("prices", {}).values()
                if p.get("market") or p.get("mid")), None)
    return [round(eur, 2) if eur else None, round(usd, 2) if usd else None]


def meta_decks(legal):
    """Up to META_TOP archetypes (each with META_MIN lists or more) by play share over the META_DAYS
    window of Limitless online Standard events, the META_EVENTS biggest. For each: its best-placed
    list mapped onto cards.js prints; how often every card shows up, in all lists and in the
    top-placing quarter; and its real match results, overall and against every other archetype."""
    by_code, by_name = {}, {}
    norm = lambda s: re.sub(r"^basic ", "", s.lower().replace("’", "'")).strip()
    for g in legal["cards"]:
        for p in g["p"]:
            by_code[f"{p[1]} {p[2]}".upper()] = (p[0], g)
        by_name.setdefault(norm(g["n"]), (g["p"][0][0], g))
    by_code_id = {p[0]: g["n"] for g in legal["cards"] for p in g["p"]}

    cut = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(time.time() - META_DAYS * 86400))
    events, page = [], 1
    while page < 30:
        got = get(f"{LIMITLESS}/tournaments?game=PTCG&format=STANDARD&limit=100&page={page}", fatal=False)
        if not got:
            break
        events += [t for t in got if t["date"] >= cut]
        if got[-1]["date"] < cut:
            break
        page += 1
    events = sorted(events, key=lambda t: -t["players"])[:META_EVENTS]
    if not events:
        return None

    lists, names, players = {}, {}, 0                   # archetype id -> [(score, cards)]
    results = {}                                          # (a, b) -> [a's wins, losses, ties]
    for n, t in enumerate(events, 1):
        time.sleep(0.6)                                   # Limitless answers 429 to a faster pace
        rows = get(f"{LIMITLESS}/tournaments/{t['id']}/standings", fatal=False) or []
        print(f"  [{n:3}/{len(events)}] {t['name'][:40]:40} {t['players']:4} players")
        deck_of = {}
        for r in rows:
            deck, dl = r.get("deck") or {}, r.get("decklist")
            if not deck.get("id") or deck["id"] == "other":    # Limitless's catch-all, not an archetype
                continue
            deck_of[r.get("player")] = deck["id"]
            if not isinstance(dl, dict):
                continue
            players += 1
            names[deck["id"]] = deck["name"]
            cards = []                                    # [print id, n], or [None, n, name, P/T/E] if unknown
            for part in ("pokemon", "trainer", "energy"):
                for e in dl.get(part) or []:
                    hit = by_code.get(f"{e.get('set')} {e.get('number')}".upper()) or by_name.get(norm(e["name"]))
                    cards.append([hit[0], e["count"]] if hit else [None, e["count"], e["name"], part[0].upper()])
            rec = r.get("record") or {}
            score = (rec.get("wins", 0) * 3 + rec.get("ties", 0)) * 1000 + t["players"] - (r.get("placing") or 999)
            lists.setdefault(deck["id"], []).append((score, cards))
        time.sleep(0.6)
        for m in get(f"{LIMITLESS}/tournaments/{t['id']}/pairings", fatal=False) or []:
            a, b, w = deck_of.get(m.get("player1")), deck_of.get(m.get("player2")), m.get("winner")
            if not a or not b or a == b:
                continue
            r = (1, 0, 0) if w == m["player1"] else (0, 1, 0) if w == m["player2"] else (0, 0, 1) if w == 0 else None
            if r:
                for x, y, rr in ((a, b, r), (b, a, (r[1], r[0], r[2]))):
                    acc = results.setdefault((x, y), [0, 0, 0])
                    for k in range(3):
                        acc[k] += rr[k]

    top = [k for k in sorted(lists, key=lambda k: -len(lists[k])) if len(lists[k]) >= META_MIN][:META_TOP]
    where = {k: i for i, k in enumerate(top)}
    out = []
    for k in top:
        ls = sorted(lists[k], key=lambda x: -x[0])
        best = ls[:max(3, len(ls) // 4)]                  # the top-placing quarter
        name_of = lambda c: (by_code_id.get(c[0]) if c[0] else None) or c[2]
        counts, top_counts = {}, {}
        for group, acc in ((ls, counts), (best, top_counts)):
            for _, cards in group:
                seen = {}
                for c in cards:
                    seen[name_of(c)] = seen.get(name_of(c), 0) + c[1]
                for nm, v in seen.items():
                    acc.setdefault(nm, []).append(v)
        usage = []
        for nm, v in counts.items():
            pct, tpct = round(100 * len(v) / len(ls)), round(100 * len(top_counts.get(nm, [])) / len(best))
            if pct >= 5 or tpct >= 10:
                mode = max(set(v), key=v.count)
                usage.append([nm, pct, round(sum(v) / len(v), 1), mode, tpct])
        won = [sum(results.get((k, o), [0, 0, 0])[i] for o in lists) for i in range(3)]
        out.append({"id": k, "name": names[k], "share": round(100 * len(ls) / players, 1), "lists": len(ls),
                    "cards": ls[0][1], "usage": sorted(usage, key=lambda u: -u[1]),
                    "win": round(100 * (won[0] + won[2] / 2) / sum(won), 1) if sum(won) else None, "games": sum(won)})
    mu = [[where[a], where[b], *r] for (a, b), r in results.items()
          if a in where and b in where and where[a] < where[b] and sum(r) >= META_GAMES]
    return {"fetched": time.strftime("%Y-%m-%d %H:%M"), "days": META_DAYS, "events": len(events),
            "players": players, "decks": out, "mu": mu}


def query_all(q, fields):
    """Every card matching q, paging past the 250 cap; None once the API gives up."""
    cards, page, total = [], 1, None
    while total is None or len(cards) < total:
        res = get(f"{TCG}?{urllib.parse.urlencode({'q': q, 'pageSize': 250, 'page': page, 'select': fields})}",
                  fatal=False)
        if res is None:
            return None
        total = res.get("totalCount", 0)
        cards += res.get("data", [])
        page += 1
    return cards


def legal_cards():
    """One entry per distinct card, every legal print of it inside (newest first): the picker
    shows one tile per card and the deck chooses the art. Pokémon count as the same card only
    when name, HP, attacks and abilities all match; Trainers and Energy go by name."""
    raw = []
    for q in [f"regulationMark:{m}" for m in LEGAL] + ["supertype:Energy subtypes:Basic set.id:sve"]:
        got = query_all(q, CARD_FIELDS)
        if got is None:
            return None
        raw += got
    # the Black Star Promos pokemontcg.io lacks, from TCGdex: only the legal ones
    extra = [c for c in tcgdex_promos({c["id"] for c in raw}) if c.get("regulationMark") in LEGAL]
    print(f"  + {len(extra)} legal promos pokemontcg.io lacks")
    raw += extra
    # newest set first; among the basic Energies prefer the prints that carry a set code
    raw.sort(key=lambda c: (c["set"].get("releaseDate", ""), bool(c["set"].get("ptcgoCode"))), reverse=True)

    groups, sets = {}, {}
    for c in raw:
        kind, key = c["supertype"][0], c["name"]          # P / T / E
        if kind == "P":
            key += json.dumps([c.get("hp"), [(a["name"], a.get("damage")) for a in c.get("attacks") or []],
                               [a["name"] for a in c.get("abilities") or []]])
        s = c["set"]
        code = s.get("ptcgoCode") or s["id"].upper()      # the code deck lists use: "4 Pikachu 30C 29"
        sets[code] = s["name"]
        img = (c.get("images") or {}).get("small", "")
        if img == f"https://images.pokemontcg.io/{s['id']}/{c['number']}.png":
            img = ""                                      # derivable; newer sets live on another host
        groups.setdefault(key, None)
        if groups[key] is None:
            hp = c.get("hp") or ""
            groups[key] = {k: v for k, v in {
                "n": c["name"], "c": kind, "sub": c.get("subtypes") or [], "t": c.get("types") or [],
                "hp": int(hp) if hp.isdigit() else None,
                "dex": (c.get("nationalPokedexNumbers") or [None])[0],
                # what the deck analysis reads: evolution, attacks [name, cost, damage, text],
                # abilities [name, text], Trainer/Energy rules, weakness, resistance, retreat
                "ef": c.get("evolvesFrom"),
                "atk": [[a["name"], "".join(ECODE.get(e, "C") for e in a.get("cost") or []),
                         a.get("damage") or "", a.get("text") or ""] for a in c.get("attacks") or []] or None,
                "ab": [[a["name"], a.get("text") or ""] for a in c.get("abilities") or []] or None,
                "rt": " ".join(c.get("rules") or []) or None,
                "wk": "".join(ECODE.get(w["type"], "") for w in c.get("weaknesses") or []) or None,
                "rs": "".join(ECODE.get(w["type"], "") for w in c.get("resistances") or []) or None,
                "rc": len(c.get("retreatCost") or []) if kind == "P" else None,
                "p": []}.items() if v is not None}
        # a print: [id, set code, number, image or "", Cardmarket €, TCGplayer $, regulation mark or ""]
        groups[key]["p"].append([c["id"], code, c["number"], img] + eur_usd(c) + [c.get("regulationMark") or ""])

    eur = tcgdex_eur({p[0]: (sets[p[1]], p[2], g["n"]) for g in groups.values() for p in g["p"] if p[4] is None})
    for g in groups.values():
        for p in g["p"]:
            if p[4] is None and p[0] in eur:
                p[4] = eur[p[0]]
            if p[4] is None and p[5] is None and p[0] in OLD_PRINT:   # nothing this run: the last run's € and $
                p[4], p[5] = OLD_PRINT[p[0]]

    order = {"P": 0, "T": 1, "E": 2}
    cards = sorted(groups.values(), key=lambda g: (
        order[g["c"]], g.get("dex", 9999), g["c"] == "E" and "Basic" not in g["sub"], g["n"]))
    return {"fetched": time.strftime("%Y-%m-%d %H:%M"), "legal": LEGAL, "sets": sets, "cards": cards}


def previous_js(name):
    """A data file this script wrote earlier, read back (window.X = {...};), or None."""
    path = os.path.join(HERE, name)
    try:
        raw = open(path, encoding="utf-8").read().strip()
        return json.loads(raw[raw.index("=") + 1:].rstrip(";\n"))
    except Exception:
        return None


def previous():
    """The last data.js's cards: what a species keeps when pokemontcg.io fails on it this run, and
    with --quick, what every species already fetched keeps (old prices included)."""
    path = os.path.join(HERE, "data.js")
    if not os.path.exists(path):
        return {}
    raw = open(path, encoding="utf-8").read().strip()
    try:
        return json.loads(raw[raw.index("=") + 1:].rstrip(";\n")).get("tcg", {})
    except Exception:
        return {}


def main():
    old_prices()                                          # read before this run overwrites the files
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

    old = previous()
    tcg = dict(old) if "--quick" in sys.argv else {}     # by default every species is re-fetched: fresh prices
    todo = [s for s in wanted if s not in tcg]
    print(f"· TCG cards: {len(wanted)} species, {len(todo)} to fetch"
          f"{' (--quick: the rest keep their old prices)' if len(todo) < len(wanted) else ''} …")
    failed = []
    for n, sp in enumerate(todo, 1):
        token = sorted(re.split(r"[^A-Za-z0-9]+", sp), key=len, reverse=True)[0]
        sp_tokens, cards, page, total = tokens(sp), [], 1, None
        while total is None or len(cards) < total:      # the API caps a page at 250
            q = urllib.parse.urlencode({"q": f"name:*{token}*", "pageSize": 250,
                                        "page": page, "select": FIELDS + ",images"})
            res = get(f"{TCG}?{q}", fatal=False)
            if res is None:
                break
            total = res.get("totalCount", 0)
            cards += res.get("data", [])
            page += 1
        if res is None and (sp in old or not cards):    # gave up: keep the last run's cards and prices
            failed.append(sp)
            if sp in old:
                tcg[sp] = old[sp]
            continue
        cards = [c for c in cards if belongs(c["name"], sp_tokens)]  # drop Mewtwo from Mew, etc.
        tcg[sp] = [tcg_item(c) for c in cards]
        print(f"  [{n:3}/{len(todo)}] {sp:22} {len(cards):3} cards" +
              (f"  (of {total} name matches)" if total and total != len(cards) else ""))

    # previous() carries over every species ever fetched -> keep only the ones still listed
    tcg = {sp: tcg[sp] for sp in wanted if sp in tcg}
    # the Black Star Promos pokemontcg.io lacks (all of MEP, some of SVP) go in each Pokémon's list too
    promos, added = tcgdex_promos(), 0
    for sp, cs in tcg.items():
        ids, sp_tokens = {c["id"] for c in cs}, tokens(sp)
        more = [tcg_item(c) for c in promos if c["id"] not in ids and belongs(c["name"], sp_tokens)]
        cs += more
        added += len(more)
    print(f"  + {added} promo prints from TCGdex across the species lists")
    eur = tcgdex_eur({c["id"]: (c["set"], c["number"], c["name"]) for cs in tcg.values() for c in cs if c["price"][0] is None})
    for cs in tcg.values():
        for c in cs:
            if c["id"] in eur:
                c["price"] = [eur[c["id"]], f"€{eur[c['id']]:,.2f}", "cardmarket trend"]
            keep_old(c)
    out = {"fetched": time.strftime("%Y-%m-%d %H:%M"), "collections": collections, "tcg": tcg}
    path = os.path.join(HERE, "data.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write("window.DEX = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n")

    print(f"· Deckbuilder: legal cards ({'/'.join(LEGAL)}) + basic Energy …")
    legal = legal_cards()
    if legal is None:
        print("  ! pokemontcg.io gave up — kept the previous cards.js, just run the script again")
        legal = previous_js("cards.js")                  # the meta can still be mapped onto it
    else:
        with open(os.path.join(HERE, "cards.js"), "w", encoding="utf-8") as f:
            f.write("window.CARDS = " + json.dumps(legal, ensure_ascii=False, separators=(",", ":")) + ";\n")
        prints = sum(len(g["p"]) for g in legal["cards"])
        print(f"  {len(legal['cards'])} cards ({prints} prints) -> cards.js")

    if legal:
        print(f"· Deckbuilder: meta from Limitless (last {META_DAYS} days, {META_EVENTS} biggest events) …")
        meta = meta_decks(legal)
        if meta is None:
            print("  ! Limitless gave nothing back — kept the previous meta.js")
        else:
            with open(os.path.join(HERE, "meta.js"), "w", encoding="utf-8") as f:
                f.write("window.META = " + json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + ";\n")
            print(f"  {len(meta['decks'])} archetypes, {len(meta['mu'])} real matchups; top: "
                  + " · ".join(f"{d['name']} {d['share']}%" for d in meta["decks"][:8]) + " -> meta.js")

    # Browsers cache data.js / cards.js / meta.js hard, so a refresh would keep showing the old data
    # until a manual hard-reload. Stamp the tags with this run's timestamp instead.
    page = os.path.join(HERE, "index.html")
    if os.path.exists(page):
        html = open(page, encoding="utf-8").read()
        stamped = re.sub(r'<script src="(data|cards|meta)\.js(?:\?v=[^"]*)?">',
                         lambda m: f'<script src="{m.group(1)}.js?v={time.strftime("%Y%m%d%H%M")}">', html)
        if stamped != html:
            open(page, "w", encoding="utf-8").write(stamped)
            print("  cache-buster stamped into index.html")

    total = sum(len(v) for v in tcg.values())
    print(f"\n✓ {total} cards for {len(tcg)} species -> data.js ({os.path.getsize(path)/1e6:.1f} MB)")
    if failed:
        print(f"  ! {len(failed)} species failed ({', '.join(failed)}) — they kept the last run's cards; run again to retry")
    print("  open index.html — it now runs fully offline. Re-run to add species or refresh prices.")


if __name__ == "__main__":
    sys.exit(main())
