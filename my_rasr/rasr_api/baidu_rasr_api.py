import json
import logging
import math
import threading
import time
import uuid

import pyaudio
import websocket
from channels.generic.websocket import WebsocketConsumer

import my_rasr.const
from .process_ws_message import process_message, end_message
from .realtime_noise_reduce import process_noise_data, np_audioop_rms

# 消息
result = ""
# 识别结束标志
finished_sign = False
# ws断开连接标志
disconnect_sign = False

# 百度
# 鉴权信息
baidu_app_id = 1
baidu_app_key = ""
# 语音模型，可以修改为其他语音模型测试
baidu_dev_pid = 1


class BaiduResponseConsumer(WebsocketConsumer):
    def connect(self):
        # ws连接时设置
        global finished_sign, disconnect_sign, result
        finished_sign = False
        disconnect_sign = False
        result = ""
        self.accept()

    def disconnect(self, code):
        # ws断开后设置
        global finished_sign, disconnect_sign
        finished_sign = True
        disconnect_sign = True
        # print(code)
        # print("disconnect")
        # pass

    def receive(self, text_data=None):
        global baidu_app_id, baidu_app_key, baidu_dev_pid
        text_data_json = json.loads(text_data)
        # print(text_data_json)
        message = process_message(text_data_json)

        # 若是201，获取鉴权信息，执行语音识别
        if message["code"] == 201:
            # 获取鉴权信息
            baidu_app_id = message["auth"]["app_id"]
            baidu_app_key = message["auth"]["app_key"]
            baidu_dev_pid = message["auth"]["dev_pid"]
            # 开启线程调用识别方法
            baidu_rasr_go_thread = threading.Thread(target=baidu_rasr_go)
            baidu_rasr_go_thread.start()
            # 通知前端开始调用识别
            self.send(text_data=json.dumps(message))
        # 若是202，返回识别内容
        elif message["code"] == 202:
            message["result"] = result
            # 如果识别结束，发送识别结束消息
            if finished_sign:
                res = end_message()
                res["result"] = result
                self.send(text_data=json.dumps(res))
            else:
                self.send(text_data=json.dumps(message))
        # 若是888，则断开ws
        elif message["code"] == 888:
            self.send(text_data=json.dumps(message))
            self.close()
        # 否则返回处理后的消息
        else:
            self.send(text_data=json.dumps(message))


logger = logging.getLogger()  # 日志


def send_start_params(ws):
    """
    开始参数帧
    :param websocket.WebSocket ws:
    :return:
    """
    req = {
        "type": "START",
        "data": {
            "appid": int(baidu_app_id),
            "appkey": baidu_app_key,
            "dev_pid": int(baidu_dev_pid),  # 识别模型
            "cuid": uuid.uuid1().hex[-12:],  # 随便填不影响使用。机器的mac或者其它唯一id，百度计算UV用。
            "sample": 16000,  # 固定参数
            "format": 'pcm'  # 固定参数
        }
    }
    body = json.dumps(req)
    ws.send(body, websocket.ABNF.OPCODE_TEXT)
    # logger.info("send START frame with params:" + body)


