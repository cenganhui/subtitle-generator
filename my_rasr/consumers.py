import logging
import threading
import uuid

import pyaudio
import websocket
from channels.generic.websocket import WebsocketConsumer
import json

# 控制死循环标志
flag1 = True
# 控制消息更新标志
flag = False
# 消息
result = {}


class ChatConsumer(WebsocketConsumer):
    def connect(self):
        self.accept()

    def disconnect(self, code):
        pass

    def receive(self, text_data=None):
        global flag1
        global flag
        text_data_json = json.loads(text_data)
        print(text_data_json)
        # message = text_data_json['message']
        message = chat_code_to_msg(text_data_json['code'], text_data_json['msg'])

        # 若是201，执行语音识别
        if message['code'] == 201:
            self.send(text_data=json.dumps(message))
            threading.Thread(target=baidu_go).start()
            # 循环判断消息更新并推送到前端
            while flag1:
                if flag:
                    self.send(text_data=json.dumps(result))
                    flag = False
            flag1 = True
        else:
            self.send(text_data=json.dumps(message))


def chat_code_to_msg(code, msg):
    if code == 200:
        res = {
            'code': 200,
            'message': "I am server!"
        }
        return res
    if code == 201:
        res = {
            'code': 201,
            'message': "go!"
        }
        return res
    if code == 888:
        res = {
            'code': 888,
            'message': "Good Bye!"
        }
        return res


logger = logging.getLogger()


def send_start_params(ws):
    """
    开始参数帧
    :param websocket.WebSocket ws:
    :return:
    """
    req = {
        "type": "START",
        "data": {
            "appid": 21967891,
            "appkey": "6vrWBXxGPCm08nDzfsjFdNd3",
            "dev_pid": 15372,  # 识别模型
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

    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000
    RECORD_SECONDS = 20
    p = pyaudio.PyAudio()

    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    print('*' * 10, '开始录音')
    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK)
        ws.send(data, websocket.ABNF.OPCODE_BINARY)

    print('*' * 10, '录音结束\n')
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
        send_start_params(ws)
        send_audio(ws)
        send_finish(ws)
        # logger.debug("thread terminating")

    threading.Thread(target=run).start()


def on_message(ws, message):
    """
    接收服务端返回的消息
    :param ws:
    :param message: json 格式，可自行解析
    :return:
    """
    text_message = json.loads(message)
    global flag
    global result
    # 若为一句话结束，则更新消息
    if text_message['type'] == 'FIN_TEXT':
        logger.info("Response: " + text_message['result'])
        res = {
            'code': 200,
            'message': text_message['result']
        }
        print(res)
        flag = True
        result = res
        # ChatConsumer.send(text_data=json.dumps(res))
    else:
        flag = False
    # logger.info("Response: " + message)


def on_error(ws, error):
    """
    库的报错信息
    :param ws:
    :param error: json 格式，可自行解析
    :return:
    """
    logger.error("error: " + str(error))


def on_close(ws):
    """
    WebSocket 关闭
    :param websocket.WebSocket ws:
    :return:
    """
    logger.info("ws close ...")
    ws.close()
    # 关闭时重置标志
    global flag1
    global flag
    flag1 = False
    flag = False

# 调用百度语音识别api
def baidu_go():
    logging.basicConfig(format="[%(asctime)-15s] [%(funcName)s()][%(levelname)s] %(message)s")
    logger.setLevel(logging.DEBUG)  # 调整为logging.INFO，日志会少一点
    # logger.info("begin")
    # websocket.enableTrace(True)
    # uri = const.URI + "?sn=" + str(uuid.uuid1())
    uri = "ws://vop.baidu.com/realtime_asr" + "?sn=" + str(uuid.uuid1())
    # logger.info("uri is " + uri)
    ws_app = websocket.WebSocketApp(uri,
                                    on_open=on_open,  # 连接建立后的回调
                                    on_message=on_message,  # 接收消息的回调
                                    on_error=on_error,  # 库遇见错误的回调
                                    on_close=on_close)  # 关闭后的回调

    ws_app.run_forever()
