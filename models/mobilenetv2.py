"""MobileNetV2 in PyTorch
See the paper "MobileNetV2: Inverted Residuals and Linear Bottlenecks"
(https://arxiv.org/abs/1801.04381)
for more details.
"""
import math
import torch
import torch.nn as nn


def conv2d(inplanes, out_planes, kernel_size=3, stride=1, padding=0, groups=1, bias=False, bitw=None):
    """convolution with padding"""
    return qnn.QuantConv2d(inplanes, out_planes, kernel_size=kernel_size, stride=stride,
                           padding=padding, groups=groups, bias=bias,
                           nbits=qcfg['bitw'] if bitw == None else bitw,
                           symmetric=qcfg['symmetric'])


def relu6(inplace=False):
    """ReLU6 activation"""
    return qnn.QuantReLU6(inplace=inplace, nbits=qcfg['bita'])


def identity(bitw=None):
    return qnn.QuantIdentity(nbits=qcfg['bitw'] if bitw == None else bitw,
                             symmetric=qcfg['symmetric'])

class ConvBNReLU(nn.Module):
    def __init__(self, in_planes, out_planes, kernel_size=3, stride=1, groups=1, bitw=None, quant_input=True):
        super(ConvBNReLU, self).__init__()
        padding = (kernel_size - 1) // 2 if kernel_size > 1 else 0
        
        if not quant_input:
            self.quant_act = identity(bitw)
        self.conv = conv2d(in_planes, out_planes, kernel_size, stride, padding, groups=groups, bitw=bitw)
        self.bn = nn.BatchNorm2d(out_planes)
        self.act = relu6(inplace=False)

    def forward(self, x):
        if hasattr(self, 'quant_act'):
            x = self.quant_act(x)
        return self.act(self.bn(self.conv(x)))


class InvertedResidual(nn.Module):
    def __init__(self, inp, oup, stride, expand_ratio, quant_input=True):
        super(InvertedResidual, self).__init__()
        self.stride = stride
        assert stride in [1, 2]

        hidden_dim = int(round(inp * expand_ratio))
        self.use_res_connect = self.stride == 1 and inp == oup

        layers = []
        if expand_ratio != 1:
            # pw
            layers.append(ConvBNReLU(inp, hidden_dim, kernel_size=1, quant_input=quant_input))
        layers.extend([
            # dw
            ConvBNReLU(hidden_dim, hidden_dim, stride=stride, groups=hidden_dim),
            # pw-linear
            conv2d(hidden_dim, oup, 1, 1),
            nn.BatchNorm2d(oup),
        ])
        self.conv = nn.Sequential(*layers)

    def forward(self, x):
        if self.use_res_connect:
            return x + self.conv(x)
        else:
            return self.conv(x)


