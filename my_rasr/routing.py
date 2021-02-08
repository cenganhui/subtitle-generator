from django.conf.urls import url

# from . import consumers
from .rasr_api import baidu_rasr_api
from .rasr_api import tencent_rasr_api
from .rasr_api import xunfei_rasr_api
from .rasr_api import youdao_rasr_api

websocket_urlpatterns = {
    # url(r'^ws-channel/', consumers.ResponseConsumer.as_asgi(), name='ws-channel'),
    url(r'^baidu-ws-channel/', baidu_rasr_api.BaiduResponseConsumer.as_asgi(), name='baidu-ws-channel'),
    url(r'^xunfei-ws-channel/', xunfei_rasr_api.XunfeiResponseConsumer.as_asgi(), name='xunfei-ws-channel'),
    url(r'^youdao-ws-channel/', youdao_rasr_api.YoudaoResponseConsumer.as_asgi(), name='youdao-ws-channel'),
    url(r'^tencent-ws-channel/', tencent_rasr_api.TencentResponseConsumer.as_asgi(), name='tencent-ws-channel'),
}
