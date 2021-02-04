import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from urllib.parse import quote

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

# 讯飞
# 鉴权信息
xunfei_app_id = ""
xunfei_app_key = ""
# 垂直领域个性化参数：法院: court 教育: edu 金融: finance 医疗: medical 科技: tech
# 设置示例：pd="edu"参数pd为非必须设置，不设置参数默认为通用
xunfei_pd = ""
# 结束标志
end_tag = "{\"end\": true}"


class XunfeiResponseConsumer(WebsocketConsumer):
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
        global xunfei_app_id, xunfei_app_key, xunfei_pd
        text_data_json = json.loads(text_data)
        # print(text_data_json)
        message = process_message(text_data_json)

        # 若是201，获取鉴权信息，执行语音识别
        if message["code"] == 201:
            # 获取鉴权信息
            xunfei_app_id = message["auth"]["app_id"]
            xunfei_app_key = message["auth"]["app_key"]
            xunfei_pd = message["auth"]["pd"]
            # 开启线程调用识别方法
            xunfei_rasr_go_thread = threading.Thread(target=xunfei_rasr_go)
            xunfei_rasr_go_thread.start()
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
    :return: uri
    """
    ts = str(int(time.time()))
    tt = (xunfei_app_id + ts).encode('utf-8')
    md5 = hashlib.md5()
    md5.update(tt)
    baseString = md5.hexdigest()
    baseString = bytes(baseString, encoding='utf-8')

    apiKey = xunfei_app_key.encode('utf-8')
    signa = hmac.new(apiKey, baseString, hashlib.sha1).digest()
    signa = base64.b64encode(signa)
    signa = str(signa, 'utf-8')
    uri = my_rasr.const.XUNFEI_URL + "?appid=" + xunfei_app_id + "&ts=" + ts + "&signa=" + quote(signa)
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
    RECORD_SECONDS = 20  # 录音时间
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
    发送结束标识
    :param ws:
    :return:
    """
    ws.send(bytes(end_tag.encode('utf-8')))
    # print("send end tag success")


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
        print("receive result end")
        return

    # 返回内容转字典并进行解析
    result_dict = json.loads(message)
    # 与服务器建立连接
    if result_dict["action"] == "started":
        print("handshake success, result: " + message)
    # 服务器返回的识别内容
    if result_dict["action"] == "result":
        # 进一步解析
        result_data_dict = json.loads(result_dict["data"])
        result_data_seg_id = result_data_dict["seg_id"]
        result_data_cn = result_data_dict["cn"]
        result_data_cn_st = result_data_cn["st"]
        result_data_cn_type = result_data_cn_st["type"]
        result_data_cn_st_rt = result_data_cn_st["rt"]
        # print(result_data_cn_type)
        # 若识别内容为一句话结束，则拼接句子并更新消息
        if int(result_data_cn_type) == 0:
            sentence = ""
            for item in result_data_cn_st_rt:
                result_ws = item["ws"]
                for ws in result_ws:
                    result_cw = ws["cw"]
                    for cw in result_cw:
                        result_w = cw["w"]
                        sentence += result_w
                        # print(result_w)
            print("识别结果：" + sentence)
            # 拼接识别结果
            result += sentence
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


def xunfei_rasr_go():
    """
    调用讯飞语音识别api
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
