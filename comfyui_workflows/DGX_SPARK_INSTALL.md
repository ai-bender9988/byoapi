# ComfyUI on NVIDIA DGX Spark — install guide

Reproduces the ComfyUI setup this app's ComfyUI/LTX 2.3 integration
(section 7b of `README.md`) talks to — same custom node packs, same
base model components, same LoRA stack as `comfyui_workflows/ltx-2.3.json`.
Written for a fresh DGX Spark (GB10 Blackwell Superchip, ARM64/aarch64,
unified CPU+GPU memory) — the live server this was verified against
reported: ComfyUI 0.28.3, Python 3.12.3, PyTorch 2.12.1+cu130.

Two ways to use this:
- **`install-comfyui-dgx-spark.sh`** automates everything that's safe to
  automate (base ComfyUI, PyTorch/CUDA, ComfyUI-Manager, the verified
  custom node packs) and clones `ltx-2.3.json` into the new install's
  `user/default/workflows/` folder so it's ready to load. It does **not**
  download any model/LoRA `.safetensors` files — see "Models & LoRAs"
  below for why, and what to do instead.
- This document explains every step the script performs, plus the parts
  it deliberately leaves to you.

---

## 1. Prerequisites

```bash
python3 --version    # expect 3.10+
nvcc --version        # expect CUDA 13.x
nvidia-smi             # confirm the GB10 GPU is visible
```

