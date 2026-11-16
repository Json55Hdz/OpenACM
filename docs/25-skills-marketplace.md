# Skill marketplace

A **skill** is a Markdown document with instructions the assistant reads when it is relevant. Skills do not run code, but they steer the assistant, so installing one is a decision: you always read the whole text first.

## Where skills come from

| Label | Meaning |
|---|---|
| `sistema` | Ships with OpenACM |
| `plugin · name` | Provided by a plugin (it lives and goes with that plugin) |
| `marketplace` | Installed from the community catalog or from a link/file |
| *(none)* | Written by you |

## Installing

Open **Skills** in the dashboard and scroll to **Marketplace de skills**:

1. Pick one from the catalog, paste a link, upload a `.md` file or paste the text.
2. OpenACM shows the name, author, the full content and a **reading aid** with warnings (override phrases, hidden characters, commands that download and run code, secrets leaving the machine...). It never approves anything on its own.
3. Press **Instalar**. If there are serious findings you must type the skill's name first.

Links must be `https` GitHub raw links (`raw.githubusercontent.com` or a gist). What gets installed is exactly what was previewed (checked by SHA-256), and catalog entries are verified against the hash the catalog announces.

## Publishing yours

Anyone can publish:

1. Write `my-skill.md`:

   ```markdown
   ---
   name: "my-skill"
   description: "One sentence: what it is for and when to use it"
   category: "development"
   author: "your-name"
   ---

   # My skill
   Instructions for the assistant...
   ```

   `name` uses lowercase letters, numbers, `-` and `_` (2-60 characters). Maximum size 60 KB.
2. Fork the OpenACM repository, add the file to `marketplace/skills/`, run `python marketplace/build_index.py` and open a pull request.
3. Or just share the raw GitHub link: anyone can install it by link.

The catalog URL can be changed with the setting `skills.marketplace_url` (still restricted to GitHub hosts).

## API

- `GET /api/skills/marketplace` - catalog, with installed flags
- `POST /api/skills/market/preview` - `{url | content}` -> parsed skill + findings (installs nothing)
- `POST /api/skills/market/install` - `{content, sha256, confirm_name}`
