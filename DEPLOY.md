# Publish the Pokédex

Three parts, in this order:

1. **Sheet** — your collection (private, Google sign-in).
2. **Google OAuth client** — who is allowed to reach it.
3. **GitHub Pages** — the site itself (public URL).
4. **Cloudflare Access** *(optional)* — makes the site itself private too.

The site files hold no secrets: card data, artwork links, no collection. Your data only ever lives
in your Sheet and in each browser's localStorage.

---

## 1. The Sheet (database)

1. New Google Sheet → **Extensions → Apps Script**.
2. Delete the sample code, paste all of `apps_script.gs`.
3. **Project Settings (⚙) → Script Properties → Add script property**: `ALLOWED` = your Google
   address, exactly as Google spells it (comma-separate several). It lives outside the code, so
   re-pasting the script never wipes it and your address stays out of the public repo.
4. **Deploy → New deployment → Web app**
   - *Execute as*: **Me**
   - *Who has access*: **Anyone** ← required; a browser `fetch` carries no Google session, so
     the guard has to live inside the script (`verify_`), not in this setting
5. Copy the `https://script.google.com/macros/s/…/exec` URL.

Re-deploy (**Deploy → Manage deployments → edit → Version: New version**) after any script edit —
editing alone changes nothing that is served.

**What lands in the Sheet.** The site rewrites these tabs on every save, one row per entry:

| Tab | Columns |
|---|---|
| `Gen 1` | Pokémon · Owned · Card IDs (one per line) · Favourite — plus a last `Unsorted` row for owned cards that match no Pokémon |
| `30th Celebration` | Pokémon · Owned · Card ID · Number · Rarity · Section |
| `My Cards` | Card · Set · Number · Card ID · Qty · Category · Price — one row per legal print you own |
| `Trade` | Same columns as `My Cards` — the cards in your Trade binder, kept apart from My Cards. Older prints (picked under **🕰 Every card**) are in here too, with the set's full name: their row is all another device needs to show them |
| `Traded` | Date · Card · Set · Number · Card ID · Qty · From · Price — one row per card traded out; a trade's rows share its date, and Price is what it was worth then |
| `Looking for` | Card · Set · Number · Card ID · Qty · For · Price — what the public landing page lists: the cards your decks still lack (For = `Decks`, any print will do), then the 30th Celebration cards and Gen 1 Pokémon you don't own yet |
| `Deck · <name>` (one per deck) | Qty · Card · Card ID · Category · Role · Cover — and on the right the deck's scores, archetype, price, tags, notes, role overrides, Built, copies moved into it, then its saved versions |

They are for reading: the next save from any device rewrites them, so hand edits do not stick.

**The public landing page.** Signed out, the site shows a read-only page with two tabs, *Looking for*
and *For trade*, so you can send the link to anyone. It reads the `Looking for` and `Trade` tabs, and
only those, with no sign-in (`?public=1` on the `/exec` URL); every other tab still needs your Google
token. `…/#lookingfor` and `…/#fortrade` open a tab directly, and a link to one list shows only that
list, with no tabs or filters: `…/#lookingfor-decks`, `…/#lookingfor-collections` (30th + Gen 1),
`…/#lookingfor-30th`, `…/#lookingfor-gen1`. **🔗 Copy link** copies whatever is on screen, so pick a
filter first to share just that list. After updating to this version of
`apps_script.gs` and re-deploying, sign in once: the site fills the `Looking for` tab on that first load.
Renaming or deleting a deck renames or removes its tab. The earlier single `Decks` tab is read once
and then removed.

**After a script change** (a new tab layout, as the per-deck tabs were): paste the new code, then
re-deploy *before* pushing the site. Until then the new site shows "update the Apps Script first"
and saves only on the device, so an old script can never hand it back data that wipes your decks.

**Switching over from the old `state` tab** (one JSON blob): re-deploy the script *first*. Until
the `Gen 1` tab exists it still serves a cached old site as before. The first load of the new site
copies the old JSON into the two tabs; from then on `state` is never written again and stays as a
rollback point, and an old cached copy of the site gets "site updated — reload the page".

---

## 2. Google OAuth client

