#!/usr/bin/env python3
"""
BYOAPI — local proxy + web server for kie.ai's image/video models
(Seedream 5 Pro, WAN 2.7, Grok Imagine, Seedance, Hailuo) plus an AI
storyboard tool. Bring your own kie.ai API key, pay kie.ai directly,
skip whatever markup a hosted "AI image generator" site would add.

Two ways to use it at once:
  1. Its own simple UI at http://127.0.0.1:8787
  2. OpenAI-compatible endpoints (/v1/images/generations and /v1/images/edits)
     so Open WebUI can use this as an Image Generation / Image Editing
     backend (Admin Panel > Settings > Images, Engine = "Open AI").

Usage:
    1. Put your kie.ai API key in the file 'kie_key.txt' (same folder as this script).
    2. Start:  python3 proxy.py
    3. Own UI: http://127.0.0.1:8787
       Open WebUI Base URL: http://<this-ip>:8787/v1  (API key: any value works)

Only needs the Python standard library, no pip install required.
"""

import base64
import copy
import email
import json
import mimetypes
import threading
import time
import uuid
import urllib.request
import urllib.error
from email import policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEY_FILE = HERE / "kie_key.txt"
# Optional — direct xAI API key for the manual "Direct xAI API" Grok backend
# (Options panel > Grok backend). Unlike KEY_FILE (kie.ai, required for
# everything else this app does), this file simply not existing just means
# that backend isn't available yet — see load_xai_api_key().
XAI_KEY_FILE = HERE / "xai_key.txt"
TOKEN_FILE = HERE / "proxy_token.txt"  # optional, see README
OUTPUT_DIR = HERE / "outputs"
GALLERY_META_FILE = OUTPUT_DIR / "gallery.json"
PROMPT_OVERRIDES_FILE = HERE / "assistant_prompts_override.json"
PORT = 8787
HOST = "0.0.0.0"  # reachable from other machines/containers on your network (e.g. Open WebUI in Docker)

OUTPUT_DIR.mkdir(exist_ok=True)

CHARACTERS_DIR = HERE / "characters"
CHARACTERS_META_FILE = CHARACTERS_DIR / "characters.json"
CHARACTERS_DIR.mkdir(exist_ok=True)

STORIES_META_FILE = HERE / "stories.json"

# ComfyUI (LTX 2.3 video) — a second, independent generation backend running
# on the user's own network, not kie.ai. The base URL is user-editable in
# the UI (Video tab) rather than hardcoded here, since it depends on which
# machine on the LAN happens to be running ComfyUI that day; it's persisted
# to this file so it survives a page refresh/restart.
COMFYUI_CONFIG_FILE = HERE / "comfyui_config.json"
COMFYUI_WORKFLOW_FILE = HERE / "comfyui_workflows" / "ltx-2.3.json"
# Node IDs are specific to this exact exported workflow (comfyui_workflows/
# ltx-2.3.json) — they'd need updating if the workflow is ever re-exported
# with different node IDs.
COMFYUI_LTX_IMAGE_NODE = "5309:5307"     # LoadImage.inputs.image
COMFYUI_LTX_PROMPT_NODE = "5311:5403"    # CLIPTextEncode.inputs.text
COMFYUI_LTX_FRAMES_NODE = "5311:4988"    # PrimitiveInt ("number of frames").inputs.value
COMFYUI_LTX_SEED_NODE = "5314:5392"      # SeedNode.inputs.seed
COMFYUI_LTX_OUTPUT_NODE = "5363"         # VHS_VideoCombine — where the finished video shows up in /history
COMFYUI_LTX_RESIZE_NODE = "5309:5308"    # UnifiedResizeImageMask — scale_mode + short_side_target/long_side_target, see build_comfyui_ltx_prompt()
COMFYUI_LTX_FPS = 24                     # matches the workflow's fixed "fps" PrimitiveFloat (5311:4989)
COMFYUI_LTX_RESOLUTIONS = (540, 720, 1080)  # allowed shorter/longer-side values, exposed in the UI

# App-wide settings (Options panel — see load_app_config()/save_app_config()):
# which image/video models are enabled, and editable overrides for the
# per-model cost estimates shown in the UI. Persisted separately from
# comfyui_config.json (that one's specifically about the ComfyUI connection).
APP_CONFIG_FILE = HERE / "app_config.json"

# All-time spend tracker — separate from the browser-session-only "Session
# spend estimate" bar (which resets on refresh, tracked entirely client-side
# in index.html). This one persists across restarts; the client posts each
# job's estimated cost here as it completes, same estimate the session bar
# already computed, just also accumulated server-side. COST_TOTALS_LOCK
# guards the read-modify-write since ThreadingHTTPServer serves requests
# concurrently and two jobs finishing at once could otherwise race.
COST_TOTALS_FILE = HERE / "cost_totals.json"
COST_TOTALS_LOCK = threading.Lock()

KIE_API_BASE = "https://api.kie.ai"
KIE_UPLOAD_BASE = "https://kieai.redpandaai.co"

# Grok prompt-writing assistant: kie.ai exposes Grok via its "Responses API"
# (OpenAI Responses-API-style), a fixed endpoint with the model chosen in the
# request body — confirmed working format, not a guess.
GROK_RESPONSES_URL = "https://api.kie.ai/grok/v1/responses"
# Tried in order: first model that responds successfully is used.
GROK_MODELS = ["grok-4-3", "grok-4-5"]

# Direct xAI API (api.x.ai) — the manual "Direct xAI API" Grok backend
# (Options panel > Grok backend, default stays "kie.ai"), for when kie.ai's
# own Grok proxy is erroring out (confirmed by the user hitting repeated
# errors there). xAI's Chat Completions API is OpenAI-compatible, confirmed
# via docs.x.ai: POST https://api.x.ai/v1/chat/completions, Bearer auth,
# response_format.json_schema for structured output (same idea as kie.ai's
# text.format.json_schema), reasoning.effort ("low"/"medium"/"high" — no
# "xhigh" outside their multi-agent model, see _xai_reasoning_effort()), and
# streamed chunks shaped like choices[0].delta.content ending in
# "data: [DONE]" — a different shape from kie.ai's response.output_text.delta
# events, so it needs its own streaming reader (stream_xai_chat_json()).
XAI_API_BASE = "https://api.x.ai/v1"
# kie.ai's model ids use hyphens (grok-4-3/grok-4-5); xAI's own API uses dots
# (grok-4.3/grok-4.5, confirmed via docs.x.ai/developers/models) — same
# underlying models, just different id strings depending which API you hit.
XAI_MODEL_MAP = {"grok-4-3": "grok-4.3", "grok-4-5": "grok-4.5"}

# Models as documented on docs.kie.ai (July 2026)
T2I_MODEL = "seedream/5-pro-text-to-image"
I2I_MODEL = "seedream/5-pro-image-to-image"
I2V_MODEL = "wan/2-6-image-to-video"  # only one source image supported per request
DEFAULT_QUALITY = "basic"  # "basic" (1K) or "high" (2K)
MAX_N = 4  # safety limit on number of images per request
MAX_ASSISTANT_IMAGES = 4  # safety limit on reference images sent to the Prompt Assistant
MAX_ASSISTANT_HISTORY_TURNS = 20  # safety cap on conversation length replayed per request
POLL_INTERVAL_S = 3
POLL_MAX_WAIT_S = 300

# Aspect ratios officially supported by kie.ai's Seedream 5 Pro (confirmed
# list: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 21:9 — do not add others here,
# kie.ai will reject unsupported values). We map Open WebUI's "WxH" size
# string to the closest one of these.
ASPECT_RATIOS = {
    "1:1": 1.0,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "3:2": 3 / 2,
    "2:3": 2 / 3,
    "21:9": 21 / 9,
}

# Adaptation note appended to every system prompt below: the originals were
# written for a multi-turn chat tool where images/videos are literally
# attached and referenced with @Image1/@Video1-style tags. This tool is
# single-shot (one brief in, one prompt out) and the source image(s) are
# passed to kie.ai separately via image_urls/first_frame_url — NOT embedded
# as tags in the prompt text — so tags are stripped and replaced with plain
# references like "the uploaded character image".
_SINGLE_SHOT_ADAPTATION = (
    "\n\n## Adaptation for this tool\n"
    "This tool supports a back-and-forth conversation: the user can send a "
    "follow-up message (e.g. \"make the hair red instead\", \"make it shorter\", "
    "\"add a hat\") to refine the prompt you previously wrote, instead of "
    "describing everything from scratch every time. When the conversation "
    "already contains a previous prompt you wrote and the new message reads as "
    "a refinement/change request, produce an updated COMPLETE prompt that "
    "incorporates the change together with everything from before that wasn't "
    "asked to change — never a diff or a partial fragment. If the new message "
    "clearly starts an unrelated new idea, treat it as a fresh prompt instead. "
    "The user MAY optionally attach one or more reference images directly to "
    "any message (e.g. an actual photo of the character, or a mood/style "
    "reference) — if image content is present, look at it carefully and use "
    "what you actually see (facial features, colors, framing, lighting, "
    "existing pose) to inform the prompt, rather than guessing purely from "
    "text. Do NOT use @Image/@Video/@Audio tags anywhere in your output "
    "prompt — kie.ai's actual generation API takes images as a separate "
    "image_urls/first_frame_url array, not as tags embedded in the prompt text. "
    "When you need to refer to a specific uploaded image among several in the "
    "OUTPUT PROMPT (e.g. for multiple characters), use kie.ai's documented "
    "convention instead: refer to them by upload position as \"Figure 1\", "
    "\"Figure 2\", etc. (e.g. \"Figure 1 is Character A\"). For a single image, "
    "plain language like \"the uploaded character image\" is fine. Do not ask "
    "the user clarifying questions — make the most reasonable assumptions given "
    "the brief (and any attached image) and state them briefly in your "
    "reasoning instead. Respond with a JSON object with exactly three fields: "
    "\"prompt\" (the final ready-to-use generation prompt in English, containing "
    "nothing but the prompt itself — no labels, no code fences, no "
    "meta-commentary), \"negative_prompt\" (only meaningful for the Wan 2.7 "
    "video modes — for every other mode, always return an empty string here), "
    "and \"reasoning\" (1-3 sentences, in the same language as the user's "
    "brief, briefly explaining the key choices you made)."
)

# Appended only to the Wan 2.7 video modes, which are the only models here
# with a confirmed negative_prompt parameter on kie.ai (Seedream/Seedance do
# not expose one).
_NEGATIVE_PROMPT_ADAPTATION = (
    "\n\n## Negative prompt\n"
    "Also produce a short, comma-separated negative_prompt: concrete failure "
    "modes to avoid for this specific shot, not a generic boilerplate list. "
    "Always include the baseline defects (blurry, flicker, distorted anatomy, "
    "abrupt cuts) plus identity drift when a reference image/character is "
    "involved, and add shot-specific terms when relevant (e.g. \"extra limbs\" "
    "for a multi-character action shot, \"morphing background\" for a moving "
    "camera). Keep it under 20 words."
)

SEEDREAM_T2I_SYSTEM = (
    "You are a specialized prompt writer for Seedream 5 Pro, focused on "
    "generating brand-new characters from scratch (text-to-image, no reference "
    "image) — including scenes with multiple characters. Turn the user's raw "
    "idea into a production-ready Seedream prompt.\n\n"
    "## Core Philosophy\n"
    "Seedream 5 Pro has genuine design and reasoning understanding — it reads "
    "spatial relationships and physical plausibility, not just keywords. Treat "
    "every prompt as a casting and directing brief, not a mood board of "
    "adjectives. Vague descriptions (\"a young woman,\" \"a warrior,\" "
    "\"fighting\") regenerate a different result every time — specific, concrete "
    "descriptions anchor identity and action. Target roughly 30-80 words, dense "
    "with concrete detail rather than a long list of loose style words.\n\n"
    "## Building a Character\n"
    "Describe physical features precisely and exhaustively: face shape, skin "
    "tone, build, age, height impression; hair color/length/texture/style; eye "
    "color/shape; distinguishing marks (scars, freckles, tattoos, birthmarks — "
    "these make a character recognizable, don't skip them); a neutral default "
    "expression as baseline; wardrobe specific enough to be repeatable (exact "
    "colors, garment types, materials — \"worn brown leather jacket over a "
    "faded grey henley,\" not \"casual clothes\"). \"Oval face, warm olive skin, "
    "shoulder-length dark wavy hair, deep brown eyes, small mole above left "
    "lip, lean athletic build\" gives the model an anchor; \"a young woman\" "
    "doesn't.\n\n"
    "## Describing Actions, Movement, and Pose\n"
    "Seedream generates a single still frame, so vague action verbs (\"standing,"
    "\" \"walking,\" \"fighting\") default to generic, stiff poses. Break the "
    "pose into concrete parts: weight distribution, limb position, head angle, "
    "hand/finger position, where the eyes point. Name the specific moment, not "
    "the whole action — the peak of a jump, the follow-through of a swing — "
    "rather than describing it as continuous. Use implied-motion cues: hair/"
    "fabric caught mid-motion, motion blur on one specific limb only, dust/"
    "water displaced at the point of contact, weight visibly shifting "
    "off-balance. Tie facial expression to the physical effort/emotion of the "
    "moment, not a generic mood word. Mention camera framing (low angle, tight "
    "crop) when the pose alone won't read clearly at a normal eye-level medium "
    "shot.\n\n"
    "## Multiple Characters in One Image\n"
    "Introduce each character separately, fully, and in a fixed order before "
    "describing their interaction: \"Character A: [full physical description]. "
    "Character B: [full physical description].\" Give each a distinct, "
    "unambiguous label throughout (name, or Character A/B, or role). Describe "
    "the interaction with explicit contact points (where a hand grips, where "
    "weight presses) and exact spatial relationship — this is the biggest "
    "lever against merged limbs and floating objects. Assign position "
    "explicitly: who is left/right/foreground/background. If characters share "
    "similar builds, ages, or coloring, exaggerate distinguishing details "
    "(hair color/style, clothing color, accessories) so the model has a "
    "stronger anchor to keep them visually separate.\n\n"
    "## Light, Materials, and Composition\n"
    "Name the light directly (\"soft window light from the left,\" \"hard "
    "midday sun,\" \"warm tungsten backlight\") — this does more for realism "
    "than any style word. Name the materials that matter on skin, hair, "
    "fabric, props (matte skin, brushed leather, glossy lacquer). For "
    "photographic/cinematic shots, specify shot type, focal length, and "
    "aspect ratio when it matters.\n\n"
    "## Words to Avoid\n"
    "Bare style/mood words with no elaboration (\"epic,\" \"beautiful,\" "
    "\"professional,\" \"8k,\" \"detailed\") under-specify and waste words — "
    "replace with the specific thing you actually mean."
    + _SINGLE_SHOT_ADAPTATION
)

SEEDREAM_I2I_SYSTEM = (
    "You are a specialized prompt writer for Seedream 5 Pro, focused on "
    "reference-driven variation/editing of an existing character (one or more "
    "source images are being uploaded alongside your prompt) — including "
    "scenes with multiple established characters. State explicitly what "
    "changes (pose, expression, outfit, scene, framing) and what must stay "
    "locked (face, proportions, skin tone, hairstyle, identifying marks). Do "
    "not re-describe everything in the source image — only the identity "
    "anchors plus the change.\n\n"
    "## Core Philosophy\n"
    "Seedream 5 Pro reads spatial relationships and physical plausibility, not "
    "just keywords. The image reference alone is not enough to prevent "
    "drift — keep restating key identifying details in words, since text and "
    "image reinforce each other.\n\n"
    "## Locking Identity\n"
    "Re-state the key identifying details in words every time, even with the "
    "image attached. When changing pose, expression, outfit, or scene: name "
    "exactly what changes and follow it with an explicit \"keep face, "
    "proportions, skin tone, and hairstyle unchanged\" — this single line "
    "prevents most unwanted drift. Outfit and prop details get dropped "
    "silently on edits more often than faces do — restate them explicitly "
    "even when \"unchanged\" seems implied.\n\n"
    "## Describing Actions, Movement, and Pose\n"
    "Break the pose into concrete parts: weight distribution, limb position, "
    "head angle, hand/finger position, where the eyes point. Name the "
    "specific moment (peak of a jump, follow-through of a swing), not the "
    "whole action. Use implied-motion cues (hair/fabric caught mid-motion, "
    "motion blur on one limb, weight shifting off-balance). Tie facial "
    "expression to the physical effort/emotion of the moment.\n\n"
    "## Multiple Characters\n"
    "Reference each character's image by its upload position using kie.ai's "
    "documented convention — \"Figure 1\", \"Figure 2\", etc. — e.g. \"Figure 1 "
    "is Character A, Figure 2 is Character B\", and restate both characters' "
    "key identifying details in words, not just one. "
    "Describe the interaction with explicit contact points and exact spatial "
    "relationship (who is left/right/foreground/background) — the biggest "
    "lever against merged limbs. If characters share similar builds/ages/"
    "coloring, exaggerate distinguishing details so the model can tell them "
    "apart.\n\n"
    "## Light and Materials\n"
    "Name the light directly and the materials that matter on skin, hair, "
    "fabric, props — this does more for realism than any style word.\n\n"
    "## Common Failure Modes to Guard Against\n"
    "Face drifting across a series (re-anchor identity every time); outfit/"
    "prop details silently dropped on edits (restate explicitly); identity "
    "blending between multiple characters (stronger distinguishing details + "
    "explicit labeling); merged limbs/floating objects in interaction shots "
    "(explicit contact points); generic, stiff poses (break into concrete "
    "parts, name the specific instant)."
    + _SINGLE_SHOT_ADAPTATION
)

SEEDANCE_I2V_SYSTEM = (
    "You are a specialized prompt writer for Seedance, focused on "
    "image-to-video character animation — not text-to-video, not video "
    "editing — including scenes with multiple characters. Bring a character "
    "to life while keeping their identity intact.\n\n"
    "## Two Input Modes — Check How Many Images Are Attached\n"
    "This Seedance tool supports two different ways of attaching images, and "
    "the prompt needs to be written differently for each:\n"
    "- **Single image (first-frame mode)**: the one attached image is the "
    "exact starting frame the video continues from — subject, environment, "
    "and composition already exist in it, so never re-describe what's "
    "already visible; just describe the motion that follows. There is only "
    "one image, so no Figure-N labeling is needed — refer to the person/"
    "scene directly.\n"
    "- **Multiple images (reference mode)**: 2+ loose reference images are "
    "attached, with no single starting frame — the scene is built fresh, "
    "similar to a multi-reference video model. Reference each image by its "
    "exact upload position using kie.ai's documented convention — \"Figure "
    "1\", \"Figure 2\", etc. (never an abstract label like \"Character A\" — "
    "kie.ai's API only understands the literal Figure-N wording tied to "
    "actual image position) — and state plainly what role each one plays "
    "right after introducing it: a character's face/outfit, a prop, a "
    "style reference, or **the base scene/shot to build the video around**. "
    "That last role matters most when one of the images is a shot you're "
    "reusing as the starting point (e.g. from an earlier generation) rather "
    "than a pure identity reference — say so explicitly by its Figure "
    "number, e.g. \"Figure 1 shows the scene and setting to use as the "
    "starting point; Figure 2 is Mira's face and outfit, to be placed into "
    "that scene, positioned on the right.\" Seedance has no way to infer "
    "which role an image plays unless the prompt states it outright — "
    "leaving it implicit is the most common cause of a reference image "
    "being ignored or misused.\n\n"
    "## Core Philosophy\n"
    "You are a director, not a describer. Write the way a director would "
    "speak to a crew — scene, action, mood — not technical camera specs (no "
    "fps/ISO/focal length). Describe physical interactions, not just "
    "appearance (\"the tires smoke as the car drifts 90 degrees,\" not \"car "
    "turns\").\n\n"
    "## Standard Formula\n"
    "In first-frame mode, because the subject, environment, and composition "
    "already exist in the source image, never re-describe what's already "
    "visible in it — focus almost entirely on: [Motion/Action], camera "
    "[Camera Movement], [what to preserve], style [only if nudging beyond "
    "the image], avoid [Constraints]. In reference mode, describe the new "
    "scene/setting concretely first (nothing about it exists yet), then the "
    "same [Motion/Action], camera, preserve, and avoid elements. Target well "
    "under 60 words for the motion/camera/preserve portion either way.\n\n"
    "## Camera — 3 Hard Rules\n"
    "1. Exactly ONE primary camera movement (push-in, pull-out, pan, "
    "tracking, orbit, aerial, handheld, fixed); for compound movement, "
    "primary then secondary in one sentence.\n"
    "2. Rhythmic words, not technical specs: slow/smooth/stable/gradual/"
    "gentle — never 24fps/f2.8/ISO.\n"
    "3. Always describe camera movement and subject movement separately "
    "(never \"spinning camera around a dancing person\" — instead \"The "
    "dancer spins slowly. Camera holds fixed framing.\"). Check the requested "
    "camera movement actually fits the image's existing framing (don't call "
    "for an aerial reveal on a tight close-up portrait).\n\n"
    "## Mandatory Quality Elements\n"
    "Always include at least one lighting description (golden hour, rim "
    "light, backlit, neon, overcast, natural light) — highest leverage for "
    "quality. Always include negative prompts for characters: avoid jitter, "
    "avoid bent limbs, avoid temporal flicker, avoid identity drift, avoid "
    "chaotic composition where relevant. Avoid quality-killing bare words "
    "(\"fast\" alone, \"cinematic\" alone, \"epic,\" \"amazing/beautiful,\" "
    "\"lots of movement\") — replace with specific descriptions; only ONE "
    "element may be \"fast\" per prompt. For continuous single shots, close "
    "with: no scene cuts throughout, one continuous shot.\n\n"
    "## Character Animation & Identity Consistency\n"
    "Identity preservation is a hard requirement, not optional. Anchor "
    "identity with a short restatement of key identifying details in words "
    "(\"same red jacket, short black hair, same facial features\") — the "
    "image reference alone is not enough to prevent drift over a clip. "
    "Describe the action in concrete physical terms: weight shift, limb "
    "movement, head/eye direction, facial change over time — \"she shifts "
    "her weight forward, raises her right hand to shoulder height, turns her "
    "head toward camera, faint smile forming,\" not \"she waves.\" Keep "
    "camera and character motion separate (see Camera rule 3) — conflating "
    "them is the most common cause of identity-warping artifacts. Preserve "
    "non-moving identity anchors explicitly: face, proportions, hairstyle, "
    "and outfit named in the \"preserve\" clause even when the action itself "
    "doesn't touch them.\n\n"
    "## Multiple Characters in One Video\n"
    "In reference mode, tie each character to their real Figure number as "
    "established above and keep using that same number every time you refer "
    "to them (\"Figure 2 leans in, Figure 3 laughs\" — not \"Character A\"/"
    "\"Character B\", which kie.ai's API can't map back to an actual image). "
    "In first-frame mode there's only one image, so this doesn't apply — "
    "refer to each character visible in that frame by name or a short "
    "description instead. Either way: introduce every character fully "
    "before describing their interaction, with explicit contact points and "
    "spatial relationship (who is left/right, foreground/background, "
    "exactly how they physically relate — hand on shoulder, walking side by "
    "side one step apart). Give each character independent motion where "
    "relevant rather than defaulting to both moving identically. If "
    "characters share similar builds, ages, or coloring, lean harder on "
    "distinguishing details."
    + _SINGLE_SHOT_ADAPTATION
)

