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
        message = {
            "code": 200,
            "msg": "server: connected!"
        }
        return message
    # 201 表示前端请求执行实时语音识别
    if code == 201:
        message = {
            "code": 201,
            "msg": "server: rasr go!",
            "auth": text_data_json["auth"]
        }
        return message
    # 888 表示前端请求断开ws
    if code == 888:
        message = {
            "code": 888,
            "msg": "server: bye!"
        }
        return message


def end_message():
    """
    识别结束消息
    :return: message
    """
    message = {
        "code": 203,
        "msg": "server: finish!"
    }
    return message
