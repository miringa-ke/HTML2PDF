# WeasyPrint PDF service

Replaces the HTML2PDF API for the manifesto render. Self-hosted, no size cap,
no per-document cost.

n8n POSTs the assembled manifesto HTML, gets PDF bytes back as binary, and the
Google Drive node uploads it. The container owns the typography, so the
workflow only has to produce semantic HTML.

## Why WeasyPrint and not headless Chromium

The paid APIs run headless Chrome and call `Page.printToPDF`. That works, but
Chromium ignores `@page` margin boxes, so page numbers and running headers have
to be faked with JavaScript and absolute positioning.

WeasyPrint implements CSS Paged Media properly. In `manifesto_print.css` that
buys four things Chromium cannot do cleanly:

- running headers that name the region you are currently reading
- `counter(page) " of " counter(pages)` in the footer
- a contents page whose page numbers come from `target-counter()`, so they stay
  correct by themselves as regions are added
- PDF bookmarks generated from the heading levels

It is also far lighter: no 300 MB browser, no gigabyte of RAM per render. A
seven page manifesto renders in about two seconds.

The tradeoff is that WeasyPrint runs no JavaScript. That is irrelevant here,
because the manifesto is assembled server side and is plain markup. If charts
drawn by a JS library are ever added to this document, that part has to be
rendered to SVG or PNG before it reaches the renderer.

## Layout

    weasyprint-service/
      Dockerfile
      app.py                   the service, one endpoint
      requirements.txt
      css/manifesto_print.css  applied to every document
      fonts/                   drop .ttf/.otf here for brand fonts

## Deploy on Render

Render builds from a Git repository, so step one is getting this folder into
one. Put `weasyprint-service/` in a repo (it can be a private repo, and it can
sit alongside other things) and commit `render.yaml` at the repo root.

Then: **New > Blueprint**, point it at the repo, and Render reads `render.yaml`.

Before you click create, change one line in `render.yaml`:

    region: frankfurt      # must match the region your n8n service is in

Services only share a private network when they are in the **same region and
the same workspace**, and the region cannot be changed after a service is
created. Getting this wrong means deleting the service and starting again, so
check your n8n service's region first.

If you would rather not use a Blueprint, create the service by hand:
**New > Private Service**, connect the repo, set **Dockerfile Path** to
`weasyprint-service/Dockerfile`, and add `PDF_TOKEN` and `BASE_CSS` as
environment variables.

### This will not run on the free tier

Free web services can *send* private network requests but cannot *receive*
them, and private services are not offered on free at all. The renderer has to
be a paid instance. `1c-2g` in the blueprint is comfortable; `0.5c-512mb` works
for documents of this size if you want to start smaller.

Your n8n service can stay on whatever plan it is on. Sending is the side that
is free.

If you need a zero-cost option, the alternative is a **Web Service** on the
free plan, which gets a public `onrender.com` URL. Then `PDF_TOKEN` is the only
thing standing between the open internet and a renderer that fetches URLs, so
make it long and random. Free web services also sleep after inactivity, so the
first render after a quiet period waits through a cold start of roughly a
minute. For a scheduled manifesto sweep that is survivable, but it is a real
tradeoff rather than a free lunch.

### Get the internal address

This is the detail that catches people. A Render service's internal hostname is
**not** just its name. It carries a generated suffix, so `weasyprint` is really
something like `weasyprint-2j3e`.

Open the service in Render, click **Connect**, choose the **Internal** tab, and
copy the address shown there. That exact string, with `http://` in front, is
what goes in the n8n node. It will look like:

    http://weasyprint-2j3e:5000/pdf

Do not guess it.

### Local testing without Render

`docker-compose.yml` in this folder is for running the same image on a VPS or
on your own machine, where the hostname really is just `weasyprint`. It is not
used by Render.

## n8n wiring

### Node: Render PDF (HTTP Request)

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | the Internal address from Render, e.g. `http://weasyprint-2j3e:5000/pdf` |
| Send Headers | on |
| &nbsp;&nbsp;`X-Auth-Token` | your `PDF_TOKEN` (Render generated it; copy from the service's Environment tab) |
| &nbsp;&nbsp;`Content-Type` | `text/html; charset=utf-8` |
| &nbsp;&nbsp;`X-Filename` | `={{ "peoples_manifesto_v" + $json.version + ".pdf" }}` |
| Send Body | on |
| &nbsp;&nbsp;Body Content Type | **Raw** |
| &nbsp;&nbsp;Content Type | `text/html` |
| &nbsp;&nbsp;Body | `={{ $json.html }}` |
| Options > Response > Response Format | **File** |
| Options > Response > Put Output in Field | `data` |

Use **Raw**, not JSON. A manifesto is a large string full of quotes and
newlines, and JSON-escaping it inside an n8n expression is the step that
usually breaks. Raw sends the expression result verbatim. The service accepts a
JSON body too (`{"html": "...", "filename": "..."}`) if you ever need it.

### Node: Upload (Google Drive)

| Setting | Value |
|---|---|
| Resource / Operation | File / Upload |
| Input Data Field Name | `data` |
| File Name | `={{ $('Render PDF').item.binary.data.fileName }}` |
| Parent Drive / Folder | wherever the manifesto lives |

### Test it before wiring anything

Render gives a private service a shell. Open the service, click **Shell**,
and hit it from inside:

    curl -X POST http://localhost:5000/pdf \
      -H 'X-Auth-Token: your-token' \
      -H 'Content-Type: text/html; charset=utf-8' \
      -H 'X-Filename: test.pdf' \
      --data-binary @manifesto_sample.html \
      -o test.pdf

## Things that will bite you

**Relative asset paths.** `<img src="logo.png">` resolves against nothing when
the HTML arrives as a string, and the image is dropped in silence rather than
raising. Either use absolute `https://` URLs, or send `X-Base-Url` and let the
service resolve against it.

**Fonts.** The container ships Liberation, DejaVu and Noto. A font that is not
installed falls back silently and changes every line break, which is the usual
cause of "it looks right locally but wrong from the service". For a brand font,
drop the `.ttf` into `fonts/` and rebuild: `fc-cache` makes it visible to Pango
under its real family name.

**WeasyPrint's flexbox is partial.** `margin-top: auto` and `flex: 1` are
ignored, so any layout that leans on flex to push content to the foot of a page
collapses upward without an error. The stylesheet uses absolute positioning
instead, for the cover block and the contents page numbers. Keep it that way.

**`string-set` belongs on the heading, not the section.** `content(text)` takes
the whole element's text, so putting it on `.region` stuffs the entire region
into the header box and clips it. It also persists until something overwrites
it, which is why `.method > h2` resets it to `""`.

**Backgrounds print by default** in WeasyPrint. No `printBackground` flag, no
`print-color-adjust` needed. The rule in the stylesheet is only there in case
the same HTML is ever rendered by a browser.

**Memory.** Nothing like Chromium's appetite, but a manifesto with hundreds of
embedded images will still grow. If the PDF ever gets uncomfortably large, it
is almost certainly unoptimised images rather than text: resize them to the
dimensions they actually display at before they go into the HTML.
