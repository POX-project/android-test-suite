# POX PROJECT — Android Test Suite (TSF)

[![CI & Validation](https://github.com/POX-project/android-test-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/POX-project/android-test-suite/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-brightgreen.svg)](https://www.python.org/)

An automated, asynchronous Android hardware and subsystem diagnostic audit suite with a rich interactive terminal interface ([Textual](https://github.com/Textualize/textual)) and headless CI/CLI execution modes.

---

## ⚡ Features & Test Modules

- **Battery Health & Wear**: Evaluates capacity, charge cycle history, and temperature state.
- **Biometric Subsystem**: Probes fingerprint and face authentication HAL responsiveness.
- **CPU & Thermal Throttling**: Monitors core frequencies, stress behavior, and thermal trip points.
- **Display & Touch**: Evaluates resolution, refresh rates, density, and touch input nodes.
- **GPU Diagnostics**: Checks render capability, GLES info, and Vulkan driver profiles.
- **Hardware Presence**: Validates physical components, camera sensors, audio nodes, and radios.
- **Network & Throughput**: Conducts packet-loss pings, DNS resolution, and speed checks.
- **OOM & Memory Killer**: Validates low-memory killer daemon (LMKD) behavior and swap/zRAM allocation.
- **Root & Privilege Integrity**: Detects Magisk, APatch, KernelSU, su binaries, and SELinux enforcement.
- **Storage Benchmark**: Sequential write and read speed tests with baseline threshold evaluations.
- **Thermal Mapping**: Polls thermal zones across CPU, GPU, skin, and battery.
- **UI Monkey Testing**: Automated stress events against Android UI surfaces.

---

## 🛠️ Universal & Per-SoC Thresholds

Audit scoring adapts to hardware capabilities to prevent unfair grading on low-end hardware versus flagships via `config/thresholds.yaml`:
- **Default Profile**: Standard baselines for mid-range chipsets.
- **Exynos 7904 / Low-End eMMC**: Sequential ~120 MB/s calibrated scoring.
- **Snapdragon 8 Gen 2 / UFS 4.0**: High-throughput flagship grading.
- **Google Tensor G3**: Custom thermal and neural baseline evaluations.

---

## 🚀 Getting Started

### 1. Requirements

- Python 3.10 or newer
- Android Debug Bridge (`adb`) installed on host machine
- Android device with USB debugging enabled

```bash
pip install -r requirements.txt
```

### 2. Interactive Terminal UI (TUI)

Launch the full-screen terminal dashboard:
```bash
python3 main.py
```

### 3. Headless / CLI Mode

Run unattended audits for CI or shell scripting:
```bash
python3 main.py --headless
```

Or run individual module test drivers:
```bash
python3 test_headless.py
```

---

## 🇵🇸 Solidarity
**FREE PALESTINE** — Support justice, end oppression, and spread awareness on all matters of shared humanity.