DGX Spark's Blackwell GB10 GPU is `sm_121` — standard PyPI PyTorch wheels
(built for CUDA 12.x) don't support it and will silently fail to use the
GPU (or error outright). You need PyTorch built against **CUDA 13.0**
specifically, per NVIDIA's own [DGX Spark ComfyUI
playbook](https://github.com/NVIDIA/dgx-spark-playbooks/tree/main/nvidia/comfy-ui).

If you hit memory pressure during a large model load (DGX Spark's unified
memory is shared between CPU and GPU, unlike a discrete-GPU box):
```bash
sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
```

---

## 2. Base ComfyUI

```bash
python3 -m venv comfyui-env
source comfyui-env/bin/activate

# CUDA 13.0 build — required for GB10/sm_121, not the default PyPI wheel
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu130

git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI/
pip install -r requirements.txt
```

## 3. ComfyUI-Manager

Lets you install/update custom nodes from ComfyUI's own web UI afterward,
and is what `--enable-manager` (see the launch command in section 7) turns
on. [Comfy-Org/ComfyUI-Manager](https://github.com/Comfy-Org/ComfyUI-Manager):

```bash
cd custom_nodes
git clone https://github.com/Comfy-Org/ComfyUI-Manager comfyui-manager
cd comfyui-manager
pip install -r requirements.txt
cd ../..
```

---

## 4. Custom node packs

Four packs, cloned into `ComfyUI/custom_nodes/`, each with `pip install -r
requirements.txt` afterward if it has one:

| Pack | Source | Provides |
|---|---|---|
| **ComfyUI-LTXVideo** | [Lightricks/ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) (official) | `LTXVConditioning`, `LTXVEmptyLatentAudio`, `LTXVConcatAVLatent`, `LTXVSeparateAVLatent`, `LTXVPreprocess`, `LTXVScheduler`, `LTXVAudioVAEDecode` — the core LTX 2.3 nodes the workflow's sampling chain is built from |
| **ComfyUI-KJNodes** | [kijai/ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) | `LTXVImgToVideoInplaceKJ` — conditions the video latent from your starting image |
| **ComfyUI-VideoHelperSuite** | [Kosinkadink/ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | `VHS_VideoCombine` — the final node that muxes frames + audio into the output .mp4 |
| **10S-Comfy-nodes** | [TenStrip/10S-Comfy-nodes](https://github.com/TenStrip/10S-Comfy-nodes) | `LTX_lora_loader` (the multi-LoRA stack node), `LTXReferenceEnable`/`LTXReferenceConditioning`, and `LTXFaceIdentityReinforcer` (face-consistency node, see README section 7b) |

```bash
cd custom_nodes
for repo in \
  Lightricks/ComfyUI-LTXVideo \
  kijai/ComfyUI-KJNodes \
  Kosinkadink/ComfyUI-VideoHelperSuite \
  TenStrip/10S-Comfy-nodes
do
  git clone "https://github.com/$repo"
  dir="${repo##*/}"
  [ -f "$dir/requirements.txt" ] && pip install -r "$dir/requirements.txt"
done
cd ..
```

**One node's source I could not verify**: `UnifiedResizeImageMask` (the
resize node the resolution setting in this app's Video tab controls — see
`COMFYUI_LTX_RESIZE_NODE` in `proxy.py`). It isn't part of any of the four
packs above per their published node lists. If ComfyUI reports it missing
after installing everything else, check ComfyUI-Manager's "Install Missing
Custom Nodes" first — it can usually resolve a node by class name even
when a web search can't.

---

## 5. Models & LoRAs

**Why the script doesn't auto-download these**: some of the files in
`ltx-2.3.json`'s LoRA stack are community fine-tunes, not official
Lightricks releases, and two of them I could not confirm still have a
public download source (one appears only on a CivitAI *archive* mirror,
which typically means the original listing was taken down). I'm not going
to guess at re-hosting a link for a removed listing. **If you already have
these files from your current install, the safest move is copying them
directly rather than re-downloading from anywhere** — see the "copy
instead of download" note at the end of this section.

### Official components (verified sources)

| File (as used in `ltx-2.3.json`) | Source |
|---|---|
| `LTX23_video_vae_bf16.safetensors`, `LTX23_audio_vae_bf16.safetensors` | [Lightricks/LTX-2.3](https://huggingface.co/Lightricks/LTX-2.3) |
| `gemma_3_12B_it_fp8_scaled.safetensors` | fp8 variant of Google's Gemma 3 text encoder — check [Lightricks/LTX-2.3-fp8](https://huggingface.co/Lightricks/LTX-2.3-fp8) first; base (unquantized) is [google/gemma-3-12b-it-qat-q4_0-unquantized](https://huggingface.co/google/gemma-3-12b-it-qat-q4_0-unquantized) |
| `ltx-2.3_text_projection_fp8.safetensors` | [Lightricks/LTX-2.3](https://huggingface.co/Lightricks/LTX-2.3) (~0.5GB connector file, loaded alongside the text encoder) |
| `Best_FaceID_v1.0_LoRA.safetensors` | [Alissonerdx/LTX-Best-Face-ID](https://huggingface.co/Alissonerdx/LTX-Best-Face-ID) — pairs with the `LTXFaceIdentityReinforcer` node |
| `LTX2.3_DMD_fro99-avgrank47.safetensors` | [TenStrip/LTX2.3_DMD_Lora](https://huggingface.co/TenStrip/LTX2.3_DMD_Lora) — distillation LoRA, lets the workflow run at 9 sampling steps |
| `LTX-2.3-OmniNFT-RL-Lora_bf16.safetensors` | [Kijai/LTX2.3_comfy](https://huggingface.co/Kijai/LTX2.3_comfy) on Hugging Face — audio/video sync + motion-coherence RL LoRA |

Recommended install path (needs `pip install -U "huggingface_hub[cli]"` and
`hf auth login` first for gated repos):
```bash
cd ComfyUI/models
hf download Lightricks/LTX-2.3 --include "*vae*" --local-dir checkpoints
hf download Lightricks/LTX-2.3-fp8 --include "*gemma*" --local-dir clip
hf download TenStrip/LTX2.3_DMD_Lora --local-dir loras
hf download Kijai/LTX2.3_comfy --include "*OmniNFT*" --local-dir loras
hf download Alissonerdx/LTX-Best-Face-ID --local-dir loras
```
Double-check each downloaded filename matches the table above exactly —
`LTX_lora_loader`'s `stack_data` in `ltx-2.3.json` references these by
exact filename, so a renamed file needs the JSON updated to match (or vice
versa).

### The main checkpoint and two LoRAs (unverified / personal)

| File | Notes |
|---|---|
| `10Eros_v1_bf16.safetensors` (the actual UNET checkpoint, node `5310:5008`) | A community LTX 2.3 fine-tune, not the stock Lightricks checkpoint. |
| `LTX_10Eros-v14_LoRA_fro99-avgrank104.safetensors` | The only reference I found was on a CivitAI **archive** mirror (`civarchive.com`) rather than CivitAI itself — that usually means the original listing was removed. Didn't link it here for that reason. |
| `LTX_SulphurEXP_LoRA_fro99-avgrank105.safetensors` | No public listing found at all. |

If you don't already have local copies of these three, you'll need to
track down wherever you originally sourced them (or the stock
`Lightricks/LTX-2.3` base checkpoint works as a `unet_name` substitute if
you're fine losing the `10Eros` fine-tune's specific look — you'd also
want to drop the two LoRAs tied to it from the stack).

`JoyAI-Echo-content_r256.safetensors` also wasn't independently
confirmable, though it's referenced as the source the DMD distillation
deltas were extracted from — likely available wherever you got
`LTX2.3_DMD_fro99-avgrank47.safetensors`'s description pointed.

### Copy instead of download

If this is a **second** DGX Spark (or a reinstall of the same one), the
fastest and most reliable path for every file above — official or not —
is copying `models/checkpoints/`, `models/clip/`, `models/vae/`, and
`models/loras/` straight from the working install, e.g.:
```bash
rsync -avP old-spark:/path/to/ComfyUI/models/ ./ComfyUI/models/
```
That sidesteps every sourcing question above entirely.

---

## 6. Load the workflow

```bash
mkdir -p ComfyUI/user/default/workflows
cp /path/to/comfyui_workflows/ltx-2.3.json ComfyUI/user/default/workflows/
```
Opening it in ComfyUI's UI will auto-arrange the nodes (this is an
API-format export, not a UI-format save with saved positions — see the
note in README.md section 7b).

## 7. Launch

Matches the live server's actual startup flags:
```bash
python main.py --listen 0.0.0.0 --port 8188 --enable-manager
```
`--listen 0.0.0.0` is what makes it reachable from other machines on your
network — required for this app (`proxy.py`) to reach it at all, since it
runs on a different machine.

## 8. Point this app at it

In this app's Video tab, once ComfyUI's server is up: select "ComfyUI —
LTX 2.3", enter `http://<spark-ip>:8188` in the server URL field, pick a
resolution. Both are saved to `comfyui_config.json` after the first use.

## 9. Verify

```bash
curl -I http://localhost:8188                                    # server responds
curl -s http://localhost:8188/object_info/LTXFaceIdentityReinforcer | head -c 200   # face node registered
curl -s http://localhost:8188/object_info/LTX_lora_loader | grep -o '"[^"]*\.safetensors"'  # which loras it can actually see
```
The last command's output should include every filename from the table in
section 5 — if one's missing, ComfyUI can't find it in `models/loras/`
yet.
