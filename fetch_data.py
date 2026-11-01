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
FILES = {"gen1": "pokedexGen1.txt"}
LABELS = {"gen1": "Gen 1"}

# "anniv" isn't a species list like the others -> it's the master checklist of one real-world
# release: every card from the set itself plus its Classic Collection insert (same shape as the
# 25th Anniversary's Celebrations + Celebrations: Classic Collection).
ANNIV_KEY = "anniv"
ANNIV_LABEL = "30th Celebration"
ANNIV_SETS = ["me55", "me55c"]

# Deckbuilder -> cards.js: every card legal in Standard (these regulation marks) plus the basic
# Energies, which carry no mark and are always legal. Rotation = edit LEGAL and re-run.
LEGAL = ["H", "I", "J"]
CARD_FIELDS = ("id,name,supertype,subtypes,types,hp,number,set,images,nationalPokedexNumbers,attacks,abilities,"
               "rules,weaknesses,resistances,retreatCost,evolvesFrom,cardmarket,tcgplayer")
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
        # a print: [id, set code, number, image or "", Cardmarket €, TCGplayer $]
        groups[key]["p"].append([c["id"], code, c["number"], img] + eur_usd(c))

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

    # previous() carries over every species ever fetched -> keep only the ones still listed
    tcg = {sp: tcg[sp] for sp in wanted if sp in tcg}
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
        print(f"  ! {len(failed)} species failed ({', '.join(failed)}) — just run the script again")
    print("  open index.html — it now runs fully offline. Re-run to add species or refresh prices.")


if __name__ == "__main__":
    sys.exit(main())
