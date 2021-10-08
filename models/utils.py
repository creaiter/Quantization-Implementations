import os 
import copy


def set_arch_name(cfg):
    r"""Set architecture name
    """
    arch_name = copy.deepcopy(cfg.arch)

    if cfg.arch in ['resnet', 'preactresnet']:
        arch_name += f'-{cfg.layers}'

    elif cfg.arch in ['mobilenetv2']:
        if cfg.width_mult != 1.0:
            arch_name += f'x{cfg.width_mult}'

    return arch_name
