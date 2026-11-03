<div align="center">

# ✨ Pokédex Proxies ✨

**A cozy little home for a Pokémon TCG collection: catch 'em, build 'em, trade 'em, price 'em.**

<sub>◓ one HTML file · no build step · no server · works on your phone ◓</sub>

[**Open the site →**](https://simbs38.github.io/PokeProxies/)

</div>

---

## 🎒 What's inside

| | |
|---|---|
| 📖 **Gen 1 & 30th Celebration** | Checklists for every original Pokémon form and the full 30th Celebration master set, with card art, rarities and favourite prints. |
| 🗂️ **My Cards** | A binder of every Standard-legal print you own, searchable by name, set, type or kind. |
| 🃏 **Decks** | A deckbuilder that simulates your list against the real meta: scores (Consistency, Speed, Power), matchups, an archetype guess, swap tips, and a "To buy" list sorted by cost. |
| 🔁 **Trade binder** | Cards set aside to trade. Pick a group, see its price, throw in extras from My Cards, then **Trade out** with a full history and undo. |
| 💶 **Prices** | What everything is worth. **🔄 Refresh prices** pulls live Cardmarket prices right in your browser: no sign-in, no token. |
| 📊 **Data** | How fresh the cards, prices and meta are, plus a button that re-fetches all of it on GitHub. |
| ☁️ **Sync** | Optional: sign in with Google and your collection lives in your own Google Sheet, readable tab by tab. |

## 🧪 Where the data comes from

- 🃏 **Cards & sets**: [pokemontcg.io](https://pokemontcg.io)
- 💶 **Prices**: Cardmarket trend € and TCGplayer $, through pokemontcg.io and [TCGdex](https://tcgdex.dev)
- 🏆 **Meta**: the last 4 weeks of online Standard events on [Limitless](https://play.limitlesstcg.com)
- 🎨 **Artwork**: [PokéAPI sprites](https://github.com/PokeAPI/sprites)

A GitHub Action (`.github/workflows/refresh-data.yml`) re-runs `fetch_data.py` every Monday and republishes the site.

## 🏃 Run it yourself

```bash
python3 fetch_data.py          # refresh cards.js, data.js and meta.js (a few minutes)
python3 -m http.server 8765    # then open http://localhost:8765
```

Or just open `index.html`: everything it needs is in the folder.

## 🔒 Secrets stay secret

This repo is public, so it holds **no secrets**: only card data, artwork links and code.

- 🗝️ The GitHub token for **Refresh data** lives in the Apps Script's *Script Properties*, never in the repo.
- 📧 Who may sync is an `ALLOWED` script property too, so no email address lands here.
- 🪪 The Google client ID in `index.html` is public by design; every request is re-checked by the Apps Script.
- 🎒 Your collection only ever lives in your Google Sheet and your browser's local storage.

Full setup (Sheet, Google sign-in, Pages, the token) is in [DEPLOY.md](DEPLOY.md).

## 💛 Fan project

Made with love for playing with friends. Pokémon and all related names are trademarks of Nintendo, The Pokémon Company, Creatures and GAME FREAK. This project is not affiliated with or endorsed by them.

<div align="center"><sub>Gotta price 'em all ⚡</sub></div>
