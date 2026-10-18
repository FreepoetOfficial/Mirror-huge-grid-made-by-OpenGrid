# 配置字段完整说明

运行配置位于树莓派的 `~/opengrid-shadow/config.json`。修改后执行 `sudo systemctl restart opengrid-shadow`。JSON 不支持注释，逗号也必须合法。

## camera

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `mode` | `auto` | 依次尝试 Picamera2、OpenCV，最后模拟源；实机可设 `picamera2` 让相机错误直接暴露 |
| `index` | 0 | USB/OpenCV 相机序号 |
| `width`, `height` | 320, 240 | 采集分辨率；Pi 4B 1 GB 不宜盲目增大 |
| `fps` | 12 | 目标帧率，当前温度与 I²C 带宽折中 |

## processing

| 字段 | 默认值 | 作用与调节方向 |
|---|---:|---|
| `threshold` | 40 | 基础背景差阈值；增大可减少噪点，但会漏掉低对比物体 |
| `adaptive_threshold` | true | 根据当前噪声自动提高阈值 |
| `noise_sigma` | 6.0 | 噪声对阈值的权重 |
| `hysteresis_ratio` | 0.65 | 弱边缘阈值相对强阈值的比例 |
| `max_brightness_shift` | 35 | 可补偿的整体亮度偏移上限 |
| `min_area_ratio` | 0.025 | 主体最小画面占比；增大可去小噪声 |
| `calibration_seconds` | 4.0 | 启动空场背景学习时间 |
| `background_learning_rate` | 0.001 | 背景慢速更新；大则适应快，也更容易吞掉静止人物 |
| `stationary_timeout_seconds` | 10.0 | 固定残留满足重建条件的累计时间 |
| `stationary_motion_ratio` | 0.003 | 判为静止的连通域内部运动上限 |
| `stationary_iou` | 0.92 | 与前一主体高度重合的阈值 |
| `stationary_decay_multiplier` | 2.0 | 判定固定残留后的加速渐弱倍数 |
| `rise_ms` | 160 | 新剪影渐亮时间 |
| `fall_ms` | 550 | 剪影离开后的渐弱时间 |
| `edge_blur` | 3 | 缩小前边缘平滑尺度 |
| `pixel_on_threshold` | 0.35 | 24×32 像素判定点亮的覆盖阈值 |
| `edge_min_brightness` | 0.28 | 剪影边缘最低相对亮度 |
| `depth_gradient_pixels` | 6.0 | 从边缘到满亮的内部距离 |
| `output_cutoff` | 0.10 | 低于此归零，防止微弱尾影 |
| `gamma` | 1.0 | 亮度曲线；大于 1 压暗中间层，小于 1 提亮中间层 |
| `max_level` | 15 | 官方硬件最大亮度级；范围 0–15 |
| `mirror` | true | 水平镜像，使画面像镜子 |

## hardware

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | false | 是否启用实体 I²C 输出 |
| `driver` | `i2c` | 当前硬件驱动 |
| `i2c_bus` | 1 | `/dev/i2c-1` |
| `reconnect_seconds` | 2.0 | 离线板重试间隔 |
| `layout` | 4×3 地址矩阵 | 每项就是该物理位置的实测地址；行对应从上到下，列对应从左到右 |
| `board_rotations` | 全部 270 | 每块内容顺时针旋转角度，可用 0/90/180/270 |

地址可以写十六进制字符串（如 `"0x27"`）或四位地址位字符串（如 `"0111"`，解析为 `0x20 + 二进制值`）。由于当前装置的实测对应关系特殊，建议直接保留十六进制地址。

## hardware.ripple

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | true | 是否开启按键涟漪 |
| `boards_per_frame` | 4 | 每个视频帧轮询几块板；越大响应越快但 I²C 负载越高 |
| `key_cooldown_seconds` | 0.25 | 同一按键重复触发间隔 |
| `duration_seconds` | 5.0 | 单次涟漪最长寿命 |
| `speed_pixels_per_second` | 8.5 | 波前传播速度 |
| `wavelength_pixels` | 5.0 | 环间距 |
| `ring_width_pixels` | 5.5 | 环带宽度/柔和度 |
| `strength` | 0.72 | 暗背景上的涟漪发光强度 |
| `image_modulation` | 0.42 | 对原摄像头剪影亮度的扰动强度 |
| `attack_seconds` | 0.12 | 按下后渐亮时间 |
| `decay_seconds` | 3.2 | 衰减时间常数 |
| `max_active` | 8 | 同时保留的最多涟漪数 |

## web

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `host` | `0.0.0.0` | 监听所有网卡，使局域网设备可访问 |
| `port` | 8080 | HTTP 端口 |

网页接口没有账号认证，不应直接暴露到公网。展览网络建议使用隔离的局域网或防火墙限制访问。
