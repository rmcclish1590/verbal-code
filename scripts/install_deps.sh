#!/bin/bash
set -euo pipefail

echo "Installing verbal-code dependencies..."

sudo apt update
sudo apt install -y \
    build-essential \
    cmake \
    pkg-config \
    libpipewire-0.3-dev \
    libxcb1-dev \
    libxcb-xinput-dev \
    libxkbcommon-dev \
    libxkbcommon-x11-dev \
    libgtk-3-dev \
    libxdo-dev

echo "All dependencies installed successfully."
