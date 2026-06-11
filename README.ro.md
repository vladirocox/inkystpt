# Inky pHAT Dashboard

> Vizualizează și [integrarea STPT Transit pentru Home Assistant](https://github.com/vladirocox/stpt-ha-integration) — monitorizare stații în timp real în HA.

Dashboard pe cerneală electronică pentru Raspberry Pi Zero 2W cu Inky pHAT (roșu, 212×104).
Afișează vremea, plecări live ale transportului în comun (STPT Timișoara), ora curentă și informații despre redări de pe orice dispozitiv Chromecast.

## Hardware

- Raspberry Pi Zero 2W
- Pimoroni Inky pHAT (roșu) — 3 culori (alb, negru, roșu)
- SPI activat (`dtoverlay=spi0-0cs` în `/boot/config.txt`)

## Arhitectură

Două servicii systemd:

- **dashboard-display.service** — redește conținutul pe Inky pHAT
- **dashboard-web.service** — server web Flask pe portul 8080

Ambele folosesc `config.yaml` prin `config_manager.py` (scrieri atomice). Interfața web
scrie în `/tmp/reload_flag` când configurația se schimbă, pentru ca bucla de afișare să preia actualizările.

## Configurare inițială

### 1. Flash și pornire

Instalează Raspberry Pi OS Lite (64-bit). Activează SSH (plasează un fișier `ssh` gol pe partiția de boot).

```bash
# Conectează-te prin SSH, activează SPI
sudo raspi-config  # Interface Options → SPI → Enable
sudo reboot
```

### 2. Instalează dependințele

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv git
git clone https://github.com/vladirocox/inkystpt.git /home/pi/dashboard
cd /home/pi/dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Instalează serviciile

```bash
sudo cp deploy/dashboard-web.service deploy/dashboard-display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dashboard-web dashboard-display
sudo systemctl start dashboard-web dashboard-display
```

### 4. Configurează din browser

Deschide `http://<pi-hostname>.local:8080` și urmează asistentul de configurare:

1. **Parola** — protejează interfața web
2. **Detaliile tale** — nume, fus orar, locație (pentru vreme)
3. **Stația de autobuz** — caută stații STPT (Timișoara, România)
4. **Chromecast** — opțional, pentru afișarea redării curente
5. **Previzualizare și finalizare** — previzualizează ecranul, apoi finalizează

După configurare, afișajul începe să arate date live automat.

## Ce se afișează

- **Linia de sus**: Salut + temperatură + simbol vreme (ASCII: `O` senin, `~` noros, `=` ceață, `;` ploaie, `*` zăpadă, `!` furtună)
- **Ceas**: Ora curentă în format `HH:MM`
- **Plecări autobuz**: Date live din API-ul STPT (roșu), completate cu programul de mâine (ore `+1`) când datele live sunt puține
- **Redare acum**: Informații Chromecast (când se redă ceva)

## Surse de date

- **Vremea**: [Open-Meteo](https://open-meteo.com/) (gratuit, fără cheie API)
- **Autobuz live**: Proxy STPT la `live.stpt.ro`
- **Program de rezervă**: scraper pentru `smtt.ro` (transport public Timișoara)
- **Redare acum**: mDNS pe rețeaua locală + pychromecast (funcționează cu orice Chromecast, Google Home sau dispozitiv Cast)

## Securitate

- Parola stocată ca hash bcrypt în `config.yaml`
- Cookie-ul sesiunii expiră după 30 de minute
- **Nu expune portul 8080 la internet.** Doar rețea locală. Folosește un VPN sau tunel SSH pentru acces remote.

## Resetare parolă

```bash
ssh pi@<pi-ip>
# Editează /home/pi/dashboard/config.yaml și setează password_hash: ''
sudo systemctl restart dashboard-web
# Apoi vizitează http://<pi-ip>:8080/setup
```

## Actualizare

```bash
rsync -avz --delete --exclude=venv --exclude=config.yaml /path/to/dashboard/ pi@<pi-ip>:/home/pi/dashboard/
ssh pi@<pi-ip> "sudo systemctl restart dashboard-web dashboard-display"
```

## Fișiere

```
dashboard/
├── display_loop.py           # Bucla principală de afișare + randare
├── mock_render.py            # Previzualizare PNG (fără Inky)
├── config.yaml               # Configurare utilizator (creată automat)
├── requirements.txt
├── web/
│   ├── server.py             # Aplicația Flask, toate rutele
│   ├── config_manager.py     # Citire/scriere configurare thread-safe
│   ├── api/
│   │   ├── bus_api.py        # Căutare stații STPT + sosiri live
│   │   ├── cast_api.py       # Descoperire Chromecast
│   │   └── schedule_api.py   # Scraper program smtt.ro
│   └── templates/
│       ├── setup.html        # Asistent de configurare în 5 pași
│       ├── login.html        # Pagina de autentificare
│       └── settings.html     # Pagina de setări
├── deploy/
│   ├── dashboard-display.service
│   └── dashboard-web.service
└── assets/routes/
    └── lines-config.json     # Mapare stații-linii
```

## Dezinstalare

```bash
sudo systemctl stop dashboard-web dashboard-display
sudo systemctl disable dashboard-web dashboard-display
sudo rm /etc/systemd/system/dashboard-web.service /etc/systemd/system/dashboard-display.service
sudo systemctl daemon-reload
rm -rf /home/pi/dashboard
# Opțional: elimină pachetele de sistem
# sudo apt remove python3-pip python3-venv git
# Opțional: dezactivează SPI
# sudo raspi-config
```
