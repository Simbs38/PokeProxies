<div align="center">

# ✨ Pokédex Proxies ✨

**A cozy little home for a Pokémon TCG collection: catch 'em, build 'em, trade 'em, price 'em.**

<sub>◓ one HTML file · no build step · no server · works on your phone ◓</sub>

[**Open the site →**](https://simbs38.github.io/PokeProxies/)

</div>

---

## 🎒 What's inside

- 📖 **Collections**: checklists to tick off, with card art, rarities and favourite prints.
- 🗂️ **My Cards**: a binder of every card you own, searchable by name, set, type or kind.
- 🃏 **Deck builds**: build decks from your cards, see how they hold up against the meta, and what's left to buy.
- 💶 **Prices**: what everything is worth, refreshed live from Cardmarket.

## 🧪 Where the data comes from

- 🃏 **Cards & sets**: [pokemontcg.io](https://pokemontcg.io)
- 💶 **Prices**: Cardmarket trend € and TCGplayer $, through pokemontcg.io and [TCGdex](https://tcgdex.dev)
- 🏆 **Meta**: the last 4 weeks of online Standard events on [Limitless](https://play.limitlesstcg.com)
- 🎨 **Artwork**: [PokéAPI sprites](https://github.com/PokeAPI/sprites)

A GitHub Action (`.github/workflows/refresh-data.yml`) re-runs `fetch_data.py` every Monday and republishes the site.

## 🏃 Run it yourself

**1. The data and the site**

```bash
python3 fetch_data.py          # refresh cards.js, data.js and meta.js (a few minutes)
python3 -m http.server 8765    # then open http://localhost:8765
```

**2. Your Google Sheet** 📊

The site opens behind a Google sign-in and keeps your collection in a Google Sheet of your own, so set one up:

1. Make a new Google Sheet → **Extensions → Apps Script**, and paste in all of `apps_script.gs`.
2. **Project Settings ⚙ → Script Properties**: add `ALLOWED` = your Google address (comma-separate a few to share).
3. In [Google Cloud](https://console.cloud.google.com), create an **OAuth client ID** (Web application). Add your site's origin and `http://localhost:8765` as **Authorised JavaScript origins**, and add yourself as a test user.
4. Put that client ID in `CLIENT_ID`, in both `index.html` and `apps_script.gs`.
5. Back in Apps Script: **Deploy → New deployment → Web app**, execute as **Me**, access **Anyone**. Copy the `/exec` URL into `SYNC_URL` in `index.html`.
6. Open the site, sign in with Google, and your Sheet fills up with tabs: collections, My Cards, Trade, and one tab per deck. ✨

Optional: add a `GITHUB_TOKEN` script property to make the Data page's **Refresh data** button work.
The step-by-step version, with GitHub Pages hosting, is in [DEPLOY.md](DEPLOY.md).

## 🔒 Secrets stay secret

This repo is public, so it holds **no secrets**: only card data, artwork links and code.

- 🗝️ The GitHub token for **Refresh data** lives in the Apps Script's *Script Properties*, never in the repo.
- 📧 Who may sync is an `ALLOWED` script property too, so no email address lands here.
- 🪪 The Google client ID in `index.html` is public by design; every request is re-checked by the Apps Script.
- 🎒 Your collection only ever lives in your Google Sheet and your browser's local storage.

## 💛 Fan project

Made with love for playing with friends. Pokémon and all related names are trademarks of Nintendo, The Pokémon Company, Creatures and GAME FREAK. This project is not affiliated with or endorsed by them.

<div align="center"><sub>Gotta price 'em all ⚡</sub></div>