def send_audio(ws):
    """
    发送二进制音频数据，注意每个帧之间需要有间隔时间
    :param websocket.WebSocket ws:
    :return:
    """
    global disconnect_sign
    global finished_sign
    global result
    disconnect_sign = False
    finished_sign = False
    result = ""
    CHUNK = 1024  # 数据块大小
    FORMAT = pyaudio.paInt16  # 16bit编码格式
    CHANNELS = 1  # 单声道
    RATE = 16000  # 16000采样频率
    RECORD_SECONDS = 20  # 录音时间

    WIDTH = 2
    THRESH = -55
    NOISE_LEN = 16

    noise = []

    lThresh = time.time() - 1
    avgQuiet = -60

    p = pyaudio.PyAudio()
    # 创建音频流
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    print('*' * 10, '开始录音识别', '*' * 10)
    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        # 判断ws是否断开，若断开则中断录音识别
        if disconnect_sign:
            break
        data = stream.read(CHUNK)

        # process
        level = np_audioop_rms(data, WIDTH)
        if level:
            level = 20 * math.log10(level) - 100
        else:
            level = -101

        # gather the samples that represent noise
        # always be updating in case of bad samples
        if level < THRESH:
            if time.time() - lThresh > 1:  # time to delay after the last time the threshold was reached before stopping transmission
                avgQuiet = (avgQuiet * (
                        NOISE_LEN - 1) + level) / NOISE_LEN  # moving average of the volume of the noise
                if level < avgQuiet:
                    noise.append(data)
                    if len(noise) > NOISE_LEN:
                        noise.pop(0)
        else:
            lThresh = time.time()

        data = process_noise_data(CHUNK, data, noise)

        ws.send(data, websocket.ABNF.OPCODE_BINARY)
    print('*' * 10, '录音识别结束', '*' * 10)

    stream.stop_stream()
    stream.close()
    p.terminate()


def send_finish(ws):
    """
    发送结束帧
    :param websocket.WebSocket ws:
    :return:
    """
    req = {
        "type": "FINISH"
    }
    body = json.dumps(req)
    ws.send(body, websocket.ABNF.OPCODE_TEXT)
    # logger.info("send FINISH frame")


def send_cancel(ws):
    """
    发送取消帧
    :param websocket.WebSocket ws:
    :return:
    """
    req = {
        "type": "CANCEL"
    }
    body = json.dumps(req)
    ws.send(body, websocket.ABNF.OPCODE_TEXT)
    # logger.info("send CANCEL frame")


def on_open(ws):
    """
    连接后发送数据帧
    :param websocket.WebSocket ws:
    :return:
    """

    def run(*args):
        """
        发送数据帧
        :param args:
        :return:
        """
        send_start_params(ws)  # 开始帧
        send_audio(ws)  # 中间帧
        send_finish(ws)  # 结束帧
        # logger.debug("thread terminating")

    threading.Thread(target=run).start()


def on_message(ws, message):
    """
    接收服务端返回的消息
    :param ws:
    :param message: json 格式，可自行解析
    :return:
    """
    global result
    text_message = json.loads(message)
    # 若为一句话结束，则更新消息
    if text_message['type'] == 'FIN_TEXT':
        # logger.info("Response: " + text_message['result'])
        print("识别结果：" + text_message['result'])
        # 拼接识别结果
        result += text_message['result']
    # logger.info("Response: " + message)


def on_error(ws, error):
    """
    库的报错信息
    :param ws:
    :param error: json 格式，可自行解析
    :return:
    """
    logger.error("error: " + str(error))
    # 关闭时重置标志
    global finished_sign
    # 识别结束
    finished_sign = True


def on_close(ws):
    """
    WebSocket 关闭
    :param websocket.WebSocket ws:
    :return:
    """
    logger.info("ws close ...")
    ws.close()
    # 关闭时重置标志
    global finished_sign
    # 识别结束
    finished_sign = True


def baidu_rasr_go():
    """
    调用百度语音识别api
    :return:
    """
    logging.basicConfig(format="[%(asctime)-15s] [%(funcName)s()][%(levelname)s] %(message)s")  # 设置日志打印格式
    logger.setLevel(logging.INFO)  # 调整为logging.INFO，日志会少一点
    # logger.info("begin")
    # websocket.enableTrace(True)
    # 拼接uri
    uri = my_rasr.const.BAIDU_URI + "?sn=" + str(uuid.uuid1())
    # logger.info("uri is " + uri)
    ws_app = websocket.WebSocketApp(uri,
                                    on_open=on_open,  # 连接建立后的回调
                                    on_message=on_message,  # 接收消息的回调
                                    on_error=on_error,  # 库遇见错误的回调
                                    on_close=on_close)  # 关闭后的回调

    ws_app.run_forever()
