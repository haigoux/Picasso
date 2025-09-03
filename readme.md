# Picasso
## Raspberry Pi DVR System
```
⚠️ WARNING!!!! ⚠️
These docs are unfinished and are not guaranteed to work
```
What is Picasso?
Picasso is software that allows a camera operator to use the Raspberry Pi as a DVR/Capture Card for USB video devices such as capture cards, webcams, camcorders etc. It can be very useful for tapeless cameras as it was originally designed for.

## How to use
Before you get started, please note that this software has only been tested on the Raspberry Pi 4B which has a **hardware video encoder**. 

Installing this software is recommended on a fresh install of the OS but it should work if not.

### Dependencies
1. python3.10+
2. python3-venv 
3. python3-pip
4. ffmpeg
5. v4l-utils

```bash
sudo apt update && sudo apt install -y python3.10 python3-venv python3-pip ffmpeg v4l-utils git
```

### Install Picasso
```
mkdir ~/picasso_src cd ~/picasso_src
git clone {GIT URL} .
```

### Setup virtual environment
```
python3 -m venv venv
```

### Activate and Install packages
```
source venv/bin/activate
pip install -r requirements.txt
```

### Configure the program
*note: the config file will not appear until the program is ran first*
```
nano ~/.configs/picasso/config.json
```

### Run Picasso
Running Picasso can be done in 2 ways.

It is recommended to setup a daemon to have it run on boot and automatically restart in the event of an error or system failure

#### 1. Directly
```
python runner.py
```

#### 2. Systemd (or your preferred method)
```
sudo nano /etc/systemd/system/picasso.service
```
Enter
```ini
[Unit]
Description=Gunicorn daemon for serving test-app
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=
Environment=
ExecStart=
ExecReload=
RestartSec=5

[Install]
WantedBy=multi-user.target
```
Save, then, enable the service
```bash
sudo systemctl daemon-reload command # reload config
systemctl start test-app.service # start service
systemctl enable test-app.service # enable at boot
```
