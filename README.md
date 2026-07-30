# BYOAPI — Local UI for kie.ai (Seedream, WAN, Grok Imagine, Seedance & more)

**Bring Your Own API key.** A self-hosted, single-file web app for
generating images and video with today's best models — **Seedream 5
Pro, WAN 2.7, Grok Imagine, Seedance, Hailuo**, and more — by talking
straight to the [kie.ai](https://kie.ai) API with your own key, instead
of paying a subscription markup to some site that's doing exactly the
same API call behind a nicer checkout page. Plus an **AI storyboard
tool** that turns a topic or a rough idea into a full multi-scene
story: consistent characters, a key image per scene, and an animated
clip for each one, stitched together from nothing but a few sentences
of input. It's one Python script and one HTML file, needs nothing
installed beyond Python itself, and runs entirely on your own machine —
the only network calls it makes are to kie.ai's API (and, optionally,
directly to xAI — see section 5a).

**What's in it:**

- **Image generation** — Seedream 5 Pro, WAN 2.7 Image, and Grok
  Imagine, all in one tab, with automatic text-to-image vs.
  image-editing depending on whether you've attached a source image.
- **Video generation** — eight kie.ai models (Wan 2.6, Wan 2.7, three
  Seedance variants, Grok Imagine Video, Hailuo 02) plus **ComfyUI/LTX
  2.3** support for running your own local video workflow instead.
- **📖 Story tab** — describe a topic or paste in a rough story and Grok
  breaks it into a shot list, writes an image prompt per scene, and
  keeps recurring characters (and the environment, when it should)
  visually consistent from scene to scene automatically. Generate every
  scene's image, then animate each one into a short video clip, all
  without leaving the page.
- **👤 Character library** — save a name, an identity description, and
  reference photos once, then reuse that person across every image,
  video, and story scene without redescribing them every time.
