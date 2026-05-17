# Inky pHAT Dashboard

E-ink dashboard for Raspberry Pi Zero 2W with an Inky pHAT (red, 212×104).
Shows weather, live bus departures (STPT Timișoara), current time, and Google Home now-playing info.

## Hardware

- Raspberry Pi Zero 2W
- Pimoroni Inky pHAT (red) — 3-color (white, black, red)
- SPI enabled (`dtoverlay=spi0-0cs` in `/boot/config.txt`)

## Architecture

Two systemd services:

- **dashboard-display.service** — renders content to the Inky pHAT
- **dashboard-web.service** — Flask web server on port 8080

They share `config.yaml` via `config_manager.py` (atomic writes). The web UI
writes to `/tmp/reload_flag` when config changes so the display loop picks up updates.

## First-time Setup

### 1. Flash & boot

Install Raspberry Pi OS Lite (64-bit). Enable SSH (place empty `ssh` file on boot partition).

```bash
# SSH in, enable SPI
sudo raspi-config  # Interface Options → SPI → Enable
sudo reboot
```

### 2. Install dependencies

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv git
git clone https://github.com/vladirocox/inkystpt.git /home/pi/dashboard
cd /home/pi/dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Install services

```bash
sudo cp deploy/dashboard-web.service deploy/dashboard-display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dashboard-web dashboard-display
sudo systemctl start dashboard-web dashboard-display
```

### 4. Configure via browser

Open `http://<pi-hostname>.local:8080` and follow the setup wizard:

1. **Password** — protect the web UI
2. **Your details** — name, timezone, location (for weather)
3. **Bus station** — search STPT stops (Timișoara, Romania)
4. **Google Home** — optional, for now-playing display
5. **Preview & finish** — preview the display, then finish

After setup, the display starts showing live data automatically.

## What's on the display

- **Top line**: Greeting + temperature + weather symbol (ASCII: `O` clear, `~` cloudy, `=` fog, `;` rain, `*` snow, `!` storm)
- **Clock**: Current time in `HH:MM`
- **Bus departures**: Live STPT API data (red), supplemented with tomorrow's schedule (`+1` times) when live data is sparse
- **Now playing**: Google Home media info (when playing)

## Data sources

- **Weather**: [Open-Meteo](https://open-meteo.com/) (free, no API key)
- **Live bus**: STPT proxy at `live.stpt.ro`
- **Schedule fallback**: scraper for `smtt.ro` (Timișoara public transit)
- **Now playing**: local network mDNS discovery + pychromecast

## Security

- Password stored as bcrypt hash in `config.yaml`
- Session cookie expires after 30 minutes
- **Do not expose port 8080 to the internet.** Local network only. Use a VPN or SSH tunnel for remote access.

## Reset password

```bash
ssh pi@<pi-ip>
# Edit /home/pi/dashboard/config.yaml and set password_hash: ''
sudo systemctl restart dashboard-web
# Then visit http://<pi-ip>:8080/setup
```

## Update

```bash
rsync -avz --delete --exclude=venv --exclude=config.yaml /path/to/dashboard/ pi@<pi-ip>:/home/pi/dashboard/
ssh pi@<pi-ip> "sudo systemctl restart dashboard-web dashboard-display"
```

## Files

```
dashboard/
├── display_loop.py           # Main display loop + render
├── mock_render.py            # PNG preview (no Inky needed)
├── config.yaml               # User config (auto-created)
├── requirements.txt
├── web/
│   ├── server.py             # Flask app, all routes
│   ├── config_manager.py     # Thread-safe config read/write
│   ├── api/
│   │   ├── bus_api.py        # STPT bus search + live arrivals
│   │   ├── cast_api.py       # Chromecast discovery
│   │   └── schedule_api.py   # smtt.ro schedule scraper
│   └── templates/
│       ├── setup.html        # 5-step onboarding wizard
│       ├── login.html        # Login page
│       └── settings.html     # Settings page
├── deploy/
│   ├── dashboard-display.service
│   └── dashboard-web.service
└── assets/routes/
    └── lines-config.json     # Stop-to-line mapping
```

## Uninstall

```bash
sudo systemctl stop dashboard-web dashboard-display
sudo systemctl disable dashboard-web dashboard-display
sudo rm /etc/systemd/system/dashboard-web.service /etc/systemd/system/dashboard-display.service
sudo systemctl daemon-reload
rm -rf /home/pi/dashboard
# Optional: remove system packages
# sudo apt remove python3-pip python3-venv git
# Optional: disable SPI
# sudo raspi-config
```
