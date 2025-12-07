#!/usr/bin/env bash
set -euo pipefail

#set up dcmtk first
sudo apt update
sudo apt install -y dcmtk

# create dcmtk service

sudo cp dcmqrscp/dcmtk-dcmqrscp.service /etc/systemd/system/dcmtk-dcmqrscp.service
sudo systemctl daemon-reload
sudo systemctl enable --now dcmtk-dcmqrscp.service
sudo systemctl status dcmtk-dcmqrscp.service
# You can see dcmqrscp logs in journalctl -u dcmtk-dcmqrscp.service -f

# set up retention + FIFO-on-low-space script
sudo cp dcmqrscp/dcmtk-prune.sh /usr/local/bin/dcmtk-prune.sh
sudo chmod +x /usr/local/bin/dcmtk-prune.sh

# set up cron job to run prune script daily at 2am
(crontab -l 2>/dev/null; echo "0 2 * * * /usr/local/bin/dcmtk-prune.sh >> /var/log/dcmtk-prune.log 2>&1") | crontab -
# initial run
/usr/local/bin/dcmtk-prune.sh
# You can see prune logs in /var/log/dcmtk-prune.log

# set up iptables rule to redirect port 104 to 11104 (dcmtk-dcmqrscp default)
sudo apt install -y iptables
sudo iptables -t nat -A PREROUTING -p tcp --dport 104 -j REDIRECT --to-port 11104

# create dcmtk user and group if they don't exist
if ! id -u dcmtk >/dev/null 2>&1; then
  sudo useradd -r -s /bin/false -M dcmtk
fi

# create directories, index.dat and set permissions
# storage root for AEs
sudo mkdir -p /var/lib/dcmtk/db/DCMTK_STR_SCP
sudo touch /var/lib/dcmtk/db/DCMTK_STR_SCP/index.dat
sudo chown -R dcmtk:dcmtk /var/lib/dcmtk
sudo chmod -R 750 /var/lib/dcmtk

# install configurator app

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
sudo cp dcmqrscp/dcmtk-configurator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dcmtk-configurator.service

# Install nginx and set up reverse proxy
sudo apt install -y nginx apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd admin
sudo cp dcmqrscp/dcmtk-configurator-nginx.conf /etc/nginx/sites-available/dcmtk-configurator
sudo ln -s /etc/nginx/sites-available/dcmtk-configurator /etc/nginx/sites-enabled/dcmtk-configurator
sudo rm /etc/nginx/sites-enabled/default || true
sudo systemctl restart nginx

echo "Nginx reverse proxy set up with basic authentication."

SERVIP=$(hostname -I | awk '{print $1}')
echo "You can access the configurator at http://$SERVIP/ with username 'admin' and the password you set."

echo "Install complete. DCMTK DICOM Storage SCP is running and will store files under /var/lib/dcmtk/db/DCMTK_STR_SCP"
