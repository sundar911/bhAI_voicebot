# STT Benchmarking on AWS EC2

Step-by-step guide to run the full benchmarking pipeline on a GPU instance.

## 1. Launch EC2 Instance

| Setting | Value |
|---------|-------|
| **Instance type** | `g4dn.xlarge` (1× NVIDIA T4 16 GB, 4 vCPU, 16 GB RAM) |
| **AMI** | Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.8 (Ubuntu 24.04) |
| **Storage** | 50 GB gp3 (models download ~15 GB) |
| **Security group** | SSH (port 22) from your IP |
| **Key pair** | Your existing key pair or create a new one |

Cost: ~$0.53/hr on-demand. Full benchmark (5 models × 3 domains × 86 files) takes ~30–60 min.

## 2. SSH Into the Instance

```bash
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>
```

## 3. Setup Environment

Ubuntu 24.04 requires a virtual environment (PEP 668). Use `--system-site-packages` to inherit
the AMI's pre-installed PyTorch and CUDA — no need to re-download them.

```bash
# Clone repo
git clone https://github.com/sundar911/bhAI_voicebot.git
cd bhAI_voicebot

# Create venv (inherits system PyTorch/CUDA)
python3 -m venv .venv --system-site-packages
source .venv/bin/activate

# Install project deps
pip install -e ".[benchmarking]"
pip install onnxruntime-gpu huggingface_hub

# HuggingFace login
export HF_TOKEN="hf_your_token_here"
huggingface-cli login --token $HF_TOKEN

# Verify GPU
python3 -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0)}')"
```

## 4. Transfer Files to EC2

From your **local machine** (not EC2):

```bash
# Upload audio zip
scp -i your-key.pem sharepoint_audio.zip ubuntu@<EC2_PUBLIC_IP>:~/bhAI_voicebot/

# Upload ground truth
scp -i your-key.pem source_of_truth_transcriptions.xlsx ubuntu@<EC2_PUBLIC_IP>:~/bhAI_voicebot/
```

Back on **EC2**:

```bash
cd ~/bhAI_voicebot
unzip sharepoint_audio.zip -d data/sharepoint_sync/
```

## 5. Run Benchmarking

```bash
# Full run (all 5 models × 3 domains)
bash benchmarking/run_benchmark.sh

# Quick test (fastest model, one domain — ~2 min)
bash benchmarking/run_benchmark.sh --models "meta_mms" --domains "hr_admin"

# Specific models
bash benchmarking/run_benchmark.sh --models "vaani_whisper whisper_large_v3"

# CPU mode (no GPU needed, much slower)
bash benchmarking/run_benchmark.sh --device cpu
```

The script is re-runnable — it skips audio files that already have transcriptions.

## 6. Retrieve Results

From your **local machine**:

```bash
# Download comparison CSVs
scp -i your-key.pem -r ubuntu@<EC2_PUBLIC_IP>:~/bhAI_voicebot/benchmarking/results/ ./benchmarking/results/

# Download all transcription JSONL files
scp -i your-key.pem -r ubuntu@<EC2_PUBLIC_IP>:~/bhAI_voicebot/data/transcription_dataset/ ./data/transcription_dataset/
```

## 7. Teardown

**Stop** the instance when done to avoid charges. Terminate if you don't plan to reuse it.

```bash
# From local — or just use the AWS Console
aws ec2 stop-instances --instance-ids <INSTANCE_ID>
```
