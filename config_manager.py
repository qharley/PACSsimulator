#!/usr/bin/env python3
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import re
import tempfile
import shutil
import os

@dataclass
class HostEntry:
    symbolic: str
    aet: str
    hostname: str
    port: int

@dataclass
class SCUEntry:
    ae_title: str
    hostname: str
    ip: str
    port: int

class ConfigManager:
    def __init__(self, cfg_path: str, hosts_path: str):
        self.cfg_path = cfg_path
        self.hosts_path = hosts_path
        self.raw = ''
        self.hosts: Dict[str, HostEntry] = {}
        self.scus: Dict[str, SCUEntry] = {}
        self._load()

    def _load(self):
        with open(self.cfg_path, 'r') as f:
            self.raw = f.read()
        self._parse()

    def _parse(self):
        # Reset
        self.hosts = {}
        self.scus = {}

        # Parse HostTable section
        m = re.search(r'HostTable\s+BEGIN(.*?)HostTable\s+END', self.raw, re.S|re.I)
        if m:
            body = m.group(1)
            # lines like: symbolic = (AE, host, port)
            for line in body.splitlines():
                line = line.strip()
                if not line or line.startswith('#'): continue
                if '=' in line:
                    sym, rhs = [x.strip() for x in line.split('=',1)]
                    # handle comma separated grouped entries (skip groups)
                    if ',' in rhs and '(' not in rhs:
                        continue
                    p = re.match(r'\(?\s*([A-Za-z0-9_\-]+)\s*,?\s*\)?\s*=\s*\(?\s*([A-Za-z0-9_\-]+)\s*,\s*([A-Za-z0-9_\-\.]+)\s*,\s*([0-9]+)\s*\)?', line)
                    if p:
                        # fallback: parsed differently; just continue
                        continue
                    # Try parsing of form: sym = (AE, host, port)
                    p2 = re.match(r'([A-Za-z0-9_\-]+)\s*=\s*\(\s*([A-Za-z0-9_\-]+)\s*,\s*([A-Za-z0-9_\-\.]+)\s*,\s*([0-9]+)\s*\)', line)
                    if p2:
                        symb = p2.group(1)
                        aet = p2.group(2)
                        host = p2.group(3)
                        port = int(p2.group(4))
                        self.hosts[symb] = HostEntry(symbolic=symb, aet=aet, hostname=host, port=port)
        # Parse AETable section (we only pick up peers that reference HostTable names)
        m2 = re.search(r'AETable\s+BEGIN(.*?)AETable\s+END', self.raw, re.S|re.I)
        if m2:
            body = m2.group(1)
            for line in body.splitlines():
                line = line.strip()
                if not line or line.startswith('#'): continue
                # simple split: AETitle  StorageArea  Access  Quota  Peers
                parts = re.split(r'\s+', line)
                if len(parts) < 5: continue
                aet = parts[0]
                # peers is last token(s); we attempt to find HostTable symbol in the line
                for sym in self.hosts.keys():
                    if sym in line:
                        # associate AE with the first host in hosttable matched
                        he = self.hosts[sym]
                        # try to find IP from /etc/hosts
                        ip = self._ip_for_hostname(he.hostname)
                        if ip:
                            self.scus[aet] = SCUEntry(ae_title=aet, hostname=he.hostname, ip=ip, port=he.port)
                        else:
                            self.scus[aet] = SCUEntry(ae_title=aet, hostname=he.hostname, ip='', port=he.port)
                        break
        # Also parse /etc/hosts to find extra hosts
        self._load_hosts_file()

    def _load_hosts_file(self):
        # Keep a quick mapping of hostname->ip
        self.hosts_ip = {}
        if os.path.exists(self.hosts_path):
            with open(self.hosts_path,'r') as f:
                for line in f:
                    line=line.strip()
                    if not line or line.startswith('#'): continue
                    parts=line.split()
                    if len(parts) >= 2:
                        ip = parts[0]
                        for hn in parts[1:]:
                            self.hosts_ip[hn]=ip

    def _ip_for_hostname(self, hostname: str) -> Optional[str]:
        return self.hosts_ip.get(hostname)

    def read_all(self) -> Dict[str, Dict]:
        # return hosts and scus as lists
        return {
            'hosts': list(self.hosts.values()),
            'scus': list(self.scus.values())
        }

    def add_scu(self, scu: SCUEntry):
        # if host exists, don't duplicate; create hosttable entry symbol name from AE
        symbol = scu.ae_title.lower()
        # add host to /etc/hosts if absent
        self._load_hosts_file()
        if scu.hostname not in self.hosts_ip:
            # append to hosts file
            with open(self.hosts_path, 'a') as f:
                f.write(f"{scu.ip} {scu.hostname} # DICOM SCU\n")
            self.hosts_ip[scu.hostname]=scu.ip
        # add a HostTable symbolic entry if not present
        if symbol not in self.hosts:
            self.hosts[symbol] = HostEntry(symbolic=symbol, aet=scu.ae_title, hostname=scu.hostname, port=scu.port)
        # add to scus map
        self.scus[scu.ae_title] = scu
        # and rewrite the internal raw config to include host and aetable entries
        self._sync_to_raw()

    def edit_scu(self, old_ae: str, new_scu: SCUEntry):
        # replace AE entry and possibly hostname/ip
        if old_ae not in self.scus:
            raise KeyError('AE not found')
        # if hostname changed, update /etc/hosts (append only - not removing IPs automatically)
        self.scus.pop(old_ae)
        self.scus[new_scu.ae_title] = new_scu
        # ensure host present
        self._load_hosts_file()
        if new_scu.hostname not in self.hosts_ip:
            with open(self.hosts_path, 'a') as f:
                f.write(f"{new_scu.ip} {new_scu.hostname} # DICOM SCU\n")
            self.hosts_ip[new_scu.hostname]=new_scu.ip
        # regenerate hosttable entry
        sym = new_scu.ae_title.lower()
        self.hosts[sym] = HostEntry(symbolic=sym, aet=new_scu.ae_title, hostname=new_scu.hostname, port=new_scu.port)
        self._sync_to_raw()

    def delete_scu(self, ae_title: str):
        if ae_title not in self.scus:
            raise KeyError('AE not found')
        scu = self.scus.pop(ae_title)
        # remove corresponding hosttable symbol if no other SCU references its host
        host = scu.hostname
        still_used = any(s.hostname==host for s in self.scus.values())
        if not still_used:
            # find symbol(s) matching this host and remove
            syms = [k for k,v in self.hosts.items() if v.hostname==host]
            for s in syms:
                del self.hosts[s]
            # also remove host from /etc/hosts (we will rewrite hosts file without the host entries)
            self._remove_host_from_hostsfile(host)
        self._sync_to_raw()

    def _remove_host_from_hostsfile(self, hostname: str):
        # rewrite hosts file removing lines that mention hostname with DICOM SCU tag or exact match
        tmp = tempfile.NamedTemporaryFile('w', delete=False)
        with open(self.hosts_path,'r') as f, tmp:
            for line in f:
                if hostname in line and '# DICOM SCU' in line:
                    continue
                tmp.write(line)
        shutil.move(tmp.name, self.hosts_path)

    def _sync_to_raw(self):
        # Insert HostTable entries and AETable entries into self.raw conservatively.
        # We will replace HostTable and AETable blocks.
        hostlines = []
        for sym, he in self.hosts.items():
            hostlines.append(f"{sym} = ({he.aet}, {he.hostname}, {he.port})")
        aelines = []
        for aet, scu in self.scus.items():
            # write a simple AETable line that references the host symbol
            sym = scu.ae_title.lower()
            aelines.append(f"{aet} /var/lib/dcmtk/db/{aet} RW (500, 1gb) {sym}")
        raw = self.raw
        raw = re.sub(r'HostTable\s+BEGIN.*?HostTable\s+END', 'HostTable BEGIN\n' + '\n'.join(hostlines) + '\nHostTable END', raw, flags=re.S|re.I)
        raw = re.sub(r'AETable\s+BEGIN.*?AETable\s+END', 'AETable BEGIN\n' + '\n'.join(aelines) + '\nAETable END', raw, flags=re.S|re.I)
        self.raw = raw

    def write_back(self):
        # Atomic write
        fd, tmpname = tempfile.mkstemp(dir=os.path.dirname(self.cfg_path))
        with os.fdopen(fd,'w') as f:
            f.write(self.raw)
        shutil.move(tmpname, self.cfg_path)