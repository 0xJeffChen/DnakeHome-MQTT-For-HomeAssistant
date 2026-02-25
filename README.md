# DnakeHome-MQTT-For-HomeAssistant

DnakeHome (MQTT) 插件为 Home Assistant 提供了对 Dnake 智能家居设备的本地 MQTT 控制支持。

## 🌟 功能特性

该插件支持通过 MQTT 协议发现并控制以下类型的 Dnake 设备：

- 🌡️ **空调 (Climate)**: 支持模式切换、温度调节及风速控制。
- ♨️ **地暖 (Climate/Heater)**: 支持开关及目标温度设置。
- 🌀 **新风 (Fan)**: 支持开关、风速调节及预设模式。
- 🌬️ **空气盒子 (Sensor)**: 实时监测以下指标：
  - 温度 (°C)
  - 湿度 (%)
  - PM2.5 (μg/m³)
  - PM1.0 (μg/m³)
  - PM10 (μg/m³)

## 🚀 安装指南

### 手动安装

1. 下载此仓库的源代码。
2. 将 `custom_components/DnakeHome_MQTT` 文件夹拷贝到你 Home Assistant 配置目录下的 `custom_components` 文件夹中。
3. 重启 Home Assistant。

## ⚙️ 配置说明

在 Home Assistant UI 中通过以下步骤添加集成：

1. 进入 **配置** > **设备与服务**。
2. 点击右下角的 **添加集成**。
3. 搜索 `DnakeHome_Mqtt` 并点击。
4. 在弹出的配置窗口中填写以下信息：
   - **Broker**: MQTT 服务器地址（默认：`192.168.5.100`）
   - **Port**: MQTT 端口（默认：`1883`）
   - **Subscribe Topic**: 订阅主题
   - **Publish Topic**: 发布主题
   - **Account**: 账号信息
   - **Gateway**: 网关 ID
   - **Display**: 显示设备 ID

## 📡 技术细节

- **IoT 类别**: `local_push` (本地推送，实时性高)。
- **依赖库**: `paho-mqtt>=2.1.0`。
- **设备自动发现**: 插件会自动监听 MQTT 消息并根据设备类型映射表发现新设备。

### 设备类型映射

| 设备类型 ID | 平台 | 描述 |
| :--- | :--- | :--- |
| 1536 | `climate` | 空调 |
| 2048 | `climate` | 地暖 |
| 1792 | `fan` | 新风 |
| 3077 | `sensor` | 空气盒子 |

## 🤝 贡献与反馈

如果你在使用过程中遇到问题或有功能改进建议，欢迎提交 Issue 或 Pull Request。

---
**Maintainer**: [@chenzf](https://github.com/0xJeffChen)
