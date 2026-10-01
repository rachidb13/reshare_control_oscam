# Quickstart: Ubuntu 18.04 Installer

## Automated tests

```sh
cd /var/www/oscam_reshare_control-006
PYTHONPATH=src .venv/bin/python -m pytest tests/ -q
git diff --exit-code master -- install.sh   # must print nothing (SC-004)
```

## Manual check on a real Ubuntu 18.04 VPS

```sh
scp install-ubuntu18.sh root@<vps>:/root/
ssh root@<vps> 'RC_SOURCE_URL=<tarball of this branch> sh /root/install-ubuntu18.sh'
```

Then verify:

1. Open the printed `http://IP:PORT/` in a browser and log in as `admin` with the printed
   password. You should get the same panel as on a 20.04+ box.
2. `systemctl status reshare-control-web reshare-control.timer`: both active.
3. `systemctl cat reshare-control-web | grep ExecStart` contains `/usr/bin/python3.8`.
4. `dpkg -l | grep -i wireguard` and `ip link | grep wg` return nothing.
5. Reboot. The panel comes back.
6. Re-run the installer. The output says "existing password", and the config is unchanged.

Refusal check: on a 20.04 box, `sh install-ubuntu18.sh` exits 1, prints the standard
install command, and `/etc/reshare-control` is not created.