- **✨ Prompt Assistant** — an embedded, conversational Grok assistant
  that writes production-ready prompts for whichever model/mode you're
  currently using, with a real back-and-forth (refine, don't restart)
  instead of a single one-shot generation.
- **Cost tracking & an Options panel** — a running spend estimate
  (session and all-time), per-model enable/disable toggles, editable
  pricing overrides, and every Grok system prompt in the app collected
  in one editable place.
- **Resilience built in** — if kie.ai's own Grok proxy has a bad day,
  an optional direct-xAI fallback (manual or automatic) keeps prompt
  writing and story generation working.
- **🔥 NSFW mode — on by default** — every Grok system prompt in the
  app (thirteen of them) ships with an explicit counterpart, actively
  used out of the box; a prominent switch at the top of the Options
  panel turns it off if you'd rather it not be. See section 5a for
  details — kie.ai's/xAI's own content moderation on the actual
  generation calls still applies regardless of this setting.

Everything below walks through setup and every feature in detail — for
a quick start, jump to sections 0–4 and come back for the rest as you
need it.

**Donations:** `bc1q7gtpm7r8uvdg8gzyqn4e0awrxmmcx2ltm4lwx9`

---

## 0. Download this project

No `git` command needed:

1. Go to the [GitHub page](https://github.com/ai-bender9988/byoapi).
2. Click the green **"Code"** button, then **"Download ZIP"**.
3. Extract the downloaded ZIP file somewhere on your computer — on
   Windows, right-click it and choose **"Extract All..."**; on Mac,
   just double-click it. The extracted folder (containing `proxy.py`,
   `index.html`, `run.bat`, and everything else) is your project
   folder — that's what the rest of these steps mean by "the project
   folder." On Windows, `run.bat` is the file you'll double-click in
   step 4 to actually start the app.

---

## 1. Install Python

You need Python 3.10 or newer (the code uses `str | None`-style type
hints, which only work at runtime from 3.10 on). No other packages are
required — everything here uses only Python's standard library, no
`pip install` needed.

**Check if you already have it:**

- **Windows:** open Command Prompt (search "cmd" in the Start menu) and run:
  ```
  python --version
  ```
  or
  ```
  python3 --version
  ```
- **macOS:** open Terminal (Cmd+Space, type "Terminal") and run:
  ```
  python3 --version
  ```
- **Linux:** open a terminal and run:
  ```
  python3 --version
  ```

If you see something like `Python 3.11.4`, you're good — skip to step 2.

**If Python isn't installed:**

- **Windows:** download the installer from [python.org/downloads](https://www.python.org/downloads/).
  During installation, make sure to check the box **"Add python.exe to PATH"**
  before clicking Install — this is easy to miss and without it the `python`
  command won't work in your terminal.
- **macOS:** download the installer from [python.org/downloads](https://www.python.org/downloads/)
  and run it. (macOS ships with an old Python 2 in some versions — always use
  `python3`, not `python`, on Mac.)
- **Linux:** Python 3 is usually preinstalled. If not, use your package
  manager, e.g. `sudo apt install python3` on Debian/Ubuntu.

After installing, close and reopen your terminal, then verify again with
`python --version` (Windows) or `python3 --version` (macOS/Linux).

---

## 2. Get a kie.ai API key

1. Go to [kie.ai](https://kie.ai) and create an account (or log in).
2. Open your **Dashboard**.
3. Find the **API Keys** section (sometimes under account/profile settings)
   and create a new API key.
4. Copy the key — you'll only need to do this once.
5. You'll also need credits in your kie.ai account to actually generate
   images; check their dashboard for how to add credits.

---

## 3. Set up this project

Already downloaded the project in step 0? Then just:

1. **Give the app your kie.ai API key.** There are two ways — pick
   whichever's easier, both end up the same:
   - **Through the app itself (no text editor needed):** skip straight
     to section 4 and start the app — it runs fine with no key yet.
     Once it's open, click **"⚙ Options"** at the top and paste your
     key into the **"API keys"** section there (see section 5a). This
     is the easiest route if you're using `run.bat`.
   - **By hand, before starting the app:** rename
     `kie_key.example.txt` to `kie_key.txt`, open it in a plain text
     editor, and paste your key in — nothing else, just the key.
2. Optional: to be able to switch to the "Direct xAI API" Grok backend
   (Options panel, section 5a — bypasses kie.ai's Grok proxy entirely for
   when it's erroring out), get an xAI API key from console.x.ai and give
   it to the app the same way as above — either through the same
   "API keys" section in Options, or by renaming `xai_key.example.txt`
   to `xai_key.txt` and pasting it there by hand. Skip this if you're
   fine staying on kie.ai only — everything works exactly as before
   without it.

---

## 4. Run it

**Windows — the easy way:** double-click **`run.bat`** in the project
folder. It checks that Python is installed **and that it's new enough
(3.10+)** — if either isn't true, it automatically opens
python.org's download page in your browser (it doesn't download or
install anything itself — you still click through the installer
yourself, same as always) and tells you exactly what to click during
setup ("Add python.exe to PATH"). It also reminds you if `kie_key.txt`
isn't set up yet (without blocking you; see section 3), starts the
server, and opens your browser to the app automatically after a couple
of seconds. Close its window (or press Ctrl+C in it) any time to stop
the server — same as the manual method below.

**Everyone else (or if you'd rather use a terminal):** open a terminal,
navigate to the project folder, and run:

```bash
python3 proxy.py
```

(On Windows, use `python proxy.py` if `python3` isn't recognized.)

You should see something like:

```
API key found in kie_key.txt.
Own UI:          http://127.0.0.1:8787
Open WebUI base: http://<this-ip>:8787/v1  (Engine = Open AI, API key = any value)
(Ctrl+C to stop)
```

Now open **http://127.0.0.1:8787** in your browser.

Leave this terminal window open while you use the tool — closing it (or
pressing Ctrl+C) stops the server.

---

## 5. Using the UI

The app has four tabs: **🖼 Image** (the default), **🎬 Video**,
**📖 Story**, and **👤 Characters**.

- **Image** (default tab): pick an **Image model** (Seedream 5 Pro,
  WAN 2.7 Image, or Grok Imagine), optionally attach source image(s) in
  the dropzone (click or drag-and-drop — up to 10 for Seedream, 9 for
  WAN 2.7 Image, 5 for Grok Imagine), type a prompt, and click
  **Generate**. Text-to-image vs. image-to-image is decided
  automatically: attach images and your prompt becomes an edit
  instruction for them; leave it empty and you get a brand-new image
  from the prompt alone. The aspect ratio selector only applies to
  text-to-image — it hides once images are attached, since output then
  follows the source image's size (see sections 7a and 7c).
- **Video**: pick a **Video model** — Wan 2.6, Wan 2.7 I2V, Wan 2.7
  R2V, one of the Seedance/Grok Imagine/Hailuo models (section 7 covers
  what each one needs), or **ComfyUI — LTX 2.3**, which runs on your
  own network instead of kie.ai (section 7b) — upload the required
  source image(s), describe the motion/action, pick a duration, and
  click **Generate video**. Or skip writing a prompt entirely and click
  **🍀 Feeling Lucky with Grok** (see the end of section 6).

Images usually take 10–60 seconds, video more like 1–3 minutes. You
don't have to wait for one to finish before starting the next — click
**Generate** again right away and each run gets its own card with its
own status, so several can be in flight at once.

Everything you generate is saved locally in the `outputs/` folder and
shows up in the **Gallery** at the bottom of the page — this matters
because kie.ai's own result links expire, so without it you'd lose
access to anything you don't download yourself. The gallery loads 24
items at a time with a "Show more" button (it's built to grow into the
hundreds without slowing down). Above the grid: a **search box**
filters by prompt text as you type; a **model dropdown** (populated
automatically from whatever's actually in your gallery) filters to one
model at a time; and a **"★ Favorites only"** checkbox filters to just
the items you've starred. Click the ★ on any thumbnail to
favorite/unfavorite it — favorites are saved server-side (`gallery.json`),
so they survive a refresh. All three filters combine (e.g. search text
+ one model + favorites-only at once). Click "↺ Reuse" on any job card
or gallery thumbnail to reload that prompt and its settings; source
images aren't stored for gallery reuse though (only job cards from the
current session keep them), so image-edit and video reuse from the
gallery needs a re-upload. Hover a thumbnail and click × to delete it
permanently.

Click a gallery image (or a Story scene image) to open it in the shared
**lightbox**: it opens fit-to-screen; click the image itself to switch
to native pixel size (scrollable if it's bigger than your screen), and
click again to switch back — the image toggles between the two sizes
rather than closing. To close the lightbox, click anywhere outside the
image, press Escape, or click the × in the corner. Right-click an image
still gives you the normal "open in new tab"/"save image as" browser
menu, untouched.

---

## 5a. Options panel

The "⚙ Options" button (top of the page, next to the session spend
estimate) opens a settings panel, persisted server-side
(`app_config.json`) so it survives a restart:

- **Image models / Video models**: checkboxes to enable or disable
  individual models. Disabling one removes it from every relevant
  dropdown (Image tab, Video tab, and the Story tab's "Video engine"
  selector for ComfyUI-LTX/Seedance 1.5 Pro) — and it's enforced
  server-side too, in `/api/create-task` and `/api/comfyui-queue`, so a
  stale browser tab (or the API called directly) can't slip a disabled
  model through either. If the currently-selected model in a dropdown
  gets disabled, that dropdown falls back to the first still-enabled
  option automatically.
- **Pricing**: every per-model rate behind the cost estimates shown
  throughout the app (Seedream's 1K/2K/extra-reference rates, each video
  model's $/second, Seedance 1.5 Pro's with-audio rate, and the other
  Seedance models' unconfirmed audio surcharge) is editable here, for
  when kie.ai's published rates change. "Reset to built-in defaults"
  restores the values documented in section 10 without needing to know
  what they were. This only affects what this app *estimates* — it has
  no effect on what kie.ai actually charges your account.
- **Spend cap**: an optional hard ceiling (in USD, 0 = disabled) on the
  All-time spend estimate. Once that total reaches the cap,
  `/api/create-task` refuses to start any new kie.ai image/video job —
  enforced server-side, so it holds even from a stale browser tab, not
  just a disabled button in the UI. The spend bar shows how much is left
  ("$X.XX left of $Y.YY cap") once one is set. Same caveat as everywhere
  else in this section: it's checked against this app's own *estimate*,
  not kie.ai's real billing, so leave some headroom rather than setting
  it to the exact edge of what you're willing to spend.
- **Seed control**: off by default. Turning it on reveals a "Seed" field
  on the Image and Video tabs, but only for the three kie.ai models that
  actually accept one — confirmed against kie.ai's own API docs, not
  guessed: **WAN 2.7 Image**, **WAN 2.7 First/Last Frame to Video**, and
  **WAN 2.7 Reference to Video**. Every other model here (Seedream 5 Pro,
  Grok Imagine, WAN 2.6, all four Seedance variants, Hailuo 02) has no
  seed parameter in kie.ai's documented API at all, so the field simply
  doesn't appear for them regardless of this setting. The field is
  always blank by default (kie.ai picks randomly when it's left out) and
  resets to blank after every generation — fill it in for one specific
  job to reproduce or nudge a previous result, rather than it silently
  staying pinned to a fixed value.
- **API keys**: lets you set/replace your kie.ai and xAI API keys from the
  UI instead of hand-editing `kie_key.txt`/`xai_key.txt`, the same way the
  Video tab already lets you set a ComfyUI server URL instead of editing
  `comfyui_config.json` by hand. A key that's already saved is never shown
  back here (the label just says "currently set" / "not set") — leaving a
  field blank and clicking "Save keys" leaves that key untouched, so
  updating one doesn't require re-typing the other. The kie.ai field works
  even before any `kie_key.txt` exists yet (a fresh install), so you never
  strictly have to touch the file by hand.
- **Grok backend**: every Grok call in this app (Story generation, Prompt
  Assistant, scene video prompts) normally goes through kie.ai's own Grok
  Responses API. kie.ai's Grok proxy does intermittently return its own
  server errors, though, independent of anything this app does — so
  there's a way around it: switching this setting to **"Direct xAI
  API"** bypasses kie.ai entirely and calls xAI's own Chat Completions
  API instead, using the xAI key set above (get one at console.x.ai).
  It's a **manual** switch — kie.ai stays the default until you change
  it, so a flaky kie.ai proxy never silently starts routing (and
  billing) elsewhere on its own. Picking "Direct xAI API" with no xAI
  key set fails immediately with a clear message instead of a confusing
  retry loop. The two Grok model choices (`grok-4-3`/`grok-4-5`) map
  straight across to xAI's own ids (`grok-4.3`/`grok-4.5`); the Story
  tab's "X-High" reasoning effort quietly clamps to "High" on this
  backend, since xAI only documents low/medium/high.

  A separate checkbox, **"Automatically fall back to direct xAI if
  kie.ai fails"** (off by default), sits on top of that manual switch:
  while the backend above is still "kie.ai," a failed call gets one
  silent retry against xAI (if a key is set) before the error surfaces.
  Live-confirmed end to end with kie.ai's Grok proxy genuinely down —
  both `/api/generate-prompt` and `/api/generate-story` correctly fell
  back to `api.x.ai`. If both attempts fail, the error message names
  which backend each failure came from. And when a fallback *succeeds*,
  it's never silent either: a small amber "⚠ kie.ai failed — used
  direct xAI instead" notice shows up right next to the result — in the
  Prompt Assistant's chat history, the Story tab's "Done" status line,
  and the relevant scene's video job card — so you always know which
  backend actually produced what you're looking at.
- **Grok prompts**: every system prompt this app sends to Grok, all
  thirteen, each collapsed behind a clearly-labeled summary so it's
  unambiguous which is which:

  | Label in the Options panel | `proxy.py` constant | Used by |
  |---|---|---|
  | Seedream — Text to Image | `SEEDREAM_T2I_SYSTEM` | Image tab, Prompt Assistant, no source image |
  | Seedream — Image Edit | `SEEDREAM_I2I_SYSTEM` | Image tab, Prompt Assistant, with a source image |
  | Seedance — Image to Video | `SEEDANCE_I2V_SYSTEM` | Video tab, Prompt Assistant; also the Story tab's "Seedance 1.5 Pro"/"Hailuo 02 Standard" video engines |
  | WAN 2.7 Image — Edit | `WAN_IMAGE_I2I_SYSTEM` | Image tab, Prompt Assistant, WAN 2.7 Image model |
  | Grok Imagine — Image Edit | `GROK_IMAGE_I2I_SYSTEM` | Image tab, Prompt Assistant, Grok Imagine model (with a source image) |
  | WAN 2.7 — First/Last Frame to Video | `WAN_I2V_SYSTEM` | Video tab, Prompt Assistant |
  | WAN 2.7 — Reference to Video | `WAN_R2V_SYSTEM` | Video tab, Prompt Assistant |
  | ComfyUI — LTX 2.3 | `VIDEO_LTX_MOTION_SYSTEM` | Video tab, Prompt Assistant, "Feeling Lucky with Grok" |
  | Story tab — Scene generation | `STORY_SYSTEM` | The shot-list writer behind "Generate story" |
  | Story tab — Scene video motion | `STORY_LTX_MOTION_SYSTEM` | Per-scene "Generate video" when the LTX engine is picked |
  | Story tab — Scene video motion (Grok Imagine Video) | `GROK_IMAGE_VIDEO_MOTION_SYSTEM` | Per-scene "Generate video" when the Grok Imagine Video engine is picked |
  | Story tab — "Rewrite for ..." → Grok Imagine style | `GROK_IMAGE_STORY_SCENE_CONVERT_SYSTEM` | Per-scene image-prompt style conversion button (section 8a) |
  | Story tab — "Rewrite for ..." → Seedream style | `SEEDREAM_STORY_SCENE_CONVERT_SYSTEM` | Same button, converting the other direction |

  This is the same override/reset mechanism, the same
  `assistant_prompts_override.json` file, and the exact same
  `/api/assistant-prompts` endpoint the embedded Prompt Assistant editor
  ("&#9998; Edit system prompt" on the Image/Video tabs) uses — editing a
  prompt here changes the same thing editing it there would, they're
  just two different places to reach the same overrides. If you edit
  the Story generation prompt, keep both `{{MAX_SCENES}}` placeholders
  (and the `{{IMAGE_PROMPT_STYLE}}` one) in it — the app substitutes
  those automatically, and removing them silently stops that from
  working rather than erroring.

  Each of the thirteen prompts actually has **two** fields: **Normal**
  (as documented above) and **NSFW** underneath it — both pre-filled with
  a real, built-in prompt (`DEFAULT_ASSISTANT_SYSTEM_PROMPTS`/
  `DEFAULT_ASSISTANT_SYSTEM_PROMPTS_NSFW` in `proxy.py`, both committed to
  this repo), editable and independently resettable. A prominent **"🔥
  NSFW mode"** switch at the very top of this panel decides which set
  Grok actually gets — **on by default**: every fresh install starts
  with explicit prompts active across all thirteen. Turn it off there to
  go back to the Normal set instead. This only changes which
  *instructions* get sent to Grok — it has no effect on kie.ai's or
  xAI's own content moderation on the actual image/video generation
  calls, which can still reject a result independently. Like the model
  toggles above (and unlike the auto-fallback checkbox), this setting
  **is** remembered across restarts — it stays however you left it. Any
  further edits you make to either field are still saved to
  `assistant_prompts_override.json`, which stays gitignored — only the
  built-in starting points are part of the repo, your own tweaks on top
  of them are not.

---

## 6. Prompt Assistant (Grok-written prompts)

The assistant is **embedded right where you write prompts**: on the
Image and Video tabs there's a "✨ Prompt Assistant" button next to the
Prompt label. Clicking it unfolds an assistant panel below the form —
describe your idea in plain language there, press Send, and **Grok**
writes a polished, production-ready prompt. Clicking "Use this prompt"
on a reply fills the prompt field right above it — no tab-switching, no
re-uploading.

**The assistant's writing mode is derived automatically** from where
you are: which tab you're on, which model you've selected, and (on the
Image tab) whether source images are attached. A hint line at the top
of the panel always shows what it's currently writing for. There is no
mode dropdown to get wrong anymore. The mapping:

| Context | System prompt used |
|---|---|
| Image tab, no source images | Seedream — new image from text |
| Image tab, Seedream + source images | Seedream — image edit |
| Image tab, WAN 2.7 Image + source images | WAN 2.7 — image edit |
| Image tab, Grok Imagine + source images | Grok Imagine — image edit |
| Video tab, Wan 2.6 or a Seedance model | Seedance — animate to video |
| Video tab, Wan 2.7 I2V | WAN 2.7 — first/last frame to video |
| Video tab, Wan 2.7 R2V | WAN 2.7 — reference-to-video |
| Video tab, ComfyUI — LTX 2.3 | LTX 2.3 — motion prompt |

Each mode uses a detailed, purpose-built system prompt (adapted from
expert prompt-engineering guides for these specific models) covering
identity locking, concrete pose/action writing, camera rules for
video, multi-character scenes, and (for the Wan 2.7 video modes) an
auto-written **negative prompt** that "Use this prompt" fills into the
negative-prompt field too.

**It's a real conversation, not one-shot**: while the assistant is
open, the panel on the right shows its chat (the jobs list comes back
when you close the assistant). Send a follow-up message any time —
"make the hair red instead", "make it shorter", "add a hat" — and Grok
refines the previous prompt using the full conversation as context.
Each assistant reply gets its own "Use this prompt" button, so you can
go back and use an earlier version too. Click **"New conversation"** to
clear the history for the current mode and start fresh.

Conversations are kept **separately per mode** (the conversation shown
follows the auto-derived mode above) and are **not saved to disk** —
they live only in the browser tab and are lost on refresh. The full
conversation is resent to kie.ai on every message (the Grok API itself
is stateless per request), so very long conversations mean more tokens
per message — use "New conversation" once a thread has served its
purpose.

The assistant asks Grok for **structured output** (prompt + negative
prompt + a short reasoning explanation as separate fields, via kie.ai's
`text.format` JSON-schema mechanism) so each reply's prompt bubble
contains only the final prompt — the negative prompt (Wan 2.7 video
modes only) and the reasoning behind the key choices are shown
separately underneath it, in small text.

**Optional reference images**: below the brief field, you can attach up
to 4 images (drag-and-drop or click) that Grok will actually look at
(via kie.ai's Grok vision/`input_image` support) before writing the
prompt — for the edit and video modes this means Grok describes the
real character's identity/framing instead of guessing from text alone.
These images are sent straight to Grok as base64 (no separate upload
step needed, unlike the generation models). If you click "Use this
prompt" while the generation form's own image slot is still empty, the
same reference image(s) are copied over automatically so you don't
have to re-upload them for the actual generation.

It calls kie.ai's Grok Responses API (`https://api.kie.ai/grok/v1/
responses`), trying `grok-4-3` first and falling back to `grok-4-5` if
that one fails. No other providers are used for this feature.

If both fail, the error message shown includes kie.ai's full response
for each attempt (and the same detail is printed to the terminal
running `proxy.py`), so you can see exactly what went wrong rather than
a generic failure.

Note: the underlying system prompts reference `@Image`/`@Video`-style
tags in their original form (written for a chat tool where files are
literally attached); since this tool sends images to kie.ai separately
via `image_urls`/`first_frame_url`, those tags are explicitly excluded
from the assistant's output. **How to actually refer to multiple
uploaded images in the generated prompt text** differs by model, and
the app writes each one's prompts accordingly:

- **Seedream** uses plain positional language — "Figure 1", "Figure
  2", etc., matching upload order in `image_urls` (kie.ai's own
  Seedream 5.0 prompt guide gives *"Replace the costume in Figure 1
  with the one in Figure 2"* as an example). It's just descriptive
  text the model interprets, not a parsed tag — `image_urls[0]` =
  "Figure 1", `image_urls[1]` = "Figure 2", and so on.
- **Seedance/Wan video models** use plain role labels instead
  ("Character A" / "Character B"), since positional "Figure N" phrasing
  isn't separately confirmed for those.
- **Grok Imagine** (image editing and image-to-video both) requires an
  actual `@image(n)` token in the prompt text — `@image1`, `@image2`,
  etc. — a hard binding mechanism, not just a naming convention; see
  section 7c for the full detail on this one.

**Editing the system prompts**: click "✎ Edit system prompt" at the
top of the assistant panel to view and edit the exact instructions Grok
receives for the currently active (auto-derived) mode. Your edit is saved per mode in
`assistant_prompts_override.json` (created automatically) and used from
then on for that mode — "Reset to default" deletes your override and
goes back to the built-in prompt. This is meant for small tweaks (tone,
extra rules, house style); if you rewrite it heavily, keep in mind the
built-in prompts also contain the instruction that tells Grok not to
use `@Image`-style tags and to reply with structured JSON — removing
that part will likely break parsing of the response.

**🍀 Feeling Lucky with Grok** (Video tab only, next to Generate video):
skips the assistant panel entirely. Click it and Grok writes a motion
prompt from your attached source image(s) — using the exact same
system prompt the assistant would use for the currently selected video
model (see the mode table above) — and generation is queued
immediately with that prompt, with no review or edit step in between.
It works with every video model, not just ComfyUI/LTX. If the Prompt
field has text in it, that's sent to Grok as a short brief/hint to
follow; leave it empty and Grok invents a motion entirely on its own
from what's visible in the image(s). Under the hood this is the exact
same `/api/generate-prompt` endpoint and system prompts as the regular
assistant — "Feeling Lucky" is just a shortcut that calls it once with
a synthetic brief (when yours is empty) and skips straight to
`Generate video` with the result.

---

## 7. Video generation (Wan 2.6, Wan 2.7, Seedance 1.5 Pro, Seedance 2, Seedance 2 Fast, Seedance 2 Mini, Grok Imagine Video 1.5, Hailuo 02 Standard)

The "Image-to-Video" tab offers eight kie.ai video models via a **Video
model** dropdown at the top (plus ComfyUI/LTX 2.3, section 7b, a ninth
option that runs on your own network instead); the form below it adapts
automatically to whichever one you pick (image upload requirement,
duration options, audio toggle, negative prompt, aspect ratio) since
each model has different capabilities and parameters on kie.ai.

- **Wan 2.6** (`wan/2-6-image-to-video`) — one required source image,
  5 or 10 second duration, 720p fixed, no audio option. Only one source
  image is accepted per request (unlike Image-to-Image, which accepts
  several).
- **Wan 2.7 — First / Last Frame to Video** (`wan/2-7-image-to-video`) —
  one required start-frame image, plus an *optional* second image used
  as the end frame (upload both, in that order, and Wan 2.7 infers the
  motion between them). 2–15 second duration (confirmed on kie.ai's
  playground), 1080p fixed in this app (kie.ai also offers 720p — edit
  `resolution` in `VIDEO_MODELS` if you want that instead), no audio,
  and a **negative prompt** field (kie.ai supports one for this model,
  unlike Seedream/Seedance).
- **Wan 2.7 — Reference to Video** (`wan/2-7-r2v`) — reference images
  (character/prop/style — sent as kie.ai's `reference_image` array)
  **and/or reference videos** (motion/voice/style replication — sent as
  `reference_video`), sharing one combined budget of **5 items total**
  (kie.ai's own cap across images+videos) — the reference-video dropzone
  appears once you're on this model, and its room shrinks as you add
  images and vice versa. An aspect ratio selector (kie.ai's docs note
  this is only used when no start frame overrides it, which this app
  never passes for R2V), 2–10 second duration (confirmed on kie.ai's
  playground; kie.ai's own docs additionally state duration must be an
  integer, default 5), 1080p fixed, negative prompt supported.
  Deliberately not exposing kie.ai's `reference_voice` input (a separate
  audio-only timbre reference) — video already covers the "replicate
  motion/style from existing footage" use case this app targets.
- **Seedance 1.5 Pro** (`bytedance/seedance-1.5-pro`) — 0–2 optional
  source images (leave empty for text-only), 4/8/12 second duration,
  480p fixed, with an audio on/off toggle (audio generation costs
  extra). If you don't upload an image, you also get an aspect ratio
  selector; uploading an image makes the output match that image's
  size instead.
- **Seedance 2** (`bytedance/seedance-2`), **Seedance 2 Fast**
  (`bytedance/seedance-2-fast`), and **Seedance 2 Mini**
  (`bytedance/seedance-2-mini`) — image-to-video, with a **"Use as exact
  starting frame"** checkbox controlling which of kie.ai's two separate
  image-input mechanisms gets used:
  - **Checked (default)**: one required source image, sent as
    `first_frame_url` — the video continues precisely from that exact
    frame.
  - **Unchecked**: up to **9** loose reference images, sent as
    `reference_image_urls` — a looser style/identity reference rather
    than "continue from this exact frame." A **reference video(s)**
    dropzone also appears in this mode (up to **3**, sent as
    `reference_video_urls` — a separate budget from the 9 images, not
    shared). Switching the checkbox clears any already-attached
    images/videos, since the two modes don't mean the same thing.
  Both modes share a free-form duration field (kie.ai's documented
  range is roughly 4–15 seconds, not a fixed set of values), 480p fixed,
  aspect ratio selector, and an audio on/off toggle. Deliberately not
  using kie.ai's `reference_audio_urls` input for these three. Seedance
  2 Fast trades some quality for faster generation; Seedance 2 Mini is
  the cheapest and fastest of the three, aimed at quick
  iteration/prototyping over polished final output (kie.ai's Mini also
  supports 720p, but this app keeps it at 480p for consistency with its
  siblings — edit `resolution` in `VIDEO_MODELS` in `index.html` if you
  want 720p for Mini specifically).
- **Grok Imagine Video 1.5 Preview** (`grok-imagine/image-to-video`) —
  1-7 required source images (`image_urls`; this app never uses Grok
  Imagine's own separate text-to-image `task_id`/`index` chaining
  mechanism, since that's a different, unimplemented workflow), a
  free-form 6-30 second duration field (confirmed on
  `docs.kie.ai/market/grok-imagine/image-to-video` — note kie.ai
  documents `duration` as a **string**, not a number, unlike every other
  model here; this app sends it as one), 480p fixed (kie.ai also offers
  720p — edit `resolution` in `VIDEO_MODELS` if you want that), and an
  aspect ratio selector — **a strict enum here, unlike every other
  video model in this app: only `1:1`/`16:9`/`9:16`/`3:2`/`2:3` are
  accepted** (confirmed on kie.ai's own OpenAPI spec), and only
  actually applied server-side when more than one image is attached
  (single-image mode follows the image's own size instead). This app's
  own aspect-ratio selectors (both the Video tab's and the Story tab's)
  offer a wider set, including `4:3`/`3:4`/`21:9` — sending one of those
  straight through used to get rejected by kie.ai outright;
  `GROK_IMAGINE_VIDEO_ASPECT_RATIOS`/`closestAspectRatioFrom()` in
  `index.html` now clamp to the nearest accepted value before sending,
  specifically for this one model. No audio field is documented for
  this endpoint. Also selectable as a fast, no-local-server video engine
  for Story tab scenes (section 8a), alongside Seedance 1.5 Pro and
  ComfyUI/LTX — and the only Story tab video engine that actually uses
  more than one image: on the Video tab, this app only ever sends the
  image(s) you manually attach, same as always, but on the Story tab
  specifically, `generateSceneVideo()` also fetches the scene's
  checked/matched characters' saved reference photos and attaches those
  too (@image2, @image3, ... — same required `@image(n)` prompt
  convention as Grok Imagine's image editing, confirmed on the same docs
  page), capped at 7 total. A dedicated system prompt,
  `GROK_IMAGE_VIDEO_MOTION_SYSTEM` in `proxy.py` (Story tab only — the
  Video tab's own Prompt Assistant mode for this model still reuses the
  regular Seedance one, since it never deals with more than one image),
  tells Grok that @image1 is always the scene's key frame and any
  further images are always character identity references, not
  alternate scenes/props — a narrower, more specific case than
  Seedance's fully generic multi-image "reference mode" (see below).
- **Hailuo 02 — Image to Video Standard**
  (`hailuo/02-image-to-video-standard`) — one required start-frame image
  plus an *optional* end-frame image, same first/last-frame idea as Wan
  2.7 I2V above but with singular field names (`image_url`/
  `end_image_url`, not arrays). Duration is a **string enum with only
  two allowed values, `"6"` or `"10"`** (confirmed on
  `docs.kie.ai/market/hailuo/02-image-to-video-standard` — no free-form
  range like the other models here), resolution a string enum
  (`"512P"`/`"768P"`, locked to 512P here per request — kie.ai defaults
  to 768P; edit `resolution` in `VIDEO_MODELS` if you want that
  instead). No aspect ratio, no negative prompt, no audio field
  documented for this endpoint. Also selectable as a Story tab video
  engine (section 8a), same as Seedance 1.5 Pro and Grok Imagine.

Common notes:
- Supported image formats across these models: JPEG, PNG, WebP; max
  10MB per file (30MB for the Wan 2.7 models per kie.ai's own limit,
  though this app's upload dropzones still advertise 10MB for
  consistency with the others).
- A per-second cost estimate is shown above the "Generate video" button,
  using **confirmed rates from kie.ai's own pricing page** for the exact
  resolution/mode each model runs at in this app (Wan 2.6 at 720p; Wan
  2.7 I2V/R2V at 1080p, $0.12/s; the four Seedance models at 480p,
  always with a single first-frame image rather than a video input, so
  the cheaper "with video input" tier never applies here). For Seedance
  1.5 Pro, kie.ai prices audio on/off as a full separate rate ($0.0175/s
  with audio vs $0.00875/s without), and the app switches between them
  automatically. The other three audio-capable models (Seedance 2 / 2
  Fast / 2 Mini) don't split their price by audio in kie.ai's table at
  all, so the flat `VIDEO_AUDIO_SURCHARGE_USD` (currently $0.01/s) used
  for those three when audio is on remains an unconfirmed guess —
  kie.ai's own UI just says "additional cost applies" without a figure.
  **Grok Imagine Video 1.5** ($0.008/s at 480p) and **Hailuo 02
  Standard** ($0.01/s at 512p — kie.ai actually prices it per video,
  $0.06 for 6s / $0.10 for 10s, but that's exactly linear so it fits the
  same per-second model as everything else here) are both confirmed
  directly from the user's own kie.ai pricing dashboard, not a
  third-party or official-upstream estimate — both are meaningfully
  cheaper than xAI's/MiniMax's own published rates, since kie.ai applies
  its own discount on top (kie.ai's dashboard shows −90% vs xAI's
  official $0.08/s for Grok Imagine, for example). All rates live in
  `VIDEO_PRICING_USD_PER_SECOND` (and the two audio-related constants
  next to it) near the top of the `<script>` in `index.html`; update
  them if kie.ai changes pricing — or via the Options panel (section
  5a), which edits the same values without touching code.
  `NO_PRICING_VIDEO_MODELS` (currently empty) is the escape hatch for a
  future model added before its kie.ai rate is confirmed.
- Only the two Wan 2.7 video models have a confirmed `negative_prompt`
  parameter on kie.ai — for the other four, describe what you want to
  avoid as part of the main prompt text instead. The Prompt Assistant's
  two Wan 2.7 video modes (section 6) write a negative prompt
  automatically; for the other modes it's always left empty.

---

## 7a. WAN 2.7 Image (text-to-image and image editing)

The Image tab starts with an
**Image model** dropdown: **Seedream 5 Pro** (the default, described in
sections 5, 6, and 10) or **WAN 2.7 Image** (`wan/2-7-image`).

WAN 2.7 Image is a single, unified model for both generation and
editing — on the Image tab, uploading source image(s) turns
your prompt into an edit instruction (`input_urls`, **confirmed capped
at 9 images** by kie.ai's own API reference — this app enforces that
limit specifically for this model, separate from Seedream's 10-image
cap; switching Image models with more than 9 already attached trims
down to 9 automatically); leaving them empty
generates from scratch. **Aspect ratio** is sent for this model too, for
text-to-image generations only — kie.ai's API reference confirms
`aspect_ratio` as an optional parameter for wan/2-7-image, with its own
allowed-value list distinct from Seedream's: `1:1`, `16:9`, `4:3`,
`21:9`, `3:4`, `9:16`, plus two extreme banner ratios Seedream doesn't
offer, `8:1` and `1:8`. The aspect ratio selector's options switch
automatically to match whichever Image model is selected. Once source
images are attached the selector is hidden for this model instead,
since output size there follows the uploaded image, not
`aspect_ratio` — kie.ai's docs note the parameter only applies "when no
image input is provided." `n` is fixed at 1 generation per click
in this app; kie.ai's own optional knobs for gallery mode (up to 12
images/request), custom color palettes, and interactive box-based
region editing are not exposed here, matching the app's general
preference for a small, predictable set of controls over kie.ai's full
parameter surface.

**Cost estimate**: $0.024/image, confirmed directly from the user's own
kie.ai pricing dashboard (4.8 credits, a −20% discount vs the $0.03
official/fal.ai rate) — shown as one flat rate regardless of 1K/2K,
since kie.ai's own pricing table doesn't break it out by resolution.
Editable via the Options panel (section 5a) or `PRICING_USD.wanImage`
in `index.html`.

---

## 7b. ComfyUI — LTX 2.3 (image to video, your own network)

A second, completely independent video backend alongside the kie.ai
models above: instead of calling kie.ai, this option talks directly to
a **ComfyUI server running on your own network**, running **your own
exported LTX 2.3 workflow** (`comfyui_workflows/ltx-2.3.json`) — nothing
runs through kie.ai, and there's no kie.ai cost for it.

**Setup**: select "ComfyUI — LTX 2.3" in the Video tab's model dropdown,
then enter your ComfyUI server's address (e.g. `http://192.168.1.50:8188`)
and pick a **resolution** (540/720/1080px) and which side it **applies
to** (shorter or longer — the other side follows automatically from the
source image's own aspect ratio) in the fields that appear — all three
are saved locally (`comfyui_config.json`) so you only need to set them
once per server. This applies to Story tab
scene videos too (section 8a), not just this tab, since they share the
same ComfyUI pipeline. Upload a source image, write a prompt, pick a
duration (5/10/15/20 seconds — the only options, since the workflow
needs an exact frame count), and click "Generate video" like any other
model.

**How it works**: the app uploads your source image straight to
ComfyUI's own `/upload/image` endpoint — with a fresh, unique filename
every time (important: ComfyUI's LoadImage node reads the file from
disk at *execution* time, not at upload/queue time, so a static
filename would let a later upload in a queue silently overwrite an
earlier queued job's source image before it actually ran — this bit
the Story tab specifically, generating several scene videos back to
back) — clones your `ltx-2.3.json` workflow and fills in five values — the uploaded image,
your prompt, the frame count, a fresh random seed, and the resolution
— then queues it via ComfyUI's `/prompt` endpoint and polls `/history`
the same way the kie.ai models are polled, until the video's ready.
Everything else in the workflow (LoRA stack, sampler settings) comes
straight from your exported file, completely untouched. Frame count is
computed as `seconds × 24 + 1` — the `+1` matches the workflow's own
"number of frames" node (its default of 481 is exactly 20s × 24fps + 1,
LTX's temporal VAE needs an odd count), so 5/10/15/20s map to
121/241/361/481 frames. The resolution field sets the resize node's
`short_side_target` or `long_side_target` directly, matching whichever
side you picked (its `scale_mode` input switches between "Shorter Side"
and "Longer Side" accordingly) — the actual output dimensions round to
the nearest multiple of 32 per the workflow's own `divisible_by`
setting, so e.g. 720 on a square image comes out as 704×704, not
exactly 720×720. Once ComfyUI finishes, the app downloads the
result and saves it locally the same way as every other generation —
same gallery, same "↺ Reuse" behavior.

**If you re-export your workflow** (a different node layout, a newer
LTX version, etc.), the node IDs this app writes into are hardcoded in
`proxy.py` (`COMFYUI_LTX_IMAGE_NODE`, `COMFYUI_LTX_PROMPT_NODE`,
`COMFYUI_LTX_FRAMES_NODE`, `COMFYUI_LTX_SEED_NODE`,
`COMFYUI_LTX_RESIZE_NODE`, `COMFYUI_LTX_OUTPUT_NODE`) and will need
updating to match the new
node IDs, alongside replacing `comfyui_workflows/ltx-2.3.json` itself
with the new export (ComfyUI's menu → Dev mode enabled → "Save (API
Format)", not the regular save, which exports the UI graph instead of
the plain node-id → inputs format this app sends directly to
`/prompt`). Re-exporting will drop the "LTX Face Identity Reinforcer"
node described below (it's not part of ComfyUI's own graph export
tooling) — it'll need re-adding by hand the same way it was added here.

**Face consistency**: `ltx-2.3.json` includes a `LTXFaceIdentityReinforcer`
node (from the [10S-Comfy-nodes](https://github.com/TenStrip/10S-Comfy-nodes)
pack — confirmed already installed here via the existing
`LTXReferenceEnable`/`LTXReferenceConditioning` nodes from the same
pack) wired in just before the sampler, using the same source image
already used elsewhere in the graph as its identity reference. It's
paired with the [LTX-Best-Face-ID
LoRA](https://huggingface.co/Alissonerdx/LTX-Best-Face-ID)
(`Best_FaceID_v1.0_LoRA.safetensors`, added to the LoRA stack in node
`5272`) — the node's defaults (`source_id: 2.0`, `identity_strength: 1.0`)
are specifically tuned for that LoRA per its own documentation, so it's
there in your `models/loras` folder for the node to actually reach full
effect. On top of this, `STORY_LTX_MOTION_SYSTEM` in `proxy.py` also
writes an explicit closing "these details stay unchanged throughout"
clause into every motion prompt and steers away from actions/camera
choices known to trigger drift (rapid head turns, hair over the face,
extreme close-ups paired with camera movement) — prompt-level and
node-level reinforcement together, since this workflow has no separate
`stg_scale`-style guidance knob to tune (it runs on a distilled/DMD
LoRA setup at a fixed `cfg=1`, not the full Dev pipeline with tunable
CFG/STG).

---

## 7c. Grok Imagine (text-to-image and image editing)

A third **Image model** option, alongside Seedream 5 Pro and WAN 2.7
Image — available on the Image tab, and as a second choice (next to
Seedream 5 Pro) for the Story tab's own per-scene image generation (see
"Image engine" in section 8a below). Two different kie.ai model strings
depending on mode (confirmed on `docs.kie.ai/market/grok-imagine/
text-to-image` and `.../image-to-image`), switched automatically the
same way the other models already are (source images attached →
editing, empty → generation):

- **Text-to-image** (`grok-imagine/text-to-image`): `prompt`,
  `aspect_ratio` (`1:1`/`16:9`/`9:16`/`3:2`/`2:3`), always sent with
  `enable_pro: true` ("Quality" — a 4-image-per-generation batch,
  $0.025 total). kie.ai's own pricing page also lists a cheaper "Speed"
  variant (`enable_pro: false`, 6 images/generation, $0.02 total), but
  this app always uses Quality — there's no user-facing choice for it,
  unlike Seedream/WAN's resolution picker. **Important: this endpoint
  returns multiple images per generation, not one.** This app doesn't
  discard the extra images: `pollTaskForJob()` returns every
  `resultUrls` entry (not just the first, which is what every other
  model here only ever produces one of anyway), `runJob()` saves each
  one to the gallery as its own entry, and the job card shows all of
  them as a small grid (`job.imageUrls`, plural) instead of the usual
  single image. On the Story tab specifically, where a scene needs
  exactly one image, the scene card shows all 4 and waits for a click
  to pick one instead (see section 8a).
- **Image editing** (`grok-imagine/image-to-image`): `prompt` and
  `image_urls`, capped at **5** images (`MAX_IMAGES_GROK_IMAGINE_I2I`
  in `index.html`) — ⚠ **not actually confirmed against kie.ai's own
  API reference**, which as of this writing states "maximum one image
  per request" for this endpoint, with no higher cap documented
  anywhere kie.ai-side; xAI's own direct API docs describe multi-image
  editing but cap it at 3 source images. 5 was requested anyway ("try
  it, a real API error will tell us if it's wrong") — if kie.ai/xAI
  actually reject more than 1 (or 3) images, that surfaces as a normal
  job error rather than silently misbehaving. No `enable_pro`/quality
  parameter, no negative prompt. **`aspect_ratio` isn't documented for
  this endpoint at all** (docs.kie.ai's OpenAPI spec lists only
  `prompt`, `image_urls`, and `nsfw_checker`) — but a real test against
  the live API proved kie.ai quietly accepts one anyway and genuinely
  honors it, exactly matching xAI's own direct-API docs ("works for
  image generation and image editing with **multiple** images"):
  requesting `16:9` with a single attached image came back unchanged at
  the source image's own 1:1, while the identical request with 2 images
  attached came back at exactly 1280×720. So this app sends
  `aspect_ratio` unconditionally (harmless in the single-image case)
  and only shows the **Aspect ratio** selector once 2+ images are
  attached — with exactly 1, it hides in favor of a short hint
  explaining that single-image edits ignore it and follow that image's
  own size instead. Always returns exactly one image, same as every
  other model's i2i mode.
  **Multi-image prompts must reference each attached image by a
  literal `@image1`, `@image2`, ... token** in the prompt text itself —
  this is Grok Imagine's own required binding mechanism between text
  and a specific uploaded image, not just a naming convention (unlike
  Seedream/WAN's descriptive-only "Figure 1", "Figure 2..."). The
  Prompt Assistant's dedicated `grok_image_i2i` system prompt
  (`GROK_IMAGE_I2I_SYSTEM` in `proxy.py`) instructs Grok to always
  include one `@image(n)` token per attached image; on the Story tab,
  `attachCharacterReferences()` builds its own identity-locking
  sentences the same way (swapping "Figure N" for "@imageN" whenever
  the selected image engine is Grok Imagine — see section 8a).

Both send `nsfw_checker: false` explicitly (kie.ai's own documented
default, but sent anyway for consistency with Wan 2.6 above).

**Cost estimates**, both confirmed directly from the user's own kie.ai
pricing dashboard: **image-to-image** $0.02/image (4 credits);
**text-to-image** $0.025 for the whole 4-image batch (5 credits) — a
per-*generation* rate, not per image, since one click always produces
the whole batch for that one price. Editable via the Options panel
(section 5a) or the `grokImage*` keys in `PRICING_USD` in `index.html`.

---

## 8. Character library

The "👤 Characters" tab lets you build up a small local library of
reusable characters — a name, a written identity description, and 1+
reference images — so you don't have to redescribe someone or hunt for
the right photos every time you want to generate them again.

**Two ways to create a character:**

1. **Generate a character sheet** (recommended): write the identity
   description, optionally attach 1-4 existing reference photo(s) of the
   person, pick a layout, and click "Generate character sheet." It
   lays out multiple angles/expressions in one grid image — a single
   consistent reference instead of juggling several separate photos.
   With no reference photos, you get a brand-new character generated
   purely from the identity description (Seedream 5 Pro Text-to-Image,
   high quality). With reference photos attached, it instead **edits
   those photos into the grid layout** (Image-to-Image) while locking
   identity to them — the prompt states outright that the photos show
   the exact same person and must stay unchanged in face, proportions,
   skin tone, and identifying features (using "Figure 1", "Figure 2..."
   when more than one photo is attached). That makes it a genuine way
   to turn one or two real photos into a full multi-angle/body
   reference sheet of that same real person. The result appears as a
   normal job card on the right — once it's done, click "💾 Save as
   character" to store it. Three layouts:
   - **3x2 grid** — 3 angles (front / three-quarter / side) × 2
     expression rows, for face/expression consistency. 4:3.
   - **2x2 grid** — front / three-quarter / side / back, for a compact
     all-angle reference. 4:3.
   - **Body reference** — two rows of four: 4 large, sharp headshots
     (front / three-quarter / side profile / front with a slight smile)
     that carry all facial identity, plus 4 identically-scaled
     full-body views (front / back / three-quarter / side) for when
     **body proportions and silhouette** need to stay consistent, not
     just the face. **The faces in the full-body row are deliberately
     blurred**: at full-body scale a grid panel renders the face small
     and badly detailed, and a later generation using the sheet as
     reference would otherwise pick up that degraded face — blurring
     forces models to take identity from the sharp headshots and only
     body/proportion information from the full-body row. Uses 4:3 (two
     rows of four portrait-shaped cells). The prompt explicitly asks
     for even, shadow-free lighting and matched scale across all four
     full-body panels so build, torso length, limb length, and shoulder
     width are directly comparable — useful as the "👤 Use character"
     reference for edits or animations where the character's build
     needs to read correctly from multiple angles.
2. **Upload existing photos manually**: drag/drop up to 4 images in the
   Characters tab, then click "Save character" — useful if you already
   have good reference photos of someone (or of a character generated
   earlier in a different tab).

Both ways also let you optionally attach **one reference video** in
its own dropzone on the Characters tab (MP4/MOV/MKV, up to 30MB). This
video isn't used for image generation, character sheets, or anything
image-based — it's stored purely so it can later be attached as
kie.ai's `reference_video` when this character is picked on the Video
tab with **Wan 2.7 R2V** selected, for motion/voice/style replication
alongside (or instead of) the character's reference photos.

**Using a saved character**: a "👤 Use character" button appears next
to the Prompt field (Image tab), the source image field (Video tab),
and the reference-image field (Prompt Assistant). Clicking it opens a
small picker of your saved characters; selecting one inserts the
identity description at the start of that field's prompt text, and —
for fields that take images — attaches as many of the character's
saved reference photos as still fit in that context (e.g. all 4 on the
Image tab if it has 4 and the field is empty, but only the first one
for Wan 2.6 on the Video tab, since that model only accepts a single
image). On the Video tab, when Wan 2.7 R2V is selected, a **separate**
"👤 Use character" button next to the reference-video dropzone attaches
just that character's saved video (if it has one) — the picker there
only lists characters that actually have a video attached, and it never
touches the prompt text or reference images, so you can mix and match
(e.g. photos from one character, a video from another).

Characters are stored locally in the `characters/` folder plus
`characters/characters.json` for the metadata — same pattern as the
`outputs/` gallery. Delete a character from the list to remove both the
metadata entry and its image/video file(s) permanently. The "Saved
characters" gallery shows every saved reference photo for a character
(not just one cover thumbnail), with a photo count badge when there's
more than one and a 🎬 badge when a reference video is attached —
click any photo to open it full-size.

**Editing a saved character**: click "✎ Edit" on a character's card to
load its name, identity text, photos, and video back into the form
above (existing photos/video show up as removable thumbnails, exactly
like freshly-uploaded ones), with the button relabeled "Update
character". Change whatever you like — rename it, rewrite the identity
text, remove a photo, add new ones, swap the video — then click
"Update character" to save the changes in place (same character `id`,
so anything referencing it, like a saved Story, still points at the
same character). "Cancel edit" discards the in-progress edit and
returns the form to create-a-new-character mode. Only photos you
actually removed are re-uploaded/reprocessed; untouched ones are kept
as-is on disk.

**Using a gallery result as input, without drag-and-drop**: every
image/video in the "Generated" gallery below has a "➕ Use" button
alongside the existing "↺ Reuse" one. Where "↺ Reuse" restores a past
job's prompt/settings but explicitly can't restore its source image(s)
(the gallery only stores results, not the inputs that made them), "➕
Use" does the opposite — it takes that gallery result itself and
attaches it as an input on whichever tab is currently open, no
drag-and-drop required (useful on mobile, where dragging a file onto a
dropzone isn't possible at all): on the Image tab it's added to the
source image(s) for an edit; on the Video tab, an image goes to the
source image(s) and a video goes to the reference-video slot (if the
selected model supports one); on the Characters tab, it's added to the
reference photo(s)/video of whatever character you're currently
creating or editing. Each click respects that context's normal max
count, same as everywhere else in the app.

---

## 8a. Story tab (text → storyboard → images)

The "📖 Story" tab turns a topic or idea into a full storyboard — a shot
list, a key image per scene, and (when you're ready) an animated clip
for each one, all without leaving the tab. Grok writes the scenes and
each one's image prompt, keeps recurring characters (and, where it
should, the environment) consistent from scene to scene automatically,
and you review and generate each scene's image and video yourself, one
click at a time or all at once. **There's no web search or URL
fetching** — Grok works purely from what you type and any checked
characters' saved text, no live research (see "Why no web search"
further below for why that was removed).

**How it works:**

1. Optionally check one or more of your saved characters (Characters
   tab). For each checked character there's also a small **"role in
   this story"** text field (e.g. "the protagonist", "the office worker
   whose printer explodes") — this is how you tell Grok that a generic,
   unnamed figure in your story/topic ("a woman", "she") should actually
   be that specific established character, without ever having to edit
   any scene prompt yourself.

   Only their exact name, identity description, and role note go to
   Grok as text — **no reference photo, and Grok never writes out any
   physical description itself.** Grok's only job is to mark which
   established character(s) appear in each scene (by exact name, in the
   `characters` array) and, inside that scene's `image_prompt`, refer to
   them only as a bare placeholder — "Character A" for the first
   established character in that scene, "Character B" for the second,
   and so on — used the same way a pronoun or an already-introduced
   subject would be: "Character A leans against the railing, laughing,
   while Character B points toward the horizon."

   The actual substitution happens when you click "Generate image" for
   a scene: this app looks up that character's saved identity text,
   fetches their first saved reference photo if they have one, and
   rewrites the prompt with a proper introduction — "Figure 1 is Mira:
   [full identity text]." (kie.ai's normal "Figure N" numbering,
   matching actual photo-attachment order — not every established
   character necessarily has a photo, so this depends on this app's own
   attachment order, not Grok's) or just "Mira: [identity text]." as a
   text-only anchor when there's no saved photo. Every later "Character
   A" mention in that scene gets swapped for the same short label (see
   `attachCharacterReferences()` in `index.html`). The more concrete and
   exhaustive your saved identity description is (section 8), the more
   consistent the character looks across scenes — this substitution
   reuses it byte-for-byte every time, which is more reliable than
   asking a model to retype it consistently on its own. It's also
   deliberate: Grok never touching appearance text or a photo is what
   keeps a Story request fast enough to reliably beat kie.ai's
   server-side timeout — see the note on that further below.
   - **Character letters are assigned once, for the whole story — not
     per scene.** Grok labels people "Character A", "Character B", etc.
     in the prompt text, and that letter stays fixed for a given person
     across every scene they appear in, no matter how far apart —
     Character A is always whoever you checked first, Character B
     whoever's second, and so on, and any *recurring but unsaved*
     person Grok invents (e.g. "a man in a blue jacket" who shows up in
     several scenes) gets a letter too, continuing the alphabet after
     your saved characters'. Substitution then expands each established
     character's own letter to their real identity/photo(s), so this
     stays correct even if a scene happens to mention two established
     characters in a different order than another scene does. **All of
     a character's saved reference photos are attached, not just the
     first** — same as "Use character" everywhere else in the app.
   - **Every scene automatically chains the previous scene's own
     generated image as Figure 1** (a "Chain previous scene's image"
     checkbox appears from scene 2 onward, checked by default) — this
     is the main mechanism keeping *people* (clothing, hairstyle, build)
     consistent across a cut to a new location, not just same-setting
     continuations: anyone visible in the previous scene, established or
     improvised, can be recognized and kept consistent in the next one,
     even a scene set somewhere completely different. Any established
     character's own saved photos are still attached *in addition* to
     that chained image (as Figure 2, 3, ...), for extra identity-
     locking beyond what it shows. Uncheck the box for a scene you want
     generated fresh with no relation to what came before (e.g. a
     flashback, or an unrelated new scene). Grok's own
     `continues_from_previous_scene` judgement only changes the
     *wording* used — "continues directly, keep the background pixel-
     consistent too" vs. "same people, but the setting has changed" — it
     no longer controls whether chaining happens at all. If the box is
     checked but the previous scene isn't actually generated yet (or its
     image couldn't be fetched), the scene still generates — just
     without it — and a warning appears on the scene card saying so,
     rather than silently dropping it; "▶ Generate all scenes" (see step
     5) avoids this entirely by always waiting for each scene before
     starting the next.
2. Type a topic, or your own story text/idea, into the input field.
   There's **no web search and no URL fetching** — Grok writes purely
   from what you typed (plus any checked characters' saved text) and
   its own general knowledge, the same way a human writer would with no
   internet access: elaborating and dramatizing an already-detailed
   idea/story works well, while a bare topic name it doesn't already
   know much about will come out more generic. See `STORY_SYSTEM` in
   `proxy.py` for the exact writing rules Grok follows.
3. Pick a **target number of scenes** (4/6/8/10/12/16 — default 6) and
   click "Generate story". Grok treats this as a target to actually
   reach, not just a ceiling: if the topic doesn't naturally supply
   enough distinct beats on its own, it invents plausible connecting
   moments (a transition, a smaller supporting action, an establishing
   shot) rather than stopping short — still concrete and specific, not
   filler. Each scene represents roughly 10 seconds of eventual video —
   one continuous visual beat, not a whole sequence — with a short
   human-readable narration and a full Seedream-style image-generation
   prompt for that scene's key frame. Higher counts mean a longer,
   heavier Grok call — see "Why no web search" below for the 120-second
   edge-timeout this app otherwise stays well clear of; if a very high
   scene count ever hits it, just retry or pick a lower count.

   **The "Grok model" dropdown next to the button** picks exactly one
   model (default `grok-4-3`) — there's no automatic fallback to the
   other one on failure. That used to exist, but it meant a failure
   silently turned into a long extra wait on a second model instead of
   telling you what actually happened; now a failure (including hitting
   the 120s edge timeout below) surfaces immediately with a message
   telling you to try again, switch models, or lower the reasoning
   effort/scene count yourself.

   **The "Reasoning effort" selector** (Low/Medium/**High** default/
   X-High) trades speed for multi-scene consistency. While it's writing,
   the status line shows **live progress** ("Grok is writing... (N
   characters received so far)") instead of sitting on a silent wait —
   see "Why no web search" below for how that's implemented and why it
   also turned out to reliably dodge the 120s edge timeout that used to
   bite High/X-High at a high scene count.

   **Every scene's `image_prompt` is written in a style matching
   whichever "Image engine" (step 5 below) is selected at the moment
   you click "Generate story"** — Seedream and Grok Imagine genuinely
   want different prompting styles (Seedream rewards an exhaustively
   itemized, attribute-dense description; Grok Imagine responds better
   to a punchier, more natural-language directive, per direct user
   feedback, not a kie.ai-documented rule), and `STORY_SYSTEM`
   (`proxy.py`) now writes accordingly from the start via its
   `{{IMAGE_PROMPT_STYLE}}` placeholder, instead of always writing
   Seedream-style prompts regardless of which engine will actually
   render them. Switching the "Image engine" selector afterward doesn't
   retroactively rewrite already-generated scenes — see the "🔀 Rewrite
   for Grok Imagine" button below for converting an individual scene
   on demand instead.
4. Scenes render as a **grid in its own full-width section below the
   normal form area** (up to 1800px wide, independent of the narrow
   two-column layout the rest of the app uses), capped at 4 columns so
   thumbnails stay readable even on a 1920px-wide screen instead of
   shrinking to fit more of them (3 columns at 1280px, fewer on
   narrower screens). Each card's image/video box follows whatever
   **aspect ratio** is currently selected below (9:16 gives tall
   portrait cards, 16:9 gives wide ones), so a 16-scene story stays
   scannable and each card gets a real, correctly-proportioned image
   instead of a tiny cropped thumbnail — the full frame always fits
   inside the cell (letterboxed if its own ratio doesn't exactly match
   the selected one) rather than being cropped to fill it. **Click any
   scene image to open it in a lightbox** — a near-fullscreen overlay
   with a small pop/fade-in so the transition is visible, not an
   instant jump, fit to your screen by default. Click the image itself
   to toggle to its native pixel size (scrolls if that's bigger than
   your screen) and back — this does not close it. Close the lightbox
   by clicking the dimmed background, pressing **Escape**, or clicking
   the **×** in the corner — the same lightbox is also used for the
   **Gallery** (click any gallery image; right-click still offers "open
   in new tab"/"save image as" normally, since that's the underlying
   link's own browser behavior, untouched). The story's title, shown
   above the grid, is an **editable text
   field** — rename it before saving if Grok's generated title isn't
   what you want. Each card shows just the narration and image/video up
   front. Everything
   else — the editable image prompt (Grok's short "Character
   A"-placeholder text, not the final prompt — see below), the "chain
   previous scene" checkbox, and the "Last sent" line showing the
   **actual final prompt** sent to Seedream (with the Figure-N/identity
   text this app injects, not just what's in the textarea) — lives
   behind a "Details" toggle on each card, so review only opens what
   you actually click into — and stays open: while a scene's image or
   video is generating, its card's status text updates roughly every
   3 seconds, but only that one card's DOM is touched, not the whole
   grid, so an open "Details" section (on that card or any other) and
   your scroll position are never disturbed by it.

   Pick an **aspect ratio** for the scene images above the scene list
   (defaults to 9:16) — this only affects scenes generated from that
   point on, and reshapes the grid's cards to match. Pick an **image
   engine**: **Seedream 5 Pro** (default, 1K — these are draft key
   frames you'll often regenerate per scene, not final deliverables, so
   1K keeps iteration cheap; rerun manually on the Image tab with 2K if
   a specific scene needs the higher resolution) or **Grok Imagine**
   (section 7c). Then click "Generate image" per scene. If the scene
   has a checked/matched character, their saved reference photo(s) get
   fetched and attached automatically, so it runs as Image-to-Image
   (identity locked by photo *and* text) instead of Text-to-Image —
   with Grok Imagine, the same identity-locking sentences are built but
   using its own required `@image1`, `@image2`, ... convention instead
   of "Figure 1", "Figure 2" (section 7c), and capped at 5 attached
   images instead of Seedream's 10.

   **Grok Imagine's text-to-image always returns a 4-image batch, not
   one** — when it does (a scene with no character/continuity images
   attached, so nothing to edit), the scene card shows all 4 side by
   side instead of a single image, and the scene isn't really "done"
   until you click one to keep. "▶ Generate all scenes" still waits for
   the *job* to finish either way, but a scene left at the picker stage
   still needs that manual click before it counts as having an image
   for continuity-chaining into the next one. The result appears inline
   in the scene card (and also as a normal job card on the right, so
   "↺ Reuse" and the gallery both work on it) — click "↺ Regenerate
   image" to try again with a tweaked prompt.

   **"🔀 Rewrite for Grok Imagine" / "🔀 Rewrite for Seedream"** (in a
   scene's "Details" section, next to the editable prompt textarea)
   convert that one scene's existing `image_prompt` into the clicked
   button's style. Both are always shown, regardless of what the
   "Image engine" selector above the scene grid is currently set to —
   that selector only controls what a fresh "Generate image" click
   uses, so tying this button's target to it too would mean right after
   generating a story with Seedream still selected, the only option
   offered is "Rewrite for Seedream" (a no-op, since that's already the
   current style); showing both explicitly sidesteps that. This works
   without regenerating the story or touching any other scene — useful
   for a scene written in the wrong style (e.g. a story started under
   Seedream, now being tried with Grok Imagine, or vice versa), or just
   to try converting one scene without switching the whole story over.
   It's a REWRITE, not a fresh rewrite-from-scratch: it sends Grok
   the story's title/synopsis, this scene's narration, which exact
   "Character X" label belongs to which named character (so it never
   invents a new one), the previous scene's actual image when there is
   one (for continuity awareness only, never described in the output),
   and the existing prompt text — and is instructed to preserve the
   scene's content and every "Character X" label exactly, changing only
   the prose style (`GROK_IMAGE_STORY_SCENE_CONVERT_SYSTEM`/
   `SEEDREAM_STORY_SCENE_CONVERT_SYSTEM` in `proxy.py`, sharing every
   rule except which style to convert into). The rewritten text replaces
   the textarea's contents directly; nothing is generated automatically
   — review it and click "Generate image" yourself when it looks right.

   **"▶ Generate all scenes"** (below the scene list) generates every
   scene in order, one at a time, waiting for each one to actually
   finish before starting the next — the point being that a
   continuity-chained scene needs the previous scene's image to already
   exist, which isn't guaranteed if you fire off "Generate image" on
   several scenes by hand in quick succession. Scenes that already have
   a generated image are skipped, so it's safe to run again after
   manually generating a few scenes yourself, to just fill in the rest.
   Click **"⏹ Stop"** (appears next to it while running) to end the run
   after the scene currently in progress finishes — there's no way to
   cancel a generation already in flight (kie.ai has no cancel
   endpoint), so "Stop" just means "don't start the next one."
5. Once a scene's image looks right, animate it right there in the
   scene card: pick a **duration** and click "🎬 Video" (both appear
   once the scene has an image). Which engine animates it is set once,
   for the whole story, by the **"Video engine"** selector above the
   scene list:
   - **ComfyUI — LTX 2.3** (default): needs a ComfyUI server configured
     on the Video tab first (see section 7b), durations 5/10/15/20s.
     Uses `STORY_LTX_MOTION_SYSTEM` in `proxy.py` to write the motion
     prompt.
   - **Seedance 1.5 Pro**: runs entirely through kie.ai, no local
     server needed — faster to set up, but capped at 4/8/12s and 480p.
     Uses the same `SEEDANCE_I2V_SYSTEM` system prompt the Video tab's
     Prompt Assistant uses for this model.
   - **Grok Imagine Video 1.5 Preview**: also entirely through kie.ai,
     no local server — capped at 480p, 6/10/15/20/30s in this app's
     picker (the model itself allows any value 6-30s). The only Story
     tab video engine that also attaches this scene's checked
     characters' saved reference photos (@image2, @image3, ..., capped
     at 7 images total) alongside the scene's own key frame (@image1) —
     every other engine here only ever uses the one key frame. Uses its
     own dedicated `GROK_IMAGE_VIDEO_MOTION_SYSTEM` system prompt, since
     it needs Grok Imagine's own required `@image(n)` referencing
     convention (see section 7) rather than Seedance's "Figure N".
   - **Hailuo 02 Standard**: also entirely through kie.ai, no local
     server — capped at 512P, and only 6s or 10s (the model itself
     doesn't accept any other duration). Reuses `SEEDANCE_I2V_SYSTEM`
     too.

   Either way, the scene's image, its narration, the next scene's
   narration (for context — what this clip should move toward without
   necessarily resolving it), and the chosen duration are sent to Grok
   to write a duration-aware motion prompt, which then goes straight
   into the matching pipeline (ComfyUI/LTX per section 7b, or the
   normal kie.ai job flow for Seedance). The result plays inline in the
   scene card and is saved to the gallery the same as everything else.
   This is entirely separate from the scene's *image* generation above
   — regenerating one doesn't touch the other. If a video ever fails to
   play inline (a codec quirk, a moved/deleted file, anything) instead
   of showing a silently blank box it swaps in a direct link to open the
   file on its own.
6. Click **"💾 Save story"** to persist the current title/synopsis/
   characters/scenes — **including each scene's generated video, not
   just its image** — to disk, so it survives a page refresh. Saved stories appear as a row of compact, side-by-side tiles
   in their own full-width **"Saved stories"** section (with a search
   box and a "Show more" button once there are more than a handful),
   click **"Load"** on one to bring it back into the editor above
   exactly as it was. Clicking **"Save story"** again on the same story
   (freshly generated, or already loaded from the list) **updates that
   same entry in place** instead of creating a duplicate — the status
   line reads "Saved ..." the first time and "Updated ..." on every
   save after that, and the tile shows an "(updated)" date once it's
   been saved more than once. This makes it safe to save repeatedly
   while iterating on a story (e.g. after each scene's image or video
   finishes generating) without piling up near-identical copies.

**Page order while on the Story tab**: the form (brief, characters,
scene count, aspect ratio, video engine) stays in the normal narrow
panel at the top; below that, in order, are the full-width **scene
grid**, the full-width **Saved stories** tile row, and finally the
**Gallery** — each only as wide/tall as it needs to be, so the scene
grid and its images get the most screen space.

**Why no web search**: the Story tab briefly had a URL-input mode and a
`tools: [{"type": "web_search"}]` option (kie.ai's Grok Responses API
supports this, see `docs.kie.ai/market/grok/grok-4-3`) so Grok could
research a bare topic or fetch a pasted article before writing. Both
were removed: web search (and, for a while, a reference photo sent as
vision input for character consistency, also since removed) routinely
pushed request time past kie.ai's own Cloudflare edge's **120-second
server-side timeout** — a hard proxy-layer cutoff between kie.ai's edge
and their origin, not something this app's own request timeout can wait
out. Story generation is now a pure creative-writing task grounded only
in what you type (and any saved character text).

**Streaming, not a single blocking call**: `generate_story_with_grok()`
(`proxy.py`) sends `stream: true` to Grok and reads the response
incrementally via Server-Sent Events (`stream_grok_json()`), instead of
waiting for one big JSON blob back. Confirmed compatible with the
structured `json_schema` output this app relies on — the deltas are just
the output JSON's text arriving token-by-token; concatenate and
`json.loads()` once the stream ends. Two things came out of this:

1. **Live progress**: the proxy relays a `{"progress": N}` line back to
   the browser (over a plain incrementally-written HTTP response, no
   Content-Length — `/api/generate-story` now streams newline-delimited
   JSON) roughly every 200 characters Grok has produced so far, and the
   Story tab's status line updates with it live instead of sitting on a
   silent wait.
2. **The 120s timeout stopped being a practical problem**: repeated live
   tests at High/X-High effort with up to 16 scenes — configurations
   that reliably took 90-235s non-streaming and sometimes failed or
   needed a model fallback around the ~120s mark — completed in a single
   uninterrupted response every time via streaming (63-110s, no
   failures). The likely reason: kie.ai's edge cutoff is probably about
   the non-streaming buffer-then-forward path specifically (or an idle
   timeout that continuous chunks never trigger), not a hard wall-clock
   limit on the whole request — but this is inferred from consistent
   test results, not confirmed against kie.ai's own internals, so treat
   "no more timeouts" as "much less likely," not "impossible." If a
   generation ever does fail, the Story tab's model/effort selectors
   (and the honest error message) are still there as before.

**Saved stories**: click "💾 Save story" to persist the current story
(title/synopsis/characters/scenes, including whichever scene images are
already generated) to disk — see section 8a's step 6 above for where
saved stories show up and how to load one back. Without an explicit
save, a story only lives in the browser tab and is lost on refresh.

---

## 9. Session cost tracker

A small bar under the title shows a running "Session spend estimate"
that adds up every generation (image or video) since you opened the
page, using the same rough per-item rates as the estimates shown before
each Generate click. Click "reset" to zero it out.

It also adds a flat estimate for every Grok text call made through
kie.ai — Prompt Assistant turns, Story generation, per-scene rewrites,
and video motion prompts. Unlike the image/video rates above, this
figure (default $0.01/call, ~2 credits) isn't from kie.ai's published
pricing — there's no public per-call rate for Grok text calls — it's an
estimate based on the user's own kie.ai dashboard usage, editable in the
Options panel like everything else. It's skipped for calls that used
the direct-xAI backend or fell back to it (see section 5a), since those
aren't billed through kie.ai credits at all.

This is **in-memory only** — like the jobs list and Prompt Assistant
conversations, it resets when you refresh the page. It's meant as a
lightweight sanity check while experimenting (especially useful once
video generations are in the mix, since those cost more per item than
images), not as an accounting record — for that, use your kie.ai
dashboard's actual usage/billing page.

Right next to it, an **"All-time"** total tracks the same estimates but
persists across restarts (`cost_totals.json`) — every job's cost is
added to both counters at once. Its own "reset" button asks for
confirmation first, since unlike the session counter this is meant to be
a lasting record rather than something you clear casually.

---

## 10. Pricing disclaimer

> **The prices shown in the app (and below) reflect kie.ai's published
> rates as of late July 2026.** kie.ai can change pricing at any time —
> always check your kie.ai dashboard/console for your actual, current
> billing before relying on the estimate shown in this tool.
>
> **These are rough, locally-computed estimates, not a bill and not
> billing data from kie.ai.** They can be wrong or drift from what
> kie.ai actually charges. This app and its cost estimates are provided
> as-is, with no warranty of accuracy — you use it, and rely on any
> figure it shows, entirely at your own risk. No responsibility is taken
> for any costs or charges you incur through kie.ai, xAI, or any other
> service this app talks to.

Image pricing on kie.ai:

| Item | Price |
|---|---|
| Seedream 5 Pro, text-to-image, 1K | $0.035 / image |
| Seedream 5 Pro, text-to-image, 2K | $0.07 / image |
| Seedream 5 Pro, image-to-image, 1K | $0.035 / image |
| Seedream 5 Pro, image-to-image, 2K | $0.07 / image |
| Seedream 5 Pro, input/reference image | first one free, $0.0025 each after that |
| WAN 2.7 Image (text-to-image and editing) | $0.024 / image |
| Grok Imagine, image-to-image | $0.02 / image |
| Grok Imagine, text-to-image | $0.025 per 4-image batch (not per image) |

Video pricing (confirmed, as run in this app — see section 7 above for
the audio caveat on Seedance 2 / 2 Fast / 2 Mini):

| Model | Resolution | Price |
|---|---|---|
| Wan 2.6 (image-to-video) | 720p | $0.07 / sec |
| Wan 2.7 (first/last frame-to-video) | 1080p | $0.12 / sec |
| Wan 2.7 (reference-to-video) | 1080p | $0.12 / sec |
| Seedance 1.5 Pro, without audio | 480p | $0.00875 / sec |
| Seedance 1.5 Pro, with audio | 480p | $0.0175 / sec |
| Seedance 2 (image-to-video) | 480p | $0.095 / sec |
| Seedance 2 Fast (image-to-video) | 480p | $0.0775 / sec |
| Seedance 2 Mini (image-to-video) | 480p | $0.0475 / sec |
| Grok Imagine Video 1.5 | 480p | $0.008 / sec |
| Hailuo 02 Standard | 512P | $0.01 / sec |

All of the above were confirmed directly from a real kie.ai account
dashboard — if you find any of them out of date, edit them yourself in
the Options panel (section 5a) rather than the source, or in the
`PRICING_USD`/`VIDEO_PRICING_USD_PER_SECOND` objects near the top of
the `<script>` section in `index.html` if you want new defaults baked
in.

---

## 11. Using it with Open WebUI (optional)

`proxy.py` also exposes OpenAI-compatible endpoints
(`/v1/images/generations` and `/v1/images/edits`), so Open WebUI can use
it directly as a backend for both **Image Generation** and **Image
Editing** (img2img via attaching an image in the chat).

1. Start `python3 proxy.py` (it binds to `0.0.0.0`, so it's also reachable
   from an Open WebUI instance running in Docker or on another machine on
   your network — note the IP address of the machine running this script).
2. In Open WebUI: **Admin Panel → Settings → Images**
   - **Image Generation**
     - Engine: `Open AI`
     - API Base URL: `http://<ip-of-this-machine>:8787/v1`
       (if Open WebUI itself runs in Docker and the proxy runs on the
       Docker host, use `http://host.docker.internal:8787/v1` instead)
     - API Key: any non-empty value (not checked unless you set up
       `proxy_token.txt`, see below)
     - Model: any text, e.g. `seedream-5-pro` (this value isn't actually
       used to pick the kie.ai model — that's hardcoded in `proxy.py` as
       `seedream/5-pro-text-to-image`)
   - **Image Editing** (for img2img from chat)
     - Enable Image Edit: on
     - Engine: `Open AI`
     - API Base URL: same `.../v1` as above
     - API Key: same as above
3. Save, then test with **Verify Connection** or just try a prompt.

In the chat, you can then attach an image and ask for an edit — that
automatically goes to `/v1/images/edits`, which uploads the image(s) to
kie.ai and calls Seedream 5 Pro image-to-image.

**Note:** each generation takes 10–60+ seconds, and the proxy keeps the
HTTP connection to Open WebUI open until the result is ready. If Open
WebUI shows a timeout error, that's usually a timeout setting on Open
WebUI's side, not a failed generation on kie.ai's end.

**How to trigger it in Open WebUI's chat:** click the "+" icon next to
the message box and turn on the **Image Generation** toggle, then type
your prompt and send — this works regardless of which chat model you're
using. For image editing, just attach an image and describe the change.
(As of Open WebUI v0.7+, generating an image from a prior text response
via a message-action button requires installing the community "Generate
Image Action" function separately — the toggle method above doesn't need
that.)

### Optional access control on your network

Since the proxy listens on `0.0.0.0` (needed for Docker/other machines),
anyone on your local network can reach it without a password. To lock
this down: create a file named `proxy_token.txt` containing a secret
string of your choice. Once that file exists, every request to the
`/v1/...` routes must include an `Authorization: Bearer <token>` header —
in Open WebUI, put that string in as the "API Key" field. (The standalone
local UI doesn't use this token yet — only the `/v1/...` routes check it
for now.)

---

## 12. Stopping

Press `Ctrl+C` in the terminal window where `proxy.py` is running.

---

## Files

- `proxy.py` — local server + proxy to kie.ai, with both the standalone
  UI routes and the OpenAI-compatible `/v1/images/...` routes for Open WebUI
- `index.html` — the standalone UI
- `run.bat` — Windows double-click launcher (checks for Python, starts
  `proxy.py`, opens your browser automatically); see section 4
- `kie_key.txt` — your API key (create it yourself, rename `kie_key.example.txt`)
- `xai_key.txt` — optional, only needed for the "Direct xAI API" Grok backend
  (Options panel, section 5a); create it yourself, rename `xai_key.example.txt`
- `proxy_token.txt` — optional, for access control if you're on `0.0.0.0`
- `outputs/` — created automatically; holds your saved images/videos and
  `gallery.json` with their metadata
- `assistant_prompts_override.json` — created automatically the first
  time you edit and save a system prompt in the Prompt Assistant; safe
  to delete to reset everything back to the built-in defaults
- `characters/` — created automatically; holds saved character images
  and `characters.json` with their metadata

## Known limitations

- The **jobs list** (the live cards showing each generation's status)
  only lives for the current browser session — refreshing clears it.
  Everything you've actually generated still persists in the
  **Gallery**, though (see section 5), since that's saved to disk
  separately. (Open WebUI keeps its own chat history with the generated
  images included.)
- Source images uploaded to kie.ai are automatically deleted after a few
  days on their end (irrelevant to your results, since those stay saved
  locally or in Open WebUI).
- Model IDs (`seedream/5-pro-text-to-image`, `seedream/5-pro-image-to-image`,
  `wan/2-6-image-to-video`, `wan/2-7-image-to-video`, `wan/2-7-r2v`,
  `wan/2-7-image`, `bytedance/seedance-1.5-pro`, `bytedance/seedance-2`,
  `bytedance/seedance-2-fast`, `bytedance/seedance-2-mini`,
  `grok-imagine/image-to-video`, `hailuo/02-image-to-video-standard`,
  `grok-imagine/text-to-image`, `grok-imagine/image-to-image`),
  aspect ratio
  options, and the OpenAI-style request fields are based on kie.ai's and
  Open WebUI's documentation as of July 2026; if either changes their
  API, update `proxy.py` / `index.html` accordingly.
- The proxy processes each generation task synchronously with polling;
  running several at once is fine (each runs on its own thread), but a
  single request with `n > 1` images takes `n` times as long since those
  run sequentially within that one request.

## License

MIT — see [LICENSE](LICENSE).
