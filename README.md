# 字幕生成器

## 相关命令
```bash
# 插件
pip install PyAudio-0.2.11-cp38-cp38-win_amd64.whl
pip install PyMySQL
pip install websocket-client
pip install django-cors-headers
pip install channels -i http://pypi.douban.com/simple/

# 项目
python manage.py startapp xxxapp
python manage.py makemigrations xxxapp
python manage.py migrate
python manage.py runserver ip:port

# git
git config user.email "123"
git config --global user.email "123"
```

## 相关技术
- **百度实时语音识别API：** https://ai.baidu.com/ai-doc/SPEECH/2k5dllqxj
- **讯飞实时语音识别API：** https://www.xfyun.cn/doc/asr/rtasr/API.html
- **Django：** https://www.django.cn/