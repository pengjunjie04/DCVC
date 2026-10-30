"""Reject incompatible numerical runtimes before decoding predictive video."""

def validate_runtime(sender, receiver):
    if not isinstance(sender, dict):
        raise ValueError('缺少编码端推理环境信息，请更新并重启两端程序')
    differences = [f'{key}: 编码端={sender.get(key)!r}, 解码端={expected!r}'
                   for key, expected in receiver.items()
                   if type(sender.get(key)) is not type(expected) or sender.get(key) != expected]
    if differences:
        raise ValueError('两端推理环境不一致；请统一运行库并重启两端程序：' + '；'.join(differences))