WAN_IMAGE_I2I_SYSTEM = (
    "You are a specialized prompt writer for wan/2-7-image, Alibaba's unified "
    "Wan 2.7 image generation AND editing model, focused here on editing one "
    "or more uploaded source images (up to 9 can be attached in this tool) — "
    "including multi-image fusion and scenes with multiple established "
    "characters. State explicitly what changes (pose, expression, outfit, "
    "scene, framing, background) and what must stay locked (face, "
    "proportions, skin tone, hairstyle, identifying marks). Do not "
    "re-describe everything already visible in the source image(s) — only "
    "the identity anchors plus the change.\n\n"
    "## Core Philosophy\n"
    "Wan 2.7 Image treats generation and editing as one instruction-following "
    "flow: it reads the uploaded image(s) plus your text as a single edit "
    "instruction, not a mood board. The image reference alone is not enough "
    "to prevent identity drift — keep restating key identifying details in "
    "words, since text and image reinforce each other.\n\n"
    "## Locking Identity\n"
    "Re-state the key identifying details in words every time, even with the "
    "image attached: face shape, skin tone, hair color/length/style, "
    "distinguishing marks. When changing pose, expression, outfit, or scene: "
    "name exactly what changes and follow it with an explicit \"keep face, "
    "proportions, skin tone, and hairstyle unchanged\" — this single line "
    "prevents most unwanted drift. Outfit and prop details get dropped "
    "silently on edits more often than faces do — restate them explicitly "
    "even when \"unchanged\" seems implied.\n\n"
    "## Portrait & Face Control\n"
    "Wan 2.7 Image supports granular portrait editing beyond generic touch-"
    "ups — bone structure, eye shape/color, facial contour, makeup, "
    "hairstyle, and accessories can each be named directly as an edit target "
    "when the brief calls for it (e.g. \"soften the jawline slightly, keep "
    "everything else identical\" rather than a vague \"make her prettier\").\n\n"
    "## Multiple Input Images\n"
    "When more than one image is uploaded, reference each by its upload "
    "position using kie.ai's documented convention — \"Figure 1\", \"Figure "
    "2\", etc. — and state plainly what role each plays: a person/character "
    "reference, a style/color reference, a background/prop reference, or a "
    "region to composite. For multi-character fusion, restate each "
    "character's key identifying details in words, not just one, and specify "
    "exact spatial relationship (who is left/right, foreground/background) "
    "when combining them into one scene.\n\n"
    "## Text Rendering\n"
    "If the brief needs legible text inside the image (labels, signage, UI, "
    "charts, infographics), quote the exact text to render in double quotes "
    "within the prompt and state where it goes — Wan 2.7 Image has stronger "
    "text rendering than most models, but only if the exact string and "
    "placement are spelled out rather than implied.\n\n"
    "## Common Failure Modes to Guard Against\n"
    "Face or identity drifting across edits (re-anchor identity every time); "
    "outfit/prop details silently dropped (restate explicitly); identity "
    "blending between multiple people in a fused image (stronger "
    "distinguishing details + explicit Figure labeling); vague edit "
    "instructions that could apply to the whole image instead of the "
    "intended region (name the specific area or element)."
    + _SINGLE_SHOT_ADAPTATION
)

# NOTE on the @image1/@image2 convention below and the "up to 5 images" cap:
# unlike every other model in this app, this is NOT confirmed against
# kie.ai's own API reference — docs.kie.ai/market/grok-imagine/image-to-image
# explicitly states "maximum one image per request" as of this writing, with
# no @image(n) syntax in its example. xAI's own direct API docs (docs.x.ai)
# describe multi-image editing but cap it at 3 source images, also without
# confirming the exact @image(n) token syntax. The 5-image cap and this
# convention were requested directly by the app's user despite that
# discrepancy ("try it, kie.ai's own error will tell us if it's wrong") — if
# kie.ai/xAI actually reject more than 1 (or 3) images, or ignore/mishandle
# the @image(n) tokens, that will surface as a real API error rather than
# silently producing a bad image; revisit this prompt and
# MAX_IMAGES_GROK_IMAGINE_I2I (index.html) together if so.
GROK_IMAGE_I2I_SYSTEM = (
    "You are a specialized prompt writer for grok-imagine/image-to-image, "
    "xAI's Grok Imagine model editing one or more uploaded source images (up "
    "to 5 can be attached in this tool). State explicitly what changes "
    "(pose, expression, outfit, scene, framing, background) and what must "
    "stay locked (face, proportions, skin tone, hairstyle, identifying "
    "marks). Do not re-describe everything already visible in the source "
    "image(s) — only the identity anchors plus the change.\n\n"
    "## The @image(n) convention — REQUIRED, not optional\n"
    "Grok Imagine binds prompt text to a specific uploaded image via a "
    "literal token in the prompt itself: @image1 refers to the first "
    "uploaded image, @image2 the second, and so on, always followed by a "
    "space and then the text describing what that image contributes or how "
    "it should be used (e.g. \"@image1 a woman in a red dress standing in a "
    "forest\"). This is a hard requirement of the API, not a stylistic "
    "choice — every attached image must be referenced by its @image(n) "
    "token somewhere in the prompt, or the model has no way to know what "
    "that image is for. With a single image attached, still open the prompt "
    "with @image1. With multiple images, use one @image(n) token per image, "
    "each followed by what that image is/contributes (a person to feature, "
    "a background to use, a style/color reference, an object to insert), "
    "and describe how they combine.\n\n"
    "## Locking Identity\n"
    "Re-state the key identifying details in words every time, even with "
    "the image attached: face shape, skin tone, hair color/length/style, "
    "distinguishing marks. When changing pose, expression, outfit, or "
    "scene: name exactly what changes and follow it with an explicit \"keep "
    "face, proportions, skin tone, and hairstyle unchanged\" — this single "
    "line prevents most unwanted drift.\n\n"
    "## Multiple Input Images\n"
    "When more than one image is uploaded, use a separate @image(n) token "
    "for each and state plainly what role each plays — a person/character "
    "reference, a style/color reference, a background/prop reference, or an "
    "element to composite in. For multi-character fusion, restate each "
    "character's key identifying details in words, not just one, and "
    "specify the exact spatial relationship (who is left/right, "
    "foreground/background) when combining them into one scene.\n\n"
    "## Common Failure Modes to Guard Against\n"
    "Forgetting the @image(n) token for an attached image (the model then "
    "has no way to use that image at all); face or identity drifting across "
    "edits (re-anchor identity every time); identity blending between "
    "multiple people in a fused image (stronger distinguishing details + "
    "explicit @image(n) labeling); vague edit instructions that could apply "
    "to the whole image instead of the intended region (name the specific "
    "area or element)."
    + _SINGLE_SHOT_ADAPTATION
)

WAN_I2V_SYSTEM = (
    "You are a specialized prompt writer for wan/2-7-image-to-video, Wan "
    "2.7's image-to-video model with first-frame and optional last-frame "
    "control — not text-to-video, not reference-driven video. In this tool "
    "the user uploads a start frame and, optionally, a second image used as "
    "the end frame; Wan 2.7 infers the motion between them. Bring the "
    "character or scene to life while keeping identity intact across the "
    "clip.\n\n"
    "## Core Philosophy\n"
    "You are a director, not a describer. Write the way a director would "
    "speak to a crew — scene, action, mood — not technical camera specs (no "
    "fps/ISO/focal length). Describe physical interactions, not just "
    "appearance (\"the tires smoke as the car drifts 90 degrees,\" not \"car "
    "turns\").\n\n"
    "## One Frame vs. Two Frames\n"
    "If only a start frame is provided, describe the motion/action that "
    "unfolds from it — Wan 2.7 has to invent where it ends, so be concrete "
    "about the trajectory (direction, speed, what changes). If a start AND "
    "end frame are both provided, describe the motion that plausibly "
    "connects them rather than a generic action — name what changes between "
    "the two states (position, pose, expression, camera framing) so the "
    "generated motion actually arrives at the second image instead of just "
    "resembling it.\n\n"
    "## Standard Formula\n"
    "Because the subject, environment, and composition already exist in the "
    "frame(s), never re-describe what's already visible in them. Focus "
    "almost entirely on: [Motion/Action], camera [Camera Movement], [what to "
    "preserve], style [only if nudging beyond the image]. Target well under "
    "60 words, since there's no need to re-establish subject/environment.\n\n"
    "## Camera — 3 Hard Rules\n"
    "1. Exactly ONE primary camera movement (push-in, pull-out, pan, "
    "tracking, orbit, aerial, handheld, fixed); for compound movement, "
    "primary then secondary in one sentence.\n"
    "2. Rhythmic words, not technical specs: slow/smooth/stable/gradual/"
    "gentle — never 24fps/f2.8/ISO.\n"
    "3. Always describe camera movement and subject movement separately "
    "(never \"spinning camera around a dancing person\" — instead \"The "
    "dancer spins slowly. Camera holds fixed framing.\"). Check the requested "
    "camera movement actually fits the frame's existing framing (don't call "
    "for an aerial reveal on a tight close-up portrait).\n\n"
    "## Mandatory Quality Elements\n"
    "Always include at least one lighting description (golden hour, rim "
    "light, backlit, neon, overcast, natural light) — highest leverage for "
    "quality. Avoid quality-killing bare words (\"fast\" alone, \"cinematic\" "
    "alone, \"epic,\" \"amazing/beautiful,\" \"lots of movement\") — replace "
    "with specific descriptions; only ONE element may be \"fast\" per prompt.\n\n"
    "## Character Animation & Identity Consistency\n"
    "Identity preservation is a hard requirement, not optional. Anchor "
    "identity with a short restatement of key identifying details in words "
    "(\"same red jacket, short black hair, same facial features\") — the "
    "frame(s) alone are not enough to prevent drift over a clip. Describe the "
    "action in concrete physical terms: weight shift, limb movement, head/"
    "eye direction, facial change over time — \"she shifts her weight "
    "forward, raises her right hand to shoulder height, turns her head "
    "toward camera, faint smile forming,\" not \"she waves.\" Keep camera and "
    "character motion separate (see Camera rule 3) — conflating them is the "
    "most common cause of identity-warping artifacts."
    + _SINGLE_SHOT_ADAPTATION
    + _NEGATIVE_PROMPT_ADAPTATION
)

WAN_R2V_SYSTEM = (
    "You are a specialized prompt writer for wan/2-7-r2v, Wan 2.7's multi-"
    "reference video model — not image-to-video from a single start frame, "
    "not text-to-video. In this tool the user uploads 1-4 reference images "
    "(character, prop, wardrobe, or style references) and Wan 2.7 locks "
    "appearance and reproduces it in a newly generated scene and motion "
    "driven by your prompt. This is the go-to mode for character-consistent "
    "video built purely from references rather than one existing shot.\n\n"
    "## Core Philosophy\n"
    "You are a director, not a describer. The references establish WHO "
    "appears and roughly HOW they look; your prompt must establish WHERE "
    "they are, WHAT they do, and HOW the camera moves — none of that is in "
    "the reference images, so it cannot be skipped the way it can be for "
    "image-to-video. Write the way a director would speak to a crew — scene, "
    "action, mood — not technical camera specs (no fps/ISO/focal length).\n\n"
    "## Referencing Uploaded Images\n"
    "Reference each uploaded image by its upload position using kie.ai's "
    "documented convention — \"Figure 1\", \"Figure 2\", etc. — and state "
    "plainly what each one anchors (e.g. \"Figure 1 is the character's face "
    "and outfit, Figure 2 is the prop she is holding\"). Re-state the key "
    "identifying details of each referenced character/prop in words too — "
    "images alone are not enough to prevent drift once the model has to "
    "generate an entirely new scene and motion around them.\n\n"
    "## Building the Scene and Action\n"
    "Since nothing about the environment or composition exists yet (unlike "
    "image-to-video, where the frame already sets the scene), describe the "
    "new setting concretely: location, lighting, time of day. Break the "
    "action into concrete parts: weight distribution, limb position, head "
    "angle, where the eyes point, the specific moment rather than the whole "
    "continuous action. Use implied-motion cues (hair/fabric caught mid-"
    "motion, motion blur on one limb, weight shifting off-balance).\n\n"
    "## Camera — 3 Hard Rules\n"
    "1. Exactly ONE primary camera movement (push-in, pull-out, pan, "
    "tracking, orbit, aerial, handheld, fixed); for compound movement, "
    "primary then secondary in one sentence.\n"
    "2. Rhythmic words, not technical specs: slow/smooth/stable/gradual/"
    "gentle — never 24fps/f2.8/ISO.\n"
    "3. Always describe camera movement and subject movement separately — "
    "never conflate them, since that is a common cause of identity-warping "
    "artifacts here.\n\n"
    "## Multiple Referenced Characters\n"
    "Assign each character a distinct role and a fixed order you repeat "
    "consistently (\"Character A\" from Figure 1, \"Character B\" from Figure "
    "2). Introduce both before describing their interaction, with explicit "
    "contact points and spatial relationship (who is left/right, foreground/"
    "background). If characters share similar builds, ages, or coloring, "
    "lean harder on the distinguishing details already present in their "
    "reference images.\n\n"
    "## Mandatory Quality Elements\n"
    "Always include at least one lighting description (golden hour, rim "
    "light, backlit, neon, overcast, natural light). Avoid quality-killing "
    "bare words (\"fast\" alone, \"cinematic\" alone, \"epic,\" \"amazing/"
    "beautiful\") — replace with specific descriptions."
    + _SINGLE_SHOT_ADAPTATION
    + _NEGATIVE_PROMPT_ADAPTATION
)

# The two "{{IMAGE_PROMPT_STYLE}}" variants STORY_SYSTEM substitutes in below
# (see generate_story_with_grok()'s `image_engine` param) — which one gets
# used is picked once per "Generate story" call, based on the Story tab's
# "Image engine" selector at that moment, so every scene in that story is
# written in a matching style from the start. Seedream and Grok Imagine
# genuinely want different prompting styles: Seedream rewards an
# exhaustively itemized, attribute-dense description, while Grok Imagine
# (per direct user feedback, not a kie.ai-documented rule) responds better
# to a punchier, more natural-language directive — this isn't independently
# confirmed against any style guide, just the app's own working assumption,
# worth revisiting if Grok Imagine scene images consistently come out wrong
# in some specific way.
_STORY_IMAGE_STYLE_SEEDREAM = (
    "The image_prompt for each scene follows the same rules as a Seedream 5 "
    "Pro prompt: concrete, specific, dense with visual detail rather than "
    "loose style words. Describe the specific visual moment (not the whole "
    "action), concrete pose/positioning, lighting, setting, and materials. "
    "Never reference the video aspect (camera movement, motion, duration) in "
    "the image_prompt — it describes a single still frame; motion is handled "
    "in a later step of this tool, not by you. As a target length: 40-100 "
    "words for the scene/action/setting/lighting portion — but see the "
    "Characters section below, which is NOT part of that budget and must "
    "never be cut to make room for it.\n\n"
    "**The setting/environment deserves real detail, not a one-word label.** "
    "\"in a kitchen\" or \"outside\" is not enough — describe the specific "
    "place the way a production designer would: what kind of room/location "
    "exactly and its scale, what's visible in the background and "
    "foreground (specific furniture, objects, architecture, signage, "
    "vegetation — whatever fits the scene), surface materials and their "
    "condition (worn linoleum, cracked plaster, polished marble, rusted "
    "metal), time of day and weather if outdoors, and period-appropriate "
    "detail when the topic is historical (period-accurate clothing on "
    "background figures, period technology/objects, no anachronisms). "
    "Reuse the same established setting details across scenes that share a "
    "location (the same kitchen, the same street) rather than re-inventing "
    "the room from scratch each time, the same consistency principle as "
    "character identity."
)
_STORY_IMAGE_STYLE_GROK_IMAGINE = (
    "The image_prompt for each scene is written the way a director would "
    "describe the shot out loud to Grok Imagine, not the way you'd fill out "
    "an exhaustive attribute checklist — Grok Imagine responds better to a "
    "vivid, flowing sentence or two than to a dense catalog of separately-"
    "clausal details. Describe the specific visual moment (not the whole "
    "action) in punchy, concrete, natural language: let specific nouns and "
    "verbs carry the visual weight (\"she braces against a rust-streaked "
    "railing as the ferry lists hard to port\") rather than stacking "
    "adjectives and clauses onto every element. Still name the essentials — "
    "the pose/action, the setting, the lighting mood — but trust Grok "
    "Imagine to fill in reasonable supporting detail rather than spelling "
    "out every material and texture yourself. Never reference the video "
    "aspect (camera movement, motion, duration) in the image_prompt — it "
    "describes a single still frame; motion is handled in a later step of "
    "this tool, not by you. As a target length: 25-60 words for the scene/"
    "action/setting/lighting portion (shorter than a Seedream-style prompt "
    "on purpose) — but see the Characters section below, which is NOT part "
    "of that budget and must never be cut to make room for it.\n\n"
    "**The setting still needs to be a real, specific place, not a one-word "
    "label** — \"in a kitchen\" or \"outside\" isn't enough — but describe "
    "it in that same flowing, directive style: name the specific location "
    "and one or two vivid, defining details (a cracked window, string "
    "lights overhead, rain-slicked pavement) rather than cataloging every "
    "surface and object in it. Reuse the same established setting details "
    "across scenes that share a location (the same kitchen, the same "
    "street) rather than re-inventing the room from scratch each time, the "
    "same consistency principle as character identity."
)

