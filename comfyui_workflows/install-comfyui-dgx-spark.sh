#!/usr/bin/env bash
# Installs ComfyUI + ComfyUI-Manager + the four verified custom node packs
# needed for this app's ComfyUI/LTX 2.3 integration, on a DGX Spark
# (GB10 Blackwell, ARM64, CUDA 13.0). See DGX_SPARK_INSTALL.md for the full
# explanation of every step, and — importantly — for what this script does
# NOT do: it never downloads any .safetensors model/LoRA file. Several of
# the ones this workflow uses are community fine-tunes with no confirmed
# public source (see DGX_SPARK_INSTALL.md, "Models & LoRAs"); guessing at
# download URLs for those would be worse than leaving them to you. Copy
# your existing models/ folder from a working install if you have one —
# see the same section for the one-line rsync that does it.
#
# Usage:
#   ./install-comfyui-dgx-spark.sh [install_dir]
# install_dir defaults to ./ComfyUI

set -euo pipefail

INSTALL_DIR="${1:-ComfyUI}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== Prerequisite check =="
python3 --version
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader || {
  echo "nvidia-smi failed — are you actually on the DGX Spark / is the driver loaded?" >&2
  exit 1
}
if command -v nvcc >/dev/null 2>&1; then
  nvcc --version | grep -i release
else
  echo "WARNING: nvcc not found on PATH — CUDA toolkit may not be installed, continuing anyway" >&2
fi

echo "== Python venv =="
python3 -m venv comfyui-env
# shellcheck disable=SC1091
source comfyui-env/bin/activate

echo "== PyTorch (CUDA 13.0 build — required for GB10/sm_121) =="
pip3 install --upgrade pip
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu130

echo "== ComfyUI core =="
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "$INSTALL_DIR already exists, skipping clone"
else
  git clone https://github.com/comfyanonymous/ComfyUI.git "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"
pip install -r requirements.txt

echo "== ComfyUI-Manager =="
mkdir -p custom_nodes
cd custom_nodes
if [ ! -d comfyui-manager ]; then
  git clone https://github.com/Comfy-Org/ComfyUI-Manager comfyui-manager
fi
[ -f comfyui-manager/requirements.txt ] && pip install -r comfyui-manager/requirements.txt

echo "== Custom node packs =="
for repo in \
  Lightricks/ComfyUI-LTXVideo \
  kijai/ComfyUI-KJNodes \
  Kosinkadink/ComfyUI-VideoHelperSuite \
  TenStrip/10S-Comfy-nodes
do
  dir="${repo##*/}"
  if [ -d "$dir" ]; then
    echo "  $dir already present, skipping"
  else
    git clone "https://github.com/$repo"
  fi
  [ -f "$dir/requirements.txt" ] && pip install -r "$dir/requirements.txt"
done
cd ..

echo "== Workflow file =="
mkdir -p user/default/workflows
cp "$SCRIPT_DIR/ltx-2.3.json" user/default/workflows/
echo "Copied ltx-2.3.json into user/default/workflows/"

echo
echo "== Done =="
echo "Custom nodes and ComfyUI-Manager are installed. NOT done for you (see"
echo "DGX_SPARK_INSTALL.md, 'Models & LoRAs'):"
echo "  - models/checkpoints/10Eros_v1_bf16.safetensors"
echo "  - models/vae/LTX23_video_vae_bf16.safetensors, LTX23_audio_vae_bf16.safetensors"
echo "  - models/clip/gemma_3_12B_it_fp8_scaled.safetensors, ltx-2.3_text_projection_fp8.safetensors"
echo "  - models/loras/ (7 files — LTX2.3_DMD, OmniNFT-RL, SulphurEXP, 10Eros LoRA,"
echo "    JoyAI-Echo-content, Best_FaceID_v1.0_LoRA)"
echo
echo "Launch with:"
echo "  cd $INSTALL_DIR && source ../comfyui-env/bin/activate"
echo "  python main.py --listen 0.0.0.0 --port 8188 --enable-manager"
