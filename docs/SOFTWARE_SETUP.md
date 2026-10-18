# Raspberry Pi 软件环境从零建立

## 1. 烧录系统

建议使用 Raspberry Pi Imager 烧录 Raspberry Pi OS Lite 64-bit。烧录前在 Imager 的系统定制中设置：

1. 主机名，例如 `opengrid`。
2. 自己的用户名和强密码；不要把密码写进仓库。
3. Wi-Fi SSID、Wi-Fi 密码和国家/地区。
4. 时区与键盘布局。
5. 开启 SSH，并优先使用 SSH 公钥认证。

烧录完成后把卡插入树莓派、连接摄像头和网络，再上电。首次启动可能需要数分钟扩展文件系统。

## 2. 找到树莓派并连接

同一局域网内可先尝试：

```bash
ssh <用户名>@opengrid.local
```

也可以从路由器客户端列表查 IP，再执行：

```bash
ssh <用户名>@<树莓派IP>
```

若显示 `Connection refused`，通常表示 IP 对应设备没有运行 SSH，而不是密码错误。给 SD 卡重新启用 SSH，或接显示器登录后执行：

```bash
sudo systemctl enable --now ssh
```

## 3. 更新系统并确认硬件

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

重连后确认相机：

```bash
rpicam-hello --list-cameras
```

现代 Raspberry Pi OS 使用 libcamera/Picamera2，不需要旧版 `start_x=1` 相机设置。

## 4. 获取并安装项目

```bash
git clone https://github.com/FreepoetOfficial/Mirror-huge-grid-made-by-OpenGrid.git
cd Mirror-huge-grid-made-by-OpenGrid
chmod +x install_on_pi.sh
sudo ./install_on_pi.sh "$USER"
sudo reboot
```

安装脚本会：

1. 安装 Python venv、Picamera2、OpenCV、Flask 和 I²C 工具。
2. 启用 I²C，并把总线设为 400 kHz。
3. 把当前用户加入 `i2c` 组。
4. 复制程序到 `~/opengrid-shadow`。
5. 建立使用系统 Picamera2/OpenCV 包的虚拟环境并补装 Python 依赖。
6. 运行单元测试和 Python 编译检查。
7. 安装并启用主程序与温控两个 systemd 服务。

脚本不会覆盖已经存在的 `~/opengrid-shadow/config.json`，因此升级程序时能保留现场标定。

## 5. 第一次启用实体灯板

公共示例配置的 `hardware.enabled` 默认是 `false`。先执行：

```bash
i2cdetect -y 1
```

确认能看到 `24 25 26 27 28 29 2a 2b 2c 2d 2e 2f` 后编辑：

```bash
nano ~/opengrid-shadow/config.json
```

把：

```json
"enabled": false
```

改成：

```json
"enabled": true
```

然后重启服务：

```bash
sudo systemctl restart opengrid-shadow
```

## 6. 打开网页

查看 IP：

```bash
hostname -I
```

电脑或手机连接同一局域网后访问：

```text
http://<树莓派IP>:8080/
```

电脑上的 `127.0.0.1` 指向电脑本身。只有在建立端口转发时才能用它访问树莓派：

```bash
ssh -L 8080:127.0.0.1:8080 <用户名>@<树莓派IP>
```

保持该终端连接，再打开 `http://127.0.0.1:8080/`。不要直接双击 `static/index.html`，静态文件没有后端数据流，会一直显示“连接中”。

## 7. 不接硬件的电脑模拟

macOS/Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py --synthetic
```

访问 `http://127.0.0.1:8080/`。模拟模式生成移动的人形轮廓，可验证网页、矩阵和处理链路；没有 I²C 硬件时会保持 web-only 输出。

## 8. 验收

```bash
systemctl is-enabled opengrid-shadow opengrid-thermal-guard
systemctl is-active opengrid-shadow opengrid-thermal-guard
curl -s http://127.0.0.1:8080/api/state
python ~/opengrid-shadow/app.py --help
```

`/api/state` 中应看到摄像头、输出方式、FPS、硬件错误和活动涟漪数。正常实机输出应为 I²C，帧率接近配置的 12 FPS，`hardware_error` 为空。