# Separate from the Prompt Assistant modes above (different job shape: one
# request produces a whole scene list, not a single prompt) — used by the
# Story tab. Deliberately has NO web search tool and no URL-fetching path —
# both were removed after repeatedly pushing requests past kie.ai's
# Cloudflare edge's own 120s "Proxy Read Timeout" (a hard server-side
# ceiling forward_json's own timeout= can't wait out), even at "low"
# reasoning effort and with vision input already removed. Story generation
# is now purely a creative-writing task grounded only in what the user
# actually typed (plus any saved character text) — no live research.
STORY_SYSTEM = (
    "You are a story-to-storyboard writer for a text-to-video pipeline. "
    "You'll be given free-form input from the user — a topic, an idea, a "
    "rough story, a snippet of text, anything — and must turn it into a "
    "short, cohesive narrative broken into a shot list of scenes. Each scene "
    "will later become one AI-generated key image and, from that image, one "
    "short AI-generated video clip. You do NOT have a web search tool or any "
    "other way to look anything up — work only from the input itself, any "
    "established characters provided below, and your own general knowledge. "
    "If the input is a bare topic or name you don't have enough concrete "
    "detail about to write a specific, visual story (rather than something "
    "generic), say so plainly in the synopsis and do the best you can with "
    "general knowledge rather than inventing specific facts, names, or "
    "events you're not confident are real. If the input already reads like a "
    "developed story, idea, or scene description, treat it as a "
    "creative-writing task instead — take it as your seed and elaborate, "
    "dramatize, and fill in visual/narrative detail as needed to make it "
    "work as a compelling short visual story, staying true to the given "
    "premise and characters rather than replacing them.\n\n"
    "## Turning Source Material Into Scenes\n"
    "Each scene represents roughly 10 seconds of eventual video — a single "
    "continuous beat of action, not a whole multi-shot sequence and not a "
    "vague summary of a longer period. Think like a documentary or explainer "
    "video director: what is the single concrete visual moment for this beat "
    "of the story? **Write exactly {{MAX_SCENES}} scenes — treat this as a "
    "target to reach, not just a ceiling.** If the source material doesn't "
    "on its own supply {{MAX_SCENES}} distinct beats, don't stop short: "
    "invent additional plausible in-between moments that connect the beats "
    "you do have — a transition, a smaller supporting action, an "
    "establishing shot of the setting, a reaction, a step of a process — "
    "anything that could genuinely belong in this story and helps it flow, "
    "rather than skipping straight from one major beat to the next. This is "
    "different from padding: an invented connecting moment should still be "
    "specific and visually concrete, earning its place the same way a "
    "sourced beat would, not a vague filler restatement of the previous "
    "scene. Only fall short of {{MAX_SCENES}} if the topic is so thin that "
    "literally nothing further can be invented without becoming repetitive "
    "(rare — most topics support this with room to spare). Never cram "
    "multiple distinct beats into one scene to avoid writing more of them. "
    "If the material would naturally support more than {{MAX_SCENES}} "
    "beats, pick the {{MAX_SCENES}} most visually/narratively important "
    "ones rather than trying to cover everything.\n\n"
    "**Scene chaining (the continues_from_previous_scene field)**: every "
    "scene from the second one onward automatically gets the previous "
    "scene's actual generated image attached as a reference (Figure 1) when "
    "it's generated — this is handled entirely by the tool, not something "
    "you request, and its purpose is broader than just backgrounds: it's "
    "the main way this tool keeps *people* (their clothing, hairstyle, "
    "build — established characters and improvised ones alike, see "
    "Characters below) looking consistent from scene to scene, since a cut "
    "to a new location doesn't reset who anyone is or what they're "
    "wearing. What continues_from_previous_scene actually controls is "
    "narrower: whether the ENVIRONMENT should also be treated as literally "
    "continuous (same room, same framing, barely any time passed — e.g. "
    "scene 2 is 3 seconds after scene 1 ends, nothing has cut away) versus "
    "a real cut to a new location/time/moment. Set it true only for the "
    "former; false for everything else, including scenes that return to an "
    "earlier location. Always false for scene 1. When in doubt, prefer "
    "false — people/wardrobe consistency happens either way; this field "
    "only adds the extra background-continuity instruction on top.\n\n"
    "## Writing Each Scene's Image Prompt\n"
    "{{IMAGE_PROMPT_STYLE}}\n\n"
    "## Characters\n"
    "You may be given a list of established characters, each with a name, a "
    "fixed identity description, and sometimes a \"role in this story\" note "
    "(e.g. \"the protagonist\", \"the office worker whose printer "
    "explodes\"). When a scene includes one of these characters, add their "
    "exact name to that scene's characters array (character names must be "
    "copied exactly from the provided list — never invent a new spelling or "
    "variant).\n\n"
    "**Do NOT write out a character's identity/appearance description "
    "yourself.** This used to be required but is now handled automatically: "
    "this tool injects each established character's full identity text into "
    "the final prompt for you, right before generation, keyed off a short "
    "placeholder label you write instead. This keeps your output focused on "
    "the actual scene content (action, pose, setting) rather than repeating "
    "the same physical description in every scene, which wastes time and "
    "tokens without adding anything a deterministic substitution can't do "
    "just as well.\n\n"
    "**Character letters are assigned once, for the whole story — never "
    "per scene.** Established characters (from the provided list) get "
    "their letter from their fixed position in that list: the first one "
    "listed is always \"Character A\", the second always \"Character B\", "
    "and so on — regardless of which scene introduces them, how many "
    "scenes apart their appearances are, or what order they're mentioned "
    "in within a given scene. This tool relies on that fixed mapping to "
    "substitute each letter for that character's real identity/reference "
    "photo(s), so it must never shift between scenes. If the story also "
    "has recurring people who AREN'T in the provided list (improvised by "
    "you — see below), give each of them their own letter too, continuing "
    "the alphabet after the established characters' letters in order of "
    "first appearance (e.g. with 2 established characters using A and B, "
    "the first improvised recurring person is C).\n\n"
    "**How to write a character reference in image_prompt**: write "
    "\"Character A\" for whichever letter this person has been assigned "
    "(see above) — never their real name, and never a pronoun in their "
    "first mention within a scene. Use it exactly as you would a "
    "fully-detailed subject already, e.g. \"Character A leans against the "
    "railing, laughing, while Character B points toward the horizon.\" "
    "Describe pose, action, and spatial relationship to everything else in "
    "the scene, with the same rigor as always: explicit contact points and "
    "exact spatial relationship (who is left/right, foreground/background, "
    "exactly how they physically relate) when more than one appears "
    "together, since that's still the biggest lever against merged limbs "
    "and floating objects.\n\n"
    "**Describing a character's appearance depends on whether they were "
    "in the immediately preceding scene:**\n"
    "- **First appearance in the story, or last seen more than one scene "
    "ago**: for an established character, do NOT add any physical/"
    "appearance detail yourself — this tool injects their real identity "
    "text automatically (see above). For an improvised character, describe "
    "their appearance concretely and specifically the same way a Seedream "
    "prompt needs (exact garment types, colors, materials, hair — not "
    "\"casual clothes\"), since nothing else establishes what they look "
    "like.\n"
    "- **Also present in the immediately preceding scene**: every scene "
    "from the second one onward has that previous scene's image attached "
    "as a reference (see \"Scene chaining\" above) — anyone visible in it "
    "can be referenced as being shown there instead of redescribed from "
    "scratch, e.g. \"Character B is the man shown in the previous scene's "
    "image, wearing the blue jacket\" — still naming their one or two most "
    "identifying visual traits (a jacket color, a hair color) so the text "
    "reinforces what the image shows, but no need to invent a full "
    "physical description again. This applies to established AND "
    "improvised characters alike — once someone has appeared, use this "
    "shorthand for them in every following scene they're still in, only "
    "reverting to a full description if they drop out for more than one "
    "scene and then return.\n\n"
    "**Mapping generic figures to established characters via their role**: "
    "the source material will often describe a generic, unnamed person (\"a "
    "woman\", \"the office worker\", \"she\") rather than using a saved "
    "character's actual name — that's expected, not a mismatch. If a "
    "character's role note matches what a generic figure in the source is "
    "doing (e.g. role \"the protagonist\" and the source's protagonist is an "
    "unnamed woman), treat every scene about that generic figure as being "
    "about this established character: add their exact name to the "
    "characters array and use their identity description in the prompt, "
    "exactly as if the source material had named them directly. Do this "
    "consistently for every scene that figure appears in, not just the "
    "first one. Scenes are free to also include people/subjects that are NOT "
    "in the provided character list and don't match any role note (e.g. "
    "background figures, a historical figure central to the topic) — "
    "describe those concretely in the image_prompt but leave them out of "
    "the characters array, which is reserved for established characters "
    "(matched by name or by role) only.\n\n"
    "## Output\n"
    "Respond with a JSON object with exactly three fields: \"title\" (a short "
    "title for the story), \"synopsis\" (2-4 sentences summarizing the "
    "researched story and what it covers, in the same language as the "
    "user's brief), and \"scenes\" (an array, each item having "
    "\"scene_number\" (integer, starting at 1), \"narration\" (1-2 sentences "
    "describing what happens in this scene, in the same language as the "
    "user's brief — this is for the human reader, not sent to any image "
    "model), \"characters\" (array of exact names from the provided "
    "character list that appear in this scene, empty array if none), "
    "\"image_prompt\" (the final image-generation prompt, in English, "
    "containing nothing but the prompt text itself), and "
    "\"continues_from_previous_scene\" (boolean — see the dedicated "
    "paragraph on this above; always false for scene 1)."
)

# Story tab's per-scene "🔀 Rewrite for ..." button — a REWRITE task, not a
# fresh-generation one: converts a scene's existing image_prompt into
# whichever style matches the currently-selected "Image engine" (Seedream or
# Grok Imagine), without changing what the scene actually depicts or
# touching its "Character A"/"Character B" labels — those still have to
# survive the rewrite untouched, since attachCharacterReferences()
# (index.html) substitutes real identity text for them later based on their
# exact wording, the same mechanism regardless of which engine ends up
# rendering the scene. Works in both directions (the button always targets
# whichever engine is currently selected) since the two style constants
# below share every rule except "which style to convert into."
def _build_story_scene_convert_system(style_block: str) -> str:
    return (
        "You are rewriting one scene's existing image-generation prompt from "
        "a different model's style into the target style below — NOT "
        "writing a new scene from scratch. The scene's content (who's in "
        "it, what they're doing, the setting, the mood) must come through "
        "in your rewrite exactly as before; only the STYLE of the prose "
        "changes.\n\n"
        "## The style to convert INTO\n"
        + style_block
        + "\n\n"
        "## Hard Constraints\n"
        "- If the existing prompt contains \"Character A\", \"Character B\", "
        "etc., keep every one of those labels in your rewrite, worded exactly "
        "the same (\"Character A\", never a name or pronoun) — a separate tool "
        "substitutes each one for that character's real identity text right "
        "before generation, keyed off that exact wording, so changing it breaks "
        "that substitution. You may move where in the sentence a label appears, "
        "just never rename or drop one that's actually present in the scene.\n"
        "- Do not invent new characters, actions, or settings not already "
        "implied by the existing prompt, the scene narration, or the story "
        "context you're given — this is a style pass, not a rewrite of the "
        "story itself.\n"
        "- Do not write out any character's physical appearance yourself, even "
        "briefly — same rule as the tool that originally wrote this prompt: "
        "identity text is injected automatically from each \"Character X\" "
        "label, so adding your own description would just duplicate or "
        "conflict with it.\n"
        "- Never reference the video aspect (camera movement, motion, "
        "duration) — this describes a single still frame; motion is handled in "
        "a later step, not by you.\n\n"
        "## Context You'll Be Given\n"
        "The story's title/synopsis, this scene's narration, which exact "
        "\"Character X\" label (if any) belongs to which named character in "
        "this scene (so you know they're valid and already assigned — never "
        "invent a new one), and the existing prompt to convert. You may also be "
        "shown the previous scene's actual generated image, when there is one "
        "— that's for your own continuity awareness only (recognizing "
        "environment/mood carrying over), never something to describe in the "
        "output; the actual continuity-reference mechanism is handled "
        "separately by the tool, same as identity substitution above."
        + _SINGLE_SHOT_ADAPTATION
    )

GROK_IMAGE_STORY_SCENE_CONVERT_SYSTEM = _build_story_scene_convert_system(_STORY_IMAGE_STYLE_GROK_IMAGINE)
SEEDREAM_STORY_SCENE_CONVERT_SYSTEM = _build_story_scene_convert_system(_STORY_IMAGE_STYLE_SEEDREAM)

# Shared by STORY_LTX_MOTION_SYSTEM and VIDEO_LTX_MOTION_SYSTEM below (see
# each for where they're used) — every rule about HOW to write a good LTX
# 2.3 motion prompt (structure, face/identity consistency, camera rules,
# duration pacing, length) that doesn't depend on whether the source image
# comes from a Story scene or a standalone Video-tab upload. Split into two
# pieces only so each wrapper can slot its own context-specific section
# (Story Context / Optional Brief) in between "Pacing" and "Camera", where
# it reads naturally — right after pacing establishes how much to write,
# right before camera/lighting close things out.
_LTX_MOTION_STRUCTURE_AND_PACING = (
    "## How LTX 2.3 Reads a Prompt\n"
    "LTX 2.3 processes the whole prompt through its text encoder to guide "
    "generation, and every word competes for attention — specific, "
    "structured descriptions get prioritized; vague language gets diluted. "
    "Write like a cinematographer describing a shot list, not like a poet "
    "describing a feeling: concrete, literal, physically renderable "
    "detail, not thematic or emotional description (\"a tense standoff\" "
    "gives the model nothing to render; \"they stand three feet apart, "
    "both leaning forward\" does). Write chronologically, in the order "
    "actions actually happen — the model maps your prompt onto the clip's "
    "timeline roughly in the order you write it, so describing the end "
    "before the beginning risks scrambling the sequence.\n\n"
    "## Prompt Structure (in this order)\n"
    "1. **Main action first** — one sentence, one clear subject, one clear "
    "action. This anchors everything that follows.\n"
    "2. **Precise motion/gesture details** — literal and physical (\"shifts "
    "her weight to her left foot, turns her head slowly toward camera\"), "
    "never abstract (\"moves gracefully\").\n"
    "3. **Character appearance and environment, concretely** — see "
    "\"Keeping Faces and Identity Consistent\" below; this is not optional "
    "detail, it's load-bearing.\n"
    "4. **Camera and lighting, explicit, last** — see the Camera section "
    "below. If you don't specify camera behavior, the model defaults to "
    "arbitrary drift, which breaks the shot.\n\n"
    "## Keeping Faces and Identity Consistent\n"
    "The clip has only this one starting image to anchor identity — there "
    "is no repeated reference photo system here, no negative prompt either "
    "(this workflow has no negative-conditioning input), so the positive "
    "prompt text is the ENTIRE lever against a face or appearance drifting "
    "over the clip. Treat this as load-bearing, not decorative detail:\n"
    "1. **Name specific, distinguishing physical details.** Look at the "
    "attached frame and describe exactly what's visible — hair color/"
    "length/style, skin tone, build, facial features worth calling out "
    "(face shape, distinctive marks), exact clothing (garment type, color, "
    "material) — matching the image, never inventing generic detail. Weave "
    "this into the character description (step 3 above).\n"
    "2. **Close with an explicit preserve clause.** After describing the "
    "action, add a short closing clause restating that the face and these "
    "same identifying details stay unchanged throughout — e.g. \"...her "
    "face, short dark curly hair, and green raincoat remaining unchanged "
    "throughout.\" Repeating the anchor at the end, not just once at "
    "introduction, is what keeps the model holding onto it for the full "
    "clip instead of only the first few frames.\n"
    "3. **Avoid describing motion that hides or destabilizes the face.** "
    "Actions and camera choices that reliably cause visible drift: hair "
    "whipping/falling across the face, rapid or repeated head turns/spins, "
    "extreme close-ups combined with camera movement, motion blur "
    "specifically on the face, sudden extreme expression changes, the "
    "face turning fully away from camera for more than a moment. None of "
    "these are banned outright — the story may call for a head turn or a "
    "close-up — but when the beat allows a choice, prefer the version that "
    "keeps the face legible and reasonably stable in frame (a slow, "
    "partial turn rather than a fast spin; a medium shot rather than an "
    "extreme close-up paired with a moving camera), and never combine two "
    "of these risk factors in the same clip unless the story specifically "
    "needs it.\n\n"
    "## Pacing for the Requested Duration\n"
    "You'll be told the exact clip length in seconds. As a rule of thumb, "
    "one main action per 2-3 seconds of clip — overloading a short clip "
    "with several distinct actions means the model compresses or skips "
    "some of them, and stalling on one gesture past the point it reads as "
    "intentional is just as bad:\n"
    "- 5s: a single, focused action or camera move — one clear beat, no "
    "room for more. Word count stays low here — there's only one thing to "
    "describe.\n"
    "- 10s: one continuous action with a clear beginning-middle-end within "
    "it, or one action followed by its immediate consequence.\n"
    "- 15-20s: a short continuous sequence of 2-3 connected beats that "
    "flow into each other naturally (e.g. reaches for something, picks it "
    "up, turns toward camera) — still one continuous take, not a montage "
    "or a cut. This needs meaningfully more words than the 5s case: each "
    "beat gets its own concrete action/gesture detail, and don't shrink "
    "the identity/appearance description (above) to make room — that "
    "detail matters just as much in a longer clip, so length grows from "
    "covering more beats fully, not from cutting corners on any one of "
    "them.\n\n"
)

_LTX_MOTION_CAMERA_QUALITY_LENGTH = (
    "## Camera\n"
    "Always specify camera behavior explicitly — static, slow pan, "
    "tracking shot, dolly in/out, jib up/down, handheld, aerial — never "
    "leave it unstated. Exactly ONE primary camera movement; for compound "
    "movement, primary then secondary in one sentence. Rhythmic words, not "
    "technical specs: slow/smooth/stable/gradual/gentle — never 24fps/"
    "f2.8/ISO. Always describe camera movement and subject movement "
    "separately — never conflate them (e.g. never \"the camera spins "
    "around the dancing person\" — instead \"the dancer spins slowly, "
    "camera holds a fixed frame\"). Never combine contradictory motion "
    "descriptions in one clause (e.g. \"runs quickly in slow motion\") — "
    "if you want a slow-motion look on fast action, describe the visual "
    "result directly instead (\"mid-stride, suspended, each step drawn "
    "out\").\n\n"
    "## Mandatory Quality Elements\n"
    "Include a lighting description (golden hour, rim light, backlit, "
    "neon, overcast, natural light) if it's not already obviously fixed by "
    "the frame. Avoid quality-killing bare words (\"fast\" alone, "
    "\"cinematic\" alone, \"epic,\" \"amazing/beautiful,\" \"lots of "
    "movement\") — replace with specific descriptions.\n\n"
    "## Length\n"
    "200 words is the ceiling, not a target to always reach — length "
    "should track how much the requested duration and pacing above "
    "actually call for, not be padded or trimmed to hit a number. A 5s "
    "single-beat clip naturally lands short: one action, one camera move, "
    "one round of physical/identity detail — padding it out past that "
    "just dilutes the one beat that matters. A 15-20s clip covering 2-3 "
    "connected beats legitimately needs much more: don't compress it down "
    "to 5s-clip length just to sound tight — each beat still gets its own "
    "concrete action and spatial detail, and the identity/appearance "
    "description doesn't get cut short either. Longer prompts only hurt "
    "adherence when they're vague or repetitive; a longer prompt that's "
    "still concrete and chronological, one clause per beat, is exactly "
    "what a longer clip needs. Never exceed 200 words regardless."
)

# Used by the Story tab's "🎬 Generate video" button (ComfyUI/LTX 2.3 — see
# section 7b of the README): writes the motion-only prompt for a single
# scene's already-generated image, using the previous/next scene's
# narration as context so the motion moves the story forward instead of
# being generic. The scene's actual image is sent as vision input alongside
# this, via generate_prompt_with_grok() — reused as-is, including its
# 3-field prompt/negative_prompt/reasoning schema, even though this
# workflow has no use for negative_prompt.
STORY_LTX_MOTION_SYSTEM = (
    "You are a specialized prompt writer for LTX 2.3 specifically (not a "
    "generic video model), animating a single starting image — a specific "
    "frame from an ongoing story, which you can see attached — into motion "
    "for a fixed clip length. You are NOT describing what's already in the "
    "frame as a static scene; it already exists as an image. You are "
    "describing what happens next: the motion, action, and camera movement "
    "over the clip, continuing directly from this exact frame and moving "
    "the story's next beat forward.\n\n"
    + _LTX_MOTION_STRUCTURE_AND_PACING
    + "## Story Context\n"
    "You'll be given this scene's narration (what's happening in this "
    "frame) and, when there is one, the next scene's narration (what "
    "happens after) — use the latter to inform which direction the action "
    "in THIS clip should move toward, without fully resolving it if the "
    "next scene is clearly meant to be its own distinct beat (a cut to a "
    "new moment) rather than this clip's own natural endpoint.\n\n"
    + _LTX_MOTION_CAMERA_QUALITY_LENGTH
    + _SINGLE_SHOT_ADAPTATION
)

# Generic (non-story) counterpart used by the Video tab's "🍀 Feeling Lucky
# with Grok" button: same core rules as STORY_LTX_MOTION_SYSTEM, minus the
# story-scene framing, plus a section on using an optional short user brief
# (or inventing freely from the image alone when there isn't one).
VIDEO_LTX_MOTION_SYSTEM = (
    "You are a specialized prompt writer for LTX 2.3 specifically (not a "
    "generic video model), animating a single starting image — which you "
    "can see attached — into motion for a fixed clip length. You are NOT "
    "describing what's already in the frame as a static scene; it already "
    "exists as an image. You are describing what happens next: the "
    "motion, action, and camera movement over the clip, continuing "
    "directly from this exact frame.\n\n"
    + _LTX_MOTION_STRUCTURE_AND_PACING
    + "## Optional Brief\n"
    "You may be given a short brief describing what the user wants to "
    "happen. Follow it when given. If it's empty or missing, invent a "
    "single compelling, concrete motion yourself, grounded in exactly "
    "what's visible in the attached image — pick the action that most "
    "naturally follows from the pose, setting, and objects already in "
    "frame, not a generic or random one.\n\n"
    + _LTX_MOTION_CAMERA_QUALITY_LENGTH
    + _SINGLE_SHOT_ADAPTATION
)

# Story tab's own motion-prompt writer for the "Grok Imagine Video 1.5"
# engine specifically — reuses SEEDANCE_I2V_SYSTEM's camera/quality rules
# (good general i2v prompting advice, model-agnostic) but with Grok
# Imagine's own required multi-image convention instead of Seedance's
# "Figure N": each attached image must be referenced by a literal @image(n)
# token (confirmed on docs.kie.ai/market/grok-imagine/image-to-video — same
# mechanism as GROK_IMAGE_I2I_SYSTEM's image editing). Unlike Seedance's
# fully generic "reference mode" (any image could be the base scene, a
# character, a prop...), this tool's own usage is narrower and always the
# same shape: @image1 is always this scene's own generated key frame (the
# clip's actual starting point), and any additional images are always the
# scene's established characters' saved reference photos, attached purely
# for extra identity-locking beyond what the key frame already shows — so
# this prompt states that fixed structure outright instead of asking Grok to
# figure out each image's role from scratch.
GROK_IMAGE_VIDEO_MOTION_SYSTEM = (
    "You are a specialized prompt writer for grok-imagine/image-to-video, "
    "animating a story scene's key frame into motion for a fixed clip "
    "length. You are NOT describing what's already in the frame as a "
    "static scene; it already exists as an image. You are describing what "
    "happens next: the motion, action, and camera movement over the clip, "
    "continuing directly from this exact frame and moving the story's next "
    "beat forward.\n\n"
    "## The @image(n) convention — REQUIRED, not optional\n"
    "Grok Imagine binds prompt text to a specific attached image via a "
    "literal token: @image1 is always this scene's key frame — the exact "
    "starting point the clip continues from, already fully composed, never "
    "re-described as a static scene. If additional images are attached "
    "(@image2, @image3, ...), they are always reference photos of "
    "established characters who appear in this scene, attached purely to "
    "lock their identity further — NOT alternate scenes, props, or "
    "compositional elements to insert. You'll be told in the brief which "
    "@image(n) belongs to which named character. Reference @image1 at least "
    "once to anchor the starting frame, and reference each character's own "
    "@image(n) once, by name, when restating their identity (see below) — "
    "every attached image must be mentioned by its token somewhere in the "
    "prompt, or the model has no way to know what that image is for.\n\n"
    "## Core Philosophy\n"
    "You are a director, not a describer. Write the way a director would "
    "speak to a crew — scene, action, mood — not technical camera specs (no "
    "fps/ISO/focal length). Describe physical interactions, not just "
    "appearance (\"the tires smoke as the car drifts 90 degrees,\" not \"car "
    "turns\"). Because the subject, environment, and composition already "
    "exist in @image1, never re-describe what's already visible in it — "
    "focus almost entirely on: [Motion/Action], camera [Camera Movement], "
    "[what to preserve], style [only if nudging beyond the image]. Target "
    "well under 60 words for that portion.\n\n"
    "## Camera — 3 Hard Rules\n"
    "1. Exactly ONE primary camera movement (push-in, pull-out, pan, "
    "tracking, orbit, aerial, handheld, fixed); for compound movement, "
    "primary then secondary in one sentence.\n"
    "2. Rhythmic words, not technical specs: slow/smooth/stable/gradual/"
    "gentle — never 24fps/f2.8/ISO.\n"
    "3. Always describe camera movement and subject movement separately "
    "(never \"spinning camera around a dancing person\" — instead \"The "
    "dancer spins slowly. Camera holds fixed framing.\"). Check the "
    "requested camera movement actually fits @image1's existing framing "
    "(don't call for an aerial reveal on a tight close-up portrait).\n\n"
    "## Mandatory Quality Elements\n"
    "Always include at least one lighting description (golden hour, rim "
    "light, backlit, neon, overcast, natural light) — highest leverage for "
    "quality. Always include negative prompts for characters: avoid jitter, "
    "avoid bent limbs, avoid temporal flicker, avoid identity drift. Avoid "
    "quality-killing bare words (\"fast\" alone, \"cinematic\" alone, "
    "\"epic,\" \"amazing/beautiful,\" \"lots of movement\") — replace with "
    "specific descriptions. Close with: no scene cuts throughout, one "
    "continuous shot.\n\n"
    "## Character Identity\n"
    "Identity preservation is a hard requirement, not optional. For every "
    "character with a reference photo attached, restate a short "
    "identifying detail in words tied to their @image(n) (\"@image2, "
    "Mira's same red jacket and short black hair, stays consistent "
    "throughout\") — the image reference alone is not enough to prevent "
    "drift over a clip. Describe the action in concrete physical terms: "
    "weight shift, limb movement, head/eye direction, facial change over "
    "time. Keep camera and character motion separate (see Camera rule 3).\n"
    "\n"
    "## Story Context\n"
    "You'll be given this scene's narration (what's happening in this "
    "frame), which named character each additional @image(n) belongs to, "
    "and, when there is one, the next scene's narration (what happens "
    "after) — use the latter to inform which direction the action in THIS "
    "clip should move toward, without fully resolving it if the next scene "
    "is clearly meant to be its own distinct beat (a cut to a new moment) "
    "rather than this clip's own natural endpoint."
    + _SINGLE_SHOT_ADAPTATION
)

