import hashlib
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

# 有道
# 鉴权信息
youdao_app_key = ""
youdao_app_secret = ""
# 语言选择，参考支持语言列表
youdao_lang_type = ""


class YoudaoResponseConsumer(WebsocketConsumer):
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
        global youdao_app_key, youdao_app_secret, youdao_lang_type
        text_data_json = json.loads(text_data)
        # print(text_data_json)
        message = process_message(text_data_json)

        # 若是201，获取鉴权信息，执行语音识别
        if message["code"] == 201:
            # 执行语音识别前重置相关标志
            global finished_sign, disconnect_sign, result
            finished_sign = False
            disconnect_sign = False
            result = ""
            # 获取鉴权信息
            youdao_app_key = message["auth"]["app_key"]
            youdao_app_secret = message["auth"]["app_secret"]
            youdao_lang_type = message["auth"]["lang_type"]
            # 开启线程调用识别方法
            youdao_rasr_go_thread = threading.Thread(target=youdao_rasr_go)
            youdao_rasr_go_thread.start()
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
    global finished_sign
    global result
    disconnect_sign = False
    finished_sign = False
    result = ""
    CHUNK = 1600  # 数据块大小
    FORMAT = pyaudio.paInt16  # 16bit编码格式
    CHANNELS = 1  # 单声道
    RATE = 16000  # 16000采样率
    RECORD_SECONDS = 10  # 录音时间

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

    print('*' * 10, '开始录音')
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
                    print("识别结果：" + sentence)
                    # 拼接识别结果
                    result += sentence
    # 服务器返回错误，断开连接
    if result_dict["action"] == "error":
        print("rtasr error: " + message)
        result = message
        ws.close()
        # 关闭时重置标志
        global finished_sign
        # 识别结束
        finished_sign = True
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
    # 关闭时重置标志
    global finished_sign
    # 识别结束
    finished_sign = True


def on_close(ws):
    logger.info("ws close ...")
    ws.close()
    # 关闭时重置标志
    global finished_sign
    # 识别结束
    finished_sign = True


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
