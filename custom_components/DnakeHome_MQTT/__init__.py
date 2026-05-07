import logging
import json
import uuid
import asyncio
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from homeassistant.core import HomeAssistant
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval
from .constant import *

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry):

    """设置集成"""

    manager = DnakeMqttManager(hass, entry)

    if not await manager.async_init():
        return False

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager

    await hass.config_entries.async_forward_entry_setups(entry, ["fan", "climate", "sensor"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry):
    """卸载集成"""
    manager = hass.data[DOMAIN].pop(entry.entry_id)
    return await manager.async_clear()


class DnakeMqttManager:
    """MQTT 管理类，封装所有回调与发送逻辑"""

    def __init__(self, hass: HomeAssistant, entry):
        self.hass = hass
        self.entry = entry
        self.mqtt_url = entry.data[CONF_BROKER]
        self.mqtt_port = entry.data[CONF_PORT]
        self.sub_topic = entry.data[CONF_SUB_TOPIC]
        self.pub_topic = entry.data[CONF_PUB_TOPIC]
        self.client = mqtt.Client(CallbackAPIVersion.VERSION2)

        self.gateway = entry.data[CONF_GATEWAY]
        self.display = entry.data[CONF_DISPLAY]
        self.account = entry.data[CONF_ACCOUNT]

        self._connected = False
        self._connected_event = asyncio.Event()
        self._reconnect_lock = asyncio.Lock()

        # 绑定回调
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_publish = self._on_publish

        # 定时任务
        self._remove_heartbeat = None

    async def async_init(self):
        """初始化连接"""
        try:
            self.client.reconnect_delay_set(min_delay=1, max_delay=60)
            self.client.loop_start()
            await self.hass.async_add_executor_job(
                self.client.connect,
                self.mqtt_url,
                self.mqtt_port,
                60
            )

            await self._wait_until_connected(timeout=10)

            # --- 启动每分钟一次的定时任务 ---
            self._remove_heartbeat = async_track_time_interval(
                self.hass,
                self._async_heartbeat_callback,
                timedelta(minutes=1)
            )

            _LOGGER.info("✅ MQTT 客户端已启动并尝试连接...")
            return True
        except Exception as e:
            _LOGGER.error("❌ 无法启动 MQTT 客户端: %s", e)
            return False

    async def _wait_until_connected(self, timeout: float):
        if self._connected:
            return
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            _LOGGER.warning("⚠️ MQTT 在 %ss 内未确认连接成功，后续发送将触发自动重连", timeout)

    def _set_connected_state(self, connected: bool):
        self._connected = connected
        if connected:
            self._connected_event.set()
        else:
            self._connected_event.clear()

    async def _ensure_connected(self) -> bool:
        if self._connected:
            return True

        async with self._reconnect_lock:
            if self._connected:
                return True

            self._connected_event.clear()
            try:
                await self.hass.async_add_executor_job(self.client.reconnect)
            except Exception:
                try:
                    await self.hass.async_add_executor_job(
                        self.client.connect,
                        self.mqtt_url,
                        self.mqtt_port,
                        60
                    )
                except Exception as e:
                    _LOGGER.error("❌ MQTT 重连失败: %s", e)
                    return False

            try:
                await asyncio.wait_for(self._connected_event.wait(), timeout=10)
                return True
            except asyncio.TimeoutError:
                _LOGGER.error("❌ MQTT 重连超时，仍未连接到 Broker")
                return False

    async def _async_heartbeat_callback(self, _now):
        """定时任务回调函数"""
        # 构建你想要发送的消息

        current_devices = dict(self.entry.data.get("devices", {}))

        new_device_map = {dev_no: info.get("type") for dev_no, info in current_devices.items()}

        # 2. 组装目标列表
        device_list = [
            {
                "devType": 0,
                "devNo": int(dev_no),  # 如果你的 MQTT 协议要求 devNo 是数字，这里转成 int
                "devCh": 3 if dev_type == 2048 else 1
            }
            for dev_no, dev_type in new_device_map.items()
        ]

        # 3. 打印或使用结果
        _LOGGER.debug("组装后的设备列表: %s", device_list)

        payload = {
            "fromDev": self.account,
            "toDev": self.gateway,
            "data": {
                "devList": device_list,
                "action": "readDev",
                "cmd": "AirFresh",
                "uuid": uuid.uuid4().hex
            }
        }


        _LOGGER.debug("正在执行定时任务：查询设备信息")
        await self.async_publish(self.sub_topic, json.dumps(payload))

    async def async_clear(self):
        """断开连接"""
        _LOGGER.info("正在停止 MQTT 客户端...")
        if self._remove_heartbeat is not None:
            self._remove_heartbeat()
            self._remove_heartbeat = None
        await self.hass.async_add_executor_job(self.client.loop_stop)
        await self.hass.async_add_executor_job(self.client.disconnect)
        return True

    async def async_publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False):
        """通用发送接口"""
        _LOGGER.info("🚀 准备下发 MQTT: 主题=%s, 内容=%s", topic, payload)
        try:
            if not await self._ensure_connected():
                _LOGGER.error("❌ 消息推送失败，MQTT 未连接")
                return False
            result = await self.hass.async_add_executor_job(
                self.client.publish, topic, payload.encode('utf-8'), qos, retain
            )
            if result.rc != 0:
                _LOGGER.error("❌ 消息推送失败，错误码: %s", result.rc)
            return result.rc == 0
        except Exception as e:
            _LOGGER.error("❌ 调用 publish 时发生异常: %s", e)
            return False

    def _on_connect(self, client, userdata, flags, rc, properties=None):

        _LOGGER.info("🔔 MQTT on_connect 触发! rc=%s", rc)
        if rc == 0:
            _LOGGER.info("✅ SUCCESS: 成功连接到 Broker [%s]", self.mqtt_url)
            client.subscribe(self.pub_topic)
            _LOGGER.info("已订阅 Topic: %s", self.pub_topic)
            client.subscribe(self.sub_topic)
            _LOGGER.info("已订阅 Topic: %s", self.sub_topic)
            self.hass.loop.call_soon_threadsafe(self._set_connected_state, True)
        else:
            _LOGGER.error("❌ ERROR: 连接失败，原因码: %s", rc)
            self.hass.loop.call_soon_threadsafe(self._set_connected_state, False)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        _LOGGER.warning("🔌 MQTT 已断开连接: reason=%s flags=%s", reason_code, disconnect_flags)
        self.hass.loop.call_soon_threadsafe(self._set_connected_state, False)

    def _on_message(self, client, userdata, msg):

        try:
            payload = json.loads(msg.payload.decode())

            # 身份校验
            if (payload.get("fromDev", "") != self.gateway or
                    payload.get("toDev", "") not in [self.display, self.account]):
                return

            data = payload.get("data", {})
            if data.get("action", "") == "cmtDevInfo":

                dev_list = data.get("devList", [])

                current_devices = dict(self.entry.data.get("devices", {}))
                config_updated = False

                for dev_item in dev_list:
                    dtype = dev_item.get("devType")
                    dno = str(dev_item.get("devNo"))  # JSON Key 建议用字符串
                    reports = dev_item.get("reports", {})

                    if dno == '73':
                        _LOGGER.info("北卧空调: %s , reports: %s", dno, reports)

                    # 1. 如果是支持的设备类型，且不在配置中
                    if dtype in DEVICE_TYPE_MAP and dno not in current_devices:
                        _LOGGER.info("✨ 发现新设备: %s (类型: %s)", dno, dtype)

                        device_info = {
                            "type": dtype,
                            "platform": DEVICE_TYPE_MAP[dtype]["platform"],
                            "name": f"Dnake_{DEVICE_TYPE_MAP[dtype]['name']}_{dno}"
                        }

                        # 存入配置，以便下次重启自动加载
                        current_devices[dno] = device_info
                        config_updated = True

                        # 2. 发出动态发现事件，通知 fan.py 等平台立即加载
                        self.hass.loop.call_soon_threadsafe(
                            self.hass.bus.async_fire,
                            EVENT_NEW_DEVICE,
                            {
                                "platform": DEVICE_TYPE_MAP[dtype]["platform"],
                                "devNo": int(dno),
                                "devType": int(dtype),
                                "type": dtype,
                                "name": f"Dnake_{DEVICE_TYPE_MAP[dtype]['name']}_{dno}"
                            }
                        )

                    # 3. 无论是否是新设备，都发送状态更新事件（给已经存在的实体更新 UI）
                    if reports:

                        # # 定义一个闭包函数，在内部按照标准方式调用
                        # def safe_update_status():
                        #     self.hass.bus.async_fire(f"{DOMAIN}_update_{dno}", {"reports": reports})
                        #
                        # self.hass.loop.call_soon_threadsafe(safe_update_status)
                        reports_copy = dict(reports)
                        self.hass.loop.call_soon_threadsafe(
                            self.hass.bus.async_fire,
                            f"{DOMAIN}_update_{dno}",
                            {"reports": reports_copy}
                        )


                # 4. 如果发现了新设备，更新持久化配置
                if config_updated:
                    _LOGGER.info("💾 正在持久化新发现的设备列表...")

                    # 定义一个闭包函数，在内部按照标准方式调用
                    def safe_update():
                        self.hass.config_entries.async_update_entry(
                            self.entry,
                            data={**self.entry.data, "devices": current_devices}
                        )

                    # 将这个不带参数的任务投递到主线程，由主线程自己去执行闭包里的逻辑
                    self.hass.loop.call_soon_threadsafe(safe_update)
            elif data.get("devList", []):
                dev_list = data.get("devList", [])
                for dev_item in dev_list:
                    dno = str(dev_item.get("devNo"))  # JSON Key 建议用字符串
                    reports = dev_item.get("reports", {})
                    if reports:

                        reports_copy = dict(reports)
                        self.hass.loop.call_soon_threadsafe(
                            self.hass.bus.async_fire,
                            f"{DOMAIN}_update_{dno}",
                            {"reports": reports_copy}
                        )

        except Exception as e:
            _LOGGER.error("解析上报报文异常: %s", e)

    def _on_publish(self, client, userdata, mid, reason_code=None, properties=None):
        _LOGGER.debug("🚀 [确认] 消息已送达 Broker，ID: %s", mid)
