#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run: sudo ./install_on_pi.sh [username]" >&2
    exit 1
fi

TARGET_USER="${1:-${SUDO_USER:-pi}}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
if [ -z "$TARGET_HOME" ]; then
    echo "User not found: $TARGET_USER" >&2
    exit 1
fi

SOURCE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP_DIR="$TARGET_HOME/opengrid-shadow"

apt-get update
apt-get install -y python3-venv python3-picamera2 python3-opencv python3-flask i2c-tools

if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_i2c 0
fi
BOOT_CONFIG="/boot/firmware/config.txt"
if [ ! -f "$BOOT_CONFIG" ]; then
    BOOT_CONFIG="/boot/config.txt"
fi
if grep -q '^dtparam=i2c_arm=on' "$BOOT_CONFIG"; then
    sed -i 's/^dtparam=i2c_arm=on.*/dtparam=i2c_arm=on,i2c_arm_baudrate=400000/' "$BOOT_CONFIG"
else
    printf '%s\n' 'dtparam=i2c_arm=on,i2c_arm_baudrate=400000' >> "$BOOT_CONFIG"
fi
if getent group i2c >/dev/null 2>&1; then
    usermod -aG i2c "$TARGET_USER"
fi

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$APP_DIR"
for item in app.py config.example.json requirements.txt thermal_guard.py shadow static tests; do
    rm -rf "$APP_DIR/$item"
    cp -a "$SOURCE_DIR/$item" "$APP_DIR/$item"
done
if [ -d "$SOURCE_DIR/wheels" ]; then
    rm -rf "$APP_DIR/wheels"
    cp -a "$SOURCE_DIR/wheels" "$APP_DIR/wheels"
fi
chown -R "$TARGET_USER:$TARGET_USER" "$APP_DIR"

if [ ! -f "$APP_DIR/config.json" ]; then
    if [ -f "$SOURCE_DIR/config.deployed.json" ]; then
        cp "$SOURCE_DIR/config.deployed.json" "$APP_DIR/config.json"
    else
        cp "$APP_DIR/config.example.json" "$APP_DIR/config.json"
    fi
    chown "$TARGET_USER:$TARGET_USER" "$APP_DIR/config.json"
fi

if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    runuser -u "$TARGET_USER" -- python3 -m venv --system-site-packages "$APP_DIR/.venv"
fi
if [ -d "$APP_DIR/wheels" ]; then
    runuser -u "$TARGET_USER" -- "$APP_DIR/.venv/bin/python" -m pip install \
        --no-index --no-deps "$APP_DIR"/wheels/*.whl
else
    runuser -u "$TARGET_USER" -- "$APP_DIR/.venv/bin/python" -m pip install \
        -r "$APP_DIR/requirements.txt"
fi

sed \
    -e "s|__TARGET_USER__|$TARGET_USER|g" \
    -e "s|__APP_DIR__|$APP_DIR|g" \
    "$SOURCE_DIR/opengrid-shadow.service" > /etc/systemd/system/opengrid-shadow.service
sed \
    -e "s|__APP_DIR__|$APP_DIR|g" \
    "$SOURCE_DIR/opengrid-thermal-guard.service" > /etc/systemd/system/opengrid-thermal-guard.service

runuser -u "$TARGET_USER" -- "$APP_DIR/.venv/bin/python" -m unittest discover \
    -s "$APP_DIR/tests" -v
runuser -u "$TARGET_USER" -- "$APP_DIR/.venv/bin/python" -m compileall -q \
    "$APP_DIR/app.py" "$APP_DIR/thermal_guard.py" "$APP_DIR/shadow" "$APP_DIR/tests"

systemctl daemon-reload
systemctl enable opengrid-shadow.service opengrid-thermal-guard.service
systemctl restart opengrid-shadow.service opengrid-thermal-guard.service

echo "Installed successfully. Open http://$(hostname -I | awk '{print $1}'):8080/"
