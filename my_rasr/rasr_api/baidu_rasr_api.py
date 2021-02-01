import json
import logging
import threading
import uuid

import pyaudio
import websocket
from channels.generic.websocket import WebsocketConsumer

import my_rasr.const

# 控制死循环标志
cycle_sign = True
# 控制消息更新标志
response_sign = False
# 消息
result = {}
# ws断开连接标志
disconnect_sign = False

# 百度
# 鉴权信息
baidu_appid = 1
baidu_appkey = ""
# 语音模型，可以修改为其他语音模型测试
baidu_dev_pid = 1


class BaiduResponseConsumer(WebsocketConsumer):
    def connect(self):
        self.accept()

    def disconnect(self, code):
        global disconnect_sign
        disconnect_sign = True
        # print(code)
        # print("disconnect")
        # pass

    def receive(self, text_data=None):
        global cycle_sign
        global response_sign
        global baidu_appid, baidu_appkey, baidu_dev_pid
        text_data_json = json.loads(text_data)
        # print(text_data_json)
        message = process_message(text_data_json)

        # 若是201，获取鉴权信息，执行语音识别
        if message["code"] == 201:
            baidu_appid = message["appid"]
            baidu_appkey = message["appkey"]
            baidu_dev_pid = message["dev_pid"]
            self.send(text_data=json.dumps(message))
            # 开启线程调用识别方法
            baidu_rasr_go_thread = threading.Thread(target=baidu_rasr_go)
            baidu_rasr_go_thread.start()

            def do_cycle():
                """
                循环判断消息更新并推送到前端
                :return:
                """
                global cycle_sign
                global response_sign
                while cycle_sign:
                    if response_sign:
                        self.send(text_data=json.dumps(result))
                        response_sign = False
                cycle_sign = True
                self.send(text_data=json.dumps(end_message()))

            # 开启线程执行消息推送
            do_cycle_thread = threading.Thread(target=do_cycle)
            do_cycle_thread.start()
        # 若是888，则断开ws
        elif message["code"] == 888:
            self.send(text_data=json.dumps(message))
            self.close()
        # 否则返回处理后的消息
        else:
            self.send(text_data=json.dumps(message))


def process_message(text_data_json):
    """
    处理前端发送的消息
    :param text_data_json: 前端发送过来的json
    :return: 返回给前端对应json
    """
    code = text_data_json["code"]
    msg = text_data_json["msg"]
    # 200 表示前端请求连接ws
    if code == 200:
        res = {
            "code": 200,
            "message": "connected!"
        }
        return res
    # 201 表示前端请求执行实时语音识别
    if code == 201:
        res = {
            "code": 201,
            "message": "go!",
            "appid": text_data_json["appid"],
            "appkey": text_data_json["appkey"],
            "dev_pid": text_data_json["dev_pid"]
        }
        return res
    # 888 表示前端请求断开ws
    if code == 888:
        res = {
            "code": 888,
            "message": "bye!"
        }
        return res


def end_message():
    """
    识别结束消息
    :return: res
    """
    res = {
        "code": 202,
        "message": "finish!"
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
            "appid": int(baidu_appid),
            "appkey": baidu_appkey,
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
    CHUNK = 1024  # 数据块大小
    FORMAT = pyaudio.paInt16  # 16bit编码格式
    CHANNELS = 1  # 单声道
    RATE = 16000  # 16000采样频率
    RECORD_SECONDS = 30  # 录音时间
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
        ws.send(data, websocket.ABNF.OPCODE_BINARY)
    disconnect_sign = False
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
    text_message = json.loads(message)
    global response_sign
    global result
    # 若为一句话结束，则更新消息
    if text_message['type'] == 'FIN_TEXT':
        # logger.info("Response: " + text_message['result'])
        res = {
            'code': 200,
            'message': text_message['result']
        }
        print(res)
        response_sign = True
        result = res
        # ChatConsumer.send(text_data=json.dumps(res))
    else:
        response_sign = False
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
    global cycle_sign
    global response_sign
    global result
    cycle_sign = False
    response_sign = False
    result = {}


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
