import noisereduce as nr
import numpy as np


def int16_to_float32(data):
    if np.max(np.abs(data)) > 32768:
        raise ValueError("Data has values above 32768")
    return (data / 32768.0).astype("float32")


def float32_to_int16(data):
    if np.max(data) > 1:
        data = data / np.max(np.abs(data))
    return np.array(data * 32767).astype("int16")


def np_audioop_rms(data, width):
    if len(data) == 0:
        return None

    fromType = (np.int8, np.int16, np.int32)[width // 2]
    d = np.frombuffer(data, fromType).astype(np.float)
    rms = np.sqrt(np.mean(d ** 2))

    return int(rms)


def process_noise_data(CHUNK, data, noise):
    """
    音频数据处理
    :param CHUNK:
    :param data:
    :param noise:
    :return:
    """
    WIN_LENGTH = CHUNK // 2
    HOP_LENGTH = CHUNK // 4

    if noise:
        data = np.frombuffer(data, np.int16)
        data = int16_to_float32(data)
        nData = int16_to_float32(np.frombuffer(b''.join(noise), np.int16))

        data = nr.reduce_noise(audio_clip=data, noise_clip=nData,
                               verbose=False, n_std_thresh=1.5, prop_decrease=1,
                               win_length=WIN_LENGTH, n_fft=WIN_LENGTH, hop_length=HOP_LENGTH,
                               n_grad_freq=4)

        data = float32_to_int16(data)
        data = np.ndarray.tobytes(data)
    return data
