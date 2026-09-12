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
3. Put your own Google address in `const ALLOWED = [...]`, save.
4. **Deploy → New deployment → Web app**
   - *Execute as*: **Me**
   - *Who has access*: **Anyone** ← required; a browser `fetch` carries no Google session, so
     the guard has to live inside the script (`verify_`), not in this setting
5. Copy the `https://script.google.com/macros/s/…/exec` URL.

Re-deploy (**Deploy → Manage deployments → edit → Version: New version**) after any script edit —
editing alone changes nothing that is served.

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

The client ID is not a secret — it ships in the page. The lock is `ALLOWED` in the Apps Script plus
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
python3 fetch_data.py --refresh      # optional, refreshes prices
git commit -am "update" && git push
```

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
| Site (card list, prices, PDF) | Nothing — public, unless you add Cloudflare Access |
| Your collection (owned / favourites / proxies) | `ALLOWED` in `apps_script.gs` — Google sign-in |
| Sheet contents | Your Google account |

The `/exec` URL on its own is useless now: every call must carry a Google ID token that the script
re-checks with Google, minted for this exact `CLIENT_ID`, for an address in `ALLOWED`. Add or revoke
someone by editing `ALLOWED` and re-deploying.

Tokens last about an hour. The page keeps working offline from `localStorage` regardless — an
expired token only stops syncing, and Google re-issues one silently on the next load. The
**⇩ Backup** button writes `collection.json` locally as a safety copy.
