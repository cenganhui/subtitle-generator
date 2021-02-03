import hashlib
import json
import logging
import threading
import time
import uuid

import pyaudio
import websocket
from channels.generic.websocket import WebsocketConsumer

import my_rasr.const
from .process_ws_message import process_message, end_message

# 控制死循环标志
cycle_sign = True
# 控制消息更新标志
response_sign = False
# 消息
result = {}
# ws断开连接标志
disconnect_sign = False

# 有道
# 鉴权信息
youdao_app_key = ""
youdao_app_secret = ""
# 语言选择，参考支持语言列表
youdao_lang_type = ""


class YoudaoResponseConsumer(WebsocketConsumer):
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
        global youdao_app_key, youdao_app_secret, youdao_lang_type
        text_data_json = json.loads(text_data)
        # print(text_data_json)
        message = process_message(text_data_json)

        # 若是201，获取鉴权信息，执行语音识别
        if message["code"] == 201:
            # 获取鉴权信息
            youdao_app_key = message["auth"]["app_key"]
            youdao_app_secret = message["auth"]["app_secret"]
            youdao_lang_type = message["auth"]["lang_type"]
            # 开启线程调用识别方法
            youdao_rasr_go_thread = threading.Thread(target=youdao_rasr_go)
            youdao_rasr_go_thread.start()
            # 通知前端开始调用识别
            self.send(text_data=json.dumps(message))

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


logger = logging.getLogger()  # 日志


def initUri():
    """
    创建请求uri
    :return:
    """
    nonce = str(uuid.uuid1())
    curtime = str(int(time.time()))
    signStr = youdao_app_key + nonce + curtime + youdao_app_secret
    # print(signStr)
    sign = encrypt(signStr)

    uri = my_rasr.const.YOUDAO_URL + "?"
    uri += "appKey=" + youdao_app_key
    uri += "&salt=" + nonce
    uri += "&curtime=" + curtime
    uri += "&sign=" + sign
    uri += "&version=v1&channel=1&format=wav&signType=v4&rate=16000&langType=" + youdao_lang_type
    print(uri)
    return uri


def encrypt(signStr):
    """
    签名
    :param signStr:
    :return:
    """
    hash = hashlib.sha256()
    hash.update(signStr.encode("utf-8"))
    return hash.hexdigest()


def send_audio(ws):
    """
    发送二进制音频数据
    :param ws:
    :return:
    """
    global disconnect_sign
    CHUNK = 1600  # 数据块大小
    FORMAT = pyaudio.paInt16  # 16bit编码格式
    CHANNELS = 1  # 单声道
    RATE = 16000  # 16000采样率
    RECORD_SECONDS = 60  # 录音时间
    p = pyaudio.PyAudio()
    # 创建音频流
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    print('*' * 10, '开始录音')
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
    发送结束标识
    :param ws:
    :return:
    """
    ws.send('{\"end\": \"true\"}', websocket.ABNF.OPCODE_BINARY)
    # logger.info("send FINISH frame")


def on_open(ws):
    """
    连接后发送数据
    :param ws:
    :return:
    """

    def run():
        """
        发送数据
        :return:
        """
        send_audio(ws)  # 音频数据
        send_finish(ws)  # 结束标识

    threading.Thread(target=run).start()


def on_message(ws, message):
    """
    接收服务端返回的消息
    :param ws:
    :param message:
    :return:
    """
    global response_sign
    global result
    # 若返回为空，直接return
    if len(message) == 0:
        return
    # 返回内容转字典并进行解析
    result_dict = json.loads(message)
    # 与服务器建立连接
    if result_dict["action"] == "started":
        print("handshake success, result: " + message)
    # 服务器返回的识别内容
    if result_dict["action"] == "recognition":
        # 进一步解析
        result_result = result_dict["result"]
        if len(result_result) != 0:
            for item in result_result:
                result_st = item["st"]
                # 若识别内容为一句话结束，则拼接句子并更新消息
                if result_st["type"] == 0:
                    sentence = result_st["sentence"]
                    res = {
                        "code": 202,
                        "msg": "server: sentence",
                        "result": sentence
                    }
                    print("识别结果：" + sentence)
                    response_sign = True
                    result = res
                else:
                    response_sign = False
        else:
            response_sign = False
    # 服务器返回错误，断开连接
    if result_dict["action"] == "error":
        print("rtasr error: " + message)
        ws.close()
        return


def on_error(ws, error):
    """
    库的报错信息
    :param ws:
    :param error: json 格式，可自行解析
    :return:
    """
    logger.error("error: " + str(error))
    ws.close()


def on_close(ws):
    logger.info("ws close ...")
    ws.close()
    # 关闭时重置标志
    global cycle_sign
    global response_sign
    global result
    cycle_sign = False
    response_sign = False
    result = {}


def youdao_rasr_go():
    """
    调用有道语音识别api
    :return:
    """
    logging.basicConfig(format="[%(asctime)-15s] [%(funcName)s()][%(levelname)s] %(message)s")
    logger.setLevel(logging.INFO)  # 调整为logging.INFO，日志会少一点
    uri = initUri()
    # logger.info("uri is " + uri)
    ws_app = websocket.WebSocketApp(uri,
                                    on_open=on_open,  # 连接建立后的回调
                                    on_message=on_message,  # 接收消息的回调
                                    on_error=on_error,  # 库遇见错误的回调
                                    on_close=on_close)  # 关闭后的回调

    ws_app.run_forever()