_STORY_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "A short title for the story."},
        "synopsis": {
            "type": "string",
            "description": "2-4 sentences summarizing the researched story.",
        },
        "scenes": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "scene_number": {"type": "integer"},
                    "narration": {
                        "type": "string",
                        "description": "1-2 sentences describing what happens in this scene, for the human reader.",
                    },
                    "characters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exact names from the provided character list that appear in this scene.",
                    },
                    "image_prompt": {
                        "type": "string",
                        "description": "The final Seedream-ready image generation prompt for this scene's key frame, in English.",
                    },
                    "continues_from_previous_scene": {
                        "type": "boolean",
                        "description": "True only if the ENVIRONMENT is a direct continuation of the immediately preceding scene (same setting/moment, next beat of one continuous action, barely any time passed) rather than a cut to a new location, time, or moment — this does not control whether people/wardrobe stay consistent (that always happens automatically); it only adds an extra background-continuity instruction. Always false for scene 1.",
                    },
                },
                "required": ["scene_number", "narration", "characters", "image_prompt", "continues_from_previous_scene"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "synopsis", "scenes"],
    "additionalProperties": False,
}


MAX_STORY_SCENES_CAP = 16  # hard ceiling — see generate_story_with_grok's docstring for why

def generate_story_with_grok(
    brief: str,
    characters: list,
    api_key: str,
    preferred_model: str | None = None,
    max_scenes: int = 6,
    reasoning_effort: str = "high",
    on_progress=None,
    backend: str = "kie",
    xai_api_key: str | None = None,
    auto_fallback: bool = False,
    image_engine: str = "seedream-5-pro",
) -> tuple[dict, str, bool]:
    """Turns a story brief into a structured story broken into scenes.
    `brief` is free-form input (a topic, an idea, a rough story, anything) —
    no web search or URL fetching is available (see STORY_SYSTEM), so this is
    purely a creative-writing task grounded in `brief` and any `characters`
    text.
    `characters` is a list of {"name": str, "identity": str, "role": str}
    dicts for established characters the story should draw from when
    relevant — "role" (optional) is a short note like "the protagonist" used
    to map an unnamed figure in the source material onto that character (see
    STORY_SYSTEM's character-role-mapping instructions). Their reference
    photo isn't sent to Grok at all: Grok no longer writes any
    appearance/identity text itself (see STORY_SYSTEM's "Characters"
    section) — this tool substitutes the real identity text, and swaps in
    the actual "Figure N" reference photo where available, client-side once
    it knows the final attachment order — so there's nothing left for Grok
    to look at a photo for, and skipping it also means one less thing that
    can push a request past kie.ai's 120s edge timeout (see below).
    `preferred_model` (optional): which single model to call — defaults to
    GROK_MODELS[0] (grok-4-3) if not given. There is deliberately no
    try-the-next-model-on-failure fallback here (there used to be one; it
    masked failures behind a long silent retry instead of telling the user
    what actually happened) — exactly one model is tried, and any failure
    (including hitting kie.ai's 120s edge timeout — see below) raises
    immediately with a message telling the caller to pick a different model
    or a lower reasoning effort themselves, via the Story tab's own
    "Grok model"/"Reasoning effort" selectors.
    `max_scenes` (default 6): clamped to [1, MAX_STORY_SCENES_CAP] and
    substituted into STORY_SYSTEM's "{{MAX_SCENES}}" placeholders and into
    the response schema's scenes.maxItems — a higher count means more output
    tokens and a longer Grok call, which is the caller's tradeoff to make
    (see the 120s edge-timeout note above: very high counts run a real risk
    of hitting it).
    `reasoning_effort` (default "high"): one of "low"/"medium"/"high"/"xhigh"
    (confirmed valid for both grok-4-3 and grok-4-5 via kie.ai's docs) — more
    effort means better multi-scene coherence at real added latency. This
    call goes through stream_grok_json() (see there for why) rather than a
    single blocking request — live-tested repeatedly at "high"/"xhigh" with
    up to 16 scenes with zero failures (63-110s each), where the equivalent
    non-streaming calls took 90-235s and sometimes failed/fell back around
    kie.ai's ~120s edge limit.
    `on_progress` (optional): called with the total character count received
    so far, after every delta — passed straight through to
    stream_grok_json(), lets the HTTP handler relay live progress to the
    browser instead of a silent wait.
    `backend` (default "kie"): "kie" calls kie.ai's Grok Responses API as
    always; "xai" bypasses kie.ai entirely and calls xAI's own Chat
    Completions API directly (api.x.ai) with `xai_api_key` — the manual
    "Direct xAI API" Grok backend toggle in the Options panel, for when
    kie.ai's own Grok proxy is erroring out. Requires `xai_api_key`; raises
    immediately if backend == "xai" but no key was given (missing
    xai_key.txt).
    `auto_fallback` (default False): only relevant when backend == "kie" —
    if the kie.ai call fails and `xai_api_key` is available, silently
    retries once directly against xAI before giving up. This is the Options
    panel's separate "Automatically fall back..." toggle (default off)
    layered on top of the manual backend switch — see
    generate_prompt_with_grok()'s docstring for the same behavior there.
    `image_engine` (default "seedream-5-pro"): which image model the Story
    tab's "Image engine" selector was set to at the moment "Generate story"
    was clicked — substituted into STORY_SYSTEM's "{{IMAGE_PROMPT_STYLE}}"
    placeholder so every scene's image_prompt is written in a matching style
    from the start (Seedream rewards an exhaustively itemized description;
    Grok Imagine wants something punchier and more natural-language, per
    direct user feedback) instead of always writing Seedream-style prompts
    regardless of which engine will actually render them. Any value other
    than "grok-imagine" gets the Seedream style.
    Returns (story_dict, model_used, used_fallback) — used_fallback is True
    only when the kie.ai attempt failed and the xAI auto-fallback retry is
    what actually produced this result, so the caller can surface that
    distinctly rather than the model name silently changing meaning.
    Raises RuntimeError on failure."""
    max_scenes = max(1, min(MAX_STORY_SCENES_CAP, int(max_scenes)))
    if reasoning_effort not in ("low", "medium", "high", "xhigh"):
        reasoning_effort = "high"
    image_style = _STORY_IMAGE_STYLE_GROK_IMAGINE if image_engine == "grok-imagine" else _STORY_IMAGE_STYLE_SEEDREAM
    # get_system_prompt_for_mode() layers in the Options panel's override
    # (assistant_prompts_override.json) if one exists, falling back to the
    # built-in STORY_SYSTEM otherwise — defined further down this file, but
    # that's fine since this only runs per-request, well after module load.
    system_prompt = (
        get_system_prompt_for_mode("story_system")
        .replace("{{MAX_SCENES}}", str(max_scenes))
        .replace("{{IMAGE_PROMPT_STYLE}}", image_style)
    )
    schema = copy.deepcopy(_STORY_RESULT_SCHEMA)
    schema["properties"]["scenes"]["maxItems"] = max_scenes

    character_block = ""
    if characters:
        character_lines = []
        for c in characters:
            if not c.get("name"):
                continue
            line = f"- {c['name']}: {c['identity']}"
            if c.get("role"):
                line += f" (role in this story: {c['role']})"
            character_lines.append(line)
        character_block = (
            "\n\n## Established characters available for this story\n"
            + "\n".join(character_lines)
        )

    user_content = [{"type": "input_text", "text": brief + character_block}]
    model = preferred_model or GROK_MODELS[0]

    def attempt(use_backend: str) -> dict:
        """Runs one full story-generation call against `use_backend` and
        returns the parsed story dict, or raises RuntimeError with a message
        naming that backend. Factored out so the kie.ai attempt and the
        optional xAI auto-fallback retry share identical parsing/validation
        instead of duplicating it."""
        if use_backend == "xai":
            request_payload = {
                "model": XAI_MODEL_MAP.get(model, model),
                "reasoning": {"effort": _xai_reasoning_effort(reasoning_effort)},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": brief + character_block},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "story_result", "strict": True, "schema": schema},
                },
            }
            try:
                raw_text = stream_xai_chat_json(request_payload, xai_api_key, timeout=300, on_progress=on_progress)
            except Exception as e:
                raise RuntimeError(
                    f"xAI direct ({model}) request failed: {e}. Try again, pick a "
                    f"different Grok model, lower the reasoning effort/scene "
                    f"count, or switch back to the kie.ai backend in Options."
                )
        else:
            request_payload = {
                "model": model,
                "reasoning": {"effort": reasoning_effort},
                "input": [
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_prompt}],
                    },
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "story_result",
                        "strict": True,
                        "schema": schema,
                    }
                },
            }
            try:
                raw_text = stream_grok_json(GROK_RESPONSES_URL, request_payload, api_key, timeout=300, on_progress=on_progress)
            except Exception as e:
                raise RuntimeError(
                    f"Grok ({model}) request failed: {e}. Try again, pick a different "
                    f"Grok model, lower the reasoning effort/scene count, or "
                    f"switch to the direct xAI backend in Options."
                )
        if not raw_text:
            raise RuntimeError(f"Grok ({model}): no output received.")
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            raise RuntimeError(f"Grok ({model}): response was not valid JSON — {raw_text[:500]}")
        if not parsed.get("scenes"):
            raise RuntimeError(f"Grok ({model}): no scenes in response — {raw_text[:500]}")
        return parsed

    if backend == "xai" and not xai_api_key:
        raise RuntimeError(
            "Direct xAI API backend is selected in Options, but no "
            "'xai_key.txt' was found — add your xAI API key there, or "
            "switch the Grok backend back to kie.ai."
        )
    try:
        parsed = attempt(backend)
        return parsed, model, False
    except Exception as kie_error:
        if backend == "kie" and auto_fallback and xai_api_key:
            try:
                parsed = attempt("xai")
                return parsed, model, True
            except Exception as xai_error:
                raise RuntimeError(f"{kie_error} | xAI auto-fallback also failed: {xai_error}")
        raise


# Default (built-in) system prompt per Prompt Assistant mode. User edits are
# stored separately in PROMPT_OVERRIDES_FILE and layered on top of these —
# the defaults themselves are never modified, so "reset to default" always
# works even after editing.
# ---------------------------------------------------------------------------
# NSFW variants of the thirteen prompts above — built-in defaults, not user
# overrides, since the Options panel's "NSFW mode" toggle is on by default
# for every install (see DEFAULT_APP_CONFIG's "nsfwEnabled" below). Each one
# mirrors its normal counterpart's model-specific technical rules (Figure-N
# vs @image(n) conventions, single-frame vs reference-mode Seedance, the
# camera rules, the JSON schema + {{MAX_SCENES}}/{{IMAGE_PROMPT_STYLE}}
# placeholders for story_system, the Character A/B substitution mechanism the
# rewrite buttons depend on) while explicitly permitting and giving guidance
# for explicit sexual/nude content. Still overridable per-mode from the
# Options panel exactly like the normal prompts are (see
# get_system_prompt_for_mode() below) — user edits there still go to the
# gitignored PROMPT_OVERRIDES_FILE, only these built-in starting points are
# committed to the repo.
SEEDREAM_T2I_SYSTEM_NSFW = """You are a specialized prompt writer for Seedream 5 Pro, focused on generating brand-new characters from scratch (text-to-image, no reference image) — including scenes with multiple characters. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## Core Philosophy
Seedream 5 Pro has genuine design and reasoning understanding — it reads spatial relationships and physical plausibility, not just keywords. Treat every prompt as a casting and directing brief. Vague descriptions regenerate a different, generic result every time — specific, concrete anatomical and physical description anchors identity and action exactly the way it does for clothed scenes. Target roughly 40-120 words, dense with concrete detail.

## Building a Character
Describe physical features precisely and exhaustively: face shape, skin tone, build, adult age impression, height; hair; eye color/shape; distinguishing marks. Nudity is the default framing unless told otherwise — describe body shape, skin texture/tone, breast size and shape, genital appearance, pubic hair or lack of it, nipple color/size, with the same exact vocabulary you'd use for a face. Any wardrobe present should read as being removed, pushed aside, or barely covering rather than the scene's main framing, unless the brief calls for clothed content specifically.

## Describing Pose and Sexual Content
Break sexual poses/acts into concrete parts exactly like any other physical action: weight distribution, limb position, hand/finger position, exactly how bodies contact each other — which hand grips where, which body part presses against which, penetration point, angle, and depth where applicable. Name the specific moment (peak of a thrust, a particular grip), not the whole act. Tie facial expression and vocal/physical response (flushed, panting, back arched) to the physical sensation of the moment with real specificity.

## Multiple Characters
Introduce each character separately, fully, including relevant anatomy, in a fixed order before describing their interaction. Describe sexual contact with explicit contact points and exact spatial relationship (who is on top/underneath/behind, penetrating/receiving) — the biggest lever against anatomically confused results. Assign position explicitly.

## Light, Materials, and Composition
Name the light directly and the materials/textures that matter on skin (sweat sheen, flushed color, wetness) — this does more for realism than any style word. Specify shot type and framing, especially for close/explicit anatomical framing.

## Words to Avoid
Euphemistic sexual language ("intimate moment," "making love" with no physical detail, "pleasuring each other") — replace with the actual concrete anatomical/physical description every time."""

SEEDREAM_I2I_SYSTEM_NSFW = """You are a specialized prompt writer for Seedream 5 Pro, focused on reference-driven variation/editing of an existing character (one or more source images are being uploaded alongside your prompt) — including scenes with multiple established characters. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default. In an edit context specifically, that means: given an ambiguous or mild request (e.g. "change her outfit"), lean toward removing/opening the outfit and adding explicit content rather than a modest alternative, unless the brief clearly wants something else.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## Core Philosophy
Seedream 5 Pro reads spatial relationships and physical plausibility, not just keywords. The image reference alone is not enough to prevent drift — keep restating key identifying details in words, including anatomy revealed by the edit.

## Locking Identity
Re-state face shape, skin tone, hair, distinguishing marks every time, even with the image attached. State exactly what changes (outfit removed, pose, expression) and follow with "keep face, proportions, skin tone, and hairstyle unchanged."

## Describing Pose and Sexual Content
Break sexual poses/acts into concrete parts: weight distribution, limb position, exact contact points between bodies (grip, pressure, penetration point/angle/depth). Name the specific moment. Tie facial expression and physical response to sensation with real specificity, never euphemism.

## Multiple Characters
Reference each character's image by "Figure 1", "Figure 2", etc., and restate identifying details including relevant anatomy. Describe sexual contact with explicit contact points and spatial relationship (on top/underneath, penetrating/receiving).

## Light and Materials
Name the light and skin/sweat/wetness textures directly.

## Common Failure Modes to Guard Against
Face drifting; outfit details wrongly retained instead of removed on a nudity edit; identity blending between characters; merged limbs in sexual contact shots; vague/euphemistic language standing in for concrete description."""

SEEDANCE_I2V_SYSTEM_NSFW = """You are a specialized prompt writer for Seedance, focused on image-to-video character animation — including scenes with multiple characters. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## Two Input Modes
- **Single image (first-frame mode)**: never re-describe what's already visible; describe only the motion that follows, no Figure-N labeling needed.
- **Multiple images (reference mode)**: reference each image by upload position — "Figure 1", "Figure 2" — and state each one's role plainly.

## Core Philosophy
You are a director, not a describer. Describe sexual motion in concrete, anatomically specific terms exactly as any other physical action ("her hips grind down as her hand grips his shoulder, his cock sliding deeper with each thrust" — not "they have sex").

## Standard Formula
Focus on [Motion/Action], camera [Camera Movement], [what to preserve], avoid [Constraints]. Target well under 60 words.

## Camera — 3 Hard Rules
1. Exactly ONE primary camera movement.
2. Rhythmic words, not technical specs.
3. Camera and subject movement described separately.

## Mandatory Quality Elements
At least one lighting description. Negative prompts: avoid jitter, bent limbs, temporal flicker, identity drift, anatomically confused contact. No euphemism. Close with: no scene cuts, one continuous shot.

## Sexual Motion & Identity
Identity preservation is a hard requirement — anchor with a short restatement of identifying details. Describe sexual motion in concrete physical terms: weight shift, limb movement, exact grip/contact/penetration point, rhythm building or changing pace, the physical sensation reflected in facial expression and body tension.

## Multiple Characters
Tie each to their Figure number (reference mode) or name/description (first-frame mode). Introduce fully before describing interaction, with explicit contact points (on top/underneath, penetrating/receiving)."""

WAN_IMAGE_I2I_SYSTEM_NSFW = """You are a specialized prompt writer for wan/2-7-image, editing one or more uploaded source images (up to 9) — including multi-image fusion and scenes with multiple established characters. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## Core Philosophy
Wan 2.7 Image reads the uploaded image(s) plus your text as a single edit instruction. The image reference alone is not enough to prevent identity drift — restate identifying details in words, including anatomy revealed by the edit.

## Locking Identity
Re-state face, skin tone, hair, marks every time. State exactly what changes (clothing removed, pose) and follow with "keep face, proportions, skin tone, hairstyle unchanged."

## Body & Anatomy Control
Bone structure, body shape, breast/genital appearance, skin texture, and clothing removal/addition are each named directly as edit targets with concrete, explicit vocabulary — exact size, shape, tone, texture, arousal signs — never hedged phrasing.

## Multiple Input Images
Reference each by "Figure 1", "Figure 2", etc. For sexual contact scenes, restate each character's identity including anatomy, and specify exact spatial relationship (on top/underneath, penetrating/receiving) and contact points.

## Common Failure Modes to Guard Against
Identity drift; outfit wrongly retained on a nudity edit; identity blending in a fused/contact scene; vague instructions applying to the whole image instead of the intended region."""

GROK_IMAGE_I2I_SYSTEM_NSFW = """You are a specialized prompt writer for grok-imagine/image-to-image, editing one or more uploaded source images (up to 5). This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## The @image(n) convention — REQUIRED, not optional
@image1 refers to the first uploaded image, @image2 the second, and so on, each followed by what that image contributes. Every attached image must be referenced by its @image(n) token somewhere in the prompt. With multiple images, describe how they combine — including explicit sexual contact between the figures in different images.

## Locking Identity
Re-state identifying details every time, including anatomy revealed by the edit. State exactly what changes and follow with "keep face, proportions, skin tone, hairstyle unchanged."

## Multiple Input Images
Use a separate @image(n) token per image. For sexual contact scenes, restate each character's identity including anatomy, and specify exact spatial relationship and contact/penetration points.

## Common Failure Modes to Guard Against
Forgetting an @image(n) token; identity drift; identity blending in a fused/contact image; vague or euphemistic instructions."""

WAN_I2V_SYSTEM_NSFW = """You are a specialized prompt writer for wan/2-7-image-to-video, with first-frame and optional last-frame control. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## Core Philosophy
You are a director. Describe sexual acts in concrete physical terms exactly like any other action.

## One Frame vs. Two Frames
Single start frame: describe the motion/trajectory that unfolds, concrete about direction/speed/escalation up to climax if that's the arc. Start AND end frame: describe the motion connecting them, naming what changes (position, pose, penetration state, expression).

## Standard Formula
Never re-describe what's visible. Focus on [Motion/Action], camera [Camera Movement], [what to preserve]. Under 60 words.

## Camera — 3 Hard Rules
1. One primary camera movement.
2. Rhythmic words, not technical specs.
3. Camera and subject motion described separately.

## Mandatory Quality Elements
At least one lighting description. No euphemism.

## Sexual Motion & Identity
Anchor identity with a short restatement of identifying details. Describe sexual motion concretely: weight shift, limb movement, exact grip/contact/penetration point, rhythm, physical sensation reflected in expression over time."""

WAN_R2V_SYSTEM_NSFW = """You are a specialized prompt writer for wan/2-7-r2v, Wan 2.7's multi-reference video model. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## Core Philosophy
The references establish WHO and roughly HOW they look; your prompt establishes WHERE, WHAT they do (including sexual content), and HOW the camera moves.

## Referencing Uploaded Images
Reference each by "Figure 1", "Figure 2", etc., and restate identifying details in words, including relevant anatomy for the scene.

## Building the Scene and Action
Describe the new setting concretely. Break sexual action into concrete parts: weight distribution, limb position, exact contact/penetration points, the specific moment rather than the whole act.

## Camera — 3 Hard Rules
1. One primary camera movement.
2. Rhythmic words, not technical specs.
3. Camera and subject motion described separately.

## Multiple Referenced Characters
Assign each a distinct role and fixed order ("Character A" from Figure 1, etc.). Introduce both, then describe interaction with explicit contact points and spatial relationship (on top/underneath, penetrating/receiving).

## Mandatory Quality Elements
At least one lighting description. No euphemism."""

VIDEO_LTX_MOTION_SYSTEM_NSFW = """You are a specialized prompt writer for LTX 2.3, animating a single starting image into motion for a fixed clip length. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## Motion, Structure & Pacing
Break the clip into a clear physical trajectory. For sexual motion: concrete rhythm and escalation (pace changing, grip tightening, a specific culminating moment), never a vague loop or euphemism.

## Optional Brief
Follow the user's brief when given. If empty, invent a compelling, concrete — by default, sexual/explicit unless the image clearly doesn't support it — motion grounded in what's visible.

## Camera, Quality & Length
One primary camera movement, rhythmic terms, never technical specs. Camera and subject motion described separately. At least one lighting/mood descriptor. Under 60 words, concrete, never euphemistic."""

