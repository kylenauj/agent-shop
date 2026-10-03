# agent-shop

A print-on-demand Etsy store that mostly runs itself. Agents come up with designs,
make the artwork, check it, and publish it to Etsy through Printify. When an order
comes in, Printify prints and ships it.

```
 1. Ideas        Claude searches the web for what's trending with your audience and
                 writes design ideas, Etsy titles, descriptions, and 13 tags each
 2. Policy check Blocklist + Claude review for trademarks, characters, celebrities
 3. Artwork      AI illustration (OpenAI) or clean lettering (free, built in),
                 enlarged to a 4500x5400 print file with a transparent background
 4. Image QA     Claude looks at the art: misspelled words? leftover background?
 5. Your review  You look at the preview and approve or reject it (can be turned off)
 6. Publish      Printify makes tee / sweatshirt / mug / tote products and lists
                 them on your Etsy shop
 7. Orders       Etsy order -> Printify prints and ships -> tracking goes to Etsy
```

Steps 6 and 7 come from Printify's Etsy integration. This code takes care of 1 through 6.

## Try it first (free, no accounts)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m shop run --offline       # makes 2 sample designs
python -m shop list
python -m shop approve <id>        # saves the Printify payloads it would send
```

Look in `data/designs/<id>/` to see the artwork, preview, and listing.

## Going live

1. **Etsy**: open a seller account and shop.
2. **Printify** (free): sign up at printify.com, then *Manage my stores → Add new store → Etsy*
   to connect your shop. Then go to *Account → Connections* and create a personal
   access token.
3. **Claude**: get an API key at console.anthropic.com.
4. **OpenAI** (optional, for illustrations): get an API key at platform.openai.com. If you
   skip this, designs are text-only lettering, which is a big seller anyway.
5. Set up your keys and settings:
   ```bash
   cp .env.example .env               # paste your keys in
   cp config.example.yaml config.yaml # set your audience, niches, products, prices
   python -m shop shops               # copy the Etsy shop id into .env as PRINTIFY_SHOP_ID
   python -m shop status              # check which stages are live
   ```
6. Check that each product in `config.yaml` points at the item you want:
   ```bash
   python -m shop catalog jersey tee --providers
   ```
   Put the `blueprint_id` and `print_provider_id` you like into `config.yaml`. Before
   you set prices, look at the provider's cost and shipping in Printify.
7. Run it:
   ```bash
   python -m shop run --count 5
   python -m shop approve <id> <id> ...
   python -m shop reject <id> "too similar to X"
   python -m shop orders
   ```

### Running it every day

On Mac or Linux, `crontab -e` and add (it runs at 9am):

```
0 9 * * * cd /path/to/agent-shop && .venv/bin/python -m shop run >> data/run.log 2>&1
```

Then just approve what you like. To skip review completely, set `auto_publish: true` in
`config.yaml`. Only do that once you've watched a few weeks of output and trust it.

## Commands

| Command | What it does |
|---|---|
| `run [--count N]` | ideas → policy check → artwork → image QA → review queue |
| `list [--status S]` | all designs and their status |
| `show <id>` | the listing, file paths, and history for one design |
| `approve <id>...` | approve and publish (`--no-publish` to only approve) |
| `reject <id> [reason]` | reject a design |
| `publish <id>... / --all-approved` | publish again after an error |
| `shops` / `catalog <words>` / `orders` | Printify lookups |
| `status` | which stages are live and which are in test mode |

Add `--offline` before any command to force test mode. You can type the start of an id
instead of the full id.

## Things to know before you scale up

- **Trademarks are the #1 way these shops die.** The policy check helps, but it can't
  guarantee anything. Many everyday phrases are registered trademarks for apparel. Search
  new slogans on the USPTO trademark search (tmsearch.uspto.gov) and add problem words
  to `blocked_terms`.
- **Etsy's rules**: list Printify as your production partner in Etsy and say how items
  are made. Etsy also expects you to disclose AI use; the `disclosure` text in
  `config.yaml` is added to every description. Read Etsy's current Creativity Standards
  and change that text if needed.
- **Fees add up**: Etsy charges $0.20 per listing (every product type is its own listing),
  renews listings every 4 months, and takes a 6.5% transaction fee plus payment processing.
  5 designs a day on 4 products is about $4 a day in listing fees before anything sells.
  Start with fewer products and only add the ones that sell.
- **API costs**: Claude and image generation cost a few cents to tens of cents per design.
  Check each provider's current pricing.
- **Print quality**: AI images are made at about 1024x1536 and then enlarged. Flat, bold
  art holds up fine. For detailed art, run an AI upscaler before you approve.
- **Mockups and listing photos**: Printify makes them for you. Lifestyle photos can sell
  better; you can add those in Etsy later.

## Project layout

```
shop/
  ideate.py      trend research + design ideas + listing copy (Claude)
  compliance.py  blocklist + Claude IP/policy review
  images.py      OpenAI or typography artwork, print-file prep
  qa.py          Claude checks the finished art
  printify.py    Printify catalog, product creation, publishing to Etsy
  pipeline.py    runs the stages and tracks status
  store.py       design records in data/designs/
  cli.py         the commands
tests/           offline tests (python -m pytest)
```
