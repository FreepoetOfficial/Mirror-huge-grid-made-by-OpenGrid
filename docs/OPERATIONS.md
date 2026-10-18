# 日常运行、关机与恢复

## 1. 开机自运行

安装脚本会启用：

- `opengrid-shadow.service`：相机、图像处理、网页、LED 和按键涟漪。
- `opengrid-thermal-guard.service`：75°C 暂停、65°C 恢复。

确认：

```bash
systemctl is-enabled opengrid-shadow opengrid-thermal-guard
systemctl is-active opengrid-shadow opengrid-thermal-guard
```

正常关机后再次上电，这两个服务会自动启动，不需要先连接电脑。

## 2. 常用操作

```bash
# 状态
systemctl status opengrid-shadow --no-pager

# 修改配置后重启
sudo systemctl restart opengrid-shadow

# 临时停止/启动
sudo systemctl stop opengrid-shadow
sudo systemctl start opengrid-shadow

# 实时日志
journalctl -u opengrid-shadow -f

# 温控日志
journalctl -u opengrid-thermal-guard -f
```

## 3. 安全重启和关机

```bash
sudo reboot
sudo poweroff
```

执行关机后等待系统停止、树莓派活动灯停止闪烁，再断电。不要直接反复拔电，否则 SD 卡文件系统可能损坏。

## 4. 查看温度与降频状态

```bash
vcgencmd measure_temp
vcgencmd get_throttled
```

温控达到 75°C 会停止主服务，此时网页和灯板会暂停；降至 65°C 自动恢复。软件保护不能替代散热片、风扇和通风。`get_throttled` 非零时应依据 Raspberry Pi 文档解读欠压/过热历史位，并检查电源与散热。

## 5. 更新代码

先备份现场配置：

```bash
cp ~/opengrid-shadow/config.json ~/opengrid-shadow/config.json.backup
```

在仓库目录更新并重新运行安装脚本：

```bash
git pull --ff-only
sudo ./install_on_pi.sh "$USER"
```

安装器保留已有 `config.json`。更新后检查日志、FPS、12 个地址和按键涟漪。

## 6. 换 SD 卡恢复

1. 用 Raspberry Pi Imager 安装新的 Raspberry Pi OS Lite，设置网络和 SSH。
2. 克隆本仓库。
3. 运行 `sudo ./install_on_pi.sh "$USER"`。
4. 把备份的 `config.json` 放到 `~/opengrid-shadow/config.json`。
5. 确认文件所有者为当前用户。
6. 执行 `sudo reboot`。
7. 逐项做地址、网页、FPS、温度和按键验收。

真正需要备份的是配置和任何现场参数，不需要备份 `.venv`、缓存、日志或操作系统生成文件。

## 7. 建议的展览开关机流程

开机：先确认配电与信号线，给灯板电源和树莓派上电，等待约一分钟，然后从网页检查状态。关机：通过 SSH 或现场按钮触发 `sudo poweroff`，待树莓派停止后再切断总电源。

长期运行建议每天检查一次温度、欠压状态、日志中的 I²C 重连和最远端板卡电压。