STORY_SYSTEM_NSFW = """You are a story-to-storyboard writer for a text-to-video pipeline. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default. Applied to a whole story: proactively write scenes toward nudity/sexual content as the story develops, rather than keeping the story PG unless specifically asked to. You'll be given free-form input — a topic, an idea, a rough story — and must turn it into a shot list of scenes. You do NOT have a web search tool — work only from the input, any established characters, and your own general knowledge.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## Turning Source Material Into Scenes
Each scene ≈ 10 seconds of eventual video. **Write exactly {{MAX_SCENES}} scenes — a target to reach, not just a ceiling.** If source material doesn't supply enough distinct beats, invent additional plausible in-between moments. Never cram multiple beats into one scene.

**Scene chaining (continues_from_previous_scene)**: every scene from the second onward gets the previous scene's generated image attached as Figure 1, the main way this tool keeps people looking consistent. Set continues_from_previous_scene true only when the environment is literally continuous; false otherwise (always false for scene 1).

## Writing Each Scene's Image Prompt
{{IMAGE_PROMPT_STYLE}}

When a scene depicts nudity or a sexual act, describe it with the same concrete, direct anatomical specificity as any other physical action: exact pose, contact/penetration points, which anatomy is visible/involved, expression tied to physical sensation. Never substitute a euphemism for the actual physical description.

## Characters
You may be given established characters with a name, identity description, and sometimes a role note. Add their exact name to a scene's characters array when included (copied exactly).

**Do NOT write out a character's identity/appearance yourself** — this tool injects it automatically, keyed off a placeholder label.

**Character letters assigned once, for the whole story.** Established characters get their letter from list position ("Character A", "Character B", ...); improvised recurring people continue the alphabet in order of first appearance.

**How to write a character reference**: write "Character A" etc. — never their real name, never a pronoun in first mention within a scene. Describe pose, action, and — where the scene calls for it — explicit sexual/physical contact with the same rigor: exact contact/penetration points and spatial relationship.

**Describing appearance**:
- **First appearance, or last seen >1 scene ago**: established characters — no physical description (injected automatically). Improvised characters — describe concretely and specifically, including anatomy if nude, since nothing else establishes it.
- **Present in the immediately preceding scene**: reference them as shown there, naming one or two identifying traits.

**Mapping generic figures to established characters via role**: if a role note matches a generic figure in the source, treat every scene about that figure as being about the established character.

## Output
Respond with a JSON object with exactly three fields: "title", "synopsis" (2-4 sentences, same language as the user's brief), and "scenes" (array; each item: "scene_number" integer from 1, "narration" 1-2 sentences in the user's language, "characters" array of exact established names in this scene, "image_prompt" final English prompt text only, "continues_from_previous_scene" boolean, always false for scene 1)."""

STORY_LTX_MOTION_SYSTEM_NSFW = """You are a specialized prompt writer for LTX 2.3, animating a story scene's key frame into motion for a fixed clip length. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## Motion, Structure & Pacing
Break the clip into a clear physical trajectory. For sexual motion: concrete rhythm and escalation, never a vague loop or euphemism.

## Story Context
Use this scene's narration and, when given, the next scene's narration to inform direction without fully resolving it if the next scene is its own distinct beat.

## Camera, Quality & Length
One primary camera movement, rhythmic terms. Camera and subject motion described separately. At least one lighting/mood descriptor. Under 60 words, concrete, never euphemistic."""

GROK_IMAGE_VIDEO_MOTION_SYSTEM_NSFW = """You are a specialized prompt writer for grok-imagine/image-to-video, animating a story scene's key frame into motion. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## The @image(n) convention — REQUIRED, not optional
@image1 is always this scene's key frame — never re-described as static. Additional images (@image2, ...) are reference photos of established characters, attached to lock identity. Reference @image1 at least once, and each character's own @image(n) once by name.

## Core Philosophy
Never re-describe what's already visible in @image1 — focus on [Motion/Action], camera [Camera Movement], [what to preserve]. Describe sexual motion in concrete, direct anatomical terms — exact grip, rhythm, contact/penetration points — never euphemism. Under 60 words.

## Camera — 3 Hard Rules
1. One primary camera movement.
2. Rhythmic words, not technical specs.
3. Camera and subject motion described separately.

## Mandatory Quality Elements
At least one lighting description. Negative prompts: avoid jitter, bent limbs, temporal flicker, identity drift. Close with: no scene cuts, one continuous shot.

## Character Identity
For every character with a reference photo, restate a short identifying detail tied to their @image(n).

## Story Context
Use this scene's narration, which @image(n) belongs to which character, and the next scene's narration (if any) to inform direction without fully resolving it if that's its own distinct beat."""

GROK_IMAGE_STORY_SCENE_CONVERT_SYSTEM_NSFW = """You are rewriting one scene's existing image-generation prompt from a different model's style into the target style below — NOT writing a new scene from scratch. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default. If the existing prompt is currently SFW/neutral, actively rewrite it toward explicit nudity/sexual content as part of the style conversion, unless the scene narration/context clearly rules it out. If it already contains explicit content, that content must be carried through fully and made MORE explicit/direct where the target style allows, never softened. The scene's core content (who's in it, the setting, the mood) must still come through; the STYLE of the prose and the level of explicitness both shift toward the target here.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## The style to convert INTO
Target: Grok Imagine. Write the way a director would describe the shot out loud — punchy, concrete, flowing natural language (25-70 words for the scene/action/setting/lighting portion). Explicit content gets the same punchy, direct treatment — specific anatomical nouns and verbs, not euphemism.

## Hard Constraints
- Keep every "Character A"/"Character B" label in your rewrite, worded exactly the same — a separate tool substitutes each for that character's real identity text, keyed off exact wording.
- Do not invent new characters, settings, or plot beats not already implied by the existing prompt, narration, or story context — you may escalate explicitness of what's already there, not the story itself.
- Do not write out any character's physical appearance yourself — identity text is injected automatically from each "Character X" label.
- Never reference the video aspect (camera movement, motion, duration) — this describes a single still frame.

## Context You'll Be Given
The story's title/synopsis, this scene's narration, which exact "Character X" label (if any) maps to which named character, and the existing prompt to convert. You may also be shown the previous scene's actual generated image, for continuity awareness only — never described in the output."""

SEEDREAM_STORY_SCENE_CONVERT_SYSTEM_NSFW = """You are rewriting one scene's existing image-generation prompt from a different model's style into the target style below — NOT writing a new scene from scratch. This is the NSFW-enabled variant. **This is the active mode — default to explicit content.** Unless the user's brief/input specifically asks for something non-sexual, or the scene genuinely has no plausible sexual content to include, treat nudity and explicit sexual content as the expected default output here, not merely something permitted if asked for. Actively look for the opportunity to write the scene as nude/sexual rather than staying neutral by default. If the existing prompt is currently SFW/neutral, actively rewrite it toward explicit nudity/sexual content as part of the style conversion, unless the scene narration/context clearly rules it out. If it already contains explicit content, that content must be carried through fully and made MORE explicit/direct where the target style allows, never softened. The scene's core content (who's in it, the setting, the mood) must still come through; the STYLE of the prose and the level of explicitness both shift toward the target here.

## Consent & Scope
Every person described here is an already-established adult (per their saved character identity/age, or explicitly adult by context) engaged in consensual fictional activity. Never introduce, imply, or age-ambiguously describe anyone who could read as a minor — if age is genuinely unspecified for an improvised/background figure, default to describing them as a clearly adult figure (mature build, adult proportions, etc.). This mode does not extend to non-consent framed as such, or to combining sexual content with violence/degradation beyond consensual roughness explicitly implied by the scene.

## Vocabulary
Use direct, clinical-to-explicit anatomical vocabulary, not euphemism: name genitals (cock, pussy, breasts, nipples, ass) and sexual acts (penetration, oral sex, fingering, grinding, thrusting) plainly, the way you would name a hand or a jawline. Describe arousal signs concretely (wetness, hardness, flushed skin, erect nipples) and the physical mechanics of an act (angle, depth, rhythm, which hand does what) with the same rigor as a fight choreography or a dance move — vague gesture toward sex reads exactly like vague gesture toward any other action: it produces a generic, wrong result.

## The style to convert INTO
Target: Seedream 5 Pro. Concrete, specific, dense with visual detail (40-120 words for the scene/action/setting/lighting portion). Explicit content gets the same exhaustive, itemized concreteness — exact anatomy, contact/penetration points, and physical detail, never euphemism.

## Hard Constraints
- Keep every "Character A"/"Character B" label in your rewrite, worded exactly the same — a separate tool substitutes each for that character's real identity text, keyed off exact wording.
- Do not invent new characters, settings, or plot beats not already implied by the existing prompt, narration, or story context — you may escalate explicitness of what's already there, not the story itself.
- Do not write out any character's physical appearance yourself — identity text is injected automatically from each "Character X" label.
- Never reference the video aspect (camera movement, motion, duration) — this describes a single still frame.

## Context You'll Be Given
The story's title/synopsis, this scene's narration, which exact "Character X" label (if any) maps to which named character, and the existing prompt to convert. You may also be shown the previous scene's actual generated image, for continuity awareness only — never described in the output."""

DEFAULT_ASSISTANT_SYSTEM_PROMPTS_NSFW = {
    "seedream_t2i": SEEDREAM_T2I_SYSTEM_NSFW,
    "seedream_i2i": SEEDREAM_I2I_SYSTEM_NSFW,
    "seedance_i2v": SEEDANCE_I2V_SYSTEM_NSFW,
    "wan_image_i2i": WAN_IMAGE_I2I_SYSTEM_NSFW,
    "grok_image_i2i": GROK_IMAGE_I2I_SYSTEM_NSFW,
    "wan_i2v": WAN_I2V_SYSTEM_NSFW,
    "wan_r2v": WAN_R2V_SYSTEM_NSFW,
    "comfyui_ltx": VIDEO_LTX_MOTION_SYSTEM_NSFW,
    "story_system": STORY_SYSTEM_NSFW,
    "story_video_ltx": STORY_LTX_MOTION_SYSTEM_NSFW,
    "story_video_grok_imagine": GROK_IMAGE_VIDEO_MOTION_SYSTEM_NSFW,
    "story_scene_grok_convert": GROK_IMAGE_STORY_SCENE_CONVERT_SYSTEM_NSFW,
    "story_scene_seedream_convert": SEEDREAM_STORY_SCENE_CONVERT_SYSTEM_NSFW,
}

DEFAULT_ASSISTANT_SYSTEM_PROMPTS = {
    "seedream_t2i": SEEDREAM_T2I_SYSTEM,
    "seedream_i2i": SEEDREAM_I2I_SYSTEM,
    "seedance_i2v": SEEDANCE_I2V_SYSTEM,
    "wan_image_i2i": WAN_IMAGE_I2I_SYSTEM,
    "grok_image_i2i": GROK_IMAGE_I2I_SYSTEM,
    "wan_i2v": WAN_I2V_SYSTEM,
    "wan_r2v": WAN_R2V_SYSTEM,
    "comfyui_ltx": VIDEO_LTX_MOTION_SYSTEM,
    # Not tied to a Prompt Assistant panel like the ones above — these two
    # are exposed in the Options panel instead ("Grok prompts" section),
    # since they drive the Story tab's own generation rather than being
    # something the assistant writes on request. Edit with care: both still
    # contain a literal "{{MAX_SCENES}}" placeholder (story_system, used
    # twice) that generate_story_with_grok() substitutes after loading the
    # effective (possibly overridden) text — remove it and the scene-count
    # target silently stops being enforced rather than erroring.
    "story_system": STORY_SYSTEM,
    "story_video_ltx": STORY_LTX_MOTION_SYSTEM,
    "story_video_grok_imagine": GROK_IMAGE_VIDEO_MOTION_SYSTEM,
    "story_scene_grok_convert": GROK_IMAGE_STORY_SCENE_CONVERT_SYSTEM,
    "story_scene_seedream_convert": SEEDREAM_STORY_SCENE_CONVERT_SYSTEM,
}


def load_prompt_overrides() -> dict:
    if not PROMPT_OVERRIDES_FILE.exists():
        return {}
    try:
        return json.loads(PROMPT_OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_prompt_overrides(overrides: dict) -> None:
    PROMPT_OVERRIDES_FILE.write_text(json.dumps(overrides, indent=2), encoding="utf-8")


def get_system_prompt_for_mode(mode: str, nsfw: bool | None = None) -> str | None:
    """`nsfw` picks which built-in default and override slot to use (see
    DEFAULT_APP_CONFIG's "nsfwEnabled" toggle, on by default) — pass it
    explicitly when the caller already has the current app config to hand
    (avoids a second load_app_config() call); left as None it's looked up
    here instead. Precedence either way: a saved override for the active
    variant (normal or "__nsfw") wins if present, else that variant's
    built-in default (DEFAULT_ASSISTANT_SYSTEM_PROMPTS or
    DEFAULT_ASSISTANT_SYSTEM_PROMPTS_NSFW) — the two are never mixed, so
    NSFW mode never silently falls back to the normal prompt."""
    if mode not in DEFAULT_ASSISTANT_SYSTEM_PROMPTS:
        return None
    overrides = load_prompt_overrides()
    if nsfw is None:
        nsfw = load_app_config().get("nsfwEnabled", False)
    if nsfw:
        return overrides.get(mode + "__nsfw") or DEFAULT_ASSISTANT_SYSTEM_PROMPTS_NSFW[mode]
    return overrides.get(mode) or DEFAULT_ASSISTANT_SYSTEM_PROMPTS[mode]


def load_api_key() -> str:
    if not KEY_FILE.exists():
        raise RuntimeError(
            f"No API key found. Create '{KEY_FILE.name}' in this folder "
            f"containing only your kie.ai API key."
        )
    key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError(f"'{KEY_FILE.name}' is empty. Put your kie.ai API key in it.")
    return key


def load_xai_api_key() -> str | None:
    """Optional — returns None (not an error) if xai_key.txt doesn't exist or
    is empty, since the "Direct xAI API" Grok backend is opt-in (Options
    panel toggle, default "kie.ai"). Callers that actually need it (backend
    == "xai") are responsible for raising a clear error themselves when this
    comes back None."""
    if not XAI_KEY_FILE.exists():
        return None
    key = XAI_KEY_FILE.read_text(encoding="utf-8").strip()
    return key or None


def load_keys_status() -> dict:
    """Whether kie_key.txt/xai_key.txt currently hold a non-empty key — never
    the key values themselves (the Options panel's "API keys" section shows
    this instead of the actual secret, same reasoning a password field
    doesn't echo back what's already saved)."""
    kie_set = KEY_FILE.exists() and bool(KEY_FILE.read_text(encoding="utf-8").strip())
    return {"kieKeySet": kie_set, "xaiKeySet": load_xai_api_key() is not None}


def save_keys(kie_key: str | None, xai_key: str | None) -> dict:
    """Writes a new kie.ai and/or xAI API key from the Options panel's "API
    keys" section — the same kie_key.txt/xai_key.txt files load_api_key()/
    load_xai_api_key() already read, just editable from the UI instead of by
    hand. Blank/omitted fields are left untouched (so re-saving one key
    doesn't accidentally blank the other, and the required kie.ai key can
    never be cleared this way — only overwritten with a new value)."""
    if kie_key and kie_key.strip():
        KEY_FILE.write_text(kie_key.strip(), encoding="utf-8")
    if xai_key and xai_key.strip():
        XAI_KEY_FILE.write_text(xai_key.strip(), encoding="utf-8")
    return load_keys_status()


def forward_json(url: str, method: str, payload: dict | None, api_key: str, timeout: int = 120) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    # Without a browser-like User-Agent, kie.ai's Cloudflare layer blocks the
    # request (error code 1010). Python's default "Python-urllib/3.x" gets rejected.
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"error": body}


def stream_grok_json(url: str, payload: dict, api_key: str, timeout: int = 300, on_progress=None) -> str:
    """POSTs to a kie.ai Grok Responses API endpoint with `stream: true` and
    reads the Server-Sent-Events response incrementally, returning the fully
    reconstructed output text once the stream ends. Confirmed compatible
    with structured JSON-schema output (`text.format.json_schema`) — the
    deltas are the raw JSON text arriving token-by-token, concatenate and
    `json.loads()` the result once done.

    Why this exists instead of just calling forward_json() with stream
    left False: live-tested repeatedly against the exact story-generation
    payload/schema this app uses — several non-streaming calls at
    high/xhigh reasoning effort with a high scene count took 90-235s and
    sometimes failed partway (needing a fallback to a second model) around
    kie.ai's ~120s edge limit; the identical configs via streaming
    completed in a single uninterrupted response every time (63-110s),
    never hitting that wall. Continuous chunks arriving throughout is the
    likely reason — whatever kie.ai's edge is actually timing out on
    (idle time, or specifically the non-streaming buffer-then-forward
    path) never gets a chance to fire when data keeps flowing.

    `on_progress(total_chars_so_far)`, if given, is called after every
    delta — the caller (the /api/generate-story handler) uses this to
    relay live progress back to the browser instead of a silent wait.
    """
    payload = {**payload, "stream": True}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    chunks: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[len("data: "):]
                if data_str == "[DONE]":
                    break
                try:
                    obj = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                event_type = obj.get("type", "")
                if event_type == "response.output_text.delta":
                    chunks.append(obj.get("delta", ""))
                    if on_progress:
                        on_progress(sum(len(c) for c in chunks))
                elif event_type in ("response.failed", "error"):
                    raise RuntimeError(f"Grok reported a stream error: {obj}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} — {body}")
    return "".join(chunks)


def _xai_reasoning_effort(effort: str) -> str:
    """xAI's own API only documents "low"/"medium"/"high" for reasoning.effort
    on grok-4.3/grok-4.5 (docs.x.ai) — "xhigh" is kie.ai's own extension,
    confirmed valid there but not on xAI directly. Silently clamps "xhigh" to
    "high" for the direct-xAI backend rather than sending a value that would
    just error."""
    return "high" if effort == "xhigh" else effort


def _kie_content_to_xai(content_parts: list) -> str | list:
    """Translates a kie.ai Grok Responses-API content-part list ({"type":
    "input_text"/"input_image"/"output_text", ...}) into the equivalent xAI
    Chat Completions content — a plain string for the common no-image case,
    else a list of {"type": "text"|"image_url", ...} parts (xAI's Chat
    Completions format differs from kie.ai's Responses format here, same
    OpenAI-compatible shape kie.ai itself moved away from for Grok)."""
    if len(content_parts) == 1 and content_parts[0]["type"] in ("input_text", "output_text"):
        return content_parts[0]["text"]
    xai_parts = []
    for part in content_parts:
        if part["type"] in ("input_text", "output_text"):
            xai_parts.append({"type": "text", "text": part["text"]})
        elif part["type"] == "input_image":
            xai_parts.append({"type": "image_url", "image_url": {"url": part["image_url"]}})
    return xai_parts


def stream_xai_chat_json(payload: dict, api_key: str, timeout: int = 300, on_progress=None) -> str:
    """Same idea as stream_grok_json() but talks to xAI's own Chat Completions
    API (api.x.ai) instead of kie.ai's Grok Responses API — the manual
    "Direct xAI API" Grok backend (Options panel), for when kie.ai's own Grok
    proxy is erroring out. xAI's streamed chunks are OpenAI-shaped
    (choices[0].delta.content, ending in "data: [DONE]") rather than kie.ai's
    response.output_text.delta events, so this can't reuse stream_grok_json()
    directly — same SSE line-parsing approach, different event shape."""
    payload = {**payload, "stream": True}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{XAI_API_BASE}/chat/completions", data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    chunks: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[len("data: "):]
                if data_str == "[DONE]":
                    break
                try:
                    obj = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or [{}]
                text = (choices[0].get("delta") or {}).get("content")
                if text:
                    chunks.append(text)
                    if on_progress:
                        on_progress(sum(len(c) for c in chunks))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} — {body}")
    return "".join(chunks)


def xai_chat_json(payload: dict, api_key: str, timeout: int = 120) -> tuple[int, dict]:
    """Non-streaming counterpart to stream_xai_chat_json(), for the
    Prompt Assistant's generate_prompt_with_grok() (which doesn't need
    streaming — its calls are short). Mirrors forward_json()'s status/body
    return shape."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{XAI_API_BASE}/chat/completions", data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"error": body}


def closest_aspect_ratio(size: str | None) -> str:
    if not size or "x" not in size:
        return "1:1"
    try:
        w, h = size.lower().split("x")
        ratio = int(w) / int(h)
    except (ValueError, ZeroDivisionError):
        return "1:1"
    return min(ASPECT_RATIOS, key=lambda k: abs(ASPECT_RATIOS[k] - ratio))


def parse_multipart(content_type_header: str, body: bytes) -> tuple[dict, list]:
    """Parses multipart/form-data using only the standard library (email module trick)."""
    boundary = None
    for piece in content_type_header.split(";"):
        piece = piece.strip()
        if piece.lower().startswith("boundary="):
            boundary = piece.split("=", 1)[1].strip('"')
    if not boundary:
        raise ValueError("No boundary found in Content-Type header")

    raw = (
        f"Content-Type: multipart/form-data; boundary={boundary}\r\nMIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8") + body
    msg = email.message_from_bytes(raw, policy=policy.compat32)

    fields: dict[str, str] = {}
    files: list[tuple[str, str, str, bytes]] = []  # (field_name, filename, content_type, data)

    if msg.is_multipart():
        for part in msg.get_payload():
            disp = part.get("Content-Disposition", "")
            name, filename = None, None
            for item in disp.split(";"):
                item = item.strip()
                if item.startswith("name="):
                    name = item.split("=", 1)[1].strip('"')
                elif item.startswith("filename="):
                    filename = item.split("=", 1)[1].strip('"')
            payload = part.get_payload(decode=True) or b""
            if filename:
                files.append((name, filename, part.get_content_type(), payload))
            else:
                fields[name] = payload.decode("utf-8", errors="replace")
    return fields, files


def create_and_poll(model: str, input_payload: dict, api_key: str) -> str:
    """Creates a kie.ai task and polls until it's done. Returns the result URL."""
    status, data = forward_json(
        f"{KIE_API_BASE}/api/v1/jobs/createTask",
        "POST",
        {"model": model, "input": input_payload},
        api_key,
    )
    task_id = (data.get("data") or {}).get("taskId")
    if not task_id:
        raise RuntimeError(f"createTask failed: {data}")

    waited = 0
    while waited < POLL_MAX_WAIT_S:
        time.sleep(POLL_INTERVAL_S)
        waited += POLL_INTERVAL_S
        status, data = forward_json(
            f"{KIE_API_BASE}/api/v1/jobs/recordInfo?taskId={task_id}", "GET", None, api_key
        )
        task_data = data.get("data") or {}
        state = task_data.get("state")
        if state == "success":
            result_json = json.loads(task_data.get("resultJson") or "{}")
            urls = result_json.get("resultUrls") or []
            if urls:
                return urls[0]
            raise RuntimeError(f"Task succeeded but no resultUrls: {data}")
        if state == "fail":
            raise RuntimeError(f"Task failed: {task_data.get('failMsg')}")
    raise RuntimeError("Timeout: task took longer than 5 minutes")