class MobileNetV2(nn.Module):
    '''Original MobileNetV2'''
    def __init__(self, num_classes=1000, width_mult=1.0):
        super(MobileNetV2, self).__init__()
        block = InvertedResidual
        input_channel = 32
        last_channel = 1280
        inverted_residual_setting = [
            # t, c, n, s, q
            [1, 16, 1, 1, True],
            [6, 24, 2, 2, False],
            [6, 32, 3, 2, False],
            [6, 64, 4, 2, False],
            [6, 96, 3, 1, False],
            [6, 160, 3, 2, False],
            [6, 320, 1, 1, False],
        ]

        # building first layer
        input_channel = int(input_channel * width_mult)
        self.last_channel = int(last_channel * max(1.0, width_mult))
        features = [ConvBNReLU(3, input_channel, stride=2, bitw=qcfg['first_conv_bitw'])]
        # building inverted residual blocks
        for t, c, n, s, q in inverted_residual_setting:
            output_channel = int(c * width_mult)
            for i in range(n):
                stride = s if i == 0 else 1
                features.append(block(input_channel, output_channel, stride, expand_ratio=t, quant_input=q))
                input_channel = output_channel
        # building last several layers
        features.append(ConvBNReLU(input_channel, self.last_channel, kernel_size=1, quant_input=False))
        # make it nn.Sequential
        self.features = nn.Sequential(*features)

        # building classifier
        self.classifier = nn.Sequential(
            #nn.Dropout(0.2),
            qnn.QuantLinear(self.last_channel, num_classes,
                            nbits=qcfg['last_fc_bitw'], symmetric=qcfg['symmetric']),
        )

        # weight initialization
        for m in self.modules():
            if isinstance(m, qnn.QuantConv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.ones_(m.weight)
                nn.init.zeros_(m.bias)
            elif isinstance(m, qnn.QuantLinear):
                nn.init.normal_(m.weight, 0, 0.01)
                nn.init.zeros_(m.bias)

    def forward(self, x):
        x = self.features(x)
        x = x.mean([2, 3]) # global average pooling
        x = self.classifier(x)
        return x


class MobileNetV2_CIFAR(nn.Module):
    '''MobileNetV2 for CIFAR-10/100'''
    def __init__(self, num_classes=10, width_mult=1.0):
        super(MobileNetV2_CIFAR, self).__init__()
        block = InvertedResidual
        input_channel = 32
        last_channel = 1280
        inverted_residual_setting = [
            # t, c, n, s
            [1, 16, 1, 1],
            [6, 24, 2, 1],
            [6, 32, 3, 1],
            [6, 64, 4, 2],
            [6, 96, 3, 1],
            [6, 160, 3, 2],
            [6, 320, 1, 1],
        ]

        # building first layer
        input_channel = int(input_channel * width_mult)
        self.last_channel = int(last_channel * max(1.0, width_mult))
        features = [ConvBNReLU(3, input_channel, stride=1, bitw=qcfg['first_conv_bitw'])]
        # building inverted residual blocks
        for t, c, n, s in inverted_residual_setting:
            output_channel = int(c * width_mult)
            for i in range(n):
                stride = s if i == 0 else 1
                features.append(block(input_channel, output_channel, stride, expand_ratio=t))
                input_channel = output_channel
        # building last several layers
        features.append(ConvBNReLU(input_channel, self.last_channel, kernel_size=1))
        # make it nn.Sequential
        self.features = nn.Sequential(*features)

        # building classifier
        self.classifier = nn.Sequential(
            #nn.Dropout(0.2),
            qnn.QuantLinear(self.last_channel, num_classes,
                            nbits=qcfg['last_fc_bitw'], symmetric=qcfg['symmetric']),
        )

        # weight initialization
        for m in self.modules():
            if isinstance(m, qnn.QuantConv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.ones_(m.weight)
                nn.init.zeros_(m.bias)
            elif isinstance(m, qnn.QuantLinear):
                nn.init.normal_(m.weight, 0, 0.01)
                nn.init.zeros_(m.bias)

    def forward(self, x):
        x = self.features(x)
        x = x.mean([2, 3])
        x = self.classifier(x)
        return x


def set_model(cfg, qnn):
    r"""
    Args:
        cfg: configuration
    """
    # set quantization configurations
    globals()['qnn'] = qnn
    global qcfg
    qcfg = dict()
    qcfg['bitw'] = cfg.bitw
    qcfg['bita'] = cfg.bita
    qcfg['first_conv_bitw'] = cfg.first_conv_bitw
    qcfg['last_fc_bitw'] = cfg.last_fc_bitw
    qcfg['symmetric'] = cfg.symmetric

    # set model configurations
    if cfg.dataset in ['cifar10', 'cifar100']:
        image_size = 32
        num_classes = int(cfg.dataset[5:])
        model = MobileNetV2_CIFAR(num_classes, cfg.width_mult)

    elif cfg.dataset in ['imagenet']:
        image_size = 224
        num_classes = 1000
        model = MobileNetV2(num_classes, cfg.width_mult)

    else:
        raise Exception('Undefined dataset for MobileNetV2 architecture.')
    
    return model, image_size
