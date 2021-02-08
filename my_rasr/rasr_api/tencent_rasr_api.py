import base64
import hashlib
import hmac
import json
import logging
import random
import threading
import time
from urllib.parse import urlencode

import pyaudio
import websocket
from channels.generic.websocket import WebsocketConsumer

import my_rasr.const
from .process_ws_message import process_message, end_message

# 消息
result = ""
# 识别结束标志
finished_sign = False
# ws断开连接标志
disconnect_sign = False

# 腾讯
# 鉴权信息
tencent_app_id = ""
tencent_secret_id = ""
tencent_secret_key = ""
# 引擎模型类型
tencent_engine_model_type = ""
# 热词id
tencent_hotword_id = ""
# 自学习模型id
tencent_customization_id = ""


class TencentResponseConsumer(WebsocketConsumer):
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
        global tencent_app_id, tencent_secret_id, tencent_secret_key, tencent_engine_model_type
        text_data_json = json.loads(text_data)
        # print(text_data_json)
        message = process_message(text_data_json)

        # 若是201，获取鉴权信息，执行语音识别
        if message["code"] == 201:
            # 获取鉴权信息
            tencent_app_id = message["auth"]["app_id"]
            tencent_secret_id = message["auth"]["secret_id"]
            tencent_secret_key = message["auth"]["secret_key"]
            tencent_engine_model_type = message["auth"]["engine_model_type"]
            # 开启线程调用识别方法
            tencent_rasr_go_thread = threading.Thread(target=tencent_rasr_go)
            tencent_rasr_go_thread.start()
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


def getNonce():
    """
    生成随机 nonce
    :return:
    """
    randomNonce = random.randint(1000, 9999)
    # print("nonce:" + str(randomNonce))
    return randomNonce


def getVoiceId():
    """
    生成随机 voice_id
    :return:
    """
    seed = "1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    temp = []
    for i in range(16):
        temp.append(random.choice(seed))
    randomVoiceId = "".join(temp)
    print("voice_id:" + randomVoiceId)
    return randomVoiceId


def initUri():
    """
    生成请求uri
    :return: uri
    """
    params = dict()
    params["secretid"] = tencent_secret_id
    params["timestamp"] = int(time.time())
    params["expired"] = int(time.time()) + 24 * 60 * 60
    params["nonce"] = getNonce()
    params["engine_model_type"] = tencent_engine_model_type
    params["voice_id"] = getVoiceId()
    params["voice_format"] = 1
    params["needvad"] = 0
    # params["hotword_id"] = tencent_hotword_id
    # params["customization_id"] = tencent_customization_id
    params["filter_dirty"] = 0
    params["filter_modal"] = 0
    params["filter_punc"] = 0
    params["convert_num_mode"] = 1
    params["word_info"] = 0
    # params["vad_silence_time"] = ""
    # 对除 signature 之外的所有参数按字典序进行排序，拼接请求 URL 作为签名原文
    sorted_params = dict()
    for i in sorted(params):
        sorted_params[i] = params[i]
    original = my_rasr.const.TENCENT_URL[6:] + tencent_app_id + "?"
    for k, v in sorted_params.items():
        original += k
        original += "="
        original += str(v)
        original += "&"
    original = original[:-1]
    # 对签名原文使用 SecretKey 进行 HmacSha1 加密，之后再进行 base64 编码
    bytes_original = bytes(original, "utf-8")
    bytes_secret_key = bytes(tencent_secret_key, "utf-8")
    hmacStr = hmac.new(bytes_secret_key, bytes_original, hashlib.sha1).digest()
    signature = base64.b64encode(hmacStr)
    # 将 signature 值进行 urlencode（必须进行 URL 编码，否则将导致鉴权失败偶现 ）
    params_signature = {
        "signature": signature
    }
    urlencode_signature = urlencode(params_signature)
    # print(urlencode_signature)
    # 最终请求 URI
    uri = "wss://" + original + "&" + urlencode_signature
    # print(uri)
    return uri


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
    CHUNK = 1280  # 数据块大小
    FORMAT = pyaudio.paInt16  # 16bit编码格式
    CHANNELS = 1  # 单声道
    RATE = 16000  # 16000采样率
    RECORD_SECONDS = 10  # 录音时间
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
    end_tag = {
        "type": "end"
    }
    body = json.dumps(end_tag)
    ws.send(body, websocket.ABNF.OPCODE_TEXT)
    print("send end tag")


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
    # 返回内容转字典并进行解析
    result_dict = json.loads(message)
    # code为0证明成功
    if result_dict["code"] == 0:
        # 若有final且为1，证明服务器识别结束
        if "final" in result_dict and result_dict["final"] == 1:
            print("finished!")
        else:
            if "result" in result_dict:
                result_data_dict = result_dict["result"]
                # 若有slice_type，证明有识别结果
                if "slice_type" in result_data_dict:
                    if result_data_dict["slice_type"] == 1 or result_data_dict["slice_type"] == 2:
                        sentence = result_data_dict["voice_text_str"]
                        print("识别结果：" + sentence)
                        result = sentence
    else:
        print(result_dict)
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


def tencent_rasr_go():
    """
    调用腾讯语音识别api
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