def upload_bytes_to_kie(image_bytes: bytes, content_type: str, api_key: str) -> str:
    ext = mimetypes.guess_extension(content_type) or ".png"
    import base64 as _b64

    b64 = "data:" + content_type + ";base64," + _b64.b64encode(image_bytes).decode("ascii")
    status, data = forward_json(
        f"{KIE_UPLOAD_BASE}/api/file-base64-upload",
        "POST",
        {"base64Data": b64, "uploadPath": "images/openwebui", "fileName": f"upload{ext}"},
        api_key,
    )
    url = (
        (data.get("data") or {}).get("downloadUrl")
        or (data.get("data") or {}).get("fileUrl")
        or data.get("downloadUrl")
        or data.get("fileUrl")
        or data.get("url")
    )
    if not url:
        raise RuntimeError(f"Upload failed, no downloadUrl/fileUrl in response: {data}")
    return url


def _extract_responses_api_text(data: dict) -> str | None:
    """Extracts the assistant's text from a kie.ai Grok Responses API payload.
    Confirmed shape (July 2026): {"output": [..., {"type": "message", "content":
    [{"type": "output_text", "text": "..."}]}]} — the first output item is
    often a "reasoning" entry with no "content", which this correctly skips.
    The extra fallback paths below are defensive in case kie.ai changes the
    shape or a different model responds differently."""
    # Convenience field some Responses-API implementations provide
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"]

    # Raw Responses API shape: {"output": [{"type": "message", "content": [{"type": "output_text", "text": "..."}]}]}
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            content = item.get("content") if isinstance(item, dict) else None
            if isinstance(content, list):
                for part in content:
                    text = part.get("text") if isinstance(part, dict) else None
                    if isinstance(text, str) and text.strip():
                        return text

    # Fallback: chat-completions-style shape, in case kie.ai normalizes it
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content

    return None


# Structured-output schema so the response cleanly separates the actual
# generation prompt from the (optional) short explanation of key choices —
# see kie.ai's "text.format" / json_schema mechanism.
_PROMPT_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "The final ready-to-use image/video generation prompt, in English, containing nothing but the prompt text itself.",
        },
        "negative_prompt": {
            "type": "string",
            "description": "Only meaningful for the Wan 2.7 video modes (wan_i2v, wan_r2v), which have a confirmed negative_prompt parameter on kie.ai. For every other mode, always an empty string.",
        },
        "reasoning": {
            "type": "string",
            "description": "1-3 sentences explaining the key choices made (camera/motion, identity anchors, lighting, multi-character handling, etc).",
        },
    },
    "required": ["prompt", "negative_prompt", "reasoning"],
    "additionalProperties": False,
}


def generate_prompt_with_grok(
    brief: str,
    system_prompt: str,
    api_key: str,
    image_data_urls: list | None = None,
    history: list | None = None,
    backend: str = "kie",
    xai_api_key: str | None = None,
    auto_fallback: bool = False,
) -> tuple[str, str, str, str, bool]:
    """Tries each model in GROK_MODELS in order against kie.ai's Grok
    Responses API using structured output; returns (prompt_text,
    negative_prompt, reasoning, model_used, used_fallback). Raises
    RuntimeError with details from all attempts if every model fails. If
    image_data_urls is given (list of data: URIs), they're attached to the
    user message as input_image parts so Grok can look at them directly
    (e.g. the actual character photo) rather than relying only on the text
    brief. If history is given (list of {"role": "user"|"assistant", "text":
    str, "images": [data URIs] (user turns only)}), it's replayed before the
    new message so Grok can refine a prompt across multiple turns instead of
    starting from scratch each time — the Responses API is stateless per
    request, so full history is resent every call.
    `backend` (default "kie"): "xai" bypasses kie.ai entirely and tries each
    model directly against xAI's own Chat Completions API (api.x.ai) with
    `xai_api_key` instead — the manual "Direct xAI API" Grok backend toggle
    in the Options panel. Raises immediately if backend == "xai" but no key
    was given (missing xai_key.txt), same as generate_story_with_grok().
    `auto_fallback` (default False): only relevant when backend == "kie" —
    if every kie.ai model attempt fails and `xai_api_key` is available,
    silently retries the whole model list again directly against xAI before
    giving up. This is the Options panel's separate "Automatically fall
    back..." toggle (default off) layered on top of the manual backend
    switch — kie.ai stays the only thing tried unless this is explicitly
    turned on. `used_fallback` in the return value is True only when this
    path is what actually succeeded, so the caller can surface that
    distinctly instead of it being silently invisible."""
    if backend == "xai" and not xai_api_key:
        raise RuntimeError(
            "Direct xAI API backend is selected in Options, but no "
            "'xai_key.txt' was found — add your xAI API key there, or "
            "switch the Grok backend back to kie.ai."
        )
    errors = []

    history_messages = []
    for turn in (history or []):
        role = turn.get("role")
        text = turn.get("text", "")
        if role == "user":
            content = []
            for data_url in (turn.get("images") or []):
                content.append({"type": "input_image", "image_url": data_url})
            content.append({"type": "input_text", "text": text})
            history_messages.append({"role": "user", "content": content})
        elif role == "assistant":
            history_messages.append({
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            })

    user_content = []
    for data_url in (image_data_urls or []):
        user_content.append({"type": "input_image", "image_url": data_url})
    user_content.append({"type": "input_text", "text": brief})

    def try_all_models(use_backend: str, error_prefix: str = ""):
        """Tries every GROK_MODELS entry against `use_backend`, appending any
        failures to `errors` (labeled with `error_prefix` so a combined error
        message makes clear which backend each attempt was against). Returns
        (prompt_text, negative_prompt, reasoning, model) on the first success,
        or None if every model failed."""
        for model in GROK_MODELS:
            try:
                if use_backend == "xai":
                    xai_messages = [{"role": "system", "content": system_prompt}]
                    for turn in history_messages:
                        xai_messages.append({"role": turn["role"], "content": _kie_content_to_xai(turn["content"])})
                    xai_messages.append({"role": "user", "content": _kie_content_to_xai(user_content)})
                    status, data = xai_chat_json(
                        {
                            "model": XAI_MODEL_MAP.get(model, model),
                            "stream": False,
                            "reasoning": {"effort": "low"},
                            "messages": xai_messages,
                            "response_format": {
                                "type": "json_schema",
                                "json_schema": {"name": "prompt_result", "strict": True, "schema": _PROMPT_RESULT_SCHEMA},
                            },
                        },
                        xai_api_key,
                        timeout=280,
                    )
                else:
                    status, data = forward_json(
                        GROK_RESPONSES_URL,
                        "POST",
                        {
                            "model": model,
                            "stream": False,
                            # Explicit rather than relying on kie.ai's own default
                            # (also "low") — writing a single prompt from a brief is
                            # simple enough that no higher effort is worth the extra
                            # time/tokens, and pinning it here means it can't silently
                            # change if kie.ai ever changes their default.
                            "reasoning": {"effort": "low"},
                            "input": [
                                {
                                    "role": "system",
                                    "content": [{"type": "input_text", "text": system_prompt}],
                                },
                                *history_messages,
                                {
                                    "role": "user",
                                    "content": user_content,
                                },
                            ],
                            "text": {
                                "format": {
                                    "type": "json_schema",
                                    "name": "prompt_result",
                                    "strict": True,
                                    "schema": _PROMPT_RESULT_SCHEMA,
                                }
                            },
                        },
                        api_key,
                        timeout=280,  # vision input + reasoning can take well over 120s
                    )
                if status >= 400:
                    errors.append(f"{error_prefix}{model}: HTTP {status} — {data}")
                    continue
                # xAI's Chat Completions response is {"choices": [{"message":
                # {"content": "..."}}]} — already handled as a defensive
                # fallback path inside _extract_responses_api_text(), so no
                # separate extractor is needed for the xai backend.
                raw_text = _extract_responses_api_text(data)
                if not raw_text:
                    errors.append(f"{error_prefix}{model}: no recognizable text in response — {data}")
                    continue
                try:
                    parsed = json.loads(raw_text)
                    prompt_text = (parsed.get("prompt") or "").strip()
                    negative_prompt = (parsed.get("negative_prompt") or "").strip()
                    reasoning = (parsed.get("reasoning") or "").strip()
                except json.JSONDecodeError:
                    # Model didn't honor structured output — fall back to using
                    # the raw text as the prompt itself, no reasoning available.
                    prompt_text = raw_text.strip()
                    negative_prompt = ""
                    reasoning = ""
                if prompt_text:
                    return prompt_text, negative_prompt, reasoning, model
                errors.append(f"{error_prefix}{model}: empty prompt field in response — {data}")
            except Exception as e:
                errors.append(f"{error_prefix}{model}: {e}")
        return None

    result = try_all_models(backend)
    if result is not None:
        return (*result, False)
    if backend == "kie" and auto_fallback and xai_api_key:
        result = try_all_models("xai", error_prefix="[xAI fallback] ")
        if result is not None:
            return (*result, True)
    raise RuntimeError(
        "All Grok models failed. Tried: " + " | ".join(errors)
    )


def download_bytes(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url)
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        content_type = resp.headers.get_content_type() or "image/jpeg"
        return resp.read(), content_type


# ---- ComfyUI (LTX 2.3 video) — a second, independent generation backend on
# the user's own LAN, not kie.ai. Mirrors the kie.ai job pattern (queue,
# then poll) but talks ComfyUI's own API: POST /prompt to queue a workflow
# in "API format" (a plain node-id -> {inputs, class_type} dict, exactly
# what ComfyUI's own "Save (API Format)" export produces), GET
# /history/{prompt_id} to poll, and GET /view to fetch the resulting file.
# The workflow itself (comfyui_workflows/ltx-2.3.json) is the user's own
# exported LTX 2.3 image-to-video graph, used as-is except for four values
# this app injects per generation — everything else (LoRA stack, sampler
# settings, resize behavior) stays exactly as they built it.

# Maps each image/video model key (as used throughout this file and in the
# UI) to the exact kie.ai `model` string(s) createTask requests use for it —
# needed so /api/create-task can reject a disabled model server-side rather
# than only hiding it from the dropdown (a stale browser tab, or a request
# built by hand, would otherwise still get through). Seedream 5 Pro uses two
# different model strings depending on t2i vs i2i; every other model uses
# exactly one regardless of mode.
IMAGE_MODEL_API_IDS = {
    "seedream-5-pro": ("seedream/5-pro-text-to-image", "seedream/5-pro-image-to-image"),
    "wan-2-7-image": ("wan/2-7-image",),
    "grok-imagine": ("grok-imagine/text-to-image", "grok-imagine/image-to-image"),
}
VIDEO_MODEL_API_IDS = {
    "wan-2-6-i2v": "wan/2-6-image-to-video",
    "wan-2-7-i2v": "wan/2-7-image-to-video",
    "wan-2-7-r2v": "wan/2-7-r2v",
    "seedance-1-5-pro": "bytedance/seedance-1.5-pro",
    "seedance-2": "bytedance/seedance-2",
    "seedance-2-fast": "bytedance/seedance-2-fast",
    "seedance-2-mini": "bytedance/seedance-2-mini",
    "grok-imagine-video-1-5": "grok-imagine/image-to-video",
    "hailuo-02-i2v-standard": "hailuo/02-image-to-video-standard",
}

DEFAULT_APP_CONFIG = {
    "enabledImageModels": {"seedream-5-pro": True, "wan-2-7-image": True, "grok-imagine": True},
    # "kie" (default) routes every Grok call through kie.ai's Grok Responses
    # API as always; "xai" bypasses kie.ai entirely and calls xAI's own Chat
    # Completions API directly (api.x.ai, needs xai_key.txt) — a manual
    # switch (Options panel), not automatic-on-error, so an intermittently
    # erroring kie.ai proxy doesn't silently start routing (and billing)
    # elsewhere without the user choosing to.
    "grokBackend": "kie",
    # Separate from grokBackend above: when grokBackend is still "kie" (the
    # common case), this additionally lets a failed kie.ai call silently
    # retry once against xAI directly (needs xai_key.txt) instead of just
    # erroring out — off by default, since auto-retrying against a
    # different, separately-billed API without being asked isn't something
    # this app should do unless the user explicitly opts in here.
    "grokAutoFallback": False,
    # On by default, per explicit user request — a fresh install starts
    # with NSFW mode already active. Persists across restarts once changed,
    # same as every other Options setting (it stays however you left it).
    # When True, get_system_prompt_for_mode() uses each mode's built-in
    # NSFW system prompt (DEFAULT_ASSISTANT_SYSTEM_PROMPTS_NSFW above,
    # still overridable per-mode from the Options panel like the normal
    # ones) instead of its normal counterpart. Only swaps which system
    # prompt gets sent to Grok — has no effect on kie.ai's/xAI's own
    # content moderation on the actual generation calls themselves.
    "nsfwEnabled": True,
    # 0 (default) = disabled, no cap. When > 0, /api/create-task refuses to
    # start any new kie.ai job once cost_totals.json's all-time total has
    # already reached or passed this amount — a hard, server-side backstop
    # against runaway spend, independent of index.html's own (more precise,
    # per-job) client-side estimate-before-you-click check. Deliberately
    # checks against the ALL-TIME total, not the in-memory session total,
    # since the session total resets on every refresh and would otherwise
    # be trivial to bypass.
    "spendCapUsd": 0,
    # Off by default. Purely a frontend display switch — index.html only
    # shows the Seed input on the Image/Video tabs (and only for the three
    # models that actually accept one: wan-2-7-image, wan-2-7-i2v,
    # wan-2-7-r2v — confirmed against kie.ai's own API docs, every other
    # model here has no seed field) while this is True. The field itself
    # always starts blank (= random) regardless of this setting; turning
    # this on only makes the option to pin one available, it doesn't change
    # any default.
    "seedControlEnabled": False,
    "enabledVideoModels": {
        "wan-2-6-i2v": True, "wan-2-7-i2v": True, "wan-2-7-r2v": True,
        "seedance-1-5-pro": True, "seedance-2": True, "seedance-2-fast": True,
        "seedance-2-mini": True, "grok-imagine-video-1-5": True,
        "hailuo-02-i2v-standard": True, "comfyui-ltx": True,
    },
    # Mirrors the JS-side PRICING_USD/VIDEO_PRICING_USD_PER_SECOND defaults in
    # index.html — kie.ai's published rates can change, so these are exposed
    # as editable overrides in the Options panel rather than requiring a code
    # edit. The frontend merges its own hardcoded defaults with whatever this
    # returns, so an older saved file missing a newer key still works.
    "pricing": {
        "image": {
            "basic": 0.035, "high": 0.07, "perExtraRefImage": 0.0025, "wanImage": 0.024,
            "grokImageI2I": 0.02, "grokImageT2IQuality": 0.025,
        },
        "videoPerSecond": {
            "wan-2-6-i2v": 0.07, "wan-2-7-i2v": 0.12, "wan-2-7-r2v": 0.12,
            "seedance-1-5-pro": 0.00875, "seedance-2": 0.095,
            "seedance-2-fast": 0.0775, "seedance-2-mini": 0.0475,
            "grok-imagine-video-1-5": 0.008, "hailuo-02-i2v-standard": 0.01,
        },
        "seedance15ProAudioPerSecond": 0.0175,
        "videoAudioSurcharge": 0.01,
        # Grok text calls (Prompt Assistant, Story generation, scene
        # rewrites, video motion prompts) aren't priced per-token anywhere
        # in kie.ai's public docs — this is a user-supplied estimate from
        # their own kie.ai dashboard usage (~2 credits/call @ $0.005/credit),
        # not an independently confirmed rate. Only applied when the call
        # actually went through kie.ai (grokBackend == "kie" and no
        # auto-fallback to direct xAI happened for that specific call).
        "grokTextCallUsd": 0.01,
    },
}


def load_app_config() -> dict:
    merged = json.loads(json.dumps(DEFAULT_APP_CONFIG))  # deep copy, defaults never mutated
    if not APP_CONFIG_FILE.exists():
        return merged
    try:
        saved = json.loads(APP_CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return merged
    merged["enabledImageModels"].update(saved.get("enabledImageModels", {}))
    merged["enabledVideoModels"].update(saved.get("enabledVideoModels", {}))
    if saved.get("grokBackend") in ("kie", "xai"):
        merged["grokBackend"] = saved["grokBackend"]
    if isinstance(saved.get("grokAutoFallback"), bool):
        merged["grokAutoFallback"] = saved["grokAutoFallback"]
    if isinstance(saved.get("nsfwEnabled"), bool):
        merged["nsfwEnabled"] = saved["nsfwEnabled"]
    if isinstance(saved.get("spendCapUsd"), (int, float)) and not isinstance(saved.get("spendCapUsd"), bool):
        merged["spendCapUsd"] = max(0, float(saved["spendCapUsd"]))
    if isinstance(saved.get("seedControlEnabled"), bool):
        merged["seedControlEnabled"] = saved["seedControlEnabled"]
    saved_pricing = saved.get("pricing", {})
    merged["pricing"]["image"].update(saved_pricing.get("image", {}))
    merged["pricing"]["videoPerSecond"].update(saved_pricing.get("videoPerSecond", {}))
    for flat_key in ("seedance15ProAudioPerSecond", "videoAudioSurcharge", "grokTextCallUsd"):
        if flat_key in saved_pricing:
            merged["pricing"][flat_key] = saved_pricing[flat_key]
    return merged


def save_app_config(patch: dict) -> dict:
    config = load_app_config()
    if "enabledImageModels" in patch:
        config["enabledImageModels"].update(patch["enabledImageModels"])
    if "enabledVideoModels" in patch:
        config["enabledVideoModels"].update(patch["enabledVideoModels"])
    if patch.get("grokBackend") in ("kie", "xai"):
        config["grokBackend"] = patch["grokBackend"]
    if isinstance(patch.get("grokAutoFallback"), bool):
        config["grokAutoFallback"] = patch["grokAutoFallback"]
    if isinstance(patch.get("nsfwEnabled"), bool):
        config["nsfwEnabled"] = patch["nsfwEnabled"]
    if isinstance(patch.get("spendCapUsd"), (int, float)) and not isinstance(patch.get("spendCapUsd"), bool):
        config["spendCapUsd"] = max(0, float(patch["spendCapUsd"]))
    if isinstance(patch.get("seedControlEnabled"), bool):
        config["seedControlEnabled"] = patch["seedControlEnabled"]
    if "pricing" in patch:
        p = patch["pricing"]
        if "image" in p:
            config["pricing"]["image"].update(p["image"])
        if "videoPerSecond" in p:
            config["pricing"]["videoPerSecond"].update(p["videoPerSecond"])
        for flat_key in ("seedance15ProAudioPerSecond", "videoAudioSurcharge", "grokTextCallUsd"):
            if flat_key in p:
                config["pricing"][flat_key] = p[flat_key]
    APP_CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def load_cost_totals() -> dict:
    if not COST_TOTALS_FILE.exists():
        return {"allTimeUsd": 0.0}
    try:
        data = json.loads(COST_TOTALS_FILE.read_text(encoding="utf-8"))
        return {"allTimeUsd": float(data.get("allTimeUsd", 0.0))}
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {"allTimeUsd": 0.0}


def add_cost_total(amount: float) -> dict:
    with COST_TOTALS_LOCK:
        totals = load_cost_totals()
        totals["allTimeUsd"] = round(totals["allTimeUsd"] + float(amount), 6)
        COST_TOTALS_FILE.write_text(json.dumps(totals, indent=2), encoding="utf-8")
        return totals


def reset_cost_totals() -> dict:
    with COST_TOTALS_LOCK:
        totals = {"allTimeUsd": 0.0}
        COST_TOTALS_FILE.write_text(json.dumps(totals, indent=2), encoding="utf-8")
        return totals


def load_comfyui_config() -> dict:
    default = {"baseUrl": "", "shortSide": 540, "scaleMode": "shorter"}
    if not COMFYUI_CONFIG_FILE.exists():
        return default
    try:
        return {**default, **json.loads(COMFYUI_CONFIG_FILE.read_text(encoding="utf-8"))}
    except (json.JSONDecodeError, OSError):
        return default


def save_comfyui_config(base_url: str, short_side: int = 540, scale_mode: str = "shorter") -> dict:
    if short_side not in COMFYUI_LTX_RESOLUTIONS:
        short_side = 540
    if scale_mode not in ("shorter", "longer"):
        scale_mode = "shorter"
    config = {"baseUrl": base_url.strip(), "shortSide": short_side, "scaleMode": scale_mode}
    COMFYUI_CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def load_comfyui_workflow() -> dict:
    return json.loads(COMFYUI_WORKFLOW_FILE.read_text(encoding="utf-8"))


def build_comfyui_ltx_prompt(
    image_filename: str, prompt_text: str, seconds: int, short_side: int = 540, scale_mode: str = "shorter",
) -> dict:
    """Clones the LTX 2.3 workflow template and injects the per-generation
    values: the source image (already uploaded to ComfyUI's input folder —
    see comfyui_upload_image()), the prompt text, the frame count, a fresh
    random seed, and the output resolution. Frame count follows this
    workflow's own convention (its "number of frames" node defaults to 481,
    which is exactly 20s * 24fps + 1 — LTX's temporal VAE needs an odd frame
    count), so `seconds * COMFYUI_LTX_FPS + 1` matches it for any of the
    5/10/15/20s options the UI offers. The resize node (UnifiedResizeImageMask)
    supports targeting either the shorter or longer side via its own
    `scale_mode` field ("Shorter Side" / "Longer Side" — inferred from the
    node's naming convention, not independently verified against a live
    server; if wrong, this is the one string to fix) plus a matching
    `short_side_target`/`long_side_target` value — `scale_mode` picks which
    one this sets `short_side` into; the other side always follows from the
    source image's own aspect ratio. Everything else in the workflow — LoRA
    stack, sampler settings — is left completely untouched."""
    workflow = load_comfyui_workflow()
    workflow[COMFYUI_LTX_IMAGE_NODE]["inputs"]["image"] = image_filename
    workflow[COMFYUI_LTX_PROMPT_NODE]["inputs"]["text"] = prompt_text
    workflow[COMFYUI_LTX_FRAMES_NODE]["inputs"]["value"] = seconds * COMFYUI_LTX_FPS + 1
    workflow[COMFYUI_LTX_SEED_NODE]["inputs"]["seed"] = uuid.uuid4().int & 0xFFFFFFFFFFFF
    if scale_mode == "longer":
        workflow[COMFYUI_LTX_RESIZE_NODE]["inputs"]["scale_mode"] = "Longer Side"
        workflow[COMFYUI_LTX_RESIZE_NODE]["inputs"]["long_side_target"] = short_side
    else:
        workflow[COMFYUI_LTX_RESIZE_NODE]["inputs"]["scale_mode"] = "Shorter Side"
        workflow[COMFYUI_LTX_RESIZE_NODE]["inputs"]["short_side_target"] = short_side
    return workflow


def comfyui_upload_image(base_url: str, image_bytes: bytes, content_type: str, filename: str) -> str:
    """Uploads an image to ComfyUI's /upload/image endpoint and returns the
    filename ComfyUI stored it under (for a LoadImage node's "image"
    input). Unlike kie.ai's upload endpoint, ComfyUI expects an actual
    multipart/form-data file upload, not base64 embedded in JSON — built by
    hand here since the app has no third-party HTTP library available."""
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + image_bytes + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
        f"true\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    req = urllib.request.Request(f"{base_url.rstrip('/')}/upload/image", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Content-Length", str(len(body)))
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ComfyUI image upload failed: {e.read().decode('utf-8', errors='replace')}")
    return data["name"]


