# 故障排查

## 网页打不开

1. 确认地址是 `http://<树莓派IP>:8080/`，不是电脑自己的 `127.0.0.1`。
2. 检查服务：`systemctl status opengrid-shadow --no-pager`。
3. 在树莓派本机测试：`curl -v http://127.0.0.1:8080/api/state`。
4. 确认电脑和树莓派在同一网络且没有访客网络隔离。
5. 查看日志：`journalctl -u opengrid-shadow -n 100 --no-pager`。

直接打开 `static/index.html` 会停在“连接中”，因为页面依赖 `/api/state`、`/api/config` 和 `/api/stream`。

## SSH 显示 Connection refused

这发生在认证之前，通常是 SSH 服务未开启、IP 错误或该 IP 已被其他设备占用。接显示器后执行 `sudo systemctl enable --now ssh`，并从路由器重新确认 IP。若是密码错误，消息通常是 `Permission denied`。

## `i2cdetect` 没有任何板

- 确认 I²C 已启用，重启后存在 `/dev/i2c-1`。
- 检查 SDA/SCL 是否接反。
- 检查树莓派与灯板是否共地。
- 检查板卡 5 V 供电及极性。
- 测 SDA/SCL 空闲电压，应被上拉到约 3.3 V，而不是 5 V。
- 暂时只接一块板和短线排查。

## 少一两块板

单块缺失不应阻断其他板输出；驱动会让故障板离线并自动重试。检查缺失地址是否重复、该板供电、接插件、支路长度和压降。若地址能扫描但应用拒绝连接，查看日志中的协议版本、报告地址或 LED 数量错误。

## 一整列不亮

先用 `i2cdetect -y 1` 区分通信故障与布局故障。若三个/四个相应地址都存在，检查 `hardware.layout` 是否把这些地址放到了正确列，以及配电支路是否独立。不要只按地址位丝印推断。

## 网页正确、实体错位

这是 `layout` 或 `board_rotations` 问题。网页按全局 24×32 显示，实体输出会再切成 12 个 8×8。交换物理位置对应的地址，或只改变错误板的 0/90/180/270 旋转。

## 实体亮度层次少

- 查看供电压降与最大亮度时的电源能力。
- 确认代码和配置使用 0–15 亮度而不是二值。
- 调节 `edge_min_brightness`、`depth_gradient_pixels` 和 `gamma`。
- 真实 LED 的扩散片、观察距离和环境光会改变感知，网页圆点效果不会完全等同于实物。

## 有固定残影或散点

先在空场重新校准。然后稳定光源与摄像头，检查风吹物体/屏幕闪烁/反光。散点优先提高阈值或最小面积；固定残留再调静止重建与输出截止值。不要把 `fall_ms` 调得过大，否则正常离开的轮廓也会长时间保留。

## 摄像头变成 synthetic

`camera.mode: auto` 会在 Picamera2 打不开时尝试其他来源，最终回退到模拟画面。把 mode 临时设为 `picamera2` 并重启，日志会显示真实原因。检查 CSI 排线、摄像头探测和是否被另一个进程占用。

## 帧率明显低于 12 FPS

- 确认 `/boot/firmware/config.txt` 或 `/boot/config.txt` 含 `dtparam=i2c_arm=on,i2c_arm_baudrate=400000`，改后要重启。
- 检查 CPU 温度、降频和欠压。
- 降低 `boards_per_frame` 会减少按键读取负载，但增加交互延迟。
- 不要提高相机分辨率；此输出最终只有 24×32。
- 过长或电容过大的 I²C 总线可能无法稳定运行 400 kHz，稳定性优先时可降速并接受较低刷新率。

## 按键无涟漪

- 确认 `hardware.enabled` 和 `hardware.ripple.enabled` 都为 true。
- 查看 `/api/state` 的 `active_ripples` 是否按下后增加。
- 若网页有波、实体没有，排查 LED 写入/布局；若网页也没有，排查按键寄存器读取、板固件协议版本和按键坐标。
- 一直按住只产生一次上升沿事件；松开后再次按下才会新触发。

## 温度高时程序停止

这是设计行为。查看 `journalctl -u opengrid-thermal-guard -n 50 --no-pager`。75°C 停止主服务，65°C 恢复。若经常触发，应改善散热和通风，而不是简单关闭保护。

## 收集完整诊断信息

```bash
hostname -I
uname -a
rpicam-hello --list-cameras
i2cdetect -y 1
systemctl status opengrid-shadow opengrid-thermal-guard --no-pager
journalctl -u opengrid-shadow -n 150 --no-pager
journalctl -u opengrid-thermal-guard -n 50 --no-pager
vcgencmd measure_temp
vcgencmd get_throttled
curl -s http://127.0.0.1:8080/api/state
```

公开日志前删除 Wi-Fi 密码、用户名、公网地址和其他隐私数据。
