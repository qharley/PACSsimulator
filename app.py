#!/usr/bin/env python3
from flask import Flask, render_template, request, abort
from config_manager import ConfigManager, SCUEntry
import subprocess
import os

CONFIG_PATH = "/etc/dcmtk/dcmqrscp.cfg"
HOSTS_PATH = "/etc/hosts"
SERVICE_NAME = "dcmtk-dcmqrscp.service"

app = Flask(__name__, template_folder="templates", static_folder="static")
cm = ConfigManager(CONFIG_PATH, HOSTS_PATH)

# Helper: require root for write actions (simple check)
def require_root():
    if os.geteuid() != 0:
        abort(403, description="Administrator privileges required")

@app.route('/')
def index():
    data = cm.read_all()
    return render_template('index.html', hosts=data['hosts'], scus=data['scus'])

# HTMX endpoint - partial list refresh
@app.route('/scu/list')
def scu_list():
    data = cm.read_all()
    return render_template('_scu_list.html', hosts=data['hosts'], scus=data['scus'])

@app.route('/scu/add', methods=['POST'])
def add_scu():
    require_root()
    ae = request.form.get('ae', '').strip().upper()
    hostname = request.form.get('hostname', '').strip()
    ip = request.form.get('ip', '').strip()
    port = request.form.get('port', '').strip() or '104'

    # basic validation
    if not ae or not hostname or not ip:
        return ("Missing fields", 400)

    entry = SCUEntry(ae_title=ae, hostname=hostname, ip=ip, port=int(port))
    try:
        cm.add_scu(entry)
        cm.write_back()
        # restart service to pick up new host/AETable
        subprocess.run(["systemctl", "restart", SERVICE_NAME], check=False)
    except (KeyError, ValueError, OSError) as e:
        return (str(e), 500)
    return render_template('_scu_list.html', **cm.read_all())

@app.route('/scu/edit', methods=['POST'])
def edit_scu():
    require_root()
    old_ae = request.form.get('old_ae')
    ae = request.form.get('ae', '').strip().upper()
    hostname = request.form.get('hostname', '').strip()
    ip = request.form.get('ip', '').strip()
    port = request.form.get('port', '').strip() or '104'

    if not old_ae or not ae or not hostname or not ip:
        return ("Missing fields", 400)

    new_entry = SCUEntry(ae_title=ae, hostname=hostname, ip=ip, port=int(port))
    try:
        cm.edit_scu(old_ae, new_entry)
        cm.write_back()
        subprocess.run(["systemctl", "restart", SERVICE_NAME], check=False)
    except (KeyError, ValueError, OSError) as e:
        return (str(e), 500)
    return render_template('_scu_list.html', **cm.read_all())

@app.route('/scu/delete', methods=['POST'])
def delete_scu():
    require_root()
    ae = request.form.get('ae')
    if not ae:
        return ("Missing AE", 400)
    try:
        cm.delete_scu(ae)
        cm.write_back()
        subprocess.run(["systemctl", "restart", SERVICE_NAME], check=False)
    except (KeyError, ValueError, OSError) as e:
        return (str(e), 500)
    return render_template('_scu_list.html', **cm.read_all())

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080)