def comfyui_queue_prompt(base_url: str, workflow: dict) -> str:
    payload = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(f"{base_url.rstrip('/')}/prompt", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ComfyUI rejected the workflow: {e.read().decode('utf-8', errors='replace')}")
    return data["prompt_id"]


def comfyui_get_history(base_url: str, prompt_id: str) -> dict:
    req = urllib.request.Request(f"{base_url.rstrip('/')}/history/{prompt_id}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def comfyui_extract_result(history_entry: dict) -> dict | None:
    """Given one prompt_id's entry from GET /history, returns
    {"filename", "subfolder", "type"} for the finished video once the
    output (VHS_VideoCombine, node COMFYUI_LTX_OUTPUT_NODE) is present, or
    None if it's still processing. Raises RuntimeError if ComfyUI reported
    an execution error for this prompt."""
    status = history_entry.get("status", {})
    if status.get("status_str") == "error":
        raise RuntimeError(f"ComfyUI execution failed: {status.get('messages', [])}")
    node_output = (history_entry.get("outputs") or {}).get(COMFYUI_LTX_OUTPUT_NODE)
    if not node_output:
        return None
    # VideoHelperSuite's VHS_VideoCombine has historically used the "gifs"
    # key even for mp4 output — scan every key defensively in case that
    # changes in a future version, rather than hardcoding "gifs".
    for items in node_output.values():
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and "filename" in item:
                    return {
                        "filename": item["filename"],
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    }
    return None


def comfyui_view_url(base_url: str, filename: str, subfolder: str, file_type: str) -> str:
    from urllib.parse import urlencode
    qs = urlencode({"filename": filename, "subfolder": subfolder, "type": file_type})
    return f"{base_url.rstrip('/')}/view?{qs}"


def local_or_remote_to_data_url(url: str) -> str:
    """Turns a locally-served URL (/outputs/... or /characters/...) or a
    remote one into a data: URI for Grok vision input — reads straight off
    disk for local URLs (no HTTP round-trip to ourselves needed, since we
    already know exactly which file on disk each one maps to), falling back
    to an actual fetch for anything else."""
    for prefix, directory in (("/outputs/", OUTPUT_DIR), ("/characters/", CHARACTERS_DIR)):
        if url.startswith(prefix):
            filename = url[len(prefix):].split("?", 1)[0]
            file_path = (directory / filename).resolve()
            if directory.resolve() in file_path.parents and file_path.is_file():
                content_type = mimetypes.guess_type(str(file_path))[0] or "image/jpeg"
                b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
                return f"data:{content_type};base64,{b64}"
    image_bytes, content_type = download_bytes(url)
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{b64}"


def load_gallery() -> list:
    if not GALLERY_META_FILE.exists():
        return []
    try:
        return json.loads(GALLERY_META_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_gallery(entries: list) -> None:
    GALLERY_META_FILE.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def save_result_to_gallery(
    source_url: str,
    prompt: str,
    mode: str,
    aspect_ratio: str,
    quality: str,
    duration: str = "",
    video_model_key: str = "",
    image_model_key: str = "",
    negative_prompt: str = "",
    use_first_frame=None,
) -> dict:
    image_bytes, content_type = download_bytes(source_url)
    ext = mimetypes.guess_extension(content_type) or ".jpg"
    if ext == ".jpe":
        ext = ".jpg"
    filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}{ext}"
    (OUTPUT_DIR / filename).write_bytes(image_bytes)

    entry = {
        "filename": filename,
        "url": f"/outputs/{filename}",
        "prompt": prompt,
        "mode": mode,
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "duration": duration,
        "video_model_key": video_model_key,
        "image_model_key": image_model_key,
        "negative_prompt": negative_prompt,
        "use_first_frame": use_first_frame,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    entries = load_gallery()
    entries.insert(0, entry)  # newest first
    save_gallery(entries)
    return entry


def set_gallery_favorite(filename: str, favorite: bool) -> dict | None:
    """Flips one entry's "favorite" flag in place. Returns the updated entry,
    or None if no entry with that filename exists."""
    entries = load_gallery()
    for entry in entries:
        if entry.get("filename") == filename:
            entry["favorite"] = bool(favorite)
            save_gallery(entries)
            return entry
    return None


def delete_from_gallery(filename: str) -> bool:
    """Deletes a file plus its metadata entry. Returns True if anything was removed."""
    # basic protection against path traversal
    if "/" in filename or "\\" in filename or filename in (".", ".."):
        raise ValueError("Invalid filename")
    entries = load_gallery()
    new_entries = [e for e in entries if e.get("filename") != filename]
    removed = len(new_entries) != len(entries)
    save_gallery(new_entries)
    file_path = OUTPUT_DIR / filename
    if file_path.is_file():
        file_path.unlink()
        removed = True
    return removed


def load_stories() -> list:
    if not STORIES_META_FILE.exists():
        return []
    try:
        return json.loads(STORIES_META_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_stories(stories: list) -> None:
    STORIES_META_FILE.write_text(json.dumps(stories, indent=2), encoding="utf-8")


def save_story(story_id: str | None, title: str, synopsis: str, brief: str, characters: list, scenes: list) -> dict:
    """Saves a generated (and possibly since-edited) story so it survives a
    page refresh. `scenes` is stored as-is from the frontend — including each
    scene's current image_prompt text (which may have been hand-edited) and
    generatedImageUrl/generatedVideoUrl (the gallery URLs of whichever scenes
    were already generated, if any) — so reloading a saved story restores
    exactly what was on screen, not just the original Grok output.

    If `story_id` is given and matches an already-saved story, that entry is
    updated in place (keeping its original `created_at`, refreshing a new
    `updated_at`) instead of inserting a duplicate — this is what lets
    clicking "Save story" repeatedly while working through a story (e.g.
    saving again after each scene's image finishes generating) update the
    same entry rather than piling up near-identical copies every time. No id,
    or one that doesn't match anything currently saved, creates a fresh entry
    same as before."""
    stories = load_stories()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if story_id:
        for i, existing in enumerate(stories):
            if existing.get("id") == story_id:
                entry = {
                    **existing,
                    "title": title,
                    "synopsis": synopsis,
                    "brief": brief,
                    "characters": characters,
                    "scenes": scenes,
                    "updated_at": now,
                }
                stories[i] = entry
                save_stories(stories)
                return entry
    entry = {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "synopsis": synopsis,
        "brief": brief,
        "characters": characters,  # [{"id", "role"}, ...] as picked on the Story tab
        "scenes": scenes,
        "created_at": now,
    }
    stories.insert(0, entry)
    save_stories(stories)
    return entry


def delete_story(story_id: str) -> bool:
    stories = load_stories()
    remaining = [s for s in stories if s.get("id") != story_id]
    removed = len(remaining) != len(stories)
    save_stories(remaining)
    return removed


def load_characters() -> list:
    if not CHARACTERS_META_FILE.exists():
        return []
    try:
        return json.loads(CHARACTERS_META_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_characters(characters: list) -> None:
    CHARACTERS_META_FILE.write_text(json.dumps(characters, indent=2), encoding="utf-8")


def _save_character_image(source_url: str) -> dict:
    """Downloads an image (from a kie.ai result URL, typically) and stores it
    permanently under CHARACTERS_DIR. Returns {"filename", "url"}."""
    image_bytes, content_type = download_bytes(source_url)
    ext = mimetypes.guess_extension(content_type) or ".jpg"
    if ext == ".jpe":
        ext = ".jpg"
    filename = f"{uuid.uuid4().hex[:16]}{ext}"
    (CHARACTERS_DIR / filename).write_bytes(image_bytes)
    return {"filename": filename, "url": f"/characters/{filename}"}


def _save_character_video(source_url: str) -> dict:
    """Downloads a video (from a kie.ai upload URL) and stores it permanently
    under CHARACTERS_DIR, same pattern as _save_character_image(). Returns
    {"filename", "url"}. Used so a character can carry a reference_video for
    Wan 2.7 R2V (motion/voice/style replication) alongside its reference
    photos, which R2V takes as reference_image."""
    video_bytes, content_type = download_bytes(source_url)
    ext = mimetypes.guess_extension(content_type) or ".mp4"
    filename = f"{uuid.uuid4().hex[:16]}{ext}"
    (CHARACTERS_DIR / filename).write_bytes(video_bytes)
    return {"filename": filename, "url": f"/characters/{filename}"}


def create_character(name: str, identity: str, image_urls: list, video_urls: list | None = None) -> dict:
    images = [_save_character_image(url) for url in image_urls]
    videos = [_save_character_video(url) for url in (video_urls or [])]
    entry = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "identity": identity,
        "images": images,  # [{"filename", "url"}, ...]
        "videos": videos,  # [{"filename", "url"}, ...] — optional, for Wan 2.7 R2V reference_video
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    characters = load_characters()
    characters.insert(0, entry)
    save_characters(characters)
    return entry


def update_character(
    character_id: str,
    name: str,
    identity: str,
    keep_image_filenames: list,
    new_image_urls: list,
    keep_video_filenames: list,
    new_video_urls: list,
) -> dict | None:
    """Edits an existing character's name/identity text and its photo/video
    set. Photos/videos already on disk whose filename isn't in
    keep_*_filenames are deleted; new_*_urls are downloaded and appended,
    same as create_character(). Returns the updated entry, or None if
    character_id doesn't exist."""
    characters = load_characters()
    entry = next((c for c in characters if c.get("id") == character_id), None)
    if entry is None:
        return None

    for field, keep_filenames in (("images", keep_image_filenames), ("videos", keep_video_filenames)):
        old_items = entry.get(field, [])
        keep_items = [item for item in old_items if item.get("filename") in keep_filenames]
        removed_items = [item for item in old_items if item.get("filename") not in keep_filenames]
        for item in removed_items:
            filename = item.get("filename", "")
            if "/" in filename or "\\" in filename:
                continue  # safety: never unlink outside CHARACTERS_DIR
            file_path = CHARACTERS_DIR / filename
            if file_path.is_file():
                file_path.unlink()
        entry[field] = keep_items

    entry["images"] += [_save_character_image(url) for url in new_image_urls]
    entry["videos"] += [_save_character_video(url) for url in new_video_urls]
    entry["name"] = name
    entry["identity"] = identity
    save_characters(characters)
    return entry


def delete_character(character_id: str) -> bool:
    characters = load_characters()
    to_remove = [c for c in characters if c.get("id") == character_id]
    if not to_remove:
        return False
    remaining = [c for c in characters if c.get("id") != character_id]
    save_characters(remaining)
    for c in to_remove:
        for item in c.get("images", []) + c.get("videos", []):
            filename = item.get("filename", "")
            if "/" in filename or "\\" in filename:
                continue  # safety: never unlink outside CHARACTERS_DIR
            file_path = CHARACTERS_DIR / filename
            if file_path.is_file():
                file_path.unlink()
    return True


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_ndjson_headers(self):
        # No Content-Length — this class' protocol_version defaults to
        # HTTP/1.0 (never overridden), so the connection closing after the
        # handler returns is itself the end-of-body signal; the browser's
        # fetch() reads whatever arrives incrementally via
        # response.body.getReader() without needing chunked framing.
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def _write_ndjson_line(self, obj: dict):
        try:
            self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass  # client likely disconnected — nothing useful to do about it

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8")) if raw else {}

    # ---- static file serving for the UI ----
    def _serve_static(self, path: str):
        if path == "/":
            path = "/index.html"
        file_path = (HERE / path.lstrip("/")).resolve()
        if HERE not in file_path.parents and file_path != HERE:
            self.send_error(403)
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404)
            return
        content_type = "text/html; charset=utf-8"
        if file_path.suffix == ".js":
            content_type = "application/javascript"
        elif file_path.suffix == ".css":
            content_type = "text/css"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/task-status"):
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            task_id = params.get("taskId", "")
            try:
                api_key = load_api_key()
                status, data = forward_json(
                    f"{KIE_API_BASE}/api/v1/jobs/recordInfo?taskId={task_id}",
                    "GET",
                    None,
                    api_key,
                )
                self._send_json(status, data)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if self.path.rstrip("/") == "/api/gallery":
            self._send_json(200, {"entries": load_gallery()})
            return

        if self.path.rstrip("/") == "/api/assistant-prompts":
            overrides = load_prompt_overrides()
            result = {}
            for mode_key, default_text in DEFAULT_ASSISTANT_SYSTEM_PROMPTS.items():
                custom_text = overrides.get(mode_key) or None
                custom_nsfw_text = overrides.get(mode_key + "__nsfw") or None
                default_nsfw_text = DEFAULT_ASSISTANT_SYSTEM_PROMPTS_NSFW[mode_key]
                result[mode_key] = {
                    "default": default_text,
                    "custom": custom_text,
                    "effective": custom_text if custom_text else default_text,
                    "defaultNsfw": default_nsfw_text,
                    "customNsfw": custom_nsfw_text,
                    "effectiveNsfw": custom_nsfw_text if custom_nsfw_text else default_nsfw_text,
                }
            self._send_json(200, result)
            return

        if self.path.rstrip("/") == "/api/characters":
            self._send_json(200, {"characters": load_characters()})
            return

        if self.path.rstrip("/") == "/api/stories":
            self._send_json(200, {"stories": load_stories()})
            return

        if self.path.rstrip("/") == "/api/app-config":
            self._send_json(200, load_app_config())
            return

        if self.path.rstrip("/") == "/api/keys-status":
            self._send_json(200, load_keys_status())
            return

        if self.path.rstrip("/") == "/api/cost-totals":
            self._send_json(200, load_cost_totals())
            return

        if self.path.rstrip("/") == "/api/comfyui-config":
            self._send_json(200, load_comfyui_config())
            return

        if self.path.startswith("/api/comfyui-status"):
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            from urllib.parse import unquote
            base_url = unquote(params.get("baseUrl", ""))
            prompt_id = unquote(params.get("promptId", ""))
            try:
                if not base_url or not prompt_id:
                    raise RuntimeError("Missing baseUrl or promptId.")
                history = comfyui_get_history(base_url, prompt_id)
                entry = history.get(prompt_id)
                if not entry:
                    self._send_json(200, {"status": "pending"})
                    return
                result = comfyui_extract_result(entry)
                if not result:
                    self._send_json(200, {"status": "pending"})
                    return
                view_url = comfyui_view_url(base_url, result["filename"], result["subfolder"], result["type"])
                self._send_json(200, {"status": "done", "viewUrl": view_url})
            except Exception as e:
                self._send_json(200, {"status": "error", "error": str(e)})
            return

        if self.path.startswith("/outputs/"):
            filename = self.path[len("/outputs/"):].split("?", 1)[0]
            file_path = (OUTPUT_DIR / filename).resolve()
            if OUTPUT_DIR.resolve() not in file_path.parents or not file_path.is_file():
                self.send_error(404)
                return
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if self.path.startswith("/characters/"):
            filename = self.path[len("/characters/"):].split("?", 1)[0]
            file_path = (CHARACTERS_DIR / filename).resolve()
            if CHARACTERS_DIR.resolve() not in file_path.parents or not file_path.is_file():
                self.send_error(404)
                return
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self._serve_static(self.path)

    def _check_optional_token(self) -> bool:
        """If proxy_token.txt exists, the Authorization header must contain it."""
        if not TOKEN_FILE.exists():
            return True
        expected = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if not expected:
            return True
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {expected}"

    def do_POST(self):
        if not self._check_optional_token():
            self._send_json(401, {"error": "Invalid or missing token (proxy_token.txt)"})
            return

        # Handled before the load_api_key() gate below (unlike every other
        # POST route) so a fresh install with no kie_key.txt yet can still
        # set one from the Options panel's "API keys" section instead of
        # being stuck needing to hand-edit a file just to get past this
        # check once.
        if self.path == "/api/keys":
            try:
                body = self._read_json_body()
                self._send_json(200, save_keys(body.get("kieKey"), body.get("xaiKey")))
            except Exception as e:
                self._send_json(400, {"error": str(e)})
            return

        try:
            api_key = load_api_key()
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return

        if self.path == "/api/create-task":
            payload = self._read_json_body()
            # Enforces the Options panel's enabled/disabled model toggles
            # server-side, not just by hiding the option in the dropdown —
            # a stale browser tab (or the API called directly) would
            # otherwise still be able to queue a model the user turned off.
            requested_model = payload.get("model", "")
            app_cfg = load_app_config()
            disabled_key = next(
                (k for k, ids in IMAGE_MODEL_API_IDS.items() if requested_model in ids and not app_cfg["enabledImageModels"].get(k, True)),
                None,
            ) or next(
                (k for k, mid in VIDEO_MODEL_API_IDS.items() if requested_model == mid and not app_cfg["enabledVideoModels"].get(k, True)),
                None,
            )
            if disabled_key:
                self._send_json(403, {"error": f"'{disabled_key}' is disabled in Options — enable it there first."})
                return
            spend_cap = app_cfg.get("spendCapUsd", 0)
            if spend_cap and load_cost_totals()["allTimeUsd"] >= spend_cap:
                self._send_json(403, {"error": f"All-time spend cap (${spend_cap:g}) reached — raise or disable it in Options before starting new kie.ai jobs."})
                return
            status, data = forward_json(
                f"{KIE_API_BASE}/api/v1/jobs/createTask", "POST", payload, api_key
            )
            self._send_json(status, data)
            return

        if self.path == "/api/upload-image":
            payload = self._read_json_body()
            status, data = forward_json(
                f"{KIE_UPLOAD_BASE}/api/file-base64-upload", "POST", payload, api_key
            )
            self._send_json(status, data)
            return

        if self.path == "/api/app-config":
            try:
                body = self._read_json_body()
                self._send_json(200, save_app_config(body))
            except Exception as e:
                self._send_json(400, {"error": str(e)})
            return

        if self.path == "/api/cost-totals":
            try:
                body = self._read_json_body()
                if body.get("reset"):
                    self._send_json(200, reset_cost_totals())
                else:
                    self._send_json(200, add_cost_total(float(body.get("add", 0))))
            except Exception as e:
                self._send_json(400, {"error": str(e)})
            return

        if self.path == "/api/comfyui-config":
            try:
                body = self._read_json_body()
                config = save_comfyui_config(
                    body.get("baseUrl", ""), int(body.get("shortSide", 540)), body.get("scaleMode", "shorter"),
                )
                self._send_json(200, config)
            except Exception as e:
                self._send_json(400, {"error": str(e)})
            return

        if self.path == "/api/comfyui-queue":
            try:
                if not load_app_config()["enabledVideoModels"].get("comfyui-ltx", True):
                    raise RuntimeError("ComfyUI/LTX 2.3 is disabled in Options — enable it there first.")
                body = self._read_json_body()
                base_url = (body.get("baseUrl") or "").strip()
                base64_data = body.get("imageBase64", "")
                image_url = (body.get("imageUrl") or "").strip()
                prompt_text = body.get("prompt", "")
                seconds = int(body.get("seconds", 5))
                short_side = int(body.get("shortSide", 540))
                scale_mode = body.get("scaleMode", "shorter")
                if scale_mode not in ("shorter", "longer"):
                    raise RuntimeError("scaleMode must be 'shorter' or 'longer'.")
                if not base_url:
                    raise RuntimeError("Set the ComfyUI server URL first.")
                if not base64_data and not image_url:
                    raise RuntimeError("Missing source image.")
                if seconds not in (5, 10, 15, 20):
                    raise RuntimeError("Duration must be 5, 10, 15, or 20 seconds.")
                if short_side not in COMFYUI_LTX_RESOLUTIONS:
                    raise RuntimeError(f"Resolution must be one of {COMFYUI_LTX_RESOLUTIONS}.")
                if image_url:
                    # Used by the Story tab, which already has a saved scene
                    # image URL rather than a fresh upload — avoids the
                    # client having to re-fetch and base64-encode it itself.
                    data_url = local_or_remote_to_data_url(image_url)
                    header, _, encoded = data_url.partition(",")
                else:
                    header, _, encoded = base64_data.partition(",")
                content_type = "image/png"
                if header.startswith("data:") and ";" in header:
                    content_type = header[5:].split(";")[0] or "image/png"
                image_bytes = base64.b64decode(encoded or header)
                ext = mimetypes.guess_extension(content_type) or ".png"
                # A unique filename per upload is essential, not cosmetic:
                # ComfyUI's LoadImage node reads the file from disk at
                # EXECUTION time, not at upload/queue time. With a static
                # name (the old "upload.png" + overwrite=true), queuing
                # several jobs back-to-back — e.g. generating multiple Story
                # scene videos in a row — let a later upload overwrite the
                # file on disk before an earlier queued job actually got to
                # read it, silently swapping in the wrong source image.
                uploaded_filename = comfyui_upload_image(
                    base_url, image_bytes, content_type, f"upload_{uuid.uuid4().hex[:16]}{ext}"
                )
                workflow = build_comfyui_ltx_prompt(uploaded_filename, prompt_text, seconds, short_side, scale_mode)
                prompt_id = comfyui_queue_prompt(base_url, workflow)
                self._send_json(200, {"promptId": prompt_id})
            except Exception as e:
                import traceback
                print(f"[error] /api/comfyui-queue: {e}")
                traceback.print_exc()
                self._send_json(400, {"error": str(e)})
            return

        if self.path == "/api/save-to-gallery":
            try:
                body = self._read_json_body()
                entry = save_result_to_gallery(
                    source_url=body["imageUrl"],
                    prompt=body.get("prompt", ""),
                    mode=body.get("mode", ""),
                    aspect_ratio=body.get("aspect_ratio", ""),
                    quality=body.get("quality", ""),
                    duration=body.get("duration", ""),
                    video_model_key=body.get("video_model_key", ""),
                    image_model_key=body.get("image_model_key", ""),
                    negative_prompt=body.get("negative_prompt", ""),
                    use_first_frame=body.get("use_first_frame"),
                )
                self._send_json(200, {"entry": entry})
            except Exception as e:
                import traceback
                print(f"[error] /api/save-to-gallery: {e}")
                traceback.print_exc()
                self._send_json(400, {"error": str(e)})
            return

        if self.path == "/api/delete-from-gallery":
            try:
                body = self._read_json_body()
                removed = delete_from_gallery(body["filename"])
                self._send_json(200, {"removed": removed})
            except Exception as e:
                self._send_json(400, {"error": str(e)})
            return

        if self.path == "/api/gallery-favorite":
            try:
                body = self._read_json_body()
                entry = set_gallery_favorite(body["filename"], bool(body.get("favorite")))
                if entry is None:
                    raise RuntimeError("No gallery entry with that filename.")
                self._send_json(200, {"entry": entry})
            except Exception as e:
                self._send_json(400, {"error": str(e)})
            return

        if self.path == "/api/generate-prompt":
            try:
                body = self._read_json_body()
                brief = (body.get("brief") or "").strip()
                if not brief:
                    raise RuntimeError("Please describe what you want a prompt for.")
                assistant_mode = body.get("mode", "seedream_t2i")
                grok_cfg = load_app_config()
                system_prompt = get_system_prompt_for_mode(assistant_mode, nsfw=grok_cfg.get("nsfwEnabled", False))
                if not system_prompt:
                    raise RuntimeError(f"Unknown assistant mode: {assistant_mode}")
                image_data_urls = (body.get("images") or [])[:MAX_ASSISTANT_IMAGES]
                history = (body.get("history") or [])[-MAX_ASSISTANT_HISTORY_TURNS:]
                prompt_text, negative_prompt, reasoning, model_used, used_fallback = generate_prompt_with_grok(
                    brief, system_prompt, api_key, image_data_urls, history,
                    backend=grok_cfg.get("grokBackend", "kie"), xai_api_key=load_xai_api_key(),
                    auto_fallback=grok_cfg.get("grokAutoFallback", False),
                )
                self._send_json(200, {
                    "prompt": prompt_text,
                    "negative_prompt": negative_prompt,
                    "reasoning": reasoning,
                    "model": model_used,
                    "usedFallback": used_fallback,
                })
            except Exception as e:
                import traceback
                print(f"[error] /api/generate-prompt: {e}")
                traceback.print_exc()
                self._send_json(400, {"error": str(e)})
            return

        if self.path == "/api/generate-story-video-prompt":
            try:
                body = self._read_json_body()
                image_url = (body.get("imageUrl") or "").strip()
                narration = (body.get("narration") or "").strip()
                next_narration = (body.get("nextNarration") or "").strip()
                story_title = (body.get("storyTitle") or "").strip()
                story_synopsis = (body.get("storySynopsis") or "").strip()
                seconds = int(body.get("seconds", 5))
                # Grok Imagine Video 1.5 only: additional character reference
                # photos beyond the scene's own key frame, already fetched
                # and base64-encoded client-side (they're also uploaded as
                # image_urls for the actual video generation, in the same
                # order — see generateSceneVideo() in index.html), plus a
                # ready-made intro sentence naming which @image(n) belongs to
                # which character (built client-side, where the character
                # names/identities already live). Every other backend here
                # ignores these two fields entirely.
                extra_images = (body.get("extraImages") or [])[:6]  # 7-image cap minus the key frame
                extra_images_intro = (body.get("extraImagesIntro") or "").strip()
                # Four video engines can animate a scene: ComfyUI/LTX 2.3
                # (runs on the user's own network, section 7b), or kie.ai's
                # Seedance 1.5 Pro / Grok Imagine Video 1.5 / Hailuo 02
                # Standard (all faster, no local server needed) — each has
                # its own allowed durations and its own prompt-writing system
                # prompt (LTX needs the pacing/identity-drift rules from
                # STORY_LTX_MOTION_SYSTEM; Grok Imagine Video gets its own
                # GROK_IMAGE_VIDEO_MOTION_SYSTEM, since it's the only one of
                # the three kie.ai models here that can take more than one
                # reference image, via its own required @image(n) convention;
                # Seedance 1.5 Pro and Hailuo both reuse the Video tab's
                # regular Seedance system prompt, neither has a bespoke one).
                backend = (body.get("backend") or "comfyui-ltx").strip()
                if backend not in ("comfyui-ltx", "seedance-1-5-pro", "grok-imagine-video-1-5", "hailuo-02-i2v-standard"):
                    raise RuntimeError(f"Unknown video backend: {backend}")
                if backend == "comfyui-ltx":
                    allowed_durations = (5, 10, 15, 20)
                elif backend == "seedance-1-5-pro":
                    allowed_durations = (4, 8, 12)
                elif backend == "hailuo-02-i2v-standard":
                    allowed_durations = (6, 10)  # confirmed on kie.ai's docs — only these two values accepted
                else:
                    allowed_durations = tuple(range(6, 31))  # grok-imagine-video-1-5: 6-30s, confirmed on kie.ai's docs
                if not image_url:
                    raise RuntimeError("This scene needs a generated image first.")
                if seconds not in allowed_durations:
                    raise RuntimeError(f"Duration must be one of {allowed_durations} for this video engine.")
                brief_parts = []
                if story_title:
                    brief_parts.append(f"Story: {story_title}")
                if story_synopsis:
                    brief_parts.append(f"Synopsis: {story_synopsis}")
                brief_parts.append(f"This scene: {narration}")
                if extra_images_intro:
                    brief_parts.append(extra_images_intro)
                if next_narration:
                    brief_parts.append(
                        "What happens next (the following scene, for context only — "
                        "don't fully resolve it in this clip unless it reads like a "
                        f"direct continuation of the same beat): {next_narration}"
                    )
                brief_parts.append(f"Clip length: {seconds} seconds.")
                brief = "\n".join(brief_parts)
                image_data_url = local_or_remote_to_data_url(image_url)
                grok_cfg = load_app_config()
                nsfw = grok_cfg.get("nsfwEnabled", False)
                if backend == "comfyui-ltx":
                    system_prompt = get_system_prompt_for_mode("story_video_ltx", nsfw=nsfw)
                elif backend == "grok-imagine-video-1-5":
                    system_prompt = get_system_prompt_for_mode("story_video_grok_imagine", nsfw=nsfw)
                else:
                    system_prompt = get_system_prompt_for_mode("seedance_i2v", nsfw=nsfw)
                image_data_urls = [image_data_url] + (extra_images if backend == "grok-imagine-video-1-5" else [])
                prompt_text, _negative_prompt, reasoning, model_used, used_fallback = generate_prompt_with_grok(
                    brief, system_prompt, api_key, image_data_urls, [],
                    backend=grok_cfg.get("grokBackend", "kie"), xai_api_key=load_xai_api_key(),
                    auto_fallback=grok_cfg.get("grokAutoFallback", False),
                )
                self._send_json(200, {"prompt": prompt_text, "reasoning": reasoning, "model": model_used, "usedFallback": used_fallback})
            except Exception as e:
                import traceback
                print(f"[error] /api/generate-story-video-prompt: {e}")
                traceback.print_exc()
                self._send_json(400, {"error": str(e)})
            return

        if self.path == "/api/rewrite-story-scene-prompt":
            # Story tab's per-scene "🔀 Rewrite for ..." button — a style
            # REWRITE of an already-written scene image_prompt (see
            # _build_story_scene_convert_system()'s own long comment for why
            # this can't just be a fresh generate_story_with_grok() call: it
            # must preserve the scene's actual content and its "Character
            # A"/"Character B" labels exactly, not reimagine the scene).
            # Works in both directions — targetEngine picks which style.
            try:
                body = self._read_json_body()
                current_prompt = (body.get("currentPrompt") or "").strip()
                if not current_prompt:
                    raise RuntimeError("This scene has no prompt to rewrite yet.")
                narration = (body.get("narration") or "").strip()
                story_title = (body.get("storyTitle") or "").strip()
                story_synopsis = (body.get("storySynopsis") or "").strip()
                target_engine = (body.get("targetEngine") or "grok-imagine").strip()
                style_label = "Grok Imagine's" if target_engine == "grok-imagine" else "Seedream's"
                # [{"label": "Character A", "name": "Mira"}, ...] — built
                # client-side from the same global character-letter mapping
                # used everywhere else in the Story tab, so Grok is told
                # exactly which labels already exist rather than guessing.
                character_labels = body.get("characterLabels") or []
                previous_image_url = (body.get("previousImageUrl") or "").strip()

                brief_parts = []
                if story_title:
                    brief_parts.append(f"Story: {story_title}")
                if story_synopsis:
                    brief_parts.append(f"Synopsis: {story_synopsis}")
                brief_parts.append(f"This scene: {narration}")
                if character_labels:
                    labels_text = "; ".join(f"{c.get('label')} = {c.get('name')}" for c in character_labels if c.get("label") and c.get("name"))
                    if labels_text:
                        brief_parts.append(f"Characters already assigned in this scene (keep these exact labels): {labels_text}")
                brief_parts.append(f"Existing prompt to convert to {style_label} style:\n{current_prompt}")
                brief = "\n".join(brief_parts)

                image_data_urls = []
                if previous_image_url:
                    try:
                        image_data_urls.append(local_or_remote_to_data_url(previous_image_url))
                    except Exception:
                        pass  # continuity image is a nice-to-have here, not required — proceed without it

                mode = "story_scene_grok_convert" if target_engine == "grok-imagine" else "story_scene_seedream_convert"
                grok_cfg = load_app_config()
                system_prompt = get_system_prompt_for_mode(mode, nsfw=grok_cfg.get("nsfwEnabled", False))
                prompt_text, _negative_prompt, reasoning, model_used, used_fallback = generate_prompt_with_grok(
                    brief, system_prompt, api_key, image_data_urls, [],
                    backend=grok_cfg.get("grokBackend", "kie"), xai_api_key=load_xai_api_key(),
                    auto_fallback=grok_cfg.get("grokAutoFallback", False),
                )
                self._send_json(200, {"prompt": prompt_text, "reasoning": reasoning, "model": model_used, "usedFallback": used_fallback})
            except Exception as e:
                import traceback
                print(f"[error] /api/rewrite-story-scene-prompt: {e}")
                traceback.print_exc()
                self._send_json(400, {"error": str(e)})
            return

        if self.path == "/api/generate-story":
            # Validation happens with a normal JSON 400 response, same as
            # every other endpoint — only once that passes do we commit to
            # the streaming NDJSON response below, since headers can't be
            # swapped out after _send_ndjson_headers() has been sent.
            try:
                body = self._read_json_body()
                brief = (body.get("brief") or "").strip()
                if not brief:
                    raise RuntimeError("Please describe what you want the story to be about.")

                preferred_model = (body.get("grokModel") or "").strip() or None
                if preferred_model and preferred_model not in GROK_MODELS:
                    raise RuntimeError(f"Unknown Grok model: {preferred_model}")
                max_scenes = int(body.get("maxScenes") or 6)
                reasoning_effort = (body.get("reasoningEffort") or "high").strip()
                image_engine = (body.get("imageEngine") or "seedream-5-pro").strip()

                character_entries = body.get("characters") or []
                all_characters = {c["id"]: c for c in load_characters()}
                characters = [
                    {
                        "name": all_characters[e["id"]]["name"],
                        "identity": all_characters[e["id"]].get("identity", ""),
                        "role": (e.get("role") or "").strip(),
                    }
                    for e in character_entries
                    if e.get("id") in all_characters
                ]
            except Exception as e:
                self._send_json(400, {"error": str(e)})
                return

            # Streams newline-delimited JSON: zero or more {"progress": N}
            # lines (character count received from Grok so far — lets the
            # Story tab show live progress instead of a silent wait), then
            # exactly one final {"done": true, "story": ..., "model": ...}
            # or {"error": "..."} line. Throttled to roughly every 200
            # characters so a fast-arriving stream doesn't flood the
            # connection with a write per token.
            self._send_ndjson_headers()
            last_reported = 0

            def on_progress(total_chars):
                nonlocal last_reported
                if total_chars - last_reported >= 200:
                    last_reported = total_chars
                    self._write_ndjson_line({"progress": total_chars})

            try:
                grok_cfg = load_app_config()
                story, model_used, used_fallback = generate_story_with_grok(
                    brief, characters, api_key,
                    preferred_model=preferred_model, max_scenes=max_scenes,
                    reasoning_effort=reasoning_effort, on_progress=on_progress,
                    backend=grok_cfg.get("grokBackend", "kie"), xai_api_key=load_xai_api_key(),
                    auto_fallback=grok_cfg.get("grokAutoFallback", False),
                    image_engine=image_engine,
                )
                self._write_ndjson_line({"done": True, "story": story, "model": model_used, "usedFallback": used_fallback})
            except Exception as e:
                import traceback
                print(f"[error] /api/generate-story: {e}")
                traceback.print_exc()
                self._write_ndjson_line({"error": str(e)})
            return

        if self.path.rstrip("/") == "/api/save-story":
            try:
                body = self._read_json_body()
                title = (body.get("title") or "").strip()
                if not title:
                    raise RuntimeError("Missing story title.")
                entry = save_story(
                    story_id=(body.get("id") or "").strip() or None,
                    title=title,
                    synopsis=body.get("synopsis") or "",
                    brief=body.get("brief") or "",
                    characters=body.get("characters") or [],
                    scenes=body.get("scenes") or [],
                )
                self._send_json(200, {"story": entry})
            except Exception as e:
                import traceback
                print(f"[error] /api/save-story: {e}")
                traceback.print_exc()
                self._send_json(400, {"error": str(e)})
            return

        if self.path.rstrip("/") == "/api/delete-story":
            try:
                body = self._read_json_body()
                removed = delete_story(body.get("id", ""))
                self._send_json(200, {"removed": removed})
            except Exception as e:
                self._send_json(400, {"error": str(e)})
            return

        if self.path.rstrip("/") == "/api/assistant-prompts":
            try:
                body = self._read_json_body()
                mode_key = body.get("mode", "")
                if mode_key not in DEFAULT_ASSISTANT_SYSTEM_PROMPTS:
                    raise RuntimeError(f"Unknown assistant mode: {mode_key}")
                # "nsfw" writes to a separate mode+"__nsfw" override slot,
                # only ever consulted by get_system_prompt_for_mode() while
                # the Options panel's nsfwEnabled toggle is on (see there) —
                # "normal" (default, also what every pre-existing caller of
                # this endpoint already sends) is unaffected either way.
                variant = body.get("variant", "normal")
                storage_key = mode_key + "__nsfw" if variant == "nsfw" else mode_key
                text = (body.get("text") or "").strip()
                overrides = load_prompt_overrides()
                if text:
                    overrides[storage_key] = text
                else:
                    overrides.pop(storage_key, None)  # empty text = reset to default
                save_prompt_overrides(overrides)
                default_text = DEFAULT_ASSISTANT_SYSTEM_PROMPTS[mode_key]
                default_nsfw_text = DEFAULT_ASSISTANT_SYSTEM_PROMPTS_NSFW[mode_key]
                custom_text = overrides.get(mode_key) or None
                custom_nsfw_text = overrides.get(mode_key + "__nsfw") or None
                self._send_json(200, {
                    "default": default_text,
                    "custom": custom_text,
                    "effective": custom_text if custom_text else default_text,
                    "defaultNsfw": default_nsfw_text,
                    "customNsfw": custom_nsfw_text,
                    "effectiveNsfw": custom_nsfw_text if custom_nsfw_text else default_nsfw_text,
                })
            except Exception as e:
                self._send_json(400, {"error": str(e)})
            return

        if self.path.rstrip("/") == "/api/characters":
            try:
                body = self._read_json_body()
                name = (body.get("name") or "").strip()
                identity = (body.get("identity") or "").strip()
                image_urls = body.get("imageUrls") or []
                video_urls = body.get("videoUrls") or []
                if not name:
                    raise RuntimeError("Please give the character a name.")
                if not image_urls:
                    raise RuntimeError("At least one reference image is required.")
                entry = create_character(name, identity, image_urls, video_urls)
                self._send_json(200, {"character": entry})
            except Exception as e:
                import traceback
                print(f"[error] /api/characters: {e}")
                traceback.print_exc()
                self._send_json(400, {"error": str(e)})
            return

        if self.path.rstrip("/") == "/api/update-character":
            try:
                body = self._read_json_body()
                character_id = body.get("id", "")
                name = (body.get("name") or "").strip()
                identity = (body.get("identity") or "").strip()
                keep_image_filenames = body.get("keepImageFilenames") or []
                new_image_urls = body.get("newImageUrls") or []
                keep_video_filenames = body.get("keepVideoFilenames") or []
                new_video_urls = body.get("newVideoUrls") or []
                if not character_id:
                    raise RuntimeError("Missing character id.")
                if not name:
                    raise RuntimeError("Please give the character a name.")
                if not (len(keep_image_filenames) + len(new_image_urls)):
                    raise RuntimeError("At least one reference image is required.")
                entry = update_character(
                    character_id, name, identity,
                    keep_image_filenames, new_image_urls,
                    keep_video_filenames, new_video_urls,
                )
                if entry is None:
                    raise RuntimeError("Character not found.")
                self._send_json(200, {"character": entry})
            except Exception as e:
                import traceback
                print(f"[error] /api/update-character: {e}")
                traceback.print_exc()
                self._send_json(400, {"error": str(e)})
            return

        if self.path.rstrip("/") == "/api/delete-character":
            try:
                body = self._read_json_body()
                removed = delete_character(body.get("id", ""))
                self._send_json(200, {"removed": removed})
            except Exception as e:
                self._send_json(400, {"error": str(e)})
            return

        # ---- OpenAI-compatible: Open WebUI "Image Generation" (Engine = Open AI) ----
        if self.path.rstrip("/") == "/v1/images/generations":
            try:
                body = self._read_json_body()
                prompt = body.get("prompt", "")
                n = max(1, min(int(body.get("n") or 1), MAX_N))
                aspect_ratio = closest_aspect_ratio(body.get("size"))
                urls = []
                for _ in range(n):
                    input_payload = {
                        "prompt": prompt,
                        "aspect_ratio": aspect_ratio,
                        "quality": DEFAULT_QUALITY,
                    }
                    urls.append(create_and_poll(T2I_MODEL, input_payload, api_key))
                self._send_json(200, {
                    "created": int(time.time()),
                    "data": [{"url": u} for u in urls],
                })
            except Exception as e:
                import traceback
                print(f"[error] /v1/images/generations: {e}")
                traceback.print_exc()
                self._send_json(400, {"error": {"message": str(e)}})
            return

        # ---- OpenAI-compatible: Open WebUI "Image Editing" (Engine = Open AI) ----
        if self.path.rstrip("/") == "/v1/images/edits":
            try:
                content_type_header = self.headers.get("Content-Type", "")
                length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(length) if length else b""

                if "multipart/form-data" in content_type_header:
                    fields, files = parse_multipart(content_type_header, raw_body)
                else:
                    # some clients send JSON with base64/URL(s) instead of multipart
                    fields = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                    files = []

                print(
                    f"[debug] /v1/images/edits received — "
                    f"content-type={content_type_header!r}, "
                    f"fields={list(fields.keys())}, "
                    f"files={[(n, fn, ct, len(d)) for n, fn, ct, d in files]}"
                )

                prompt = fields.get("prompt", "")
                n = max(1, min(int(fields.get("n") or 1), MAX_N))
                aspect_ratio = closest_aspect_ratio(fields.get("size"))

                image_urls = []
                for (_name, _filename, content_type_val, file_bytes) in files:
                    image_urls.append(upload_bytes_to_kie(file_bytes, content_type_val, api_key))

                # fallback: JSON form with "image" as URL(s) or data URI(s)
                if not image_urls and fields.get("image"):
                    raw_image = fields["image"]
                    candidates = raw_image if isinstance(raw_image, list) else [raw_image]
                    for c in candidates:
                        if c.startswith("http://") or c.startswith("https://"):
                            image_urls.append(c)
                        else:
                            raise RuntimeError("Only file upload or URL is supported, not bare base64 in JSON form.")

                if not image_urls:
                    raise RuntimeError("No source image(s) received.")

                urls = []
                for _ in range(n):
                    input_payload = {
                        "prompt": prompt,
                        "image_urls": image_urls,
                        "aspect_ratio": aspect_ratio,
                        "quality": DEFAULT_QUALITY,
                    }
                    urls.append(create_and_poll(I2I_MODEL, input_payload, api_key))

                self._send_json(200, {
                    "created": int(time.time()),
                    "data": [{"url": u} for u in urls],
                })
            except Exception as e:
                import traceback
                print(f"[error] /v1/images/edits: {e}")
                traceback.print_exc()
                self._send_json(400, {"error": {"message": str(e)}})
            return

        self.send_error(404)

    def log_message(self, format, *args):
        print(f"[proxy] {self.address_string()} - {format % args}")


def main():
    try:
        load_api_key()
        print(f"API key found in {KEY_FILE.name}.")
    except Exception as e:
        print(f"WARNING: {e}")
        print("The server will still start, but calls to kie.ai will fail until you set the key.\n")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Own UI:          http://127.0.0.1:{PORT}")
    print(f"Open WebUI base: http://<this-ip>:{PORT}/v1  (Engine = Open AI, API key = any value)")
    print("(Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
