#!/usr/bin/env bash
set -euo pipefail

DEST=/opt/dicom-configurator
sudo mkdir -p "$DEST"
sudo cp -r ./* "$DEST/"
sudo chown -R root:root "$DEST"
sudo chmod -R 755 "$DEST"

# ensure python3 and flask present
if ! command -v python3 >/dev/null; then
  echo "Please install python3"
  exit 1
fi
python3 -m pip install --quiet Flask || true

# install systemd unit
sudo cp dcmtk-configurator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dcmtk-configurator.service

echo "Install complete. Visit http://127.0.0.1:8080 to manage SCUs."