1. [console.cloud.google.com](https://console.cloud.google.com) → new project.
2. **APIs & Services → OAuth consent screen** → **External**, app name, your address as support and
   developer contact. Add your own account under **Test users** — without it, sign-in is refused.
3. **Credentials → Create OAuth client ID → Web application**.
   - **Authorised JavaScript origins**: `https://simbs38.github.io` — origin only, no path, no
     trailing slash. Add `http://localhost:8765` too if you want the sign-in button to work locally.
   - Redirect URIs: leave empty; Google Identity Services does not use them.
4. The **Client ID** goes in two places, and they must match or every call is rejected:
   `CLIENT_ID` in `index.html`, and `CLIENT_ID` in `apps_script.gs`.

The client ID is not a secret — it ships in the page. The lock is the `ALLOWED` script property plus
the origin list above.

---

## 3. GitHub Pages

The repo is already initialised and committed locally. Check whose account you are pushing as —
`gh auth status` currently shows **andreGoncalvesNyra**; a personal project probably wants a
personal account (`gh auth switch`).

```bash
cd /Users/andre/Desktop/pokedex
gh repo create pokedex --public --source=. --push
```

Then turn Pages on:

```bash
gh api -X POST repos/:owner/pokedex/pages -f "source[branch]=main" -f "source[path]=/"
gh api repos/:owner/pokedex/pages --jq .html_url
```

(Or by hand: repo → **Settings → Pages → Source: Deploy from a branch → main / (root)**.)

Live in ~1 minute at `https://<user>.github.io/pokedex/`. Open it, hit **☁ Sign in**, paste the
`/exec` URL, then **Sign in with Google**. On iPhone: **Share → Add to Home Screen**.

Pages needs a **public** repo on a free account. Nothing secret is in it — but never commit
`collection.json` (already in `.gitignore`).

Push updates later:

```bash
python3 fetch_data.py                # every run refreshes all prices (--quick: only new species)
git commit -am "update" && git push
```

Every run also rebuilds `cards.js`, the deckbuilder's list of Standard-legal cards (with their
text and Cardmarket prices; where pokemontcg.io has no € yet — the newest sets, the 30th
Celebration — the Cardmarket trend comes from TCGdex instead; the Black Star Promos pokemontcg.io doesn't carry — all of MEP, a couple dozen of SVP — come from TCGdex too, into the deckbuilder, each Gen 1 Pokémon's card list and, for MEP 094–110, the 30th Celebration's Promo Cards), and `meta.js`: up to 100 archetypes from the 150 biggest Limitless
online Standard events of the last 4 weeks, with card usage (all lists and top-placing ones) and
real archetype-vs-archetype match results — what the deck scores, tips and matchups are measured
against. It takes a few minutes (about 300 requests to Limitless). So a plain
`python3 fetch_data.py` is enough to pick up a new set or a new meta. At rotation, edit `LEGAL` in
`fetch_data.py` (the regulation marks still legal) and re-run; saved decks keep their rotated cards,
flagged "not legal" until you swap them.

**Refreshing data without a computer** — `.github/workflows/refresh-data.yml` runs
`fetch_data.py` on GitHub, commits whatever changed and republishes the site. It runs every Monday
06:00 UTC on its own; the site's **Data** tab has a **Refresh data now** button that starts it on
demand through the Apps Script. That button needs a token the script keeps:

1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens →
   Generate new token**. Repository access: **Only select repositories → PokeProxies**.
   Permissions → Repository → **Actions: Read and write**. Pick an expiry, generate, copy it.
2. Apps Script → **Project Settings → Script Properties → Add script property**: `GITHUB_TOKEN` =
   the token. (It never reaches the public site.)
3. When the token expires, generate a new one and replace the property — no redeploy needed.

The Action commits to `main`, so pull before editing locally (`git pull`).

**Prices alone need none of this.** The **Prices** page's **🔄 Refresh prices** (also on the Data page)
asks [TCGdex](https://tcgdex.dev), a free public API, straight from the browser: fresh Cardmarket €
and TCGplayer $ for every card you own or play, in a few seconds, with no sign-in and no token. They
stay on that device and sit over the site's own prices until the next data refresh brings newer ones.

**🔍 Price check** (a consultation, nothing else on the site changes). In a card's 🔍, signed in, pick a
language (English, Japanese), a grade (Raw, PSA 10/9/8, and any other grade that has sales) and, raw, a
condition (NM, LP, MP, HP, DMG); **Check price** then asks [PokemonPriceTracker](https://www.pokemonpricetracker.com/api)
for what that card goes for: TCGplayer for raw, eBay sold for graded. It's in $, shown in € at the day's ECB
rate ([Frankfurter](https://frankfurter.dev)). Nothing is asked until you press it, and an answer is kept a day
on that device, so switching conditions or grades, or opening the card again, costs nothing. A Japanese print
is a card of its own, so the first check finds the Japanese prints by name for you to pick from. That API
refuses browsers, so the call goes through the Apps Script, which keeps the key:

1. [pokemonpricetracker.com/api](https://www.pokemonpricetracker.com/api) → free plan (no card) → copy the API key.
   It gives 100 credits a day: a check costs 2, finding Japanese prints 6.
2. Apps Script → **Project Settings → Script Properties → Add script property**: `PPT_KEY` = the key.
   (It never reaches the public site.)
3. This needs the current `apps_script.gs` (paste it, then **Deploy → Manage deployments → New version**).
   The key itself needs no redeploy.

**A new set, the day it's out.** The Data page's **New sets** box asks pokemontcg.io for sets it lists
with Standard-legal cards that the site doesn't have yet. **＋ Add** fetches the set's cards straight
into that device (no sign-in, no token): they show up in the deckbuilder and My Cards at once. The
next data refresh bakes the set into `cards.js` for every device, and each device then drops its own
copy. A set shows up there only once pokemontcg.io lists it, usually around its release day.

**📄 Deck list PDF.** Made in the browser (jsPDF from cdnjs, loaded only when asked). Page 1 is
`decklist-a4.png`, the official Play! Pokémon A4 deck list at 300 dpi (its footer allows noncommercial
reproduction), filled in; the REG column reads the regulation mark `fetch_data.py` keeps on each print.
When a new season's form comes out
([Play! Pokémon rules & resources](https://www.pokemon.com/us/play-pokemon/about/tournaments-rules-and-resources)),
swap in the new form as `decklist-a4.png` (2481 × 3508), set `DLF.season` in `index.html`, and check the
form still lines up with the pixel positions in `DLF`.

---

## 4. Cloudflare Access (optional — make the site private)

Access can only guard hostnames Cloudflare serves, and `github.io` is not one. So host the same
repo on **Cloudflare Pages** (free, auto-deploys on every `git push`) and put Access in front.
GitHub Pages can stay on as a public mirror, or be switched off in Settings → Pages.

**a. Cloudflare Pages**

1. [dash.cloudflare.com](https://dash.cloudflare.com) → **Workers & Pages → Create → Pages →
   Connect to Git** → authorise GitHub → pick `pokedex`.
2. Build settings: framework **None**, build command **empty**, output directory **`/`**.
3. **Save and Deploy** → you get `https://pokedex-xxx.pages.dev`.

A private GitHub repo works here too — Cloudflare Pages builds private repos on the free plan.

**b. Access policy**

1. Same dashboard → **Zero Trust** (free plan, up to 50 users — asks for a team name once).
2. **Access → Applications → Add an application → Self-hosted**.
   - Application name: `pokedex`
   - Session duration: **1 month** (so your phone stays logged in)
   - Public hostname: your `pokedex-xxx.pages.dev`
3. **Add policy**: Action **Allow**, rule *Emails* → your address. Add a second email if a partner
   should see it.
4. Login methods: **One-time PIN** works with zero setup (emails you a code); add **Google** under
   *Settings → Authentication* if you prefer one tap.
5. Save. Opening the URL now shows Cloudflare's login before the page loads.

**c. On the phone**

Open the `.pages.dev` URL, log in once, then **Add to Home Screen**. The Access cookie lasts the
session duration you set, so you land straight on the Pokédex on return.

Access does not interfere with the Sheet sync — that call goes from your browser to Apps Script
directly.

---

## What is protected by what

| Thing | Guard |
|---|---|
| PokemonPriceTracker key (`PPT_KEY`), GitHub token (`GITHUB_TOKEN`) | Script Properties — never sent to the site |
| Site (card list, prices, PDF) | Nothing — public, unless you add Cloudflare Access |
| Your Trade binder and Looking for list | Nothing — public on purpose, read-only (the landing page) |
| The rest of your collection (cards owned, decks, favourites) | `ALLOWED` script property — Google sign-in |
| Sheet contents | Your Google account |

The `/exec` URL on its own is useless now: every call must carry a Google ID token that the script
re-checks with Google, minted for this exact `CLIENT_ID`, for an address in `ALLOWED`. Add or revoke
someone by editing the `ALLOWED` script property — it applies on the next call, no re-deploy.

Tokens last about an hour. The page keeps working offline from `localStorage` regardless — an
expired token only stops syncing, and Google re-issues one silently on the next load. The
**⇩ Backup** button writes `collection.json` locally as a safety copy.
